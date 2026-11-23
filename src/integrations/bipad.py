"""
Official Government of Nepal NDRRMA BIPAD Portal API v1 client (TRAYA-005).

Queries the verified live public endpoints on https://bipadportal.gov.np/api/v1/:
  * /alert/?limit=25&ordering=-started_on
  * /incident/?hazard=17&expand=loss&ordering=-incident_on&limit=100  (Landslide)
  * /river/?limit=40&ordering=-modified_on   (filtered to non-null waterLevel/waterLevelOn)
  * /rain/?limit=40&ordering=-measured_on    (real-time DHM rain gauges)
  * /earthquake/?limit=25&ordering=-event_on (official NSC/NEMRC earthquakes)

Scientific & data-integrity guarantees:
  * Preserves `None` (JSON `null`) for missing casualties, dates, water levels,
    and economic losses — NEVER coerces `None` to `0`.
  * Keeps official Government of Nepal NDRRMA/BIPAD records structurally
    separate from modelled forecasts.
  * Atomically caches snapshots to `cache/bipad_snapshot.json` and degrades
    gracefully in `--offline` mode or on upstream outage with zero crash.

Pure Python 3.12 standard library only (zero third-party dependencies).
"""
from __future__ import annotations

import argparse
import json
import math
import os
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from typing import Any, Callable

SRC_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if SRC_DIR not in sys.path:
    sys.path.insert(0, SRC_DIR)

import config as C
if __package__:
    from .provenance import (
        atomic_write_json,
        evaluate_envelope_sla,
        format_iso_utc,
        make_envelope,
        parse_iso_utc,
        utc_now_iso,
    )
else:
    from integrations.provenance import (
        atomic_write_json,
        evaluate_envelope_sla,
        format_iso_utc,
        make_envelope,
        parse_iso_utc,
        utc_now_iso,
    )

BIPAD_API_BASE = "https://bipadportal.gov.np/api/v1"
USER_AGENT = "Nepal-TRAYA/2.0 (+https://prazg.github.io/Nepal_TRAYA/)"
OFFICIAL_NOTICE = (
    "Official Government of Nepal NDRRMA/BIPAD records — "
    "kept structurally separate from modelled forecasts."
)
BIPAD_LICENSE_REF = "Government of Nepal NDRRMA / BIPAD Portal public API (https://bipadportal.gov.np/)"
BIPAD_SOURCE_NAME = "Government of Nepal NDRRMA / BIPAD Portal"
BIPAD_DATASET_NAME = "bipad_official_multi_hazard_snapshot"
BIPAD_HAZARD_LANDSLIDE = 17
BIPAD_SLA_HOURS = 168

CACHE_BIPAD = os.path.join(C.CACHE, "bipad_snapshot.json")

ENDPOINTS: dict[str, str] = {
    "alerts": f"{BIPAD_API_BASE}/alert/?limit=25&ordering=-started_on",
    "landslide_incidents": (
        f"{BIPAD_API_BASE}/incident/?hazard={BIPAD_HAZARD_LANDSLIDE}"
        "&expand=loss&ordering=-incident_on&limit=100"
    ),
    "dhm_rivers": f"{BIPAD_API_BASE}/river/?limit=40&ordering=-modified_on",
    "dhm_rain": f"{BIPAD_API_BASE}/rain/?limit=40&ordering=-measured_on",
    "nsc_earthquakes": f"{BIPAD_API_BASE}/earthquake/?limit=25&ordering=-event_on",
}


def _opt_int(value: Any) -> int | None:
    """Convert numeric value to int while strictly preserving None (never None -> 0)."""
    if value is None or isinstance(value, bool):
        return None
    if isinstance(value, int):
        return value
    s = str(value).strip()
    if not s:
        return None
    try:
        f = float(s)
    except ValueError:
        return None
    if not math.isfinite(f):
        return None
    return int(round(f))


def _opt_float(value: Any, ndigits: int | None = 4) -> float | None:
    """Convert numeric value to finite float while strictly preserving None."""
    if value is None or isinstance(value, bool):
        return None
    try:
        f = float(value)
    except (TypeError, ValueError):
        return None
    if not math.isfinite(f):
        return None
    return round(f, ndigits) if ndigits is not None else f


def _opt_str(value: Any) -> str | None:
    """Return stripped string or None if absent/blank."""
    if value is None:
        return None
    s = str(value).strip()
    return s if s else None


def _opt_bool(value: Any) -> bool | None:
    if value is None:
        return None
    if isinstance(value, bool):
        return value
    return None


def _extract_point(point: Any) -> tuple[dict[str, Any] | None, float | None, float | None]:
    """Validate GeoJSON Point and return (clean_point, lon, lat) preserving None."""
    if not isinstance(point, dict):
        return None, None, None
    coords = point.get("coordinates")
    if not isinstance(coords, (list, tuple)) or len(coords) < 2:
        return None, None, None
    lon = _opt_float(coords[0], 6)
    lat = _opt_float(coords[1], 6)
    if lon is None or lat is None:
        return None, None, None
    return {"type": "Point", "coordinates": [lon, lat]}, lon, lat


def _http_get_json(
    url: str,
    *,
    timeout: int = 20,
    retries: int = 3,
    backoff_base_s: float = 1.5,
) -> Any:
    """GET JSON with timeout, exponential backoff, and polite User-Agent."""
    headers = {
        "User-Agent": USER_AGENT,
        "Accept": "application/json",
    }
    last_exc: Exception | None = None
    for attempt in range(max(1, retries)):
        try:
            req = urllib.request.Request(url, headers=headers)
            with urllib.request.urlopen(req, timeout=timeout) as resp:
                raw = resp.read().decode("utf-8")
            return json.loads(raw)
        except urllib.error.HTTPError as exc:
            last_exc = exc
            if exc.code in (400, 401, 403, 404):
                break
        except Exception as exc:
            last_exc = exc
        if attempt < retries - 1:
            time.sleep(backoff_base_s * (2 ** attempt))
    raise RuntimeError(f"BIPAD GET {url} failed after {retries} attempt(s): {last_exc}")


def parse_alert(raw: dict[str, Any]) -> dict[str, Any]:
    """Normalize a single BIPAD /api/v1/alert/ record preserving nulls."""
    point, lon, lat = _extract_point(raw.get("point"))
    demo_raw = raw.get("affectedDemography")
    demo: dict[str, int | None] | None = None
    if isinstance(demo_raw, dict):
        demo = {
            "maleCount": _opt_int(demo_raw.get("maleCount")),
            "femaleCount": _opt_int(demo_raw.get("femaleCount")),
            "householdCount": _opt_int(demo_raw.get("householdCount")),
        }
    wards_raw = raw.get("wards")
    wards = [w for w in wards_raw if w is not None] if isinstance(wards_raw, list) else []
    return {
        "id": _opt_int(raw.get("id")),
        "title": _opt_str(raw.get("title")),
        "titleNe": _opt_str(raw.get("titleNe")),
        "source": _opt_str(raw.get("source")),
        "description": _opt_str(raw.get("description")),
        "startedOn": _opt_str(raw.get("startedOn")),
        "expireOn": _opt_str(raw.get("expireOn")),
        "point": point,
        "lon": lon,
        "lat": lat,
        "affectedDemography": demo,
        "verified": _opt_bool(raw.get("verified")),
        "public": _opt_bool(raw.get("public")),
        "hazard": _opt_int(raw.get("hazard")),
        "wards": wards,
    }


def parse_landslide_incident(raw: dict[str, Any]) -> dict[str, Any]:
    """Normalize a single BIPAD /api/v1/incident/?hazard=17&expand=loss record.

    Strictly preserves `None` for any missing casualty, economic loss, or date
    field so unreported impact is NEVER misrepresented as zero.
    """
    point, lon, lat = _extract_point(raw.get("point"))
    raw_loss = raw.get("loss")
    loss_dict: dict[str, Any] | None = None
    if isinstance(raw_loss, dict):
        loss_dict = {
            "id": _opt_int(raw_loss.get("id")),
            "peopleDeathCount": _opt_int(raw_loss.get("peopleDeathCount")),
            "peopleInjuredCount": _opt_int(raw_loss.get("peopleInjuredCount")),
            "peopleMissingCount": _opt_int(raw_loss.get("peopleMissingCount")),
            "peopleAffectedCount": _opt_int(raw_loss.get("peopleAffectedCount")),
            "familyAffectedCount": _opt_int(raw_loss.get("familyAffectedCount")),
            "estimatedLoss": _opt_float(raw_loss.get("estimatedLoss"), 2),
            "infrastructureDestroyedHouseCount": _opt_int(raw_loss.get("infrastructureDestroyedHouseCount")),
            "infrastructureDestroyedRoadCount": _opt_int(raw_loss.get("infrastructureDestroyedRoadCount")),
            "infrastructureDestroyedBridgeCount": _opt_int(raw_loss.get("infrastructureDestroyedBridgeCount")),
        }

    incident_on = _opt_str(raw.get("incidentOn"))
    date_iso = incident_on[:10] if incident_on and len(incident_on) >= 10 else None
    wards_raw = raw.get("wards")
    wards = [w for w in wards_raw if w is not None] if isinstance(wards_raw, list) else []

    return {
        "id": _opt_int(raw.get("id")),
        "title": _opt_str(raw.get("title")),
        "titleNe": _opt_str(raw.get("titleNe")),
        "incidentOn": incident_on,
        "date": date_iso,
        "reportedOn": _opt_str(raw.get("reportedOn")),
        "point": point,
        "lon": lon,
        "lat": lat,
        "loss": loss_dict,
        "peopleDeathCount": loss_dict["peopleDeathCount"] if loss_dict else None,
        "peopleInjuredCount": loss_dict["peopleInjuredCount"] if loss_dict else None,
        "peopleMissingCount": loss_dict["peopleMissingCount"] if loss_dict else None,
        "estimatedLoss": loss_dict["estimatedLoss"] if loss_dict else None,
        "verified": _opt_bool(raw.get("verified")),
        "approved": _opt_bool(raw.get("approved")),
        "wards": wards,
        "source": _opt_str(raw.get("source")),
        "dataSource": _opt_str(raw.get("dataSource")),
        "hazard": _opt_int(raw.get("hazard")) if raw.get("hazard") is not None else BIPAD_HAZARD_LANDSLIDE,
        "streetAddress": _opt_str(raw.get("streetAddress")),
    }


def parse_river(raw: dict[str, Any]) -> dict[str, Any] | None:
    """Normalize a BIPAD /api/v1/river/ record; drop stations with null waterLevel AND waterLevelOn."""
    water_level = _opt_float(raw.get("waterLevel"), 3)
    water_level_on = _opt_str(raw.get("waterLevelOn"))
    if water_level is None and water_level_on is None:
        return None
    point, lon, lat = _extract_point(raw.get("point"))
    return {
        "id": _opt_int(raw.get("id")),
        "title": _opt_str(raw.get("title")),
        "basin": _opt_str(raw.get("basin")),
        "waterLevel": water_level,
        "warningLevel": _opt_float(raw.get("warningLevel"), 3),
        "dangerLevel": _opt_float(raw.get("dangerLevel"), 3),
        "waterLevelOn": water_level_on,
        "status": _opt_str(raw.get("status")),
        "point": point,
        "lon": lon,
        "lat": lat,
        "district": raw.get("district"),
        "province": raw.get("province"),
        "elevation": _opt_float(raw.get("elevation"), 1),
        "steady": _opt_str(raw.get("steady")),
        "modifiedOn": _opt_str(raw.get("modifiedOn")),
    }


def parse_rain(raw: dict[str, Any]) -> dict[str, Any]:
    """Normalize a single BIPAD /api/v1/rain/ gauge record preserving nulls."""
    point, lon, lat = _extract_point(raw.get("point"))
    raw_avgs = raw.get("averages")
    averages: list[dict[str, Any]] = []
    by_interval: dict[int, float | None] = {}
    if isinstance(raw_avgs, list):
        for item in raw_avgs:
            if not isinstance(item, dict):
                continue
            iv = _opt_int(item.get("interval"))
            val = _opt_float(item.get("value"), 2)
            st_raw = item.get("status")
            st: dict[str, bool | None] | None = None
            if isinstance(st_raw, dict):
                st = {
                    "warning": _opt_bool(st_raw.get("warning")),
                    "danger": _opt_bool(st_raw.get("danger")),
                }
            averages.append({
                "interval": iv,
                "value": val,
                "status": st,
            })
            if iv in (1, 3, 6, 12, 24):
                by_interval[iv] = val

    return {
        "id": _opt_int(raw.get("id")),
        "title": _opt_str(raw.get("title")),
        "basin": _opt_str(raw.get("basin")),
        "measuredOn": _opt_str(raw.get("measuredOn")),
        "averages": averages,
        "rain_1h_mm": by_interval.get(1),
        "rain_3h_mm": by_interval.get(3),
        "rain_6h_mm": by_interval.get(6),
        "rain_12h_mm": by_interval.get(12),
        "rain_24h_mm": by_interval.get(24),
        "status": _opt_str(raw.get("status")),
        "elevation": _opt_float(raw.get("elevation"), 1),
        "point": point,
        "lon": lon,
        "lat": lat,
        "district": raw.get("district"),
        "province": raw.get("province"),
    }


def parse_earthquake(raw: dict[str, Any]) -> dict[str, Any]:
    """Normalize a single BIPAD /api/v1/earthquake/ (NSC/NEMRC) record preserving nulls."""
    point, lon, lat = _extract_point(raw.get("point"))
    return {
        "id": _opt_int(raw.get("id")),
        "magnitude": _opt_float(raw.get("magnitude"), 2),
        "address": _opt_str(raw.get("address")),
        "eventOn": _opt_str(raw.get("eventOn")),
        "point": point,
        "lon": lon,
        "lat": lat,
        "description": _opt_str(raw.get("description")),
        "district": raw.get("district"),
        "province": raw.get("province"),
        "municipality": raw.get("municipality"),
        "ward": raw.get("ward"),
    }


def _latest_observation_utc(
    alerts: list[dict[str, Any]],
    incidents: list[dict[str, Any]],
    rivers: list[dict[str, Any]],
    rain: list[dict[str, Any]],
    quakes: list[dict[str, Any]],
) -> str | None:
    """Compute the latest parsed UTC timestamp across all five BIPAD feeds."""
    candidates: list[str] = []
    for a in alerts:
        if a.get("startedOn"):
            candidates.append(str(a["startedOn"]))
    for inc in incidents:
        if inc.get("incidentOn"):
            candidates.append(str(inc["incidentOn"]))
    for rv in rivers:
        if rv.get("waterLevelOn"):
            candidates.append(str(rv["waterLevelOn"]))
    for rn in rain:
        if rn.get("measuredOn"):
            candidates.append(str(rn["measuredOn"]))
    for eq in quakes:
        if eq.get("eventOn"):
            candidates.append(str(eq["eventOn"]))

    parsed = [dt_obj for ts in candidates if (dt_obj := parse_iso_utc(ts)) is not None]
    if not parsed:
        return None
    return format_iso_utc(max(parsed))


def _load_cache(cache_path: str) -> dict[str, Any] | None:
    if not os.path.isfile(cache_path):
        return None
    try:
        with open(cache_path, encoding="utf-8") as fh:
            data = json.load(fh)
        if isinstance(data, dict) and "alerts" in data:
            return data
    except Exception:
        return None
    return None


def _empty_unavailable_payload(now_utc: str, note: str) -> dict[str, Any]:
    env = make_envelope(
        source=BIPAD_SOURCE_NAME,
        dataset=BIPAD_DATASET_NAME,
        data_class="unavailable",
        retrieved_at_utc=now_utc,
        observation_time_utc=None,
        valid_until_utc=None,
        status="unavailable",
        fallback_used=True,
        license_ref=BIPAD_LICENSE_REF,
        sla_hours=BIPAD_SLA_HOURS,
        record_count=0,
        notes=note,
    )
    return {
        "provenance": env,
        "official_notice": OFFICIAL_NOTICE,
        "alerts": [],
        "landslide_incidents": [],
        "dhm_rivers": [],
        "dhm_rain": [],
        "nsc_earthquakes": [],
    }


def _extract_results(payload: Any) -> list[dict[str, Any]]:
    if isinstance(payload, dict) and isinstance(payload.get("results"), list):
        return [r for r in payload["results"] if isinstance(r, dict)]
    if isinstance(payload, list):
        return [r for r in payload if isinstance(r, dict)]
    return []


def fetch_bipad_snapshot(
    offline: bool = False,
    *,
    cache_path: str = CACHE_BIPAD,
    timeout: int = 20,
    retries: int = 3,
    fetcher: Callable[[str], Any] | None = None,
) -> dict[str, Any]:
    """Fetch or offline-load the official NDRRMA BIPAD multi-hazard snapshot.

    Parameters
    ----------
    offline : bool
        When True, makes zero network calls and loads `cache_path` (or returns a
        clean `status="unavailable"` envelope if no snapshot is cached).
    cache_path : str
        Path to `cache/bipad_snapshot.json`.
    timeout : int
        Per-request socket timeout in seconds (default 20).
    retries : int
        Retry attempts per endpoint with exponential backoff.
    fetcher : callable, optional
        Optional dependency-injection hook `(url) -> parsed_json` for unit tests.
    """
    now_utc = utc_now_iso()
    cached = _load_cache(cache_path)

    if offline:
        if cached is None:
            return _empty_unavailable_payload(
                now_utc,
                "Offline mode and no cached cache/bipad_snapshot.json present.",
            )
        prev_prov = cached.get("provenance") if isinstance(cached.get("provenance"), dict) else {}
        retrieved = prev_prov.get("retrieved_at_utc") or now_utc
        alerts = list(cached.get("alerts") or [])
        incidents = list(cached.get("landslide_incidents") or [])
        rivers = list(cached.get("dhm_rivers") or [])
        rain = list(cached.get("dhm_rain") or [])
        quakes = list(cached.get("nsc_earthquakes") or [])
        total = len(alerts) + len(incidents) + len(rivers) + len(rain) + len(quakes)
        obs_utc = prev_prov.get("observation_time_utc") or _latest_observation_utc(
            alerts, incidents, rivers, rain, quakes
        )
        sla_check = evaluate_envelope_sla(
            {"status": "available", "data_class": "cached", "retrieved_at_utc": retrieved, "sla_hours": BIPAD_SLA_HOURS},
            ref_utc=now_utc,
        )
        env = make_envelope(
            source=BIPAD_SOURCE_NAME,
            dataset=BIPAD_DATASET_NAME,
            data_class="cached",
            retrieved_at_utc=retrieved,
            observation_time_utc=obs_utc,
            valid_until_utc=None,
            status="available" if sla_check["within_sla"] else "stale",
            fallback_used=True,
            license_ref=BIPAD_LICENSE_REF,
            sla_hours=BIPAD_SLA_HOURS,
            record_count=total,
            notes="Loaded cached BIPAD snapshot in --offline mode (zero network calls).",
        )
        return {
            "provenance": env,
            "official_notice": OFFICIAL_NOTICE,
            "alerts": alerts,
            "landslide_incidents": incidents,
            "dhm_rivers": rivers,
            "dhm_rain": rain,
            "nsc_earthquakes": quakes,
        }

    get_json = fetcher or (lambda u: _http_get_json(u, timeout=timeout, retries=retries))

    parsers: dict[str, Callable[[list[dict[str, Any]]], list[dict[str, Any]]]] = {
        "alerts": lambda rows: [parse_alert(r) for r in rows],
        "landslide_incidents": lambda rows: [parse_landslide_incident(r) for r in rows],
        "dhm_rivers": lambda rows: [p for r in rows if (p := parse_river(r)) is not None],
        "dhm_rain": lambda rows: [parse_rain(r) for r in rows],
        "nsc_earthquakes": lambda rows: [parse_earthquake(r) for r in rows],
    }

    sections: dict[str, list[dict[str, Any]]] = {}
    succeeded: list[str] = []
    failed: dict[str, str] = {}

    for key, url in ENDPOINTS.items():
        try:
            raw_payload = get_json(url)
            rows = _extract_results(raw_payload)
            sections[key] = parsers[key](rows)
            succeeded.append(key)
        except Exception as exc:
            failed[key] = str(exc)
            sections[key] = list((cached or {}).get(key) or [])

    if not succeeded:
        if cached is not None:
            prev_prov = cached.get("provenance") if isinstance(cached.get("provenance"), dict) else {}
            retrieved = prev_prov.get("retrieved_at_utc") or now_utc
            total = sum(len(sections[k]) for k in ENDPOINTS)
            obs_utc = prev_prov.get("observation_time_utc") or _latest_observation_utc(
                sections["alerts"],
                sections["landslide_incidents"],
                sections["dhm_rivers"],
                sections["dhm_rain"],
                sections["nsc_earthquakes"],
            )
            env = make_envelope(
                source=BIPAD_SOURCE_NAME,
                dataset=BIPAD_DATASET_NAME,
                data_class="cached",
                retrieved_at_utc=retrieved,
                observation_time_utc=obs_utc,
                valid_until_utc=None,
                status="stale",
                fallback_used=True,
                license_ref=BIPAD_LICENSE_REF,
                sla_hours=BIPAD_SLA_HOURS,
                record_count=total,
                notes=f"Live BIPAD fetch failed across all endpoints ({'; '.join(f'{k}: {v}' for k, v in failed.items())}); using cached snapshot.",
            )
            return {
                "provenance": env,
                "official_notice": OFFICIAL_NOTICE,
                **sections,
            }
        return _empty_unavailable_payload(
            now_utc,
            f"Live BIPAD fetch failed across all endpoints and no cache available ({'; '.join(failed.keys())}).",
        )

    total_records = sum(len(sections[k]) for k in ENDPOINTS)
    obs_utc = _latest_observation_utc(
        sections["alerts"],
        sections["landslide_incidents"],
        sections["dhm_rivers"],
        sections["dhm_rain"],
        sections["nsc_earthquakes"],
    )
    partial_fallback = bool(failed)
    note_parts = [f"Fetched {len(succeeded)}/{len(ENDPOINTS)} live BIPAD v1 endpoints"]
    if failed:
        note_parts.append(f"fallback/empty for: {', '.join(sorted(failed.keys()))}")

    env = make_envelope(
        source=BIPAD_SOURCE_NAME,
        dataset=BIPAD_DATASET_NAME,
        data_class="live_observation",
        retrieved_at_utc=now_utc,
        observation_time_utc=obs_utc,
        valid_until_utc=None,
        status="available",
        fallback_used=partial_fallback,
        license_ref=BIPAD_LICENSE_REF,
        sla_hours=BIPAD_SLA_HOURS,
        record_count=total_records,
        notes="; ".join(note_parts) + ".",
    )

    result: dict[str, Any] = {
        "provenance": env,
        "official_notice": OFFICIAL_NOTICE,
        "alerts": sections["alerts"],
        "landslide_incidents": sections["landslide_incidents"],
        "dhm_rivers": sections["dhm_rivers"],
        "dhm_rain": sections["dhm_rain"],
        "nsc_earthquakes": sections["nsc_earthquakes"],
    }
    atomic_write_json(cache_path, result)
    return result


def get_provenance(offline: bool = True, cache_path: str = CACHE_BIPAD) -> dict[str, Any]:
    """Return the canonical ProvenanceEnvelope for the BIPAD integration."""
    return fetch_bipad_snapshot(offline=offline, cache_path=cache_path)["provenance"]


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="Nepal TRĀYA BIPAD Portal v1 client")
    ap.add_argument("--offline", action="store_true", help="Zero network calls; load cache/bipad_snapshot.json")
    ap.add_argument("--refresh", action="store_true", help="Live fetch from bipadportal.gov.np/api/v1/")
    args = ap.parse_args(argv)

    res = fetch_bipad_snapshot(offline=args.offline)
    prov = res["provenance"]
    print(
        f"[bipad] status={prov['status']} class={prov['data_class']} "
        f"alerts={len(res['alerts'])} landslides={len(res['landslide_incidents'])} "
        f"rivers={len(res['dhm_rivers'])} rain={len(res['dhm_rain'])} quakes={len(res['nsc_earthquakes'])}"
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
