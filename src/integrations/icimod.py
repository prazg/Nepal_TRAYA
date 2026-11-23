"""
Thin provenance wrapper for ICIMOD HMAGLOFDB v4.0 historical GLOF records and
the Nepal Cryosphere Inventory / glacial lake static hazard assessment.

Pure Python 3.12 standard library only (zero third-party dependencies).
"""
from __future__ import annotations

import datetime as dt
import json
import os
import sys
from pathlib import Path
from typing import Any

SRC_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if SRC_DIR not in sys.path:
    sys.path.insert(0, SRC_DIR)

import config as C
from .provenance import (
    make_envelope,
    utc_now_iso,
)

ICIMOD_SOURCE_NAME = "ICIMOD HMAGLOFDB v4.0 / Nepal Cryosphere Inventory"
ICIMOD_GLOF_DATASET = "icimod_hmaglofdb_nepal_glofs"
ICIMOD_LAKES_DATASET = "nepal_cryosphere_glacial_lakes_1429"
ICIMOD_LICENSE_REF = "ICIMOD RDS Open Data Terms / RGI 7.0 CC-BY-4.0"
ICIMOD_SLA_HOURS = 8760  # Annual static/historical benchmark cadence


def _file_mtime_iso(path: Path) -> str | None:
    if not path.is_file():
        return None
    try:
        return dt.datetime.fromtimestamp(path.stat().st_mtime, tz=dt.timezone.utc).strftime(
            "%Y-%m-%dT%H:%M:%SZ"
        )
    except OSError:
        return None


def load_icimod_glof_history(repo_root: str | os.PathLike[str] | None = None) -> dict[str, Any]:
    """Load Nepal historical GLOF records (HMAGLOFDB v4.0 / glof.geojson) with provenance."""
    root = Path(repo_root).resolve() if repo_root else Path(C.ROOT).resolve()
    now_utc = utc_now_iso()

    glof_json = root / "data" / "glof_history.json"
    raw_glof = root / "raw" / "glof.geojson"
    full_csv = root / "raw" / "HMAGLOFDB_v4.csv"

    records: list[dict[str, Any]] = []
    source_path: Path | None = None

    if glof_json.is_file():
        try:
            with open(glof_json, encoding="utf-8") as fh:
                loaded = json.load(fh)
            if isinstance(loaded, list):
                records = [r for r in loaded if isinstance(r, dict)]
                source_path = glof_json
        except Exception:
            records = []
    elif raw_glof.is_file():
        try:
            with open(raw_glof, encoding="utf-8") as fh:
                gj = json.load(fh)
            feats = gj.get("features") if isinstance(gj, dict) else []
            if isinstance(feats, list):
                records = [f.get("properties") or {} for f in feats if isinstance(f, dict)]
                source_path = raw_glof
        except Exception:
            records = []

    years: list[int] = []
    for rec in records:
        yr = rec.get("year") or rec.get("Year_exact") or rec.get("Year_approx")
        if isinstance(yr, (int, float)) and not isinstance(yr, bool) and yr > 1000:
            years.append(int(yr))

    year_range = [min(years), max(years)] if years else None
    obs_utc = f"{max(years)}-12-31T00:00:00Z" if years else None

    if records and source_path is not None:
        retrieved = _file_mtime_iso(source_path) or now_utc
        note = (
            f"Historical Nepal GLOF catalogue ({len(records)} events"
            + (f", {year_range[0]}-{year_range[1]}" if year_range else "")
            + "). Full HMAGLOFDB_v4.csv present."
            if full_csv.is_file()
            else f"Historical Nepal GLOF catalogue ({len(records)} events"
            + (f", {year_range[0]}-{year_range[1]}" if year_range else "")
            + "; derived from raw/glof.geojson fallback — place raw/HMAGLOFDB_v4.csv for full regional database)."
        )
        env = make_envelope(
            source=ICIMOD_SOURCE_NAME,
            dataset=ICIMOD_GLOF_DATASET,
            data_class="historical",
            retrieved_at_utc=retrieved,
            observation_time_utc=obs_utc,
            valid_until_utc=None,
            status="available",
            fallback_used=not full_csv.is_file(),
            license_ref=ICIMOD_LICENSE_REF,
            sla_hours=ICIMOD_SLA_HOURS,
            record_count=len(records),
            notes=note,
        )
    else:
        env = make_envelope(
            source=ICIMOD_SOURCE_NAME,
            dataset=ICIMOD_GLOF_DATASET,
            data_class="unavailable",
            retrieved_at_utc=now_utc,
            observation_time_utc=None,
            valid_until_utc=None,
            status="unavailable",
            fallback_used=True,
            license_ref=ICIMOD_LICENSE_REF,
            sla_hours=ICIMOD_SLA_HOURS,
            record_count=0,
            notes="Neither data/glof_history.json nor raw/glof.geojson found.",
        )

    return {
        "provenance": env,
        "n_records": len(records),
        "year_range": year_range,
        "full_hmaglofdb_csv_present": full_csv.is_file(),
        "records": records,
    }


def load_cryosphere_inventory_provenance(
    repo_root: str | os.PathLike[str] | None = None,
) -> dict[str, Any]:
    """Return ProvenanceEnvelope for the static 1,429-lake Nepal glacial lake inventory."""
    root = Path(repo_root).resolve() if repo_root else Path(C.ROOT).resolve()
    now_utc = utc_now_iso()

    lakes_core = root / "data" / "lakes_core.json"
    summary_path = root / "data" / "summary.json"
    n_lakes = 0
    retrieved = now_utc

    if lakes_core.is_file():
        try:
            with open(lakes_core, encoding="utf-8") as fh:
                obj = json.load(fh)
            if isinstance(obj, dict):
                n_lakes = int(obj.get("n_lakes") or len(obj.get("features") or []))
            retrieved = _file_mtime_iso(lakes_core) or now_utc
        except Exception:
            n_lakes = 0
    elif summary_path.is_file():
        try:
            with open(summary_path, encoding="utf-8") as fh:
                obj = json.load(fh)
            if isinstance(obj, dict):
                n_lakes = int(obj.get("n_lakes") or 0)
            retrieved = _file_mtime_iso(summary_path) or now_utc
        except Exception:
            n_lakes = 0

    if n_lakes > 0:
        return make_envelope(
            source="Nepal Cryosphere Inventory (RGI 7.0 / Copernicus DEM GLO-30 / Rounce et al. 2016 / Veh et al. 2020)",
            dataset=ICIMOD_LAKES_DATASET,
            data_class="static_assessment",
            retrieved_at_utc=retrieved,
            observation_time_utc=None,
            valid_until_utc=None,
            status="available",
            fallback_used=False,
            license_ref="CC-BY-4.0 (RGI 7.0 / Veh et al. 2020) & Copernicus DEM GLO-30 licence",
            sla_hours=ICIMOD_SLA_HOURS,
            record_count=n_lakes,
            notes=f"Static GLOF hazard & screening assessment across {n_lakes} Nepal glacial lakes.",
        )

    return make_envelope(
        source="Nepal Cryosphere Inventory",
        dataset=ICIMOD_LAKES_DATASET,
        data_class="unavailable",
        retrieved_at_utc=now_utc,
        observation_time_utc=None,
        valid_until_utc=None,
        status="unavailable",
        fallback_used=True,
        license_ref="CC-BY-4.0 / Copernicus DEM licence",
        sla_hours=ICIMOD_SLA_HOURS,
        record_count=0,
        notes="Glacial lake inventory data/lakes_core.json not present.",
    )


def get_provenance(repo_root: str | os.PathLike[str] | None = None) -> list[dict[str, Any]]:
    """Return ProvenanceEnvelopes for ICIMOD HMAGLOFDB and the glacial-lake inventory."""
    return [
        load_icimod_glof_history(repo_root=repo_root)["provenance"],
        load_cryosphere_inventory_provenance(repo_root=repo_root),
    ]
