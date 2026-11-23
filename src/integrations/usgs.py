"""
Thin provenance wrapper around `src/alerts.py` (recent 7-day Nepal-bbox USGS
FDSN seismicity) and `src/seismic.py` (historical M>=4.0 USGS FDSN catalogue).

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

import alerts as AL
import config as C
import seismic as SZ
from .provenance import (
    evaluate_envelope_sla,
    format_iso_utc,
    make_envelope,
    utc_now_iso,
)

USGS_SOURCE_NAME = "USGS Earthquake Hazards Program (FDSN)"
USGS_LICENSE_REF = "Public Domain (U.S. Geological Survey)"
USGS_RECENT_DATASET = "usgs_recent_nepal_m25_7d"
USGS_CATALOGUE_DATASET = "usgs_historical_nepal_m4_1900"
USGS_RECENT_SLA_HOURS = 168
USGS_CATALOGUE_SLA_HOURS = 720


def _epoch_ms_to_iso(ms: Any) -> str | None:
    if ms is None or isinstance(ms, bool):
        return None
    try:
        return dt.datetime.fromtimestamp(float(ms) / 1000.0, tz=dt.timezone.utc).strftime(
            "%Y-%m-%dT%H:%M:%SZ"
        )
    except (OSError, OverflowError, TypeError, ValueError):
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


def fetch_usgs_recent(
    offline: bool = False,
    *,
    days: int = 7,
    min_mag: float = 2.5,
    cache_path: str | None = None,
) -> dict[str, Any]:
    """Return recent Nepal-bbox USGS seismicity wrapped with a ProvenanceEnvelope."""
    now_utc = utc_now_iso()
    cache = cache_path or AL.CACHE_GDACS
    data_fallback = AL.OUT_JSON
    query_url = AL.usgs_nepal_fdsn_url(days=days, min_mag=min_mag)

    if not offline:
        try:
            events = AL.fetch_usgs_recent_nepal(days=days, min_mag=min_mag)
            obs_times = [t for e in events if (t := _epoch_ms_to_iso(e.get("time")))]
            env = make_envelope(
                source=USGS_SOURCE_NAME,
                dataset=USGS_RECENT_DATASET,
                data_class="live_observation",
                retrieved_at_utc=now_utc,
                observation_time_utc=max(obs_times) if obs_times else None,
                valid_until_utc=None,
                status="available",
                fallback_used=False,
                license_ref=USGS_LICENSE_REF,
                sla_hours=USGS_RECENT_SLA_HOURS,
                record_count=len(events),
                notes=f"Live USGS FDSN query (M>={min_mag}, past {days}d, Nepal bbox).",
            )
            return {
                "provenance": env,
                "fdsn_query_url": query_url,
                "window_days": days,
                "min_mag": min_mag,
                "n_events": len(events),
                "events": events,
            }
        except Exception as exc:
            err_note = f"Live USGS FDSN query failed ({exc}); fell back to cache."
    else:
        err_note = "Offline mode; loaded cached USGS recent seismicity."

    loaded: dict[str, Any] = {}
    src_file = cache if os.path.isfile(cache) else (data_fallback if os.path.isfile(data_fallback) else "")
    if src_file:
        try:
            with open(src_file, encoding="utf-8") as fh:
                loaded = json.load(fh)
        except Exception:
            loaded = {}

    if loaded:
        usgs_block = loaded.get("usgs_recent") if isinstance(loaded.get("usgs_recent"), dict) else {}
        events = list(usgs_block.get("events") or loaded.get("recent_quakes") or [])
        retrieved = format_iso_utc(
            usgs_block.get("updated_utc") or loaded.get("usgs_updated_utc") or loaded.get("updated_utc")
        ) or _file_mtime_iso(src_file) or now_utc
        obs_times = [t for e in events if (t := _epoch_ms_to_iso(e.get("time")))]
        sla = evaluate_envelope_sla(
            {"status": "available", "data_class": "cached", "retrieved_at_utc": retrieved, "sla_hours": USGS_RECENT_SLA_HOURS},
            ref_utc=now_utc,
        )
        env = make_envelope(
            source=USGS_SOURCE_NAME,
            dataset=USGS_RECENT_DATASET,
            data_class="cached",
            retrieved_at_utc=retrieved,
            observation_time_utc=max(obs_times) if obs_times else None,
            valid_until_utc=None,
            status="available" if sla["within_sla"] else "stale",
            fallback_used=True,
            license_ref=USGS_LICENSE_REF,
            sla_hours=USGS_RECENT_SLA_HOURS,
            record_count=len(events),
            notes=err_note,
        )
        return {
            "provenance": env,
            "fdsn_query_url": query_url,
            "window_days": int(usgs_block.get("window_days") or days),
            "min_mag": float(usgs_block.get("min_mag") or min_mag),
            "n_events": len(events),
            "events": events,
        }

    env = make_envelope(
        source=USGS_SOURCE_NAME,
        dataset=USGS_RECENT_DATASET,
        data_class="unavailable",
        retrieved_at_utc=now_utc,
        observation_time_utc=None,
        valid_until_utc=None,
        status="unavailable",
        fallback_used=True,
        license_ref=USGS_LICENSE_REF,
        sla_hours=USGS_RECENT_SLA_HOURS,
        record_count=0,
        notes=f"{err_note} No cached file present.",
    )
    return {
        "provenance": env,
        "fdsn_query_url": query_url,
        "window_days": days,
        "min_mag": min_mag,
        "n_events": 0,
        "events": [],
    }


def fetch_usgs_catalogue(
    offline: bool = True,
    *,
    refresh: bool = False,
    cache_path: str | None = None,
) -> dict[str, Any]:
    """Return historical USGS Nepal M>=4.0 catalogue wrapped with a ProvenanceEnvelope."""
    now_utc = utc_now_iso()
    cache = cache_path or os.path.join(C.CACHE, "usgs_catalogue.json")
    events: list[dict[str, Any]] = []
    fallback_used = False
    note = ""

    if not offline:
        try:
            events = SZ.fetch_catalogue(cache=cache, refresh=refresh)
            note = "USGS FDSN historical M>=4.0 catalogue (1900-present) via src/seismic.py."
        except Exception as exc:
            fallback_used = True
            note = f"Live USGS catalogue fetch failed ({exc}); using cached file."
            events = SZ._load_valid_cache(cache) or []
    else:
        events = SZ._load_valid_cache(cache) or []
        note = "Offline load of cached USGS historical M>=4.0 catalogue."

    if events:
        retrieved = now_utc if (not offline and not fallback_used and refresh) else (_file_mtime_iso(cache) or now_utc)
        obs_times = [t for e in events if (t := _epoch_ms_to_iso(e.get("time")))]
        summary = SZ.summarise(events)
        env = make_envelope(
            source=USGS_SOURCE_NAME,
            dataset=USGS_CATALOGUE_DATASET,
            data_class="historical",
            retrieved_at_utc=retrieved,
            observation_time_utc=max(obs_times) if obs_times else None,
            valid_until_utc=None,
            status="available",
            fallback_used=fallback_used,
            license_ref=USGS_LICENSE_REF,
            sla_hours=USGS_CATALOGUE_SLA_HOURS,
            record_count=len(events),
            notes=note,
        )
        return {
            "provenance": env,
            "summary": summary,
            "n_events": len(events),
            "events": events,
        }

    env = make_envelope(
        source=USGS_SOURCE_NAME,
        dataset=USGS_CATALOGUE_DATASET,
        data_class="unavailable",
        retrieved_at_utc=now_utc,
        observation_time_utc=None,
        valid_until_utc=None,
        status="unavailable",
        fallback_used=True,
        license_ref=USGS_LICENSE_REF,
        sla_hours=USGS_CATALOGUE_SLA_HOURS,
        record_count=0,
        notes=f"{note} Cache absent or empty.",
    )
    return {
        "provenance": env,
        "summary": {},
        "n_events": 0,
        "events": [],
    }


def get_provenance(offline: bool = True) -> list[dict[str, Any]]:
    """Return ProvenanceEnvelopes for USGS recent and historical seismic feeds."""
    return [
        fetch_usgs_recent(offline=offline)["provenance"],
        fetch_usgs_catalogue(offline=offline)["provenance"],
    ]
