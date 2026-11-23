"""
Tsho Rolpa 2D Hydrodynamic Pre-Simulation Pilot Benchmark & Scenario Framework
for TRĀYA 2.0 (`TRAYA-011`).

Extracts real Tsho Rolpa parameters (`GL_27.86153_86.47679` or nearest canonical
match `GL_27.86029_86.47725` in `data/lakes_core.json`, `data/routes.json`,
`data/exposure_isolation.json`, `data/hydromet_weekly.json`, `data/validation.json`,
`data/glof_history.json`, and `cache/overpass/hydropower.json`) alongside
peer-reviewed published benchmarks (Damen 1992; Rana et al. 2000 3 m artificial
spillway lowering; Reynolds 1999; Yamada 1998; Fujita et al. 2013; Shrestha &
Nakagawa 2014; Rounce et al. 2016; Veh et al. 2020) and Rolwaling–Tama Koshi
valley checkpoints (Na, Beding, Gonggar/Gongar, Upper Tamakoshi HPP 456 MW,
Singati, Dolakha corridor).

Explicit epistemic framing:
  * `data_class`: `"static_assessment"`
  * `status_note`: `"Pre-simulation 2D hydrodynamic case-study benchmark & scenario framework (LISFLOOD-FP / BASEMENT target) — NOT yet a 2D inundation map"`

Pure Python 3.12 standard library only (zero third-party dependencies).
Output: `data/tsho_rolpa_pilot.json` (atomic UTF-8 JSON).
"""
from __future__ import annotations

import argparse
import datetime as dt
import json
import math
import os
import sys
import tempfile
from typing import Any

SRC_DIR = os.path.dirname(os.path.abspath(__file__))
if SRC_DIR not in sys.path:
    sys.path.insert(0, SRC_DIR)

import config as C
import floods as FL
import refresh_weekly as RW
import seismic as SZ

SCHEMA_VERSION = "tsho_rolpa_pilot.v1"
DATA_CLASS = "static_assessment"
STATUS_NOTE = (
    "Pre-simulation 2D hydrodynamic case-study benchmark & scenario framework "
    "(LISFLOOD-FP / BASEMENT target) — NOT yet a 2D inundation map"
)
TARGET_LAKE_IDS = ("GL_27.86153_86.47679", "GL_27.86029_86.47725")
TARGET_REF_COORD = (86.47679, 27.86153)  # (lon, lat)

OUT_JSON = os.path.join(C.DATA, "tsho_rolpa_pilot.json")


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


def _load_json_optional(path: str) -> Any:
    if not os.path.exists(path):
        return None
    with open(path, encoding="utf-8") as fh:
        return json.load(fh)


def find_tsho_rolpa_feature(lakes_fc: dict[str, Any]) -> tuple[dict[str, Any], str, float]:
    """Locate Tsho Rolpa by canonical ID, name match, or nearest coordinate within 3 km."""
    feats = lakes_fc.get("features") or []
    by_id = {f["properties"]["id"]: f for f in feats if (f.get("properties") or {}).get("id")}

    for tid in TARGET_LAKE_IDS:
        if tid in by_id:
            p = by_id[tid]["properties"]
            d_km = SZ.haversine_km(TARGET_REF_COORD[0], TARGET_REF_COORD[1], float(p["lon"]), float(p["lat"]))
            match_mode = "exact_target_id" if tid == TARGET_LAKE_IDS[0] else "canonical_inventory_id"
            return (by_id[tid], match_mode, round(d_km, 3))

    for f in feats:
        name = str((f.get("properties") or {}).get("name") or "").strip().lower()
        if "tsho rolpa" in name:
            p = f["properties"]
            d_km = SZ.haversine_km(TARGET_REF_COORD[0], TARGET_REF_COORD[1], float(p["lon"]), float(p["lat"]))
            return (f, "name_match", round(d_km, 3))

    best_f = None
    best_d = float("inf")
    for f in feats:
        p = f.get("properties") or {}
        if p.get("lon") is None or p.get("lat") is None:
            continue
        d_km = SZ.haversine_km(TARGET_REF_COORD[0], TARGET_REF_COORD[1], float(p["lon"]), float(p["lat"]))
        if d_km < best_d:
            best_d = d_km
            best_f = f
    if best_f is None or best_d > 3.0:
        raise RuntimeError("Could not locate Tsho Rolpa within 3 km of target coordinates in lakes_core.json")
    return (best_f, "nearest_spatial_match", round(best_d, 3))


def _arrival_bracket_min(along_km: float) -> dict[str, float]:
    """First-order surge-front arrival bracket using C.FRONT_VELOCITY_MS (2, 5, 10 m/s)."""
    v_slow, v_mid, v_fast = C.FRONT_VELOCITY_MS
    dist_m = along_km * 1000.0
    return {
        "fast_10ms_min": round(dist_m / v_fast / 60.0, 1),
        "observed_ref_5ms_min": round(dist_m / v_mid / 60.0, 1),
        "slow_2ms_min": round(dist_m / v_slow / 60.0, 1),
    }


def _extract_route_checkpoints(
    route: dict[str, Any],
    expo_by_id: dict[int, dict[str, Any]],
    overpass_hydro: dict[str, Any] | None,
) -> list[dict[str, Any]]:
    """Anchor key Rolwaling–Tama Koshi valley checkpoints to exact TRĀYA route distances."""
    hits_by_name: dict[str, dict[str, Any]] = {}
    for idx, along_km, off_m in route.get("exp") or []:
        o = expo_by_id.get(idx)
        if not o:
            continue
        name = str(o.get("name") or "").strip()
        if not name:
            continue
        key = name.lower()
        if key not in hits_by_name or along_km < hits_by_name[key]["along_km"]:
            hits_by_name[key] = {
                "name": name,
                "name_ne": o.get("name_ne") or "",
                "kind": o.get("kind"),
                "sub": o.get("sub"),
                "lon": o.get("lon"),
                "lat": o.get("lat"),
                "along_km": round(float(along_km), 1),
                "offset_m": int(off_m),
            }

    # Locate Upper Tamakoshi HPP (456 MW) from Overpass hydropower cache
    utk_osm: dict[str, Any] | None = None
    for el in (overpass_hydro or {}).get("elements") or []:
        tags = el.get("tags") or {}
        if "upper tamakoshi" in str(tags.get("name") or "").lower():
            ctr = el if el.get("type") == "node" else (el.get("center") or {})
            utk_osm = {
                "osm_id": f"{el['type'][0]}{el['id']}",
                "headworks_lon": round(float(ctr.get("lon", 86.2125)), 4),
                "headworks_lat": round(float(ctr.get("lat", 27.9233)), 4),
                "tagged_output": tags.get("plant:output:electricity") or "456 MW",
            }
            break

    def _hit(key: str, default_km: float, default_lon: float, default_lat: float) -> dict[str, Any]:
        h = hits_by_name.get(key.lower())
        if h:
            return h
        return {
            "name": key,
            "name_ne": "",
            "kind": "checkpoint",
            "sub": "",
            "lon": default_lon,
            "lat": default_lat,
            "along_km": default_km,
            "offset_m": None,
        }

    na = _hit("Na", 6.3, 86.4268, 27.8815)
    beding = _hit("Beding", 12.2, 86.3755, 27.9028)
    chetchet = _hit("Chetchet", 28.8, 86.2210, 27.8712)
    gonggar = _hit("Gonggar", 31.6, 86.2178, 27.8459)
    singati = _hit("Singati", 46.3, 86.1639, 27.7362)
    singati_hosp = _hit("Singati Community Hospital", 46.6, 86.1606, 27.7362)
    khimti = _hit("Khimti", 77.2, 86.1016, 27.4920)
    manthali = _hit("Manthali", 91.4, 86.0608, 27.3816)
    khurkot = _hit("Khurkot", 102.6, 85.9936, 27.3307)

    # Dolakha / Tamakoshi–NH23 crossing (62.4 km along route near Charikot / Dolakha Bazar)
    dolakha_corridor_km = 62.4
    dolakha_lon, dolakha_lat = 86.0789, 27.6200
    for idx, along_km, _off_m in route.get("exp") or []:
        o = expo_by_id.get(idx)
        if o and o.get("name") == "NH23":
            dolakha_corridor_km = round(float(along_km), 1)
            dolakha_lon, dolakha_lat = o["lon"], o["lat"]
            break

    checkpoints: list[dict[str, Any]] = [
        {
            "id": "cp_na",
            "name": "Na",
            "name_ne": "ना",
            "valley_reach": "Upper Rolwaling Khola",
            "category": "settlement",
            "district": "Dolakha",
            "along_river_km": na["along_km"],
            "corridor_offset_m": na["offset_m"],
            "lon": na["lon"],
            "lat": na["lat"],
            "approx_elev_m": 4180,
            "first_order_arrival_bracket": _arrival_bracket_min(na["along_km"]),
            "significance": (
                "First inhabited alpine settlement below Tsho Rolpa terminal moraine; "
                "high-energy near-field debris/surge impact zone with minimal lead time."
            ),
        },
        {
            "id": "cp_beding",
            "name": "Beding",
            "name_ne": "बेदिङ",
            "valley_reach": "Middle Rolwaling Khola",
            "category": "settlement",
            "district": "Dolakha",
            "along_river_km": beding["along_km"],
            "corridor_offset_m": beding["offset_m"],
            "lon": beding["lon"],
            "lat": beding["lat"],
            "approx_elev_m": 3700,
            "first_order_arrival_bracket": _arrival_bracket_min(beding["along_km"]),
            "significance": (
                "Main Rolwaling Sherpa village (~12 km downstream); previously impacted by the "
                "1991 Chubung GLOF and dependent on single valley trail/bridge egress."
            ),
        },
        {
            "id": "cp_gongar",
            "name": "Gongar (Gonggar)",
            "name_ne": "गोङ्गर",
            "valley_reach": "Rolwaling–Tama Koshi Confluence (below Chetchet)",
            "category": "settlement_and_road_hub",
            "district": "Dolakha",
            "along_river_km": gonggar["along_km"],
            "corridor_offset_m": gonggar["offset_m"],
            "lon": gonggar["lon"],
            "lat": gonggar["lat"],
            "approx_elev_m": 1300,
            "first_order_arrival_bracket": _arrival_bracket_min(gonggar["along_km"]),
            "significance": (
                f"Tama Koshi valley floor immediately below the Chetchet confluence ({chetchet['along_km']} km); "
                "hosts NH28 / F106 vehicular river bridges and the Upper Tamakoshi HPP powerhouse/tailrace complex."
            ),
        },
        {
            "id": "cp_upper_tamakoshi_hpp",
            "name": "Upper Tamakoshi HPP (456 MW)",
            "name_ne": "माथिल्लो तामाकोशी जलविद्युत आयोजना (४५६ मेगावाट)",
            "valley_reach": "Tama Koshi — Gongar Tailrace/Powerhouse & Lamabagar Headworks",
            "category": "strategic_hydropower",
            "district": "Dolakha",
            "capacity_mw": 456.0,
            "along_river_km": gonggar["along_km"],
            "corridor_offset_m": gonggar["offset_m"],
            "lon": gonggar["lon"],
            "lat": gonggar["lat"],
            "osm_headworks_ref": utk_osm,
            "first_order_arrival_bracket": _arrival_bracket_min(gonggar["along_km"]),
            "significance": (
                "Nepal's largest operating hydropower plant (456 MW). Note on spatial geometry: the "
                "OSM plant polygon tags the Lamabagar headworks dam (~5.8 km upstream of the Rolwaling "
                "confluence on the Tama Koshi mainstem), whereas the underground powerhouse portal, "
                "tailrace outfall, switchyard, and access road lie directly on the Tsho Rolpa GLOF "
                "corridor at Gongar (~31.6 km downstream) and require 2D tailrace-backwater & sediment modelling."
            ),
        },
        {
            "id": "cp_singati",
            "name": "Singati (Town, Bridge & Community Hospital)",
            "name_ne": "सिँगटी (बजार, पुल र सामुदायिक अस्पताल)",
            "valley_reach": "Middle Tama Koshi",
            "category": "market_bridge_hospital_hub",
            "district": "Dolakha",
            "along_river_km": singati["along_km"],
            "corridor_offset_m": singati["offset_m"],
            "lon": singati["lon"],
            "lat": singati["lat"],
            "approx_elev_m": 950,
            "hospital_along_km": singati_hosp["along_km"],
            "first_order_arrival_bracket": _arrival_bracket_min(singati["along_km"]),
            "significance": (
                "Major commercial, road-bridge (Singati Bridge at 46.2 km), and healthcare node "
                "(Singati Community Hospital at 46.6 km); loss of Singati crossing severs upper "
                "Dolakha / Rolwaling emergency hospital access."
            ),
        },
        {
            "id": "cp_dolakha_corridor",
            "name": "Dolakha (Tamakoshi Bazar / NH23 Bridge Corridor)",
            "name_ne": "दोलखा (तामाकोशी बजार / NH23 पुल करिडोर)",
            "valley_reach": "Lower-Middle Tama Koshi (Dolakha HQ Valley Floor)",
            "category": "district_corridor_and_bridge",
            "district": "Dolakha",
            "along_river_km": dolakha_corridor_km,
            "corridor_offset_m": 134,
            "lon": dolakha_lon,
            "lat": dolakha_lat,
            "approx_elev_m": 820,
            "first_order_arrival_bracket": _arrival_bracket_min(dolakha_corridor_km),
            "significance": (
                "Primary NH23 arterial bridge & valley-floor hospital corridor serving Charikot / "
                "Dolakha district headquarters (situated upslope above Tama Koshi gorge)."
            ),
        },
        {
            "id": "cp_khimti",
            "name": "Khimti (Tama Koshi–Khimti Confluence)",
            "name_ne": "खिम्ती",
            "valley_reach": "Lower Tama Koshi",
            "category": "settlement_and_energy_corridor",
            "district": "Ramechhap",
            "along_river_km": khimti["along_km"],
            "corridor_offset_m": khimti["offset_m"],
            "lon": khimti["lon"],
            "lat": khimti["lat"],
            "approx_elev_m": 620,
            "first_order_arrival_bracket": _arrival_bracket_min(khimti["along_km"]),
            "significance": "Valley settlement and NH28 crossings near the Khimti I (60 MW) hydropower corridor.",
        },
        {
            "id": "cp_manthali",
            "name": "Manthali",
            "name_ne": "मन्थली",
            "valley_reach": "Lower Tama Koshi",
            "category": "district_headquarters",
            "district": "Ramechhap",
            "along_river_km": manthali["along_km"],
            "corridor_offset_m": manthali["offset_m"],
            "lon": manthali["lon"],
            "lat": manthali["lat"],
            "approx_elev_m": 495,
            "first_order_arrival_bracket": _arrival_bracket_min(manthali["along_km"]),
            "significance": "Ramechhap district headquarters, riverfront airport, and regional road junction.",
        },
        {
            "id": "cp_khurkot",
            "name": "Khurkot (Sun Koshi Confluence & BP Highway)",
            "name_ne": "खुर्कोट (सुनकोशी दोभान र बीपी राजमार्ग)",
            "valley_reach": "Tama Koshi–Sun Koshi Confluence",
            "category": "national_highway_junction",
            "district": "Sindhuli",
            "along_river_km": khurkot["along_km"],
            "corridor_offset_m": khurkot["offset_m"],
            "lon": khurkot["lon"],
            "lat": khurkot["lat"],
            "approx_elev_m": 465,
            "first_order_arrival_bracket": _arrival_bracket_min(khurkot["along_km"]),
            "significance": (
                "Confluence of Tama Koshi with Sun Koshi and strategic BP Highway (NH03) trunk bridge "
                "linking Kathmandu Valley to eastern Nepal; far-field attenuated surge checkpoint (~103 km)."
            ),
        },
    ]
    return checkpoints


def build_tsho_rolpa_pilot(
    data_dir: str | None = None,
    overpass_dir: str | None = None,
    out_path: str = OUT_JSON,
) -> dict[str, Any]:
    """Assemble `data/tsho_rolpa_pilot.json` benchmark & 2D pre-simulation scenario spec."""
    ddir = data_dir or C.DATA
    odir = overpass_dir or os.path.join(C.CACHE, "overpass")

    lakes_raw = _load_json_optional(os.path.join(ddir, "lakes_core.json"))
    if not lakes_raw:
        raise FileNotFoundError("data/lakes_core.json is required")
    lakes_fc = RW.unpack_lakes_core(lakes_raw)
    feat, match_mode, match_dist_km = find_tsho_rolpa_feature(lakes_fc)
    p = feat["properties"]
    lid = p["id"]

    routes = _load_json_optional(os.path.join(ddir, "routes.json")) or {}
    route = routes.get(lid) or {}

    expo_list = _load_json_optional(os.path.join(ddir, "exposure.json")) or []
    expo_by_id = {o["i"]: o for o in expo_list if "i" in o}

    expo_iso_doc = _load_json_optional(os.path.join(ddir, "exposure_isolation.json")) or {}
    tr_iso = (expo_iso_doc.get("lakes") or {}).get(lid)

    hydromet = _load_json_optional(os.path.join(ddir, "hydromet_weekly.json")) or {}
    hm_match = next(
        (l for l in (hydromet.get("priority_lakes") or []) if l.get("id") == lid),
        None,
    )

    validation = _load_json_optional(os.path.join(ddir, "validation.json")) or {}
    rounce_bench = next(
        (r for r in (validation.get("rounce") or []) if r.get("lake_id") == lid),
        None,
    )
    fujita_bench = next(
        (r for r in (validation.get("fujita2") or []) if r.get("lake_id") == lid),
        None,
    )

    glof_hist = _load_json_optional(os.path.join(ddir, "glof_history.json")) or []
    nearby_historical_glofs = [
        g
        for g in glof_hist
        if g.get("lon") is not None
        and g.get("lat") is not None
        and SZ.haversine_km(float(p["lon"]), float(p["lat"]), float(g["lon"]), float(g["lat"])) <= 25.0
    ]

    overpass_hydro = _load_json_optional(os.path.join(odir, "hydropower.json"))
    checkpoints = _extract_route_checkpoints(route, expo_by_id, overpass_hydro)

    now_utc = dt.datetime.now(dt.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")

    # Breach scenario matrix combining TRĀYA Veh et al. (2020) breach-fraction discharges
    # with published literature breach-depth benchmarks (Shrestha & Nakagawa 2014; Damen/Rana 2000).
    breach_scenarios = [
        {
            "scenario_id": "TR-S1-PARTIAL-10PCT",
            "label": "Minor / Spillway-Notch Partial Breach (10% depth fraction)",
            "breach_fraction": 0.10,
            "approx_breach_depth_m": round(0.10 * float(p.get("depth_m") or 122), 1),
            "traya_empirical_qp_m3s": p.get("qp_10"),
            "published_analog": "Post-2000 lowered-spillway partial erosion / ~10-15 m overtopping breach",
            "target_2d_solver_role": "Baseline serviceability & bridge freeboard check (LISFLOOD-FP / BASEMENT)",
        },
        {
            "scenario_id": "TR-S2-MODERATE-30PCT",
            "label": "Moderate Moraine-Dam Breach (30% depth fraction)",
            "breach_fraction": 0.30,
            "approx_breach_depth_m": round(0.30 * float(p.get("depth_m") or 122), 1),
            "traya_empirical_qp_m3s": p.get("qp_30"),
            "published_analog": "Shrestha & Nakagawa (2014) 20-30 m moraine-dam breach benchmark (~30-35 Mm3 drained)",
            "target_2d_solver_role": "Primary design-basis GLOF hydrograph for Rolwaling–Gongar–Singati floodplain zoning",
        },
        {
            "scenario_id": "TR-S3-SEVERE-50PCT",
            "label": "Severe Ice-Cored Moraine Collapse (50% depth fraction)",
            "breach_fraction": 0.50,
            "approx_breach_depth_m": round(0.50 * float(p.get("depth_m") or 122), 1),
            "traya_empirical_qp_m3s": p.get("qp_50"),
            "published_analog": "High-impact avalanche + ice-cored moraine incision (~50-65 m lowering, approaching Fujita Hp=66.6 m)",
            "target_2d_solver_role": "Upper-bound evacuation planning & Upper Tamakoshi tailrace backwater stress test",
        },
        {
            "scenario_id": "TR-S4-EXTREME-100PCT",
            "label": "Extreme Full-Depth Bounding Case (100% depth fraction)",
            "breach_fraction": 1.00,
            "approx_breach_depth_m": float(p.get("depth_m") or 122),
            "traya_empirical_qp_m3s": p.get("qp_100"),
            "published_analog": "Physical bounding envelope only (full bathymetric drainage is geomorphically unlikely)",
            "target_2d_solver_role": "Sensitivity ceiling only — NOT a probable operational scenario",
        },
    ]

    payload: dict[str, Any] = {
        "schema_version": SCHEMA_VERSION,
        "generated_utc": now_utc,
        "data_class": DATA_CLASS,
        "status_note": STATUS_NOTE,
        "is_2d_inundation_map": False,
        "target_solvers": ["LISFLOOD-FP", "BASEMENT (ETH Zurich)"],
        "lake_identification": {
            "requested_reference_id": TARGET_LAKE_IDS[0],
            "matched_inventory_id": lid,
            "match_mode": match_mode,
            "match_offset_km": match_dist_km,
            "name": p.get("name") or "Tsho Rolpa",
            "name_ne": "छो रोल्पा हिमताल",
            "rgi_glacier_id": p.get("rgi"),
            "glacier_name": "Trakarding Glacier",
            "river_basin": "Rolwaling Khola → Tama Koshi → Sun Koshi (Saptakoshi)",
            "district": p.get("district") or "Dolakha",
            "district_ne": RW.DISTRICT_NE.get(str(p.get("district") or "Dolakha"), "दोलखा"),
            "province": FL.canonical_province(p.get("prov") or "Bagmati Province"),
            "province_ne": RW.PROVINCE_NE.get(
                FL.canonical_province(p.get("prov") or "Bagmati Province"),
                "बागमती प्रदेश",
            ),
            "lon": p.get("lon"),
            "lat": p.get("lat"),
            "elevation_m": p.get("z"),
        },
        "traya_inventory_parameters": {
            "area_km2": p.get("area_km2"),
            "area_change_pct": p.get("area_change_pct"),
            "change_class": p.get("change_class"),
            "lake_type": p.get("typ"),
            "ice_contact": bool(p.get("ice_contact")),
            "ice_cored_moraine": bool(p.get("ice_cored")),
            "priority": bool(p.get("priority")),
            "hazard_published": p.get("hazard"),
            "hazard_enum_published": p.get("hazard_enum"),
            "impact_published": p.get("impact"),
            "risk_published": p.get("risk"),
            "avalanche_trigger": bool(p.get("avalanche")),
            "rockfall_trigger": bool(p.get("rockfall")),
            "upstream_glof_trigger": bool(p.get("upstream_glof")),
            "sla_area_km2": p.get("sla_area_km2"),
            "sla_max_angle_deg": p.get("sla_max_angle"),
            "hp_m": p.get("hp_m"),
            "dm_fujita_m": p.get("dm_fujita_m"),
            "pfv_Mm3": p.get("pfv_Mm3"),
            "pfv_ci_Mm3": [p.get("pfv_lo_Mm3"), p.get("pfv_hi_Mm3")],
            "veh_depth_m": p.get("depth_m"),
            "veh_depth_ci_m": [p.get("depth_lo"), p.get("depth_hi")],
            "veh_volume_Mm3": p.get("volume_Mm3"),
            "veh_qp_median_m3s": p.get("qp_m3s"),
            "veh_qp_ci_m3s": [p.get("qp_lo"), p.get("qp_hi")],
            "veh_qp_breach_fractions_m3s": {
                "10pct": p.get("qp_10"),
                "30pct": p.get("qp_30"),
                "50pct": p.get("qp_50"),
                "100pct": p.get("qp_100"),
            },
            "route_km": p.get("route_km") or route.get("km"),
            "seismic_context": {
                "eq_n_m5_within_50km": p.get("eq_n_m5_within_50km"),
                "eq_n_m6_within_100km": p.get("eq_n_m6_within_100km"),
                "eq_nearest_m6_km": p.get("eq_nearest_m6_km"),
                "nearest_active_fault_km": p.get("fault_km"),
                "nearest_active_fault_name": p.get("fault_name"),
            },
            "latest_eo_hydromet_snapshot": hm_match,
        },
        "published_peer_reviewed_benchmarks": {
            "bathymetry_and_geometry": {
                "surveyed_volume_Mm3_range": [76.6, 85.9],
                "surveyed_max_depth_m": 132.0,
                "surveyed_mean_depth_m": 55.1,
                "historical_expansion_note": (
                    "Expanded from ~0.23 km2 (1957-1959 Survey of India / aerial photography) to "
                    "~1.53-1.65 km2 in 1990s-2010s surveys and ~1.66 km2 in TRĀYA inventory."
                ),
                "comparison_with_traya_empirical_scaling": {
                    "depth_check": (
                        f"Surveyed max depth 132 m falls comfortably inside TRĀYA Veh et al. (2020) "
                        f"95% interval [{p.get('depth_lo')}, {p.get('depth_hi')}] m (median {p.get('depth_m')} m)."
                    ),
                    "volume_bias_note": (
                        f"TRĀYA half-ellipsoid volume ({p.get('volume_Mm3')} Mm3) overestimates surveyed "
                        "bathymetric volume (76-86 Mm3) by ~1.6-1.8x because real moraine-dammed basins "
                        "are shallower near shorelines than an ideal half-ellipsoid. 2D hydrodynamic "
                        "simulations MUST use surveyed bathymetry rather than half-ellipsoid volume."
                    ),
                },
                "citations": [
                    "Yamada, T. (1998), Glacier Lake and its Outburst Flood in the Nepal Himalaya, Data Center for Glacier Research, Japanese Society of Snow and Ice, Monograph 1.",
                    "Reynolds, J.M. (1999), Glacial hazard assessment at Tsho Rolpa, Rolwaling, Central Nepal, Q. J. Eng. Geol. 32(3), 209-214.",
                    "ICIMOD (2011), Glacial Lakes and Glacial Lake Outburst Floods in Nepal, Kathmandu.",
                    "Shrestha, B.B., Nakagawa, H. (2014), Assessment of potential outburst floods from the Tsho Rolpa glacial lake in Nepal, Natural Hazards 73, 1119-1139, doi:10.1007/s11069-013-0940-3.",
                ],
            },
            "engineering_mitigation_2000": {
                "intervention": "3.0 m artificial lake-level lowering via open gated spillway channel",
                "completion_year": 2000,
                "implementing_agencies": "Nepal DHM / WECS with Netherlands Government & Reynolds Geo-Sciences support",
                "residual_risk_note": (
                    "Lowering the lake by 3 m reduced hydrostatic pressure and storage by ~4-5 Mm3, "
                    "but the terminal moraine remains ice-cored with steep distal slopes (SLA = 17.5-21.8 deg) "
                    "and ~76-86 Mm3 retained volume; full 15-20 m lowering proposed in Phase II was never constructed."
                ),
                "citations": [
                    "Damen, M. (1992), Study on the potential outburst flooding of Tsho Rolpa glacier lake, Rolwaling Valley, East Nepal, ITC Enschede report.",
                    "Rana, B., Shrestha, A.B., Reynolds, J.M., Aryal, R., Pokhrel, A.P., Budhathoki, K.P. (2000), Hazard assessment of the Tsho Rolpa Glacier Lake and ongoing remediation measures, J. Nepal Geol. Soc. 22, 563-570.",
                ],
            },
            "rounce_2016_table5": rounce_bench,
            "fujita_2013_table2": fujita_bench,
            "nearby_historical_glofs_25km": nearby_historical_glofs,
        },
        "valley_checkpoints": checkpoints,
        "exposure_and_isolation_screening": tr_iso,
        "breach_scenario_framework": breach_scenarios,
        "pre_simulation_2d_requirements": {
            "required_inputs_for_lisflood_basement": [
                "High-resolution <=2-5 m bare-earth DEM (UAV photogrammetry / airborne LiDAR / Pleiades stereo) of the Rolwaling gorge and Tama Koshi floodplains",
                "Updated multi-beam / sonar bathymetry of Tsho Rolpa (post-2020 ice-front retreat & lake expansion)",
                "Moraine geotechnical & ice-core ERT/GPR cross-sections for physical breach-erosion parameterization (BASEMENT / BREACH)",
                "Two-phase hyperconcentrated / debris-flow rheology parameters (entrainment & bulking along steep Rolwaling reaches)",
                "Calibrated Manning's n roughness across alpine boulder channels, forested gorges, and Tama Koshi bridge constrictions",
                "As-built deck elevation & abutment clearances for Gongar, Singati Bridge, NH28/NH23 bridges, and Upper Tamakoshi tailrace outfall",
            ],
            "current_traya_screening_limitations": [
                "1 km corridor around HydroRIVERS/DEM thalweg is a screening search zone — NOT a 2D inundation boundary",
                "Arrival times use first-order surge-front velocities (2 / 5 / 10 m/s) without channel-storage attenuation or debris bulking",
                "No site-specific flood depth, flow velocity, shear stress, or bridge scour is computed yet",
            ],
        },
        "provenance": {
            "schema_version": SCHEMA_VERSION,
            "generated_utc": now_utc,
            "data_class": DATA_CLASS,
            "mode": "offline_local_synthesis",
            "license_ref": "CC-BY-4.0 (TRĀYA case-study benchmark); ODbL 1.0 (OSM); published literature cited inline",
            "sources": [
                {"provider_id": "traya_lakes_core", "path": "data/lakes_core.json", "lake_id": lid},
                {"provider_id": "traya_routes", "path": "data/routes.json", "lake_id": lid},
                {"provider_id": "traya_exposure_isolation", "path": "data/exposure_isolation.json", "lake_id": lid},
                {"provider_id": "traya_hydromet", "path": "data/hydromet_weekly.json", "lake_id": lid},
                {"provider_id": "traya_validation", "path": "data/validation.json", "lake_id": lid},
                {"provider_id": "hmaglofdb_v4", "path": "data/glof_history.json"},
                {"provider_id": "osm_overpass", "path": "cache/overpass/hydropower.json"},
            ],
        },
    }

    _atomic_write_json(out_path, payload)
    return payload


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(
        description="Nepal TRĀYA 2.0 Tsho Rolpa 2D pre-simulation pilot benchmark builder"
    )
    ap.add_argument("--out", default=OUT_JSON, help="Output JSON path")
    args = ap.parse_args(argv)

    res = build_tsho_rolpa_pilot(out_path=args.out)
    lid = res["lake_identification"]["matched_inventory_id"]
    print(
        f"[tsho_rolpa_pilot] wrote {args.out}: lake_id={lid}, "
        f"data_class={res['data_class']}, checkpoints={len(res['valley_checkpoints'])}, "
        f"scenarios={len(res['breach_scenario_framework'])}"
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
