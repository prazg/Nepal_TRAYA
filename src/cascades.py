"""
Directed Multi-Hazard Cascade Graph Engine for TRĀYA 2.0 (`TRAYA-010`).

Evaluates 3 transparent, inspectable physical cascade chains over Nepal's live,
forecast, and static geohazard products:
  1. `rain_landslide_dam_road`    : Heavy rainfall / Dahal-Hasegawa exceedance +
                                    dated landslides -> debris-flow blockage /
                                    valley flood -> road & bridge isolation.
  2. `quake_coseismic_isolation`  : Recent M >= 4.5 earthquake (USGS or BIPAD NSC)
                                    within 100 km of steep/high-hazard basins or
                                    glacial lakes -> coseismic slope failure /
                                    moraine destabilization -> corridor access cut.
  3. `glof_infra_isolation`       : High/Very High GLOF susceptibility (plus warm
                                    rain-on-ice or seismic proximity) -> bridge &
                                    hydropower impact -> hospital access disruption.

Key epistemic safeguards:
  * Every edge declares `evidence_type` (`"observed"` | `"forecast"` | `"modelled_static"`),
    exact `trigger_rule`, `active` boolean, `confidence`, and `uncertainty_note`.
  * Undated OSM `landslide_scar` records NEVER trigger live rainfall-landslide chains.
  * Standing static GLOF susceptibility is clearly distinguished (`static_susceptibility_watch`)
    from dynamically triggered active hazards (`active_dynamic`).
  * Bilingual plain-language summaries (English + Nepali Devanagari) for every scenario.

Pure Python 3.12 standard library only (zero third-party dependencies).
Output: `data/cascades.json` (atomic UTF-8 JSON).
"""
from __future__ import annotations

import argparse
import datetime as dt
import json
import math
import os
import sys
import tempfile
import time
import urllib.parse
import urllib.request
from collections import Counter
from typing import Any

SRC_DIR = os.path.dirname(os.path.abspath(__file__))
if SRC_DIR not in sys.path:
    sys.path.insert(0, SRC_DIR)

import alerts as AL
import config as C
import floods as FL
import hydromet as HM
import refresh_weekly as RW
import seismic as SZ

SCHEMA_VERSION = "cascades.v1"
OUT_JSON = os.path.join(C.DATA, "cascades.json")
USER_AGENT = "Nepal-TRAYA/2.1 (+https://prazg.github.io/Nepal_TRAYA/)"

# Transparent physical screening thresholds
DH_OBS_WATCH_RATIO = 0.50
DH_OBS_EXCEED_RATIO = 1.00
DH_COMBINED_WATCH_RATIO = 0.75
RECENT_LANDSLIDE_DAYS = 14
RECENT_QUAKE_DAYS = 30
QUAKE_MIN_MAG = 4.5
QUAKE_RADIUS_KM = 100.0
ELEVATED_RIVER_TIERS = frozenset({"elevated", "q2_watch", "q5_warning", "q20_severe"})

SEVERITY_RANK: dict[str, int] = {
    "critical": 5,
    "high": 4,
    "moderate": 3,
    "watch": 2,
    "baseline": 1,
}

STATUTORY_AGENCIES = [
    {"name": "DHM Flood & Weather Bulletins", "url": "https://hydrology.gov.np"},
    {"name": "DMG / NEMRC Seismic Monitoring", "url": "https://seismonepal.gov.np"},
    {"name": "NDRRMA BIPAD Portal", "url": "https://bipadportal.gov.np"},
]


def _atomic_write_json(path: str, obj: Any) -> None:
    os.makedirs(os.path.dirname(os.path.abspath(path)), exist_ok=True)
    fd, tmp_path = tempfile.mkstemp(
        dir=os.path.dirname(os.path.abspath(path)),
        prefix=".tmp_",
        suffix=".json",
    )
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as fh:
            json.dump(obj, fh, separators=(",", ":"), ensure_ascii=False, allow_nan=False)
        os.replace(tmp_path, path)
    except Exception:
        if os.path.exists(tmp_path):
            try:
                os.remove(tmp_path)
            except OSError:
                pass
        raise


def _load_json_optional(path: str) -> tuple[Any, bool]:
    if not os.path.exists(path):
        return (None, False)
    try:
        with open(path, encoding="utf-8") as fh:
            return (json.load(fh), True)
    except Exception:
        return (None, False)


def _parse_iso_utc(val: Any) -> dt.datetime | None:
    if val is None or val == "":
        return None
    if isinstance(val, (int, float)) and math.isfinite(val):
        try:
            sec = float(val) / 1000.0 if abs(float(val)) > 1e11 else float(val)
            return dt.datetime.fromtimestamp(sec, tz=dt.timezone.utc)
        except (OverflowError, OSError, ValueError):
            return None
    s = str(val).strip()
    if not s:
        return None
    try:
        iso_s = s[:-1] + "+00:00" if s.endswith("Z") else s
        if len(iso_s) == 10:
            iso_s += "T00:00:00+00:00"
        d = dt.datetime.fromisoformat(iso_s)
        if d.tzinfo is None:
            d = d.replace(tzinfo=dt.timezone.utc)
        return d.astimezone(dt.timezone.utc)
    except ValueError:
        return None


def fetch_live_usgs_m45(days: int = 14) -> list[dict[str, Any]]:
    """Optional live USGS FDSN M>=4.5 query over Nepal region (stdlib only)."""
    start = (dt.datetime.now(dt.timezone.utc) - dt.timedelta(days=days)).strftime("%Y-%m-%dT%H:%M:%SZ")
    params = {
        "format": "geojson",
        "starttime": start,
        "minmagnitude": QUAKE_MIN_MAG,
        "minlatitude": AL.USGS_NEPAL_BBOX[1],
        "maxlatitude": AL.USGS_NEPAL_BBOX[3],
        "minlongitude": AL.USGS_NEPAL_BBOX[0],
        "maxlongitude": AL.USGS_NEPAL_BBOX[2],
        "orderby": "time",
        "limit": 100,
    }
    url = f"{C.USGS_QUERY}?{urllib.parse.urlencode(params)}"
    req = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
    with urllib.request.urlopen(req, timeout=20) as resp:
        gj = json.loads(resp.read().decode("utf-8"))
    out: list[dict[str, Any]] = []
    for f in gj.get("features") or []:
        p = f.get("properties") or {}
        coords = (f.get("geometry") or {}).get("coordinates") or []
        if len(coords) < 2 or p.get("mag") is None:
            continue
        ts = _parse_iso_utc(p.get("time"))
        out.append(
            {
                "id": f"usgs_{f.get('id')}",
                "source": "USGS FDSN",
                "mag": round(float(p["mag"]), 2),
                "lon": round(float(coords[0]), 4),
                "lat": round(float(coords[1]), 4),
                "depth_km": round(float(coords[2]), 1) if len(coords) > 2 and coords[2] is not None else None,
                "place": str(p.get("place") or "Nepal region"),
                "time_utc": ts.strftime("%Y-%m-%dT%H:%M:%SZ") if ts else None,
            }
        )
    return out


def _collect_recent_quakes(
    gdacs: dict[str, Any] | None,
    bipad: dict[str, Any] | None,
    live_usgs: list[dict[str, Any]] | None,
    now_dt: dt.datetime,
) -> list[dict[str, Any]]:
    """Collect and deduplicate recent M>=4.5 earthquakes from USGS, BIPAD NSC, and GDACS."""
    raw_quakes: list[dict[str, Any]] = []

    if live_usgs:
        raw_quakes.extend(live_usgs)

    # USGS recent block embedded in gdacs_alerts.json
    usgs_recent = (gdacs or {}).get("usgs_recent") or {}
    for ev in usgs_recent.get("events") or []:
        mag = ev.get("mag")
        lon = ev.get("lon")
        lat = ev.get("lat")
        if mag is None or lon is None or lat is None:
            continue
        ts = _parse_iso_utc(ev.get("time_utc") or ev.get("time"))
        raw_quakes.append(
            {
                "id": str(ev.get("id") or f"usgs_{lon}_{lat}"),
                "source": "USGS FDSN (snapshot)",
                "mag": round(float(mag), 2),
                "lon": round(float(lon), 4),
                "lat": round(float(lat), 4),
                "depth_km": ev.get("depth_km"),
                "place": str(ev.get("place") or "Nepal region"),
                "time_utc": ts.strftime("%Y-%m-%dT%H:%M:%SZ") if ts else None,
            }
        )

    # BIPAD NSC earthquakes if bipad_official.json is present
    if isinstance(bipad, dict):
        eq_lists: list[Any] = []
        for k in ("earthquakes", "latest_earthquakes", "nsc_earthquakes"):
            val = bipad.get(k)
            if isinstance(val, list):
                eq_lists.extend(val)
            elif isinstance(val, dict):
                eq_lists.extend(val.get("results") or val.get("samples") or [])
        for eq in eq_lists:
            if not isinstance(eq, dict):
                continue
            mag = eq.get("magnitude") if eq.get("magnitude") is not None else eq.get("mag")
            lon = eq.get("lon")
            lat = eq.get("lat")
            if lon is None or lat is None:
                coords = (eq.get("point") or {}).get("coordinates") or []
                if len(coords) >= 2:
                    lon, lat = coords[0], coords[1]
            if mag is None or lon is None or lat is None:
                continue
            ts = _parse_iso_utc(eq.get("eventOn") or eq.get("event_date_utc") or eq.get("time_utc"))
            raw_quakes.append(
                {
                    "id": f"bipad_eq_{eq.get('id')}",
                    "source": "BIPAD / NSC",
                    "mag": round(float(mag), 2),
                    "lon": round(float(lon), 4),
                    "lat": round(float(lat), 4),
                    "depth_km": None,
                    "place": str(eq.get("address") or eq.get("title") or "Nepal"),
                    "time_utc": ts.strftime("%Y-%m-%dT%H:%M:%SZ") if ts else None,
                }
            )

    # Filter to M >= 4.5 within RECENT_QUAKE_DAYS and Nepal region, then deduplicate
    cutoff = now_dt - dt.timedelta(days=RECENT_QUAKE_DAYS)
    filtered: list[dict[str, Any]] = []
    for q in raw_quakes:
        if float(q["mag"]) < QUAKE_MIN_MAG:
            continue
        q_dt = _parse_iso_utc(q.get("time_utc"))
        if q_dt is not None and q_dt < cutoff:
            continue
        if not (77.9 <= float(q["lon"]) <= 90.3 and 24.2 <= float(q["lat"]) <= 32.6):
            continue
        # Deduplicate close spatiotemporal matches (within 30 km and 10 min)
        is_dup = False
        for prev in filtered:
            d_km = SZ.haversine_km(float(q["lon"]), float(q["lat"]), float(prev["lon"]), float(prev["lat"]))
            p_dt = _parse_iso_utc(prev.get("time_utc"))
            dt_sec = abs((q_dt - p_dt).total_seconds()) if (q_dt and p_dt) else 0.0
            if d_km <= 30.0 and dt_sec <= 600.0:
                is_dup = True
                break
        if not is_dup:
            filtered.append(q)

    filtered.sort(key=lambda x: (float(x["mag"]), x.get("time_utc") or ""), reverse=True)
    return filtered


def _extract_bipad_signals(
    bipad: dict[str, Any] | None, now_dt: dt.datetime
) -> dict[str, Any]:
    """Parse optional `data/bipad_official.json` signals safely across schema variants."""
    out: dict[str, Any] = {
        "available": isinstance(bipad, dict),
        "rain_flood_alerts": [],
        "river_warnings": [],
        "glof_alerts": [],
        "recent_landslides": [],
    }
    if not isinstance(bipad, dict):
        return out

    cutoff_ls = now_dt - dt.timedelta(days=RECENT_LANDSLIDE_DAYS)

    # Alerts
    alerts_list = bipad.get("alerts")
    if isinstance(alerts_list, dict):
        alerts_list = alerts_list.get("results") or []
    for al in alerts_list or []:
        if not isinstance(al, dict):
            continue
        title = str(al.get("title") or "").lower()
        hz = al.get("hazard")
        if hz == 26 or "glof" in title or "glacial lake" in title:
            out["glof_alerts"].append(al)
        elif hz in (11, 14, 17, 28) or any(k in title for k in ("flood", "rain", "landslide")):
            out["rain_flood_alerts"].append(al)

    # River stations
    rivers = bipad.get("dhm_rivers") or bipad.get("rivers") or bipad.get("river_stations") or []
    if isinstance(rivers, dict):
        rivers = rivers.get("results") or []
    for rv in rivers or []:
        if not isinstance(rv, dict):
            continue
        st = str(rv.get("status") or "").upper()
        if "WARNING" in st and "BELOW" not in st:
            out["river_warnings"].append(rv)
        elif "DANGER" in st and "BELOW" not in st:
            out["river_warnings"].append(rv)

    # Landslide incidents
    incs = bipad.get("landslide_incidents") or bipad.get("incidents") or []
    if isinstance(incs, dict):
        incs = incs.get("results") or incs.get("samples") or []
    for inc in incs or []:
        if not isinstance(inc, dict):
            continue
        hz = inc.get("hazard")
        title = str(inc.get("title") or "").lower()
        if hz is not None and hz != 17 and "landslide" not in title:
            continue
        inc_dt = _parse_iso_utc(inc.get("incidentOn") or inc.get("event_date_utc"))
        if inc_dt is not None and inc_dt >= cutoff_ls:
            out["recent_landslides"].append(inc)

    return out


def _districts_ne(names: list[str]) -> list[str]:
    return [RW.DISTRICT_NE.get(n, n) for n in names]


def _provinces_for_districts(names: list[str], dist_to_prov: dict[str, str]) -> list[str]:
    provs = {dist_to_prov[d] for d in names if d in dist_to_prov and dist_to_prov[d]}
    return sorted(provs)


# ---------------------------------------------------------------------------
# Pure Cascade Graph Evaluator (deterministic & unit-testable)
# ---------------------------------------------------------------------------
def evaluate_cascades(
    rivers_watch: dict[str, Any] | None,
    hydromet: dict[str, Any] | None,
    landslides: dict[str, Any] | None,
    lakes_fc: dict[str, Any] | None,
    exposure_isolation: dict[str, Any] | None,
    bipad: dict[str, Any] | None = None,
    gdacs: dict[str, Any] | None = None,
    live_usgs: list[dict[str, Any]] | None = None,
    now_utc: dt.datetime | None = None,
    source_meta: list[dict[str, Any]] | None = None,
    mode: str = "offline",
) -> dict[str, Any]:
    """Evaluate all 3 multi-hazard cascade chains and emit the directed graph."""
    now_dt = now_utc or dt.datetime.now(dt.timezone.utc)
    now_iso = now_dt.strftime("%Y-%m-%dT%H:%M:%SZ")

    # Index lakes & districts
    lakes_list: list[dict[str, Any]] = [
        f.get("properties") or {} for f in (lakes_fc or {}).get("features") or []
    ]
    lakes_by_id = {p["id"]: p for p in lakes_list if p.get("id")}

    iso_lakes: dict[str, dict[str, Any]] = (exposure_isolation or {}).get("lakes") or {}
    iso_districts_list: list[dict[str, Any]] = (exposure_isolation or {}).get("districts") or []
    iso_dist_by_name: dict[str, dict[str, Any]] = {d["name"]: d for d in iso_districts_list if d.get("name")}
    dist_to_prov: dict[str, str] = {
        d["name"]: FL.canonical_province(d.get("prov"))
        for d in iso_districts_list
        if d.get("name") and d.get("prov")
    }

    bipad_sig = _extract_bipad_signals(bipad, now_dt)

    nodes: list[dict[str, Any]] = []
    edges: list[dict[str, Any]] = []
    active_scenarios: list[dict[str, Any]] = []
    chains_summary: dict[str, dict[str, Any]] = {}

    # =========================================================================
    # CHAIN 1: `rain_landslide_dam_road`
    # Heavy rainfall / Dahal-Hasegawa exceedance + dated landslides
    #   -> debris-flow blockage / valley flood -> road & bridge isolation
    # =========================================================================
    hm_nodes = (hydromet or {}).get("nodes") or []
    dh_obs_hot = [
        n for n in hm_nodes
        if float((n.get("dh_obs") or {}).get("max_ratio") or 0.0) >= DH_OBS_WATCH_RATIO
    ]
    dh_obs_exceed = [
        n for n in hm_nodes
        if float((n.get("dh_obs") or {}).get("max_ratio") or 0.0) >= DH_OBS_EXCEED_RATIO
    ]
    dh_comb_hot = [
        n for n in hm_nodes
        if float((n.get("dh_combined") or {}).get("max_ratio") or 0.0) >= DH_COMBINED_WATCH_RATIO
    ]

    cutoff_ls = now_dt - dt.timedelta(days=RECENT_LANDSLIDE_DAYS)
    dated_recent_ls: list[dict[str, Any]] = []
    for ev in (landslides or {}).get("events") or []:
        if ev.get("feature_type") not in ("landslide_event", "coseismic_failure"):
            continue
        ev_dt = _parse_iso_utc(ev.get("event_date_utc"))
        if ev_dt is not None and ev_dt >= cutoff_ls:
            dated_recent_ls.append(ev)

    rain_trigger_districts: set[str] = set()
    for n in dh_obs_hot + dh_comb_hot:
        if n.get("district"):
            rain_trigger_districts.add(str(n["district"]))
    ls_trigger_districts: set[str] = {
        str(e["district"]) for e in dated_recent_ls if e.get("district")
    }

    elevated_basins = [
        b for b in ((rivers_watch or {}).get("basins") or [])
        if b.get("status_now") in ELEVATED_RIVER_TIERS or b.get("status_14d") in ELEVATED_RIVER_TIERS
    ]
    flood_districts = {str(b["district"]) for b in elevated_basins if b.get("district")}

    rain_active = bool(dh_obs_hot or dh_comb_hot or bipad_sig["rain_flood_alerts"])
    dated_ls_active = bool(dated_recent_ls or bipad_sig["recent_landslides"])
    debris_flood_active = bool(
        (rain_active and (dated_ls_active or elevated_basins or bipad_sig["river_warnings"]))
        or (len(dh_obs_exceed) > 0)
        or (len(dated_recent_ls) >= 2 and bool(elevated_basins))
    )

    c1_districts = sorted(rain_trigger_districts | ls_trigger_districts | flood_districts)
    c1_iso_districts = [
        d for d in c1_districts
        if (iso_dist_by_name.get(d) or {}).get("unique_bridges_at_crossings", 0) > 0
        or (iso_dist_by_name.get(d) or {}).get("district_isolation_risk") in ("high", "moderate")
    ]
    c1_road_cut_active = bool(debris_flood_active and (c1_iso_districts or c1_districts))

    c1_bridges_exposed = sum(
        int((iso_dist_by_name.get(d) or {}).get("unique_bridges_at_crossings") or 0)
        for d in c1_iso_districts
    )
    c1_settlements_iso = sum(
        int((iso_dist_by_name.get(d) or {}).get("unique_settlements_potentially_isolated") or 0)
        for d in c1_iso_districts
    )

    rain_evidence_type = "observed" if (dh_obs_hot or bipad_sig["rain_flood_alerts"]) else "forecast"

    nodes.extend(
        [
            {
                "id": "c1_heavy_rain_dh",
                "chain_id": "rain_landslide_dam_road",
                "stage": "trigger",
                "label_en": "Heavy Rainfall & Dahal–Hasegawa Landslide Threshold",
                "label_ne": "भारी वर्षा र दाहाल–हासेगावा पहिरो सीमा",
                "evidence_type": rain_evidence_type,
                "active": rain_active,
                "severity": "high" if dh_obs_exceed else ("moderate" if rain_active else "baseline"),
                "affected_districts": sorted(rain_trigger_districts),
                "metrics": {
                    "n_nodes_dh_obs_watch": len(dh_obs_hot),
                    "n_nodes_dh_obs_exceeded": len(dh_obs_exceed),
                    "n_nodes_dh_combined_watch": len(dh_comb_hot),
                    "n_bipad_rain_flood_alerts": len(bipad_sig["rain_flood_alerts"]),
                    "max_dh_ratio_obs": round(
                        max((float((n.get("dh_obs") or {}).get("max_ratio") or 0.0) for n in hm_nodes), default=0.0),
                        3,
                    ),
                },
            },
            {
                "id": "c1_dated_landslides",
                "chain_id": "rain_landslide_dam_road",
                "stage": "trigger",
                "label_en": "Recent Dated Landslide Events (<=14 d)",
                "label_ne": "हालैका मिति प्रमाणित पहिरो घटनाहरू (१४ दिनभित्र)",
                "evidence_type": "observed",
                "active": dated_ls_active,
                "severity": "high" if len(dated_recent_ls) >= 3 else ("moderate" if dated_ls_active else "baseline"),
                "affected_districts": sorted(ls_trigger_districts),
                "metrics": {
                    "n_dated_landslides_14d": len(dated_recent_ls),
                    "n_bipad_landslides_14d": len(bipad_sig["recent_landslides"]),
                    "undated_osm_scars_excluded_from_trigger": int(
                        ((landslides or {}).get("counts_by_type") or {}).get("landslide_scar", 0)
                    ),
                },
            },
            {
                "id": "c1_debris_dam_valley_flood",
                "chain_id": "rain_landslide_dam_road",
                "stage": "intermediate",
                "label_en": "Debris-Flow Blockage & Valley Flood Amplification",
                "label_ne": "लेदो-पहिरो अवरोध तथा उपत्यका बाढी प्रकोप",
                "evidence_type": "forecast" if (elevated_basins and not dh_obs_exceed) else "observed",
                "active": debris_flood_active,
                "severity": "high" if (dh_obs_exceed and elevated_basins) else ("moderate" if debris_flood_active else "baseline"),
                "affected_districts": c1_districts,
                "metrics": {
                    "n_elevated_glofas_basins": len(elevated_basins),
                    "elevated_basin_names": [b["name"] for b in elevated_basins],
                    "n_bipad_river_warnings": len(bipad_sig["river_warnings"]),
                },
            },
            {
                "id": "c1_road_bridge_isolation",
                "chain_id": "rain_landslide_dam_road",
                "stage": "impact",
                "label_en": "Valley Road & Bridge Access Isolation",
                "label_ne": "सडक तथा पुल अवरोध र पहुँच विच्छेद",
                "evidence_type": "modelled_static" if not c1_road_cut_active else "forecast",
                "active": c1_road_cut_active,
                "severity": "high" if (c1_road_cut_active and c1_bridges_exposed >= 20) else ("moderate" if c1_road_cut_active else "baseline"),
                "affected_districts": c1_iso_districts or c1_districts,
                "metrics": {
                    "bridges_exposed_in_triggered_districts": c1_bridges_exposed,
                    "settlements_potentially_isolated_in_triggered_districts": c1_settlements_iso,
                },
            },
        ]
    )

    edges.extend(
        [
            {
                "rule_id": "RLDR-01",
                "chain_id": "rain_landslide_dam_road",
                "from": "c1_heavy_rain_dh",
                "to": "c1_debris_dam_valley_flood",
                "trigger_rule": (
                    "dh_obs.max_ratio >= 0.50 OR dh_combined.max_ratio >= 0.75 OR bipad_rain_flood_alerts > 0 "
                    "coinciding with elevated GloFAS basin, DHM river warning, or dh_obs.max_ratio >= 1.00"
                ),
                "evidence_type": rain_evidence_type,
                "active": bool(rain_active and debris_flood_active),
                "confidence": "moderate" if dh_obs_exceed else "low",
                "uncertainty_note": (
                    "Dahal & Hasegawa (2008) I-D curves are regional empirical screening envelopes based on "
                    "gridded Open-Meteo precipitation (~10-25 km), which can miss localized cloudburst cells."
                ),
                "supporting_evidence": {
                    "dh_obs_watch_nodes": [n["id"] for n in dh_obs_hot],
                    "dh_combined_watch_nodes": [n["id"] for n in dh_comb_hot],
                    "elevated_basins": [b["id"] for b in elevated_basins],
                    "bipad_river_warnings": [
                        rv.get("title") or rv.get("basin") or str(rv.get("id"))
                        for rv in bipad_sig["river_warnings"][:5]
                    ],
                },
            },
            {
                "rule_id": "RLDR-02",
                "chain_id": "rain_landslide_dam_road",
                "from": "c1_dated_landslides",
                "to": "c1_debris_dam_valley_flood",
                "trigger_rule": (
                    "dated_landslides_14d >= 1 (feature_type in {landslide_event, coseismic_failure}) "
                    "coinciding with heavy rainfall or elevated river discharge"
                ),
                "evidence_type": "observed",
                "active": bool(dated_ls_active and debris_flood_active),
                "confidence": "high" if (dated_ls_active and debris_flood_active) else "moderate",
                "uncertainty_note": (
                    "Only dated confirmed/reported landslide events enter this rule; undated OSM scars are "
                    "strictly excluded. Landslide-dam formation depends on valley constriction and material volume."
                ),
                "supporting_evidence": {
                    "n_dated_landslides_14d": len(dated_recent_ls),
                    "districts": sorted(ls_trigger_districts),
                },
            },
            {
                "rule_id": "RLDR-03",
                "chain_id": "rain_landslide_dam_road",
                "from": "c1_debris_dam_valley_flood",
                "to": "c1_road_bridge_isolation",
                "trigger_rule": (
                    "active debris_dam_valley_flood overlapping districts with mapped corridor bridges "
                    "or moderate/high road-cut isolation screening risk"
                ),
                "evidence_type": "modelled_static",
                "active": c1_road_cut_active,
                "confidence": "moderate",
                "uncertainty_note": (
                    "Bridge and settlement counts derive from 1 km corridor OSM screening (lower bound); "
                    "actual road closure requires Department of Roads / NDRRMA field confirmation."
                ),
                "supporting_evidence": {
                    "districts": c1_iso_districts or c1_districts,
                    "bridges_exposed": c1_bridges_exposed,
                    "settlements_isolated": c1_settlements_iso,
                },
            },
        ]
    )

    c1_sev = (
        "critical" if (c1_road_cut_active and dh_obs_exceed and dated_ls_active)
        else ("high" if c1_road_cut_active else ("moderate" if (rain_active or dated_ls_active) else "baseline"))
    )
    c1_sum_en = (
        f"Active rainfall-landslide-road cascade across {', '.join(c1_districts) or 'Nepal region'}: "
        f"{len(dh_obs_hot)} observed / {len(dh_comb_hot)} forecast Dahal–Hasegawa watch nodes, "
        f"{len(dated_recent_ls)} recent dated landslide(s), {len(elevated_basins)} elevated river basin(s), "
        f"and {len(bipad_sig['river_warnings'])} BIPAD DHM river warning(s), "
        f"overlapping {c1_bridges_exposed} corridor bridges."
        if (rain_active or dated_ls_active or debris_flood_active)
        else (
            "No active rainfall-landslide-debris-dam cascade: all 24 sentinel nodes are below Dahal–Hasegawa "
            "thresholds, 0 recent (<=14 d) dated landslide events are active, and all 10 GloFAS river basins are normal."
        )
    )
    c1_sum_ne = (
        f"{', '.join(_districts_ne(c1_districts)) or 'नेपाल क्षेत्र'}मा भारी वर्षा-पहिरो-सडक अवरोध शृङ्खला सक्रिय: "
        f"{len(dh_obs_hot)} अवलोकित र {len(dh_comb_hot)} पूर्वानुमान दाहाल–हासेगावा निगरानी बिन्दु, "
        f"{len(dated_recent_ls)} हालैका पहिरो घटना, {len(bipad_sig['river_warnings'])} DHM नदी चेतावनी र "
        f"{c1_bridges_exposed} पुलहरू जोखिममा।"
        if (rain_active or dated_ls_active or debris_flood_active)
        else (
            "हाल भारी वर्षा-पहिरो-सडक अवरोध शृङ्खला सक्रिय छैन: सबै २४ वर्षा निगरानी बिन्दुहरू "
            "दाहाल–हासेगावा सीमाभन्दा तल छन् र १० प्रमुख नदी बेसिनहरू सामान्य अवस्थामा छन्।"
        )
    )
    chains_summary["rain_landslide_dam_road"] = {
        "chain_id": "rain_landslide_dam_road",
        "title_en": "Rainfall → Landslide / Debris Dam → Road & Bridge Isolation",
        "title_ne": "भारी वर्षा → पहिरो / लेदो अवरोध → सडक तथा पुल विच्छेद",
        "dynamic_active": bool(rain_active or dated_ls_active or debris_flood_active),
        "severity": c1_sev,
        "affected_districts": c1_districts,
        "affected_districts_ne": _districts_ne(c1_districts),
        "summary_en": c1_sum_en,
        "summary_ne": c1_sum_ne,
    }
    if rain_active or dated_ls_active or debris_flood_active:
        active_scenarios.append(
            {
                "scenario_id": "SCN-RAIN-LANDSLIDE-ROAD",
                "chain_id": "rain_landslide_dam_road",
                "severity": c1_sev,
                "status": "active_dynamic",
                "evidence_types": sorted({e["evidence_type"] for e in edges if e["chain_id"] == "rain_landslide_dam_road" and e["active"]} or {rain_evidence_type}),
                "confidence": "high" if (dh_obs_exceed and dated_ls_active) else "moderate",
                "affected_districts": c1_districts,
                "affected_districts_ne": _districts_ne(c1_districts),
                "affected_provinces": _provinces_for_districts(c1_districts, dist_to_prov),
                "active_rule_ids": [e["rule_id"] for e in edges if e["chain_id"] == "rain_landslide_dam_road" and e["active"]],
                "summary_en": c1_sum_en,
                "summary_ne": c1_sum_ne,
                "key_metrics": {
                    "dh_obs_watch_nodes": len(dh_obs_hot),
                    "dh_combined_watch_nodes": len(dh_comb_hot),
                    "dated_landslides_14d": len(dated_recent_ls),
                    "elevated_river_basins": len(elevated_basins),
                    "bridges_exposed": c1_bridges_exposed,
                    "settlements_potentially_isolated": c1_settlements_iso,
                },
                "statutory_reference_agencies": STATUTORY_AGENCIES,
            }
        )

    # =========================================================================
    # CHAIN 2: `quake_coseismic_isolation`
    # Recent M >= 4.5 earthquake (USGS or BIPAD NSC) within 100 km of steep/
    # high-hazard basins or glacial lakes -> coseismic slope failure / moraine
    # destabilization -> corridor access cut
    # =========================================================================
    recent_quakes = _collect_recent_quakes(gdacs, bipad, live_usgs, now_dt)
    high_hazard_lakes = [
        p for p in lakes_list
        if p.get("hazard") in ("high", "very high") or p.get("priority") or p.get("ice_cored")
    ]

    quake_near_lakes: list[dict[str, Any]] = []
    quake_affected_lake_ids: set[str] = set()
    quake_affected_districts: set[str] = set()

    for q in recent_quakes:
        qlon, qlat = float(q["lon"]), float(q["lat"])
        near_lids: list[str] = []
        near_dists: set[str] = set()
        for lp in high_hazard_lakes:
            d_km = SZ.haversine_km(qlon, qlat, float(lp["lon"]), float(lp["lat"]))
            if d_km <= QUAKE_RADIUS_KM:
                near_lids.append(lp["id"])
                if lp.get("district"):
                    near_dists.add(str(lp["district"]))
        # Also match steep mountain districts within 100 km whose corridor isolation risk is moderate/high
        for d_rec in iso_districts_list:
            if d_rec.get("district_isolation_risk") not in ("high", "moderate"):
                continue
            # Check top corridor lake centroid or match via district lakes
            for lid in d_rec.get("top_corridor_lake_ids") or []:
                lp = lakes_by_id.get(lid)
                if lp and SZ.haversine_km(qlon, qlat, float(lp["lon"]), float(lp["lat"])) <= QUAKE_RADIUS_KM:
                    near_dists.add(d_rec["name"])
                    break
        if near_lids or near_dists:
            quake_near_lakes.append(
                {
                    "quake_id": q["id"],
                    "source": q["source"],
                    "mag": q["mag"],
                    "place": q["place"],
                    "time_utc": q["time_utc"],
                    "n_high_hazard_lakes_within_100km": len(near_lids),
                    "affected_districts": sorted(near_dists),
                }
            )
            quake_affected_lake_ids.update(near_lids)
            quake_affected_districts.update(near_dists)

    c2_eq_active = len(recent_quakes) > 0
    c2_coseismic_active = len(quake_near_lakes) > 0
    c2_impacted_corridors = [
        lid for lid in sorted(quake_affected_lake_ids)
        if lid in iso_lakes
        and iso_lakes[lid]["road_cut_hospital_isolation"]["corridor_disruption_risk"] in ("high", "moderate")
    ]
    c2_access_cut_active = bool(c2_coseismic_active and (c2_impacted_corridors or quake_affected_districts))
    c2_max_mag = max((float(q["mag"]) for q in recent_quakes), default=None)
    c2_near_max_mag = max((float(q["mag"]) for q in quake_near_lakes), default=None)
    c2_districts = sorted(quake_affected_districts)

    c2_bridges_exposed = sum(
        int((iso_dist_by_name.get(d) or {}).get("unique_bridges_at_crossings") or 0)
        for d in c2_districts
    )
    c2_settlements_iso = sum(
        int((iso_dist_by_name.get(d) or {}).get("unique_settlements_potentially_isolated") or 0)
        for d in c2_districts
    )

    nodes.extend(
        [
            {
                "id": "c2_recent_eq_m45",
                "chain_id": "quake_coseismic_isolation",
                "stage": "trigger",
                "label_en": "Recent M >= 4.5 Earthquake (USGS / BIPAD NSC, <=30 d)",
                "label_ne": "हालैको म्याग्निच्युड >= ४.५ भूकम्प (USGS / राष्ट्रिय भूकम्प मापन केन्द्र)",
                "evidence_type": "observed",
                "active": c2_eq_active,
                "severity": "critical" if (c2_max_mag and c2_max_mag >= 6.0) else ("high" if (c2_max_mag and c2_max_mag >= 5.0) else ("moderate" if c2_eq_active else "baseline")),
                "affected_districts": c2_districts,
                "metrics": {
                    "n_quakes_m45_30d": len(recent_quakes),
                    "max_magnitude": c2_max_mag,
                    "events": recent_quakes[:5],
                },
            },
            {
                "id": "c2_coseismic_slope_moraine",
                "chain_id": "quake_coseismic_isolation",
                "stage": "intermediate",
                "label_en": "Coseismic Slope Failure & Moraine Destabilization Screening",
                "label_ne": "भूकम्प-प्रेरित पहिरो तथा हिमताल मोरेन अस्थिरता जाँच",
                "evidence_type": "observed" if c2_coseismic_active else "modelled_static",
                "active": c2_coseismic_active,
                "severity": "critical" if (c2_coseismic_active and c2_near_max_mag and c2_near_max_mag >= 6.0) else ("high" if c2_coseismic_active else "baseline"),
                "affected_districts": c2_districts,
                "metrics": {
                    "n_quakes_within_100km_high_hazard": len(quake_near_lakes),
                    "n_high_hazard_lakes_within_100km": len(quake_affected_lake_ids),
                    "radius_km": QUAKE_RADIUS_KM,
                },
            },
            {
                "id": "c2_corridor_access_cut",
                "chain_id": "quake_coseismic_isolation",
                "stage": "impact",
                "label_en": "Mountain Corridor Access & Hospital Link Cut",
                "label_ne": "पहाडी करिडोर यातायात र अस्पताल पहुँच अवरोध",
                "evidence_type": "modelled_static",
                "active": c2_access_cut_active,
                "severity": "high" if (c2_access_cut_active and c2_settlements_iso >= 10) else ("moderate" if c2_access_cut_active else "baseline"),
                "affected_districts": c2_districts,
                "metrics": {
                    "n_impacted_corridors": len(c2_impacted_corridors),
                    "bridges_exposed_in_districts": c2_bridges_exposed,
                    "settlements_potentially_isolated": c2_settlements_iso,
                },
            },
        ]
    )

    edges.extend(
        [
            {
                "rule_id": "QCI-01",
                "chain_id": "quake_coseismic_isolation",
                "from": "c2_recent_eq_m45",
                "to": "c2_coseismic_slope_moraine",
                "trigger_rule": (
                    "observed earthquake M >= 4.5 (<=30 d, USGS or BIPAD NSC) within 100 km of "
                    "high/very-high/priority glacial lakes or steep high-isolation basins"
                ),
                "evidence_type": "observed",
                "active": c2_coseismic_active,
                "confidence": "high" if (c2_near_max_mag and c2_near_max_mag >= 5.5) else "moderate",
                "uncertainty_note": (
                    "100 km epicentral proximity is a screening radius, not a site-specific ground-motion "
                    "or PGA threshold; consult USGS ShakeMap, Nowicki Jessee (2018) ground-failure products, and DMG/NEMRC."
                ),
                "supporting_evidence": {
                    "qualifying_quakes": quake_near_lakes[:5],
                    "n_high_hazard_lakes_within_100km": len(quake_affected_lake_ids),
                },
            },
            {
                "rule_id": "QCI-02",
                "chain_id": "quake_coseismic_isolation",
                "from": "c2_coseismic_slope_moraine",
                "to": "c2_corridor_access_cut",
                "trigger_rule": (
                    "active coseismic slope/moraine screening overlapping routed GLOF/valley corridors "
                    "with moderate or high bridge-cut isolation risk"
                ),
                "evidence_type": "modelled_static",
                "active": c2_access_cut_active,
                "confidence": "moderate",
                "uncertainty_note": (
                    "Corridor access disruption reflects static OSM bridge/settlement screening along "
                    "steep valley roads; actual seismic road damage requires ground or SAR verification."
                ),
                "supporting_evidence": {
                    "n_impacted_corridors": len(c2_impacted_corridors),
                    "affected_districts": c2_districts,
                    "settlements_potentially_isolated": c2_settlements_iso,
                },
            },
        ]
    )

    c2_sev = (
        "critical" if (c2_access_cut_active and c2_near_max_mag and c2_near_max_mag >= 6.0)
        else ("high" if c2_access_cut_active else ("moderate" if c2_coseismic_active else "baseline"))
    )
    if c2_coseismic_active:
        c2_sum_en = (
            f"Active seismic-coseismic screening cascade: {len(quake_near_lakes)} recent M>={QUAKE_MIN_MAG} "
            f"earthquake(s) (max M{c2_near_max_mag:.1f}) within 100 km of {len(quake_affected_lake_ids)} high-hazard "
            f"glacial lakes across {', '.join(c2_districts) or 'Nepal region'}, exposing {c2_bridges_exposed} "
            f"corridor bridges and {c2_settlements_iso} potentially isolated settlements."
        )
        c2_sum_ne = (
            f"भूकम्प-प्रेरित पहिरो तथा करिडोर अवरोध शृङ्खला सक्रिय: {', '.join(_districts_ne(c2_districts)) or 'नेपाल क्षेत्र'} "
            f"जिल्लाका {len(quake_affected_lake_ids)} उच्च-जोखिम हिमतालहरूको १०० किमी भित्र अधिकतम "
            f"M{c2_near_max_mag:.1f} को {len(quake_near_lakes)} हालैको भूकम्प अभिलेख, {c2_bridges_exposed} पुलहरू र "
            f"{c2_settlements_iso} बस्तीहरू पहुँच विच्छेदको जोखिममा।"
        )
    elif c2_eq_active:
        c2_sum_en = (
            f"No active seismic-coseismic isolation cascade: {len(recent_quakes)} recent (<=30 d) "
            f"M>={QUAKE_MIN_MAG} regional earthquake(s) (max M{c2_max_mag:.1f}) recorded, but 0 within 100 km "
            f"of Nepal's high-hazard glacial lakes or steep isolation corridors."
        )
        c2_sum_ne = (
            f"हाल भूकम्प-प्रेरित पहिरो तथा करिडोर अवरोध शृङ्खला सक्रिय छैन: विगत ३० दिनमा क्षेत्रीय स्तरमा "
            f"अधिकतम M{c2_max_mag:.1f} का {len(recent_quakes)} भूकम्प अभिलेख भए पनि उच्च-जोखिम हिमताल तथा "
            f"पहाडी करिडोरको १०० किमी भित्र कुनै भूकम्प छैन।"
        )
    else:
        c2_sum_en = (
            "No active seismic-coseismic isolation cascade: 0 recent (<=30 d) M>=4.5 earthquakes detected "
            "within 100 km of Nepal's high-hazard glacial lakes or steep isolation corridors."
        )
        c2_sum_ne = (
            "हाल भूकम्प-प्रेरित पहिरो तथा करिडोर अवरोध शृङ्खला सक्रिय छैन: विगत ३० दिनमा उच्च-जोखिम "
            "हिमताल तथा पहाडी करिडोरको १०० किमी भित्र M>=४.५ को कुनै भूकम्प अभिलेख छैन।"
        )
    chains_summary["quake_coseismic_isolation"] = {
        "chain_id": "quake_coseismic_isolation",
        "title_en": "M >= 4.5 Earthquake → Coseismic Slope / Moraine Failure → Corridor Access Cut",
        "title_ne": "M >= ४.५ भूकम्प → भूकम्प-प्रेरित पहिरो / मोरेन अस्थिरता → करिडोर अवरोध",
        "dynamic_active": c2_coseismic_active,
        "severity": c2_sev,
        "affected_districts": c2_districts,
        "affected_districts_ne": _districts_ne(c2_districts),
        "summary_en": c2_sum_en,
        "summary_ne": c2_sum_ne,
    }
    if c2_coseismic_active:
        active_scenarios.append(
            {
                "scenario_id": "SCN-QUAKE-COSEISMIC-ISOLATION",
                "chain_id": "quake_coseismic_isolation",
                "severity": c2_sev,
                "status": "active_dynamic",
                "evidence_types": ["observed", "modelled_static"] if c2_access_cut_active else ["observed"],
                "confidence": "high" if (c2_near_max_mag and c2_near_max_mag >= 5.5) else "moderate",
                "affected_districts": c2_districts,
                "affected_districts_ne": _districts_ne(c2_districts),
                "affected_provinces": _provinces_for_districts(c2_districts, dist_to_prov),
                "active_rule_ids": [e["rule_id"] for e in edges if e["chain_id"] == "quake_coseismic_isolation" and e["active"]],
                "summary_en": c2_sum_en,
                "summary_ne": c2_sum_ne,
                "key_metrics": {
                    "n_quakes_m45_30d": len(recent_quakes),
                    "n_quakes_within_100km_high_hazard": len(quake_near_lakes),
                    "max_magnitude": c2_near_max_mag,
                    "high_hazard_lakes_within_100km": len(quake_affected_lake_ids),
                    "impacted_corridors": len(c2_impacted_corridors),
                    "settlements_potentially_isolated": c2_settlements_iso,
                },
                "statutory_reference_agencies": STATUTORY_AGENCIES,
            }
        )

    # =========================================================================
    # CHAIN 3: `glof_infra_isolation`
    # High/Very High GLOF susceptibility (+ warm rain-on-ice or seismic proximity)
    #   -> bridge & hydropower impact -> hospital access disruption
    # =========================================================================
    hm_prio_lakes = (hydromet or {}).get("priority_lakes") or []
    warm_rain_lakes = [l for l in hm_prio_lakes if l.get("warm_rain_on_ice")]
    seismic_prio_lakes = [
        lid for lid in quake_affected_lake_ids
        if (lakes_by_id.get(lid) or {}).get("priority") or (lakes_by_id.get(lid) or {}).get("ice_cored")
    ]
    glof_dynamic_active = bool(warm_rain_lakes or seismic_prio_lakes or bipad_sig["glof_alerts"])

    # High/Very High / Priority routed lakes in exposure_isolation.json
    susceptible_routed = [
        rec for rec in iso_lakes.values()
        if rec["hazard_susceptibility_static"].get("hazard") in ("high", "very high")
        or rec["hazard_susceptibility_static"].get("priority")
        or rec["hazard_susceptibility_static"].get("ice_cored")
    ]
    priority_routed = [
        rec for rec in susceptible_routed
        if rec["hazard_susceptibility_static"].get("priority")
        or rec["hazard_susceptibility_static"].get("ice_cored")
    ]
    high_iso_glof_corridors = [
        rec for rec in susceptible_routed
        if rec["road_cut_hospital_isolation"].get("corridor_disruption_risk") == "high"
    ]

    # Affected districts for GLOF chain (if dynamic active, narrow to dynamically stressed lakes;
    # otherwise report top priority/high-isolation districts for static susceptibility watch)
    if glof_dynamic_active:
        dyn_lids = (
            {l["id"] for l in warm_rain_lakes if l.get("id")}
            | set(seismic_prio_lakes)
        )
        c3_focus_corridors = [iso_lakes[lid] for lid in sorted(dyn_lids) if lid in iso_lakes]
        if not c3_focus_corridors:
            c3_focus_corridors = priority_routed
    else:
        c3_focus_corridors = priority_routed

    c3_districts_set: set[str] = set()
    for rec in c3_focus_corridors:
        for td in rec.get("traversed_districts") or []:
            c3_districts_set.add(td)
    c3_districts = sorted(c3_districts_set)

    # Deduplicated infrastructure across focus corridors (via district index for priority districts)
    c3_total_bridges = sum(
        int((iso_dist_by_name.get(d) or {}).get("unique_bridges_at_crossings") or 0)
        for d in c3_districts
    )
    c3_total_hydro_mw = round(
        sum(
            float((iso_dist_by_name.get(d) or {}).get("hydropower_mw_exposed") or 0.0)
            for d in c3_districts
        ),
        2,
    )
    c3_total_isolated = sum(
        int((iso_dist_by_name.get(d) or {}).get("unique_settlements_potentially_isolated") or 0)
        for d in c3_districts
    )

    c3_static_active = len(susceptible_routed) > 0
    c3_infra_pathway_active = bool(c3_static_active and (c3_total_bridges > 0 or c3_total_hydro_mw > 0))
    c3_hosp_pathway_active = bool(c3_infra_pathway_active and c3_total_isolated > 0)

    nodes.extend(
        [
            {
                "id": "c3_glof_high_susceptibility",
                "chain_id": "glof_infra_isolation",
                "stage": "trigger",
                "label_en": "High / Very High & Priority GLOF Susceptibility (Static)",
                "label_ne": "उच्च / अति-उच्च तथा प्राथमिकता हिमताल विस्फोटन संवेदनशीलता (स्थिर)",
                "evidence_type": "modelled_static",
                "active": c3_static_active,
                "severity": "watch",
                "affected_districts": c3_districts,
                "metrics": {
                    "n_high_or_very_high_routed_lakes": len(susceptible_routed),
                    "n_priority_or_ice_cored_routed_lakes": len(priority_routed),
                    "n_high_disruption_glof_corridors": len(high_iso_glof_corridors),
                },
            },
            {
                "id": "c3_glof_thermal_seismic_driver",
                "chain_id": "glof_infra_isolation",
                "stage": "trigger",
                "label_en": "Dynamic Thermal (Warm Rain-on-Ice) / Seismic GLOF Stress",
                "label_ne": "गतिशील तापीय (हिउँमाथि तातो वर्षा) वा भूकम्पीय हिमताल चाप",
                "evidence_type": "observed" if (seismic_prio_lakes or bipad_sig["glof_alerts"]) else "forecast",
                "active": glof_dynamic_active,
                "severity": "high" if glof_dynamic_active else "baseline",
                "affected_districts": sorted(
                    {
                        str(l.get("district"))
                        for l in warm_rain_lakes
                        if l.get("district")
                    }
                    | {
                        str((lakes_by_id.get(lid) or {}).get("district"))
                        for lid in seismic_prio_lakes
                        if (lakes_by_id.get(lid) or {}).get("district")
                    }
                ),
                "metrics": {
                    "n_warm_rain_on_ice_priority_lakes": len(warm_rain_lakes),
                    "warm_rain_lake_ids": [l["id"] for l in warm_rain_lakes],
                    "n_priority_lakes_within_100km_m45_eq": len(seismic_prio_lakes),
                    "n_bipad_glof_alerts": len(bipad_sig["glof_alerts"]),
                },
            },
            {
                "id": "c3_glof_bridge_hydro_impact",
                "chain_id": "glof_infra_isolation",
                "stage": "intermediate",
                "label_en": "Downstream Bridge & Hydropower Corridor Impact Screening",
                "label_ne": "तल्लो तटीय पुल तथा जलविद्युत करिडोर प्रभाव जाँच",
                "evidence_type": "modelled_static",
                "active": c3_infra_pathway_active,
                "severity": "high" if glof_dynamic_active else "watch",
                "affected_districts": c3_districts,
                "metrics": {
                    "unique_bridges_in_priority_districts": c3_total_bridges,
                    "hydropower_mw_in_priority_districts": c3_total_hydro_mw,
                },
            },
            {
                "id": "c3_hospital_access_disruption",
                "chain_id": "glof_infra_isolation",
                "stage": "impact",
                "label_en": "Upstream Settlement Hospital Access Disruption",
                "label_ne": "माथिल्लो उपत्यकाका बस्तीहरूमा अस्पताल पहुँच विच्छेद",
                "evidence_type": "modelled_static",
                "active": c3_hosp_pathway_active,
                "severity": "high" if glof_dynamic_active else "watch",
                "affected_districts": c3_districts,
                "metrics": {
                    "unique_settlements_potentially_isolated": c3_total_isolated,
                    "n_priority_corridors_evaluated": len(c3_focus_corridors),
                },
            },
        ]
    )

    edges.extend(
        [
            {
                "rule_id": "GII-01",
                "chain_id": "glof_infra_isolation",
                "from": "c3_glof_high_susceptibility",
                "to": "c3_glof_bridge_hydro_impact",
                "trigger_rule": (
                    "routed glacial lakes with Rounce hazard in {high, very high} or PFV >= 10 Mm3 "
                    "or documented ice-cored moraine intersecting corridor bridges or hydropower"
                ),
                "evidence_type": "modelled_static",
                "active": c3_infra_pathway_active,
                "confidence": "moderate",
                "uncertainty_note": (
                    "Static structural screening pathway (1 km search corridor, NOT a 2D hydrodynamic "
                    "inundation boundary); expresses standing exposure rather than imminent outburst probability."
                ),
                "supporting_evidence": {
                    "n_susceptible_routed_lakes": len(susceptible_routed),
                    "n_priority_or_ice_cored_routed": len(priority_routed),
                    "bridges_in_priority_districts": c3_total_bridges,
                    "hydropower_mw_in_priority_districts": c3_total_hydro_mw,
                },
            },
            {
                "rule_id": "GII-02",
                "chain_id": "glof_infra_isolation",
                "from": "c3_glof_thermal_seismic_driver",
                "to": "c3_glof_bridge_hydro_impact",
                "trigger_rule": (
                    "warm_rain_on_ice == True on priority lakes OR M >= 4.5 earthquake within 100 km "
                    "of priority/ice-cored lakes OR official BIPAD GLOF alert (hazard=26)"
                ),
                "evidence_type": "observed" if (seismic_prio_lakes or bipad_sig["glof_alerts"]) else "forecast",
                "active": glof_dynamic_active,
                "confidence": "moderate" if glof_dynamic_active else "low",
                "uncertainty_note": (
                    "Warm rain-on-ice (liquid_rain_12d >= 10 mm and freezing_margin >= 300 m) and "
                    "100 km seismic proximity are environmental stress indicators, not deterministic breach forecasts."
                ),
                "supporting_evidence": {
                    "warm_rain_lakes": [l["id"] for l in warm_rain_lakes],
                    "seismic_priority_lakes": seismic_prio_lakes,
                    "bipad_glof_alerts": len(bipad_sig["glof_alerts"]),
                },
            },
            {
                "rule_id": "GII-03",
                "chain_id": "glof_infra_isolation",
                "from": "c3_glof_bridge_hydro_impact",
                "to": "c3_hospital_access_disruption",
                "trigger_rule": (
                    "corridor bridges_at_corridor_crossing > 0 AND upstream_settlements_potentially_isolated > 0 "
                    "along susceptible GLOF corridors"
                ),
                "evidence_type": "modelled_static",
                "active": c3_hosp_pathway_active,
                "confidence": "moderate",
                "uncertainty_note": (
                    "Isolation counts reflect OSM-mapped settlements and hospitals using geodesic distance "
                    "and valley bridge crossings; actual emergency access also depends on airlift/alternative tracks."
                ),
                "supporting_evidence": {
                    "unique_settlements_potentially_isolated": c3_total_isolated,
                    "affected_districts": c3_districts,
                },
            },
        ]
    )

    c3_sev = "high" if glof_dynamic_active else ("watch" if c3_hosp_pathway_active else "baseline")
    c3_sum_en = (
        f"Active dynamic GLOF stress watch across {', '.join(c3_districts)}: "
        f"{len(warm_rain_lakes)} warm rain-on-ice priority lake(s) and {len(seismic_prio_lakes)} "
        f"priority/ice-cored lake(s) within 100 km of M>=4.5 seismicity, with downstream screening exposure "
        f"of {c3_total_bridges} bridges, {c3_total_hydro_mw:.1f} MW hydropower, and {c3_total_isolated} "
        f"potentially isolated settlements."
        if glof_dynamic_active
        else (
            f"Standing static GLOF–infrastructure–hospital susceptibility watch (no active warm rain-on-ice "
            f"or M>=4.5 seismic trigger today): {len(priority_routed)} priority/ice-cored routed corridors "
            f"span {len(c3_districts)} districts ({', '.join(c3_districts[:6])}"
            f"{'...' if len(c3_districts) > 6 else ''}), exposing {c3_total_bridges} corridor bridges, "
            f"{c3_total_hydro_mw:.1f} MW hydropower, and {c3_total_isolated} settlements potentially isolated from hospitals."
        )
    )
    c3_sum_ne = (
        f"{', '.join(_districts_ne(c3_districts))} जिल्लाहरूमा गतिशील हिमताल-पूर्वाधार-अस्पताल जोखिम सक्रिय: "
        f"{len(warm_rain_lakes)} हिउँमाथि तातो वर्षा र {len(seismic_prio_lakes)} भूकम्प-प्रभावित प्राथमिकता हिमताल, "
        f"तल्लो तटीय क्षेत्रमा {c3_total_bridges} पुल, {c3_total_hydro_mw:.1f} मेगावाट जलविद्युत र "
        f"{c3_total_isolated} बस्तीहरू अस्पताल पहुँच विच्छेदको जोखिममा।"
        if glof_dynamic_active
        else (
            f"स्थिर हिमताल-पूर्वाधार-अस्पताल संवेदनशीलता निगरानी (हाल सक्रिय तातो वर्षा वा M>=४.५ भूकम्पीय "
            f"उत्प्रेरक छैन): {len(priority_routed)} प्राथमिकता/हिउँ-कोरयुक्त हिमताल करिडोरहरू "
            f"{len(c3_districts)} जिल्लाहरूमा फैलिएका छन्, जसमा {c3_total_bridges} पुल, "
            f"{c3_total_hydro_mw:.1f} मेगावाट जलविद्युत र {c3_total_isolated} बस्तीहरू अस्पताल पहुँच विच्छेदको जोखिममा छन्।"
        )
    )
    chains_summary["glof_infra_isolation"] = {
        "chain_id": "glof_infra_isolation",
        "title_en": "GLOF Susceptibility (+ Thermal/Seismic Stress) → Bridges & Hydropower → Hospital Isolation",
        "title_ne": "हिमताल संवेदनशीलता (+ तापीय/भूकम्पीय चाप) → पुल तथा जलविद्युत → अस्पताल पहुँच विच्छेद",
        "dynamic_active": glof_dynamic_active,
        "static_susceptibility_present": c3_hosp_pathway_active,
        "severity": c3_sev,
        "affected_districts": c3_districts,
        "affected_districts_ne": _districts_ne(c3_districts),
        "summary_en": c3_sum_en,
        "summary_ne": c3_sum_ne,
    }
    if glof_dynamic_active or c3_hosp_pathway_active:
        active_scenarios.append(
            {
                "scenario_id": "SCN-GLOF-INFRA-ISOLATION",
                "chain_id": "glof_infra_isolation",
                "severity": c3_sev,
                "status": "active_dynamic" if glof_dynamic_active else "static_susceptibility_watch",
                "evidence_types": sorted(
                    {e["evidence_type"] for e in edges if e["chain_id"] == "glof_infra_isolation" and e["active"]}
                ),
                "confidence": "moderate",
                "affected_districts": c3_districts,
                "affected_districts_ne": _districts_ne(c3_districts),
                "affected_provinces": _provinces_for_districts(c3_districts, dist_to_prov),
                "active_rule_ids": [e["rule_id"] for e in edges if e["chain_id"] == "glof_infra_isolation" and e["active"]],
                "summary_en": c3_sum_en,
                "summary_ne": c3_sum_ne,
                "key_metrics": {
                    "dynamic_trigger_active": glof_dynamic_active,
                    "warm_rain_on_ice_priority_lakes": len(warm_rain_lakes),
                    "seismic_priority_lakes_100km": len(seismic_prio_lakes),
                    "priority_or_ice_cored_routed_lakes": len(priority_routed),
                    "bridges_in_priority_districts": c3_total_bridges,
                    "hydropower_mw_in_priority_districts": c3_total_hydro_mw,
                    "settlements_potentially_isolated": c3_total_isolated,
                },
                "statutory_reference_agencies": STATUTORY_AGENCIES,
            }
        )

    # Sort scenarios strictly by severity descending, dynamic before static
    active_scenarios.sort(
        key=lambda s: (
            SEVERITY_RANK.get(s["severity"], 0),
            1 if s["status"] == "active_dynamic" else 0,
            len(s.get("affected_districts") or []),
        ),
        reverse=True,
    )

    ev_type_counts = Counter(e["evidence_type"] for e in edges)
    active_edges = [e for e in edges if e["active"]]
    active_dynamic_edges = [e for e in active_edges if e["evidence_type"] != "modelled_static"]

    return {
        "schema_version": SCHEMA_VERSION,
        "generated_utc": now_iso,
        "mode": mode,
        "data_class": "multi_hazard_cascade_screening",
        "epistemic_notice": (
            "Directed screening cascade graph combining observed triggers, meteorological/hydrological "
            "forecasts, and static exposure/isolation models. Not a probabilistic multi-hazard forecast "
            "or statutory warning; always verify against DHM, DMG/NEMRC, and NDRRMA BIPAD Portal."
        ),
        "summary": {
            "n_chains": 3,
            "n_nodes": len(nodes),
            "n_edges": len(edges),
            "n_active_edges": len(active_edges),
            "n_active_dynamic_edges": len(active_dynamic_edges),
            "n_active_scenarios": len(active_scenarios),
            "n_active_dynamic_scenarios": sum(1 for s in active_scenarios if s["status"] == "active_dynamic"),
            "edges_by_evidence_type": dict(ev_type_counts),
            "highest_severity": active_scenarios[0]["severity"] if active_scenarios else "baseline",
        },
        "chains": chains_summary,
        "nodes": nodes,
        "edges": edges,
        "active_scenarios": active_scenarios,
        "provenance": {
            "schema_version": SCHEMA_VERSION,
            "generated_utc": now_iso,
            "mode": mode,
            "data_class": "multi_hazard_cascade_screening",
            "license_ref": "CC-BY-4.0 (TRĀYA graph); upstream ODbL 1.0, Copernicus EMS, Open-Meteo, USGS, GDACS, BIPAD NDRRMA",
            "sources": source_meta or [],
        },
    }


def build_cascades(
    offline: bool = True,
    out_path: str = OUT_JSON,
    data_dir: str | None = None,
) -> dict[str, Any]:
    """Load workspace data products, evaluate the 3 cascade chains, and write `data/cascades.json`."""
    ddir = data_dir or C.DATA
    rivers, has_rivers = _load_json_optional(os.path.join(ddir, "rivers_watch.json"))
    hydromet, has_hm = _load_json_optional(os.path.join(ddir, "hydromet_weekly.json"))
    landslides, has_ls = _load_json_optional(os.path.join(ddir, "landslides.json"))
    lakes_raw, has_lakes = _load_json_optional(os.path.join(ddir, "lakes_core.json"))
    expo_iso, has_iso = _load_json_optional(os.path.join(ddir, "exposure_isolation.json"))
    bipad, has_bipad = _load_json_optional(os.path.join(ddir, "bipad_official.json"))
    gdacs, has_gdacs = _load_json_optional(os.path.join(ddir, "gdacs_alerts.json"))

    lakes_fc = RW.unpack_lakes_core(lakes_raw) if isinstance(lakes_raw, dict) else None

    live_usgs: list[dict[str, Any]] | None = None
    live_usgs_ok = False
    if not offline:
        try:
            live_usgs = fetch_live_usgs_m45(days=14)
            live_usgs_ok = True
        except Exception as exc:
            print(f"  [cascades] live USGS M>=4.5 fetch failed ({exc}); using snapshot", file=sys.stderr)

    bipad_prov = (
        bipad.get("provenance")
        if isinstance(bipad, dict) and isinstance(bipad.get("provenance"), dict)
        else {}
    )
    bipad_updated_utc = bipad_prov.get("retrieved_at_utc") or (
        bipad.get("updated_utc") if isinstance(bipad, dict) else None
    )

    source_meta = [
        {"provider_id": "glofas_rivers_watch", "path": "data/rivers_watch.json", "available": has_rivers, "updated_utc": (rivers or {}).get("updated_utc")},
        {"provider_id": "open_meteo_hydromet", "path": "data/hydromet_weekly.json", "available": has_hm, "updated_utc": (hydromet or {}).get("updated_utc")},
        {"provider_id": "traya_landslides", "path": "data/landslides.json", "available": has_ls, "updated_utc": (landslides or {}).get("updated_utc")},
        {"provider_id": "traya_lakes_core", "path": "data/lakes_core.json", "available": has_lakes},
        {"provider_id": "traya_exposure_isolation", "path": "data/exposure_isolation.json", "available": has_iso, "updated_utc": (expo_iso or {}).get("generated_utc")},
        {"provider_id": "bipad_ndrrma", "path": "data/bipad_official.json", "available": has_bipad, "updated_utc": bipad_updated_utc},
        {"provider_id": "gdacs_usgs_alerts", "path": "data/gdacs_alerts.json", "available": has_gdacs, "updated_utc": (gdacs or {}).get("updated_utc")},
        {"provider_id": "usgs_fdsn_live", "endpoint": C.USGS_QUERY, "available": live_usgs_ok, "mode": "live" if live_usgs_ok else "offline_snapshot"},
    ]

    payload = evaluate_cascades(
        rivers_watch=rivers,
        hydromet=hydromet,
        landslides=landslides,
        lakes_fc=lakes_fc,
        exposure_isolation=expo_iso,
        bipad=bipad,
        gdacs=gdacs,
        live_usgs=live_usgs,
        source_meta=source_meta,
        mode="live" if live_usgs_ok else "offline",
    )
    _atomic_write_json(out_path, payload)
    return payload


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="Nepal TRĀYA 2.0 multi-hazard cascade graph engine")
    ap.add_argument("--offline", action="store_true", help="Zero network calls; use local data snapshots")
    ap.add_argument("--live", action="store_true", help="Also query live USGS FDSN M>=4.5 earthquakes")
    ap.add_argument("--out", default=OUT_JSON, help="Output JSON path")
    args = ap.parse_args(argv)

    offline = not args.live or args.offline
    res = build_cascades(offline=offline, out_path=args.out)
    s = res["summary"]
    print(
        f"[cascades] wrote {args.out}: nodes={s['n_nodes']}, edges={s['n_edges']}, "
        f"active_edges={s['n_active_edges']} (dynamic={s['n_active_dynamic_edges']}), "
        f"scenarios={s['n_active_scenarios']} (highest={s['highest_severity']})"
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
