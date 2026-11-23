"""
Nepal TRĀYA 2.0 — Data Integrations & Provenance Package.

Provides canonical provenance envelopes, build manifest & KPI baseline
builders, live/offline clients for official Government of Nepal NDRRMA BIPAD
Portal v1 and Copernicus Sentinel-1 SAR / Sentinel-2 L2A STAC, thin provenance
wrappers around existing TRĀYA hazard modules, and documented institutional
adapter stubs (DHM, NEMRC, DoR).

Pure Python 3.12 standard library only (zero third-party dependencies).
"""
from __future__ import annotations

import importlib
from typing import Any

from .provenance import (
    SCHEMA_VERSION,
    VALID_DATA_CLASSES,
    VALID_STATUSES,
    atomic_write_json,
    build_kpi_baseline,
    build_manifest,
    compute_file_sha256,
    evaluate_envelope_sla,
    format_step_summary_markdown,
    make_envelope,
    utc_now_iso,
)

_SUBMODULES: frozenset[str] = frozenset({
    "bipad",
    "copernicus",
    "dhm",
    "icimod",
    "nemrc",
    "openmeteo",
    "osm",
    "provenance",
    "roads_authority",
    "usgs",
})


def __getattr__(name: str) -> Any:
    if name in _SUBMODULES:
        return importlib.import_module(f".{name}", __name__)
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")


def __dir__() -> list[str]:
    return sorted(set(globals()) | _SUBMODULES)


__all__ = [
    "SCHEMA_VERSION",
    "VALID_DATA_CLASSES",
    "VALID_STATUSES",
    "atomic_write_json",
    "bipad",
    "build_kpi_baseline",
    "build_manifest",
    "compute_file_sha256",
    "copernicus",
    "dhm",
    "evaluate_envelope_sla",
    "format_step_summary_markdown",
    "icimod",
    "make_envelope",
    "nemrc",
    "openmeteo",
    "osm",
    "provenance",
    "roads_authority",
    "usgs",
    "utc_now_iso",
]
