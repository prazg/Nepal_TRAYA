"""
Canonical provenance envelopes, build manifest generation, KPI baseline
calculation, and GitHub Actions step-summary formatting for Nepal TRĀYA 2.0.

Pure Python 3.12 standard library only (zero third-party dependencies).
"""
from __future__ import annotations

import datetime as dt
import hashlib
import json
import math
import os
import tempfile
from collections.abc import Mapping, Sequence
from pathlib import Path
from typing import Any

SCHEMA_VERSION = "2.0.0"

VALID_DATA_CLASSES: tuple[str, ...] = (
    "live_observation",
    "forecast",
    "historical",
    "static_assessment",
    "cached",
    "unavailable",
)

VALID_STATUSES: tuple[str, ...] = (
    "available",
    "stale",
    "unavailable",
)

VALID_HEALTH_STATES: tuple[str, ...] = (
    "healthy",
    "degraded",
    "stale",
)

REQUIRED_PROVENANCE_FIELDS: tuple[str, ...] = (
    "source",
    "retrieved_at_utc",
    "license_ref",
    "data_class",
)

# Canonical key files hashed in data/manifest.json when present in repo_root
_KEY_INPUT_OUTPUT_RELPATHS: tuple[str, ...] = (
    "raw/glof.geojson",
    "raw/HMAGLOFDB_v4.csv",
    "cache/nepal_admin.json",
    "cache/terrain.json",
    "cache/glofas_weekly.json",
    "cache/glofas_climatology.json",
    "cache/hydromet_weekly.json",
    "cache/landslides.json",
    "cache/gdacs_alerts.json",
    "cache/usgs_catalogue.json",
    "cache/gem_faults.json",
    "cache/stac_scenes.json",
    "cache/bipad_snapshot.json",
    "cache/eo_sar.json",
    "cache/overpass/places.json",
    "cache/overpass/health.json",
    "cache/overpass/hydropower.json",
    "cache/overpass/bridges.json",
    "cache/overpass/borders.json",
    "data/summary.json",
    "data/lakes_core.json",
    "data/lakes.json",
    "data/routes.json",
    "data/exposure.json",
    "data/exposure_isolation.json",
    "data/cascades.json",
    "data/districts.json",
    "data/eq_history_m6.json",
    "data/glof_history.json",
    "data/faults.json",
    "data/rivers_watch.json",
    "data/landslides.json",
    "data/hydromet_weekly.json",
    "data/gdacs_alerts.json",
    "data/bipad_official.json",
    "data/eo_sar.json",
    "data/validation.json",
)


def utc_now_iso() -> str:
    """Return current UTC timestamp formatted as strict ISO-8601 Z string."""
    return dt.datetime.now(dt.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def parse_iso_utc(value: str | dt.datetime | None) -> dt.datetime | None:
    """Parse an ISO-8601 timestamp or YYYY-MM-DD string into an aware UTC datetime."""
    if value is None:
        return None
    if isinstance(value, dt.datetime):
        if value.tzinfo is None:
            return value.replace(tzinfo=dt.timezone.utc)
        return value.astimezone(dt.timezone.utc)
    s = str(value).strip()
    if not s:
        return None
    if s.endswith("Z"):
        s = s[:-1] + "+00:00"
    try:
        parsed = dt.datetime.fromisoformat(s)
    except ValueError:
        if len(s) >= 10:
            try:
                parsed = dt.datetime.fromisoformat(s[:10])
            except ValueError:
                return None
        else:
            return None
    if parsed.tzinfo is None:
        return parsed.replace(tzinfo=dt.timezone.utc)
    return parsed.astimezone(dt.timezone.utc)


def format_iso_utc(value: str | dt.datetime | None) -> str | None:
    """Normalize a datetime or ISO-8601 string to UTC ISO-8601 with trailing Z."""
    if value is None:
        return None
    if isinstance(value, dt.datetime):
        aware = value.replace(tzinfo=dt.timezone.utc) if value.tzinfo is None else value.astimezone(dt.timezone.utc)
        return aware.strftime("%Y-%m-%dT%H:%M:%SZ")
    s = str(value).strip()
    if not s:
        return None
    parsed = parse_iso_utc(s)
    if parsed is not None:
        return parsed.strftime("%Y-%m-%dT%H:%M:%SZ")
    return s


def safe_url(url: Any, *, require_https: bool = False) -> str | None:
    """Validate an HTTP(S) URL string; return None if absent or unsafe."""
    s = str(url or "").strip()
    if not s:
        return None
    if require_https:
        return s if s.startswith("https://") else None
    if s.startswith("https://") or s.startswith("http://"):
        return s
    return None


def atomic_write_json(path: str | os.PathLike[str], obj: Any, *, indent: int | None = None) -> int:
    """Atomically write strict UTF-8 JSON (allow_nan=False) and return byte size."""
    target = os.path.abspath(os.fspath(path))
    parent = os.path.dirname(target)
    os.makedirs(parent, exist_ok=True)
    fd, tmp_path = tempfile.mkstemp(dir=parent, prefix=".tmp_", suffix=".json")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as fh:
            if indent is None:
                json.dump(obj, fh, separators=(",", ":"), ensure_ascii=False, allow_nan=False)
            else:
                json.dump(obj, fh, indent=indent, ensure_ascii=False, allow_nan=False)
        os.replace(tmp_path, target)
    except Exception:
        if os.path.exists(tmp_path):
            try:
                os.remove(tmp_path)
            except OSError:
                pass
        raise
    return os.path.getsize(target)


def compute_file_sha256(path: str | os.PathLike[str]) -> str:
    """Return the lowercase hexadecimal SHA-256 checksum of a file."""
    h = hashlib.sha256()
    with open(path, "rb") as fh:
        while chunk := fh.read(65536):
            h.update(chunk)
    return h.hexdigest()


def make_envelope(
    source: str,
    dataset: str,
    data_class: str,
    retrieved_at_utc: str | dt.datetime | None,
    observation_time_utc: str | dt.datetime | None = None,
    valid_until_utc: str | dt.datetime | None = None,
    status: str = "available",
    fallback_used: bool = False,
    license_ref: str = "",
    sla_hours: int | float | None = 168,
    record_count: int = 0,
    notes: str = "",
    schema_version: str = SCHEMA_VERSION,
    *,
    requires_institutional_agreement: bool = False,
) -> dict[str, Any]:
    """Construct and validate a canonical TRĀYA 2.0 ProvenanceEnvelope dict."""
    src_str = str(source or "").strip()
    ds_str = str(dataset or "").strip()
    if not src_str:
        raise ValueError("source must be a non-empty string")
    if not ds_str:
        raise ValueError("dataset must be a non-empty string")
    if data_class not in VALID_DATA_CLASSES:
        raise ValueError(
            f"Invalid data_class {data_class!r}; expected one of {VALID_DATA_CLASSES}"
        )
    if status not in VALID_STATUSES:
        raise ValueError(
            f"Invalid status {status!r}; expected one of {VALID_STATUSES}"
        )
    if sla_hours is not None:
        if isinstance(sla_hours, bool) or not isinstance(sla_hours, (int, float)):
            raise ValueError(f"sla_hours must be numeric or None, got {sla_hours!r}")
        if not math.isfinite(float(sla_hours)) or float(sla_hours) < 0:
            raise ValueError(f"sla_hours must be finite and >= 0, got {sla_hours!r}")
    if isinstance(record_count, bool) or not isinstance(record_count, int) or record_count < 0:
        raise ValueError(f"record_count must be a non-negative int, got {record_count!r}")

    envelope: dict[str, Any] = {
        "schema_version": str(schema_version or SCHEMA_VERSION).strip(),
        "source": src_str,
        "dataset": ds_str,
        "data_class": data_class,
        "status": status,
        "retrieved_at_utc": format_iso_utc(retrieved_at_utc),
        "observation_time_utc": format_iso_utc(observation_time_utc),
        "valid_until_utc": format_iso_utc(valid_until_utc),
        "fallback_used": bool(fallback_used),
        "license_ref": str(license_ref or "").strip(),
        "sla_hours": int(sla_hours) if isinstance(sla_hours, float) and sla_hours.is_integer() else sla_hours,
        "record_count": int(record_count),
        "notes": str(notes or "").strip(),
    }
    if requires_institutional_agreement:
        envelope["requires_institutional_agreement"] = True
    return envelope


def _normalize_envelopes(envelopes: Sequence[Mapping[str, Any]] | Mapping[str, Mapping[str, Any]] | None) -> list[dict[str, Any]]:
    if not envelopes:
        return []
    if isinstance(envelopes, Mapping):
        raw_list = list(envelopes.values())
    else:
        raw_list = list(envelopes)
    return [dict(e) for e in raw_list if isinstance(e, Mapping)]


def _is_institutional_stub(env: Mapping[str, Any]) -> bool:
    if env.get("requires_institutional_agreement"):
        return True
    if env.get("data_class") == "unavailable" and env.get("status") == "unavailable":
        notes = str(env.get("notes") or "").lower()
        if "institutional_integration_spec" in notes or "institutional agreement" in notes:
            return True
    return False


def evaluate_envelope_sla(
    env: Mapping[str, Any],
    ref_utc: str | dt.datetime | None = None,
) -> dict[str, Any]:
    """Evaluate freshness of a single ProvenanceEnvelope against its SLA and expiry."""
    ref_dt = parse_iso_utc(ref_utc) or dt.datetime.now(dt.timezone.utc)
    status = str(env.get("status") or "unavailable")
    data_class = str(env.get("data_class") or "unavailable")
    sla_hours = env.get("sla_hours")
    retrieved_dt = parse_iso_utc(env.get("retrieved_at_utc"))
    valid_until_dt = parse_iso_utc(env.get("valid_until_utc"))

    age_h: float | None = None
    if retrieved_dt is not None:
        age_h = round(max(0.0, (ref_dt - retrieved_dt).total_seconds() / 3600.0), 2)

    expired = bool(valid_until_dt is not None and valid_until_dt < ref_dt)

    if status == "unavailable" or data_class == "unavailable":
        return {
            "within_sla": False,
            "effective_status": "unavailable",
            "age_hours": age_h,
            "expired": expired,
        }

    if status == "stale" or expired:
        return {
            "within_sla": False,
            "effective_status": "stale",
            "age_hours": age_h,
            "expired": expired,
        }

    if sla_hours is None:
        within = True
    elif age_h is None:
        within = False
    else:
        within = age_h <= float(sla_hours)

    return {
        "within_sla": within,
        "effective_status": "available" if within else "stale",
        "age_hours": age_h,
        "expired": expired,
    }


def _collect_input_checksums(repo_root: Path) -> dict[str, str]:
    """Compute deterministic SHA-256 checksums for key inputs and outputs under repo_root."""
    seen: set[str] = set()
    candidates: list[str] = []

    for rel in _KEY_INPUT_OUTPUT_RELPATHS:
        if rel not in seen:
            seen.add(rel)
            candidates.append(rel)

    # Also include any additional data/*.json or cache/*.json present (excluding manifest/kpi itself)
    for sub in ("cache", "data"):
        sub_dir = repo_root / sub
        if sub_dir.is_dir():
            for child in sorted(sub_dir.iterdir(), key=lambda p: p.name):
                if not child.is_file() or child.suffix.lower() != ".json":
                    continue
                if sub == "data" and child.name in ("manifest.json", "kpi_baseline.json"):
                    continue
                rel = f"{sub}/{child.name}"
                if rel not in seen:
                    seen.add(rel)
                    candidates.append(rel)

    checksums: dict[str, str] = {}
    for rel in sorted(candidates):
        full = repo_root / rel
        if full.is_file():
            checksums[rel] = compute_file_sha256(full)
    return checksums


def build_manifest(
    repo_root: str | os.PathLike[str],
    envelopes: Sequence[Mapping[str, Any]] | Mapping[str, Mapping[str, Any]],
    build_utc: str | dt.datetime,
    git_sha: str = "unknown",
    *,
    write: bool = True,
) -> dict[str, Any]:
    """Build (and by default atomically write) `data/manifest.json`."""
    root = Path(repo_root).resolve()
    build_iso = format_iso_utc(build_utc) or utc_now_iso()
    sources = _normalize_envelopes(envelopes)

    operational = [e for e in sources if not _is_institutional_stub(e)]
    stubs = [e for e in sources if _is_institutional_stub(e)]

    n_fresh = 0
    n_stale = 0
    n_unavail = 0
    n_fallback = 0

    for env in operational:
        ev = evaluate_envelope_sla(env, ref_utc=build_iso)
        if ev["effective_status"] == "available":
            n_fresh += 1
        elif ev["effective_status"] == "stale":
            n_stale += 1
        else:
            n_unavail += 1
        if env.get("fallback_used"):
            n_fallback += 1

    n_op = len(operational)
    if n_op == 0:
        overall_health = "degraded"
    elif n_stale > 0 and (n_stale * 2 >= n_op or n_fresh == 0):
        overall_health = "stale"
    elif n_unavail > 0 or n_stale > 0 or n_fallback > 0:
        overall_health = "degraded"
    else:
        overall_health = "healthy"

    manifest: dict[str, Any] = {
        "schema_version": SCHEMA_VERSION,
        "build_utc": build_iso,
        "git_sha": str(git_sha or "unknown").strip() or "unknown",
        "overall_health": overall_health,
        "source_counts": {
            "total": len(sources),
            "operational": n_op,
            "available": n_fresh,
            "stale": n_stale,
            "unavailable": n_unavail,
            "fallback_used": n_fallback,
            "institutional_stubs": len(stubs),
        },
        "sources": sources,
        "input_checksums": _collect_input_checksums(root),
    }

    if write:
        atomic_write_json(root / "data" / "manifest.json", manifest)
    return manifest


def _extract_landslide_maturity(landslides_data: Mapping[str, Any] | None) -> dict[str, Any]:
    data = landslides_data if isinstance(landslides_data, Mapping) else {}
    events_raw = data.get("events")
    events: list[Mapping[str, Any]] = [e for e in events_raw if isinstance(e, Mapping)] if isinstance(events_raw, list) else []

    dated_field = data.get("dated_events")
    undated_field = data.get("undated_scars")

    dated_list = [e for e in dated_field if isinstance(e, Mapping)] if isinstance(dated_field, list) else []
    undated_list = [e for e in undated_field if isinstance(e, Mapping)] if isinstance(undated_field, list) else []

    if isinstance(dated_field, int) and not isinstance(dated_field, bool):
        n_dated = dated_field
    elif isinstance(data.get("n_dated_events"), int):
        n_dated = int(data["n_dated_events"])
    elif dated_list:
        n_dated = len(dated_list)
    else:
        n_dated = sum(
            1
            for e in events
            if bool(e.get("date") or e.get("incident_on") or e.get("incidentOn"))
            and str(e.get("record_type") or "").lower() != "undated_scar"
        )

    if isinstance(undated_field, int) and not isinstance(undated_field, bool):
        n_undated = undated_field
    elif isinstance(data.get("n_undated_scars"), int):
        n_undated = int(data["n_undated_scars"])
    elif undated_list:
        n_undated = len(undated_list)
    else:
        n_undated = sum(
            1
            for e in events
            if not (e.get("date") or e.get("incident_on") or e.get("incidentOn"))
            or str(e.get("record_type") or "").lower() == "undated_scar"
        )

    dup_val = (
        data.get("duplicate_candidates")
        if data.get("duplicate_candidates") is not None
        else data.get("duplicate_candidates_count")
        if data.get("duplicate_candidates_count") is not None
        else data.get("n_duplicate_candidates")
        if data.get("n_duplicate_candidates") is not None
        else data.get("dedup_candidates")
        if data.get("dedup_candidates") is not None
        else data.get("potential_duplicates")
    )
    if isinstance(dup_val, int) and not isinstance(dup_val, bool):
        n_dupes = dup_val
    elif isinstance(dup_val, list):
        n_dupes = len(dup_val)
    else:
        n_dupes = sum(
            1
            for e in (events + dated_list)
            if e.get("duplicate_candidate") or e.get("duplicate_of")
        )

    # Verify null-casualty integrity: undated scars must NOT coerce missing casualties to 0
    all_checked = list(events) + list(dated_list) + list(undated_list)
    integrity_violations = 0
    for e in all_checked:
        is_undated_scar = (
            not (e.get("date") or e.get("incident_on") or e.get("incidentOn"))
            or str(e.get("record_type") or "").lower() == "undated_scar"
            or "openstreetmap" in str(e.get("source") or "").lower()
        )
        if is_undated_scar:
            for field in ("fatalities", "injuries", "deaths", "peopleDeathCount", "peopleInjuredCount"):
                if field in e and e[field] == 0:
                    integrity_violations += 1
                    break

    explicit_ok = data.get("null_casualty_integrity_ok")
    if isinstance(explicit_ok, bool):
        null_integrity_ok = explicit_ok and (integrity_violations == 0)
    else:
        null_integrity_ok = integrity_violations == 0

    total = n_dated + n_undated
    sources_present = sorted({str(e.get("source")).strip() for e in all_checked if e.get("source")})
    return {
        "dated_events": int(n_dated),
        "undated_scars": int(n_undated),
        "duplicate_candidates": int(n_dupes),
        "null_casualty_integrity_ok": bool(null_integrity_ok),
        "total_records": int(total),
        "dated_share_pct": round(100.0 * n_dated / total, 1) if total > 0 else 0.0,
        "sources_present": sources_present,
    }


def _index_admin_rows(raw: Any, key_candidates: tuple[str, ...]) -> dict[str, Any]:
    if isinstance(raw, Mapping):
        return {str(k): v for k, v in raw.items()}
    if isinstance(raw, list):
        out: dict[str, Any] = {}
        for item in raw:
            if not isinstance(item, Mapping):
                continue
            name = None
            for k in key_candidates:
                if item.get(k):
                    name = str(item[k]).strip()
                    break
            if name:
                out[name] = dict(item)
        return out
    return {}


def _aggregate_provinces_from_districts(by_dist: Mapping[str, Any]) -> dict[str, Any]:
    """Roll up district-level exposure records into province-level summaries when needed."""
    provs: dict[str, dict[str, Any]] = {}
    for rec in by_dist.values():
        if not isinstance(rec, Mapping):
            continue
        pname = str(rec.get("prov") or rec.get("province") or "").strip()
        if not pname:
            continue
        bucket = provs.setdefault(
            pname,
            {
                "n_districts": 0,
                "n_routed_corridors": 0,
                "settlements_in_corridors": 0,
                "settlements_potentially_isolated": 0,
                "bridges_at_crossings": 0,
                "health_facilities_in_corridors": 0,
                "hydropower_in_corridors": 0,
                "high_isolation_districts": 0,
            },
        )
        bucket["n_districts"] += 1
        bucket["n_routed_corridors"] += int(rec.get("n_routed_corridors") or 0)
        bucket["settlements_in_corridors"] += int(
            rec.get("unique_settlements_in_1km_corridors") or rec.get("settlements") or 0
        )
        bucket["settlements_potentially_isolated"] += int(
            rec.get("unique_settlements_potentially_isolated") or 0
        )
        bucket["bridges_at_crossings"] += int(rec.get("unique_bridges_at_crossings") or 0)
        bucket["health_facilities_in_corridors"] += int(
            rec.get("unique_health_facilities_in_corridors") or 0
        )
        bucket["hydropower_in_corridors"] += int(rec.get("unique_hydropower_in_corridors") or 0)
        if str(rec.get("district_isolation_risk") or "").lower() == "high":
            bucket["high_isolation_districts"] += 1
    return dict(sorted(provs.items()))


def _extract_exposure_coverage(
    exposure_isolation_data: Mapping[str, Any] | None,
    summary: Mapping[str, Any] | None,
    sources: Sequence[Mapping[str, Any]],
) -> dict[str, Any]:
    exp = exposure_isolation_data if isinstance(exposure_isolation_data, Mapping) else {}
    summ = summary if isinstance(summary, Mapping) else {}

    by_dist = _index_admin_rows(
        exp.get("by_district") or exp.get("districts") or exp.get("district_summary"),
        ("district", "name", "id"),
    )
    by_prov = _index_admin_rows(
        exp.get("by_province") or exp.get("provinces") or exp.get("province_summary"),
        ("province", "prov", "name", "id"),
    )
    if not by_prov and by_dist:
        by_prov = _aggregate_provinces_from_districts(by_dist)

    source_date_tags: dict[str, str] = {}
    for raw_tag_key in ("source_date_tags", "source_dates"):
        raw_tags = exp.get(raw_tag_key)
        if isinstance(raw_tags, Mapping):
            for k, v in raw_tags.items():
                if v is not None and str(v).strip():
                    source_date_tags[str(k)] = str(v).strip()

    exp_prov = exp.get("provenance")
    exp_ts = (
        (exp_prov.get("retrieved_at_utc") or exp_prov.get("generated_utc"))
        if isinstance(exp_prov, Mapping)
        else None
    ) or exp.get("generated_utc")
    if exp_ts:
        ds = str((exp_prov or {}).get("dataset") or "exposure_isolation") if isinstance(exp_prov, Mapping) else "exposure_isolation"
        source_date_tags.setdefault(ds, str(exp_ts)[:10])
    if isinstance(exp_prov, Mapping) and isinstance(exp_prov.get("sources"), list):
        for s_item in exp_prov["sources"]:
            if isinstance(s_item, Mapping) and s_item.get("provider_id"):
                tag_ts = s_item.get("retrieved_at_utc") or s_item.get("date") or exp_ts
                if tag_ts:
                    source_date_tags.setdefault(str(s_item["provider_id"]), str(tag_ts)[:10])

    for env in sources:
        ds = str(env.get("dataset") or "").strip()
        ts = env.get("observation_time_utc") or env.get("retrieved_at_utc")
        if ds and ts and any(tok in ds.lower() for tok in ("osm", "exposure", "worldpop", "bipad", "icimod", "lakes")):
            source_date_tags.setdefault(ds, str(ts)[:10])

    if "worldpop_nepal" not in source_date_tags:
        source_date_tags["worldpop_nepal"] = "2020"

    if isinstance(exp.get("national_totals"), Mapping):
        national_totals = dict(exp["national_totals"])
    elif isinstance(exp.get("totals"), Mapping):
        national_totals = dict(exp["totals"])
    elif isinstance(exp.get("summary"), Mapping):
        national_totals = dict(exp["summary"])
    else:
        national_totals = dict(summ.get("exposure_totals") or {})

    return {
        "n_provinces_covered": len(by_prov) if by_prov else int(summ.get("n_provinces") or 0),
        "n_districts_covered": len(by_dist) if by_dist else int(summ.get("n_districts") or 0),
        "by_province": by_prov,
        "by_district": by_dist,
        "national_totals": national_totals,
        "source_date_tags": source_date_tags,
    }


def _classify_link_evidence(link: Mapping[str, Any]) -> str:
    if link.get("observed") is True:
        return "observed"
    if link.get("observed") is False:
        return "modelled"
    for key in ("evidence_type", "basis", "link_type", "classification", "provenance_class", "type", "kind"):
        val = str(link.get(key) or "").strip().lower()
        if not val:
            continue
        if any(tok in val for tok in ("observ", "historic", "record", "verified", "sensor", "gauge")):
            return "observed"
        if any(tok in val for tok in ("model", "forecast", "simulat", "empiric", "screen", "project", "scenario")):
            return "modelled"
    return "modelled"


def _extract_cascade_summary(cascades_data: Mapping[str, Any] | None) -> dict[str, Any]:
    data = cascades_data if isinstance(cascades_data, Mapping) else {}
    cas_summary = data.get("summary") if isinstance(data.get("summary"), Mapping) else {}

    raw_pathways = data.get("pathways") or data.get("cascades") or data.get("chains") or []
    if isinstance(raw_pathways, Mapping):
        pathways = [v for v in raw_pathways.values() if isinstance(v, Mapping)]
    elif isinstance(raw_pathways, list):
        pathways = [p for p in raw_pathways if isinstance(p, Mapping)]
    else:
        pathways = []

    active_ids: list[str] = []
    active_scenarios = data.get("active_scenarios")
    if isinstance(active_scenarios, list) and active_scenarios:
        for sc in active_scenarios:
            if isinstance(sc, Mapping):
                active_ids.append(
                    str(sc.get("scenario_id") or sc.get("chain_id") or sc.get("id") or sc.get("name") or "scenario")
                )
            elif sc:
                active_ids.append(str(sc))
    else:
        for p in pathways:
            status = str(p.get("status") or p.get("state") or p.get("severity") or "").strip().lower()
            is_active = (
                bool(p.get("active"))
                if "active" in p
                else status in ("active", "watch", "elevated", "warning", "severe", "triggered")
            )
            if is_active:
                active_ids.append(str(p.get("chain_id") or p.get("id") or p.get("name") or "pathway"))

    if isinstance(data.get("active_pathways"), int) and not isinstance(data.get("active_pathways"), bool):
        n_active = int(data["active_pathways"])
    elif active_ids:
        n_active = len(active_ids)
    elif isinstance(cas_summary.get("n_active_scenarios"), int):
        n_active = int(cas_summary["n_active_scenarios"])
    else:
        n_active = 0

    links: list[Mapping[str, Any]] = []
    top_links = data.get("links") or data.get("edges")
    if isinstance(top_links, list):
        links.extend(lk for lk in top_links if isinstance(lk, Mapping))
    for p in pathways:
        p_links = p.get("links") or p.get("edges") or p.get("steps")
        if isinstance(p_links, list):
            links.extend(lk for lk in p_links if isinstance(lk, Mapping))

    ebt = cas_summary.get("edges_by_evidence_type")
    if isinstance(data.get("observed_links"), int) and isinstance(data.get("modelled_links"), int):
        n_obs = int(data["observed_links"])
        n_mod = int(data["modelled_links"])
    elif links:
        n_obs = sum(1 for lk in links if _classify_link_evidence(lk) == "observed")
        n_mod = sum(1 for lk in links if _classify_link_evidence(lk) == "modelled")
    elif isinstance(ebt, Mapping):
        n_obs = int(ebt.get("observed") or 0)
        n_mod = sum(int(v or 0) for k, v in ebt.items() if str(k).lower() != "observed")
    else:
        n_obs = 0
        n_mod = 0

    total_pw = (
        len(pathways)
        if pathways
        else int(cas_summary.get("n_chains") or data.get("total_pathways") or n_active)
    )
    return {
        "total_pathways": total_pw,
        "active_pathways": n_active,
        "observed_links": n_obs,
        "modelled_links": n_mod,
        "total_links": n_obs + n_mod,
        "active_pathway_ids": active_ids,
    }


def build_kpi_baseline(
    repo_root: str | os.PathLike[str],
    manifest: Mapping[str, Any],
    summary: Mapping[str, Any] | None,
    landslides_data: Mapping[str, Any] | None,
    exposure_isolation_data: Mapping[str, Any] | None,
    cascades_data: Mapping[str, Any] | None,
    *,
    write: bool = True,
) -> dict[str, Any]:
    """Build (and by default atomically write) `data/kpi_baseline.json`."""
    root = Path(repo_root).resolve()
    build_utc = format_iso_utc(manifest.get("build_utc")) or utc_now_iso()
    sources = _normalize_envelopes(manifest.get("sources"))

    # 1. Feed freshness (% of active non-stub sources within source-specific SLA)
    active_sources = [e for e in sources if not _is_institutional_stub(e)]
    stub_sources = [e for e in sources if _is_institutional_stub(e)]
    within_sla = 0
    stale_count = 0
    unavail_active = 0
    for env in active_sources:
        ev = evaluate_envelope_sla(env, ref_utc=build_utc)
        if ev["within_sla"]:
            within_sla += 1
        elif ev["effective_status"] == "stale":
            stale_count += 1
        else:
            unavail_active += 1

    feed_freshness_pct = round(100.0 * within_sla / len(active_sources), 1) if active_sources else 0.0

    # 2. Provenance completeness (% of datasets carrying source, retrieved_at_utc, license_ref, data_class)
    complete = 0
    incomplete_datasets: list[str] = []
    for env in sources:
        ok = all(
            isinstance(env.get(f), str) and bool(env.get(f).strip())
            for f in REQUIRED_PROVENANCE_FIELDS
        ) and env.get("data_class") in VALID_DATA_CLASSES
        if ok:
            complete += 1
        else:
            incomplete_datasets.append(str(env.get("dataset") or env.get("source") or "unknown"))

    provenance_completeness_pct = round(100.0 * complete / len(sources), 1) if sources else 0.0

    kpi: dict[str, Any] = {
        "schema_version": SCHEMA_VERSION,
        "generated_utc": build_utc,
        "git_sha": str(manifest.get("git_sha") or "unknown"),
        "overall_health": str(manifest.get("overall_health") or "degraded"),
        "feed_freshness_pct": feed_freshness_pct,
        "feed_freshness_detail": {
            "active_sources": len(active_sources),
            "within_sla": within_sla,
            "stale_or_expired": stale_count,
            "unavailable_active": unavail_active,
            "institutional_stubs": len(stub_sources),
        },
        "provenance_completeness_pct": provenance_completeness_pct,
        "provenance_completeness_detail": {
            "total_datasets": len(sources),
            "complete_datasets": complete,
            "required_fields": list(REQUIRED_PROVENANCE_FIELDS),
            "incomplete_datasets": incomplete_datasets,
        },
        "landslide_maturity": _extract_landslide_maturity(landslides_data),
        "exposure_coverage": _extract_exposure_coverage(exposure_isolation_data, summary, sources),
        "cascade_summary": _extract_cascade_summary(cascades_data),
    }

    if write:
        atomic_write_json(root / "data" / "kpi_baseline.json", kpi)
    return kpi


def _md_cell(val: Any) -> str:
    return str(val if val is not None else "—").replace("|", "\\|").replace("\n", " ").strip()


def format_step_summary_markdown(
    manifest: Mapping[str, Any],
    kpi: Mapping[str, Any],
) -> str:
    """Format a crisp GitHub Actions `$GITHUB_STEP_SUMMARY` Markdown report."""
    build_utc = _md_cell(manifest.get("build_utc") or kpi.get("generated_utc") or "unknown")
    git_sha = _md_cell(manifest.get("git_sha") or "unknown")
    health = str(manifest.get("overall_health") or "unknown").upper()
    schema_v = _md_cell(manifest.get("schema_version") or SCHEMA_VERSION)

    fresh_pct = kpi.get("feed_freshness_pct", 0.0)
    fresh_det = kpi.get("feed_freshness_detail") or {}
    prov_pct = kpi.get("provenance_completeness_pct", 0.0)
    prov_det = kpi.get("provenance_completeness_detail") or {}
    ls = kpi.get("landslide_maturity") or {}
    exp = kpi.get("exposure_coverage") or {}
    cas = kpi.get("cascade_summary") or {}

    null_ok = "PASS" if ls.get("null_casualty_integrity_ok") else "FAIL"

    lines: list[str] = [
        "## Nepal TRĀYA 2.0 — Build Provenance & KPI Summary",
        "",
        f"- **Build (UTC):** `{build_utc}` | **Git SHA:** `{git_sha}` | **Schema:** `{schema_v}` | **Overall Health:** `{health}`",
        "",
        "### KPI Baseline",
        "",
        "| KPI | Value | Detail |",
        "| --- | --- | --- |",
        f"| Feed Freshness | **{fresh_pct}%** | {fresh_det.get('within_sla', 0)}/{fresh_det.get('active_sources', 0)} active within SLA ({fresh_det.get('institutional_stubs', 0)} institutional stubs) |",
        f"| Provenance Completeness | **{prov_pct}%** | {prov_det.get('complete_datasets', 0)}/{prov_det.get('total_datasets', 0)} datasets complete |",
        f"| Landslide Maturity | **{ls.get('dated_events', 0)} dated / {ls.get('undated_scars', 0)} scars** | {ls.get('duplicate_candidates', 0)} duplicate candidates; null-casualty integrity: **{null_ok}** |",
        f"| Exposure Coverage | **{exp.get('n_provinces_covered', 0)} provinces / {exp.get('n_districts_covered', 0)} districts** | {len(exp.get('source_date_tags') or {})} source-date tags |",
        f"| Multi-Hazard Cascades | **{cas.get('active_pathways', 0)} active pathways** | {cas.get('observed_links', 0)} observed vs {cas.get('modelled_links', 0)} modelled links |",
        "",
        "### Source Provenance Registry",
        "",
        "| Source | Dataset | Data Class | Status | Records | Retrieved (UTC) | SLA (h) | Fallback |",
        "| --- | --- | --- | --- | ---: | --- | ---: | --- |",
    ]

    for env in _normalize_envelopes(manifest.get("sources")):
        lines.append(
            "| "
            + " | ".join(
                [
                    _md_cell(env.get("source")),
                    _md_cell(env.get("dataset")),
                    f"`{_md_cell(env.get('data_class'))}`",
                    f"`{_md_cell(env.get('status'))}`",
                    str(env.get("record_count", 0)),
                    _md_cell(env.get("retrieved_at_utc")),
                    _md_cell(env.get("sla_hours")),
                    "yes" if env.get("fallback_used") else "no",
                ]
            )
            + " |"
        )

    lines.append("")
    return "\n".join(lines)
