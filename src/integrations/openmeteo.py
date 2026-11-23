"""
Thin provenance wrapper around `src/floods.py` (Copernicus EMS GloFAS via
Open-Meteo Flood API) and `src/hydromet.py` (Open-Meteo Weather & Cryosphere
API for 24 Dahal-Hasegawa sentinel nodes and 20 priority glacial lakes).

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

import floods as FL
import hydromet as HM
from .provenance import (
    evaluate_envelope_sla,
    format_iso_utc,
    make_envelope,
    utc_now_iso,
)

GLOFAS_SOURCE_NAME = "Copernicus EMS GloFAS via Open-Meteo Flood API"
GLOFAS_DATASET_NAME = "glofas_nepal_10basins_30d"
GLOFAS_LICENSE_REF = "CC-BY-4.0 (Copernicus Emergency Management Service / Open-Meteo)"
GLOFAS_SLA_HOURS = 168

HYDROMET_SOURCE_NAME = "Open-Meteo Weather & Cryosphere API"
HYDROMET_DATASET_NAME = "openmeteo_nepal_24nodes_20lakes"
HYDROMET_LICENSE_REF = "CC-BY-4.0 (Open-Meteo)"
HYDROMET_SLA_HOURS = 168


def _load_json(path: str) -> dict[str, Any] | None:
    if not os.path.isfile(path):
        return None
    try:
        with open(path, encoding="utf-8") as fh:
            obj = json.load(fh)
        return obj if isinstance(obj, dict) else None
    except Exception:
        return None


def _file_mtime_iso(path: str) -> str | None:
    if not os.path.isfile(path):
        return None
    try:
        return dt.datetime.fromtimestamp(os.path.getmtime(path), tz=dt.timezone.utc).strftime(
            "%Y-%m-%dT%H:%M:%SZ"
        )
    except OSError:
        return None


def fetch_glofas_floods(
    offline: bool = False,
    *,
    refresh_climatology: bool = False,
    write_output: bool = False,
    out_path: str | None = None,
) -> dict[str, Any]:
    """Wrap `src/floods.py` GloFAS 10-basin watch with a canonical ProvenanceEnvelope."""
    now_utc = utc_now_iso()
    payload: dict[str, Any] | None = None

    if not offline or write_output or out_path is not None:
        target = out_path or FL.OUT_JSON
        payload = FL.build_rivers_watch(
            offline=offline,
            refresh_climatology=refresh_climatology,
            out_path=target,
        )
    else:
        payload = _load_json(FL.OUT_JSON) or _load_json(FL.CACHE_WEEKLY)

    if not payload or not isinstance(payload.get("basins"), list):
        env = make_envelope(
            source=GLOFAS_SOURCE_NAME,
            dataset=GLOFAS_DATASET_NAME,
            data_class="unavailable",
            retrieved_at_utc=now_utc,
            observation_time_utc=None,
            valid_until_utc=None,
            status="unavailable",
            fallback_used=True,
            license_ref=GLOFAS_LICENSE_REF,
            sla_hours=GLOFAS_SLA_HOURS,
            record_count=0,
            notes="No GloFAS river watch output or cache found.",
        )
        return {"provenance": env, "data": {}}

    mode = str(payload.get("mode") or ("offline" if offline else "live"))
    retrieved = format_iso_utc(payload.get("updated_utc")) or _file_mtime_iso(FL.CACHE_WEEKLY) or now_utc
    valid_until = format_iso_utc(payload.get("forecast_expires_utc"))
    fallback_used = mode in ("offline", "cached_fallback") or offline
    data_class = "forecast" if mode == "live" else ("cached" if fallback_used else "forecast")

    sla = evaluate_envelope_sla(
        {
            "status": "available",
            "data_class": data_class,
            "retrieved_at_utc": retrieved,
            "valid_until_utc": valid_until,
            "sla_hours": GLOFAS_SLA_HOURS,
        },
        ref_utc=now_utc,
    )
    status = "available" if sla["within_sla"] else "stale"
    snap_warns = int(payload.get("n_grid_snap_warnings") or 0)
    note = (
        f"GloFAS v4 10-basin discharge watch (mode={mode}, "
        f"climatology_years={payload.get('climatology_years')}, "
        f"grid_snap_warnings={snap_warns})."
    )
    env = make_envelope(
        source=GLOFAS_SOURCE_NAME,
        dataset=GLOFAS_DATASET_NAME,
        data_class=data_class,
        retrieved_at_utc=retrieved,
        observation_time_utc=retrieved,
        valid_until_utc=valid_until,
        status=status,
        fallback_used=fallback_used,
        license_ref=GLOFAS_LICENSE_REF,
        sla_hours=GLOFAS_SLA_HOURS,
        record_count=len(payload.get("basins") or []),
        notes=note,
    )
    return {"provenance": env, "data": payload}


def fetch_hydromet_watch(
    offline: bool = False,
    *,
    write_output: bool = False,
    out_path: str | None = None,
) -> dict[str, Any]:
    """Wrap `src/hydromet.py` 24-node & 20-lake watch with a canonical ProvenanceEnvelope."""
    now_utc = utc_now_iso()
    payload: dict[str, Any] | None = None

    if not offline or write_output or out_path is not None:
        target = out_path or HM.OUT_JSON
        payload = HM.build_hydromet_weekly(offline=offline, out_path=target)
    else:
        payload = _load_json(HM.OUT_JSON) or _load_json(HM.CACHE_HYDROMET)

    if not payload or not isinstance(payload.get("nodes"), list):
        env = make_envelope(
            source=HYDROMET_SOURCE_NAME,
            dataset=HYDROMET_DATASET_NAME,
            data_class="unavailable",
            retrieved_at_utc=now_utc,
            observation_time_utc=None,
            valid_until_utc=None,
            status="unavailable",
            fallback_used=True,
            license_ref=HYDROMET_LICENSE_REF,
            sla_hours=HYDROMET_SLA_HOURS,
            record_count=0,
            notes="No Open-Meteo hydromet weekly output or cache found.",
        )
        return {"provenance": env, "data": {}}

    mode = str(payload.get("mode") or ("offline" if offline else "live"))
    retrieved = format_iso_utc(payload.get("updated_utc")) or _file_mtime_iso(HM.CACHE_HYDROMET) or now_utc
    valid_until = format_iso_utc(payload.get("forecast_expires_utc"))
    fallback_used = mode in ("offline", "cached_fallback") or offline
    data_class = "forecast" if mode == "live" else ("cached" if fallback_used else "forecast")

    sla = evaluate_envelope_sla(
        {
            "status": "available",
            "data_class": data_class,
            "retrieved_at_utc": retrieved,
            "valid_until_utc": valid_until,
            "sla_hours": HYDROMET_SLA_HOURS,
        },
        ref_utc=now_utc,
    )
    status = "available" if sla["within_sla"] else "stale"
    n_nodes = len(payload.get("nodes") or [])
    n_lakes = len(payload.get("priority_lakes") or [])
    note = (
        f"Open-Meteo 7d past + 5d forecast watch ({n_nodes} sentinel nodes, "
        f"{n_lakes} priority glacial lakes; liquid rain Dahal-Hasegawa I-D; mode={mode})."
    )
    env = make_envelope(
        source=HYDROMET_SOURCE_NAME,
        dataset=HYDROMET_DATASET_NAME,
        data_class=data_class,
        retrieved_at_utc=retrieved,
        observation_time_utc=retrieved,
        valid_until_utc=valid_until,
        status=status,
        fallback_used=fallback_used,
        license_ref=HYDROMET_LICENSE_REF,
        sla_hours=HYDROMET_SLA_HOURS,
        record_count=n_nodes + n_lakes,
        notes=note,
    )
    return {"provenance": env, "data": payload}


def get_provenance(offline: bool = True) -> list[dict[str, Any]]:
    """Return ProvenanceEnvelopes for Open-Meteo GloFAS and Hydromet feeds."""
    return [
        fetch_glofas_floods(offline=offline)["provenance"],
        fetch_hydromet_watch(offline=offline)["provenance"],
    ]
