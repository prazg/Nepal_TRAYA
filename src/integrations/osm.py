"""
Thin provenance wrapper around `src/exposure.py` (OpenStreetMap Overpass API
exposure layers: settlements, health facilities, hydropower plants, bridges,
and border control posts).

Pure Python 3.12 standard library only (zero third-party dependencies).
"""
from __future__ import annotations

import datetime as dt
import json
import os
import sys
from typing import Any

SRC_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if SRC_DIR not in sys.path:
    sys.path.insert(0, SRC_DIR)

import config as C
import exposure as EX
from .provenance import (
    evaluate_envelope_sla,
    make_envelope,
    utc_now_iso,
)

OSM_SOURCE_NAME = "OpenStreetMap (via Overpass API)"
OSM_DATASET_NAME = "osm_nepal_exposure_layers"
OSM_LICENSE_REF = "ODbL 1.0 (OpenStreetMap contributors, https://www.openstreetmap.org/copyright)"
OSM_SLA_HOURS = 720  # 30-day refresh cadence for static/semi-static infrastructure layers
EXPOSURE_LAYERS: tuple[str, ...] = ("places", "health", "hydropower", "bridges", "borders")


def _file_mtime_iso(path: str) -> str | None:
    if not os.path.isfile(path):
        return None
    try:
        return dt.datetime.fromtimestamp(os.path.getmtime(path), tz=dt.timezone.utc).strftime(
            "%Y-%m-%dT%H:%M:%SZ"
        )
    except OSError:
        return None


def _inspect_overpass_cache(cache_dir: str) -> tuple[dict[str, int], dict[str, str], list[str]]:
    counts: dict[str, int] = {}
    mtimes: dict[str, str] = {}
    missing: list[str] = []
    for layer in EXPOSURE_LAYERS:
        p = os.path.join(cache_dir, f"{layer}.json")
        if not os.path.isfile(p):
            counts[layer] = 0
            missing.append(layer)
            continue
        try:
            with open(p, encoding="utf-8") as fh:
                payload = json.load(fh)
            els = payload.get("elements") if isinstance(payload, dict) else None
            counts[layer] = len(els) if isinstance(els, list) else 0
            mt = _file_mtime_iso(p)
            if mt:
                mtimes[layer] = mt
        except Exception:
            counts[layer] = 0
            missing.append(layer)
    return counts, mtimes, missing


def fetch_osm_exposure(
    offline: bool = True,
    *,
    refresh: bool = False,
    max_age_days: float | None = None,
    cache_dir: str | None = None,
) -> dict[str, Any]:
    """Wrap `src/exposure.py` Overpass infrastructure layers with a ProvenanceEnvelope."""
    now_utc = utc_now_iso()
    overpass_dir = cache_dir or EX.CACHE_DIR
    fallback_used = False
    live_note = ""

    if not offline:
        try:
            EX.collect(refresh=refresh, max_age_days=max_age_days)
            live_note = "Refreshed via Overpass mirrors in src/exposure.py."
        except Exception as exc:
            fallback_used = True
            live_note = f"Overpass live refresh failed ({exc}); using cached layers."

    counts, mtimes, missing = _inspect_overpass_cache(overpass_dir)
    total = sum(counts.values())

    if total == 0:
        env = make_envelope(
            source=OSM_SOURCE_NAME,
            dataset=OSM_DATASET_NAME,
            data_class="unavailable",
            retrieved_at_utc=now_utc,
            observation_time_utc=None,
            valid_until_utc=None,
            status="unavailable",
            fallback_used=True,
            license_ref=OSM_LICENSE_REF,
            sla_hours=OSM_SLA_HOURS,
            record_count=0,
            notes=f"No cached OpenStreetMap Overpass exposure layers found in {overpass_dir}. {live_note}".strip(),
        )
        return {
            "provenance": env,
            "layer_counts": counts,
            "layer_mtimes_utc": mtimes,
            "missing_layers": missing,
            "total_objects": 0,
        }

    retrieved = max(mtimes.values()) if mtimes else now_utc
    oldest = min(mtimes.values()) if mtimes else retrieved
    sla = evaluate_envelope_sla(
        {"status": "available", "data_class": "static_assessment", "retrieved_at_utc": oldest, "sla_hours": OSM_SLA_HOURS},
        ref_utc=now_utc,
    )
    status = "available" if (sla["within_sla"] and not missing) else "stale"
    data_class = "cached" if (offline or fallback_used) else "static_assessment"
    caveat = (
        "OSM coverage in Nepal is uneven (counts are lower bounds; absence of mapped features "
        "does not imply absence on the ground)."
    )
    notes = f"{caveat} Missing layers: {', '.join(missing)}." if missing else f"{caveat} {live_note}".strip()

    env = make_envelope(
        source=OSM_SOURCE_NAME,
        dataset=OSM_DATASET_NAME,
        data_class=data_class,
        retrieved_at_utc=retrieved,
        observation_time_utc=oldest,
        valid_until_utc=None,
        status=status,
        fallback_used=bool(offline or fallback_used),
        license_ref=OSM_LICENSE_REF,
        sla_hours=OSM_SLA_HOURS,
        record_count=total,
        notes=notes,
    )
    return {
        "provenance": env,
        "layer_counts": counts,
        "layer_mtimes_utc": mtimes,
        "missing_layers": missing,
        "total_objects": total,
    }


def get_provenance(offline: bool = True, cache_dir: str | None = None) -> dict[str, Any]:
    """Return the canonical ProvenanceEnvelope for OpenStreetMap Overpass exposure."""
    return fetch_osm_exposure(offline=offline, cache_dir=cache_dir)["provenance"]
