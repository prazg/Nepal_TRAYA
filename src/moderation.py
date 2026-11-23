"""
Community Landslide Reporting Validation, Deterministic PII Redaction &
Authenticated Agency Moderation Queue Engine for Nepal TRĀYA 2.0 (`TRAYA-008` / Issue #5).

Governance & Safety Invariants:
  * Pre-MOU sandbox default: `public_live_endpoint_enabled: False` and
    `governance_mode: "pilot_sandbox_post_mou"`.
  * Mandatory client-side EXIF stripping (`exif_stripped: True`).
  * Deterministic regex PII redaction (`redact_pii`) stripping Nepal phone
    numbers, email addresses, citizenship/license/NID numbers, and `@handles`.
  * Strict `null`-not-`0` casualty semantics on unverified community reports.
  * Flag-only duplicate detection against existing landslide inventory records
    (`auto_merged: False`, `review_status: "pending_review"`).
  * Authenticated statutory agency state machine (`deoc_officer`,
    `ndrrma_verifier`, `dhm_verifier`) with mandatory `agency_id` before any
    promotion into a canonical `schemas/landslide_event.v1.schema.json` record.

Pure Python 3.12 standard library only (zero third-party dependencies).
Output: `data/moderation_queue.json` (atomic UTF-8 JSON).
"""
from __future__ import annotations

import argparse
import copy
import datetime as dt
import hashlib
import json
import math
import os
import re
import sys
from pathlib import Path
from typing import Any

SRC_DIR = os.path.dirname(os.path.abspath(__file__))
if SRC_DIR not in sys.path:
    sys.path.insert(0, SRC_DIR)

import config as C
import landslides as LS
import seismic as SZ
from integrations import provenance as PROV

SCHEMA_VERSION = "moderation_queue.v1"
REPORT_SCHEMA_REF = "schemas/community_report.v1.schema.json"
PROMOTED_SCHEMA_REF = "schemas/landslide_event.v1.schema.json"

MODERATION_STATUSES: tuple[str, ...] = (
    "pending_agency_review",
    "verified_promoted",
    "rejected_duplicate",
    "rejected_pii",
    "rejected_unverifiable",
)

TIME_PRECISIONS: tuple[str, ...] = (
    "exact_hour",
    "day",
    "month",
    "year",
    "unknown",
)

LOCATION_SOURCES: tuple[str, ...] = ("gps", "manual_pin")

AUTHORIZED_MODERATOR_ROLES: tuple[str, ...] = (
    "deoc_officer",
    "ndrrma_verifier",
    "dhm_verifier",
)

ALLOWED_STATE_TRANSITIONS: dict[str, tuple[str, ...]] = {
    "pending_agency_review": (
        "verified_promoted",
        "rejected_duplicate",
        "rejected_pii",
        "rejected_unverifiable",
    ),
    "rejected_unverifiable": ("pending_agency_review",),
    "verified_promoted": (),
    "rejected_duplicate": (),
    "rejected_pii": (),
}

REQUIRED_REPORT_FIELDS: tuple[str, ...] = (
    "report_id",
    "feature_type",
    "moderation_status",
    "captured_at_utc",
    "event_date_utc",
    "time_precision",
    "location_source",
    "lon",
    "lat",
    "district",
    "province",
    "trigger",
    "road_blocked",
    "fatalities",
    "injuries",
    "description_redacted",
    "photo_attached",
    "exif_stripped",
    "dedup_fingerprint",
    "pii_redaction_applied",
)

OPTIONAL_REPORT_FIELDS: frozenset[str] = frozenset(
    {
        "title",
        "title_ne",
        "municipality_ward",
        "location_accuracy_m",
        "photo_sha256",
        "pii_redaction_tags",
        "offline_captured",
        "is_uat_fixture",
        "duplicate_candidates",
        "moderation_history",
        "promoted_landslide_record",
    }
)

ALLOWED_REPORT_FIELDS: frozenset[str] = frozenset(REQUIRED_REPORT_FIELDS) | OPTIONAL_REPORT_FIELDS

ISO_TS_RE = re.compile(
    r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(\.\d+)?(Z|[+-]\d{2}:\d{2})$"
)
ISO_DATE_RE = re.compile(
    r"^\d{4}-\d{2}-\d{2}(T\d{2}:\d{2}:\d{2}(\.\d+)?(Z|[+-]\d{2}:\d{2}))?$"
)
SHA256_RE = re.compile(r"^[0-9a-f]{64}$")
REPORT_ID_RE = re.compile(r"^[A-Za-z0-9_.:-]+$")

# ---------------------------------------------------------------------------
# Deterministic PII redaction patterns (Nepal-tailored)
# ---------------------------------------------------------------------------
_EMAIL_RE = re.compile(
    r"\b[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}\b"
)

# Nepal phones:
#   - International +977 / 00977 mobile & landline (with optional (0) or 0)
#   - 10-digit Nepal mobile: 98xxxxxxxx, 97xxxxxxxx, 96xxxxxxxx (with optional spaces/hyphens)
#   - Kathmandu landline: 01-xxxxxxx / 01 xxxxxxx / 01xxxxxxx
#   - Regional Nepal STD landlines: 011-xxxxxx or 0[2-9][0-9]-xxxxxx
#   - Devanagari Nepal mobile/landline digits
_PHONE_PATTERNS: tuple[re.Pattern[str], ...] = (
    re.compile(
        r"(?<!\w)(?:\+977|00977)[\s-]*(?:\(0\)|0)?[\s-]*"
        r"(?:9[678]\d(?:[\s-]?\d){7}|1[\s-]?\d{3}[\s-]?\d{4}|(?:11|[2-9]\d)[\s-]?\d{3}[\s-]?\d{3})(?!\d)(?!\.\d)"
    ),
    re.compile(r"(?<!\d)(?<!\d\.)9[678]\d(?:[\s-]?\d){7}(?!\d)(?!\.\d)"),
    re.compile(r"(?<!\d)(?<!\d\.)01[\s-]?\d{3}[\s-]?\d{4}(?!\d)(?!\.\d)"),
    re.compile(r"(?<!\d)(?<!\d\.)0(?:11|[2-9]\d)[\s-]\d{3}[\s-]?\d{3}(?!\d)(?!\.\d)"),
    re.compile(
        r"(?<![\d\u0966-\u096f])(?<![\d\u0966-\u096f]\.)(?:\+९७७[\s-]?)?"
        r"(?:९[६७८][\u0966-\u096f](?:[\s-]?[\u0966-\u096f]){7}|"
        r"०१[\s-]?[\u0966-\u096f]{3}[\s-]?[\u0966-\u096f]{4})"
        r"(?![\d\u0966-\u096f])(?!\.[\d\u0966-\u096f])"
    ),
)

# Nepal citizenship, driving license, passport, and National ID (NID) patterns
_ID_PATTERNS: tuple[re.Pattern[str], ...] = (
    # Labeled citizenship / NID / license / passport / voter ID
    re.compile(
        r"(?i)\b(?:citizenship|nagarikta|nid|national\s+id|driving\s+licen[cs]e|"
        r"licen[cs]e|lic\.?|passport|voter\s*id)\s*(?:no\.?|number|num\.?|id)?\s*"
        r"[:#-]?\s*[A-Za-z]{0,3}\d[\d/-]{4,18}\b"
    ),
    # Devanagari labeled citizenship ID
    re.compile(
        r"नागरिकता\s*(?:नं\.?|नम्बर|प्रमाणपत्र\s*नं\.?)?\s*[:#-]?\s*"
        r"[\d\u0966-\u096f][\d\u0966-\u096f/-]{4,18}"
    ),
    # Formatted Nepal citizenship number (e.g., 27-01-74-01234 or 27/01/74/01234)
    re.compile(r"(?<!\d)(?<!\d\.)\b\d{2}[-/]\d{2}[-/]\d{2,4}[-/]\d{4,6}\b(?!\d)(?!\.\d)"),
    # Formatted Nepal driving license number (e.g., 01-06-00123456)
    re.compile(r"(?<!\d)(?<!\d\.)\b\d{2}-\d{2}-\d{6,9}\b(?!\d)(?!\.\d)"),
    # Formatted Nepal National ID (e.g., 123-456-789-0)
    re.compile(r"(?<!\d)(?<!\d\.)\b\d{3}-\d{3}-\d{3}-\d\b(?!\d)(?!\.\d)"),
    # Raw 10-16 digit standalone numeric ID (excluding floats, SHA-256 hex, and hotlines)
    re.compile(r"(?<![A-Za-z0-9_-])(?<!\d\.)\d{10,16}(?![A-Za-z0-9_-])(?!\.\d)"),
)

# Social media handles (@username) — applied after email redaction
_HANDLE_RE = re.compile(
    r"(?<![A-Za-z0-9._%+-])@[A-Za-z0-9_][A-Za-z0-9_.-]{1,30}\b"
)


def redact_pii(text: str) -> tuple[str, list[str]]:
    """Deterministically strip Nepal PII from free-text narratives.

    Replaces:
      * Email addresses                        -> `[REDACTED_EMAIL]`  (tag: `"email"`)
      * Nepal mobile/landline phone numbers    -> `[REDACTED_PHONE]`  (tag: `"phone"`)
      * Citizenship / license / NID numbers    -> `[REDACTED_ID]`     (tag: `"id"`)
      * Social media `@handles`                -> `[REDACTED_HANDLE]` (tag: `"handle"`)

    Returns `(redacted_text, tags)` where `tags` lists unique matched PII categories
    in deterministic order. Operation is idempotent: calling `redact_pii` on already
    redacted output returns `(text, [])`.
    """
    if text is None:
        return ("", [])
    out = str(text)
    tags: list[str] = []

    # 1. Emails first so domain part is never misread as an @handle
    out, n_email = _EMAIL_RE.subn("[REDACTED_EMAIL]", out)
    if n_email > 0:
        tags.append("email")

    # 2. Nepal mobile & landline phone numbers
    phone_hits = 0
    for pat in _PHONE_PATTERNS:
        out, n = pat.subn("[REDACTED_PHONE]", out)
        phone_hits += n
    if phone_hits > 0:
        tags.append("phone")

    # 3. Citizenship, license, NID & passport numeric IDs
    id_hits = 0
    for pat in _ID_PATTERNS:
        out, n = pat.subn("[REDACTED_ID]", out)
        id_hits += n
    if id_hits > 0:
        tags.append("id")

    # 4. Social media @handles
    out, n_handle = _HANDLE_RE.subn("[REDACTED_HANDLE]", out)
    if n_handle > 0:
        tags.append("handle")

    return (out, tags)


def compute_dedup_fingerprint(
    lon: float,
    lat: float,
    event_date_utc: str | None,
    trigger: str | None,
) -> str:
    """Compute a deterministic SHA-256 hex deduplication fingerprint.

    Quantizes WGS84 coordinates to 3 decimal places (~110 m bucket), normalizes
    `event_date_utc` to its `YYYY-MM-DD` date key (or `"undated"`), and normalizes
    the physical trigger string.
    """
    lon_f = float(lon)
    lat_f = float(lat)
    if not (math.isfinite(lon_f) and math.isfinite(lat_f)):
        raise ValueError("lon and lat must be finite numbers")

    lon_q = f"{round(lon_f, 3):.3f}"
    lat_q = f"{round(lat_f, 3):.3f}"

    if event_date_utc is None or not str(event_date_utc).strip():
        date_key = "undated"
    else:
        parsed = PROV.parse_iso_utc(str(event_date_utc).strip())
        date_key = (
            parsed.strftime("%Y-%m-%d")
            if parsed is not None
            else str(event_date_utc).strip()[:10]
        )

    trig_norm = re.sub(r"\s+", "_", str(trigger or "unknown").strip().lower()) or "unknown"
    canonical = f"traya_community_report_v1|{lon_q}|{lat_q}|{date_key}|{trig_norm}"
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def validate_community_report(report: dict[str, Any]) -> list[str]:
    """Validate a community report dict against `schemas/community_report.v1.schema.json`.

    Returns a list of human-readable schema/governance violation messages (`[]` if valid).
    Explicitly rejects:
      * `exif_stripped != True`
      * `pii_redaction_applied != True`
      * `feature_type != "hazard_report"`
      * non-null `0` fatalities or injuries on unverified reports (strict null-not-0)
      * any unredacted PII remaining in `description_redacted` (or optional `title`)
    """
    if not isinstance(report, dict):
        return ["report must be a JSON object/dict"]

    errs: list[str] = []

    for key in REQUIRED_REPORT_FIELDS:
        if key not in report:
            errs.append(f"missing required field: {key}")

    extra = sorted(set(report.keys()) - ALLOWED_REPORT_FIELDS)
    if extra:
        errs.append(f"unexpected additional properties: {extra}")

    rid = report.get("report_id")
    if not isinstance(rid, str) or not rid.strip() or not REPORT_ID_RE.match(rid):
        errs.append(f"invalid report_id: {rid!r}")

    if report.get("feature_type") != "hazard_report":
        errs.append(
            f"feature_type must be 'hazard_report', got {report.get('feature_type')!r}"
        )

    mod_status = report.get("moderation_status")
    if mod_status not in MODERATION_STATUSES:
        errs.append(f"invalid moderation_status: {mod_status!r}")

    cap_ts = report.get("captured_at_utc")
    if not isinstance(cap_ts, str) or not ISO_TS_RE.match(cap_ts):
        errs.append(f"invalid ISO-8601 captured_at_utc: {cap_ts!r}")

    ev_dt = report.get("event_date_utc")
    tp = report.get("time_precision")
    if tp not in TIME_PRECISIONS:
        errs.append(f"invalid time_precision: {tp!r}")
    if ev_dt is None:
        if tp != "unknown":
            errs.append(
                f"null event_date_utc requires time_precision='unknown', got {tp!r}"
            )
    else:
        if not isinstance(ev_dt, str) or not ISO_DATE_RE.match(ev_dt):
            errs.append(f"invalid ISO-8601 event_date_utc: {ev_dt!r}")
        if tp not in ("exact_hour", "day", "month", "year"):
            errs.append(
                f"non-null event_date_utc requires time_precision in exact_hour|day|month|year, got {tp!r}"
            )

    if report.get("location_source") not in LOCATION_SOURCES:
        errs.append(f"invalid location_source: {report.get('location_source')!r}")

    lon, lat = report.get("lon"), report.get("lat")
    if (
        not isinstance(lon, (int, float))
        or isinstance(lon, bool)
        or not math.isfinite(float(lon))
        or not (79.5 <= float(lon) <= 88.8)
    ):
        errs.append(f"invalid lon (outside Nepal region 79.5..88.8): {lon!r}")
    if (
        not isinstance(lat, (int, float))
        or isinstance(lat, bool)
        or not math.isfinite(float(lat))
        or not (26.0 <= float(lat) <= 31.0)
    ):
        errs.append(f"invalid lat (outside Nepal region 26.0..31.0): {lat!r}")

    dist = report.get("district")
    if dist is not None and (not isinstance(dist, str) or not dist.strip()):
        errs.append(f"district must be non-empty string or null, got {dist!r}")

    prov = report.get("province")
    if prov is not None and prov not in C.CANONICAL_PROVINCES:
        errs.append(f"non-canonical province: {prov!r}")

    trig = report.get("trigger")
    if not isinstance(trig, str) or not trig.strip():
        errs.append(f"trigger must be non-empty string, got {trig!r}")

    rb = report.get("road_blocked")
    if rb is not None and not isinstance(rb, bool):
        errs.append(f"road_blocked must be bool or null, got {rb!r}")

    is_verified = mod_status == "verified_promoted"
    for ck in ("fatalities", "injuries"):
        val = report.get(ck)
        if val is not None:
            if not isinstance(val, int) or isinstance(val, bool) or val < 0:
                errs.append(f"{ck} must be non-negative int or null, got {val!r}")
            elif val == 0 and not is_verified:
                errs.append(
                    f"{ck}=0 violates strict null-not-0 rule for unverified report "
                    f"(moderation_status={mod_status!r})"
                )

    if not isinstance(report.get("photo_attached"), bool):
        errs.append("photo_attached must be bool")

    if report.get("exif_stripped") is not True:
        errs.append(
            f"exif_stripped must be strictly True for privacy compliance, got {report.get('exif_stripped')!r}"
        )

    if report.get("pii_redaction_applied") is not True:
        errs.append(
            f"pii_redaction_applied must be strictly True, got {report.get('pii_redaction_applied')!r}"
        )

    fp = report.get("dedup_fingerprint")
    if not isinstance(fp, str) or not SHA256_RE.match(fp):
        errs.append(f"dedup_fingerprint must be 64-char lowercase SHA-256 hex, got {fp!r}")

    desc = report.get("description_redacted")
    if not isinstance(desc, str):
        errs.append("description_redacted must be string")
    else:
        _, leaked_tags = redact_pii(desc)
        if leaked_tags:
            errs.append(
                f"description_redacted contains unredacted PII ({', '.join(leaked_tags)})"
            )

    if "title" in report:
        tval = report.get("title")
        if not isinstance(tval, str) or not tval.strip():
            errs.append("title must be a non-empty string when present")
        else:
            _, t_leaks = redact_pii(tval)
            if t_leaks:
                errs.append(f"title contains unredacted PII ({', '.join(t_leaks)})")

    if report.get("photo_attached") is False and report.get("photo_sha256") is not None:
        errs.append("photo_sha256 must be null when photo_attached is False")

    return errs


def check_duplicate_against_inventory(
    report: dict[str, Any],
    inventory_events: list[dict[str, Any]],
    max_km: float = 1.5,
    max_days: int = 3,
    undated_max_km: float = 0.35,
) -> list[dict[str, Any]]:
    """Flag candidate duplicate matches between a community report and existing inventory.

    NEVER auto-merges: every returned candidate carries `auto_merged: False` and
    `review_status: "pending_review"` for human agency officer inspection.
    """
    if not isinstance(report, dict) or not inventory_events:
        return []

    try:
        r_lon = float(report["lon"])
        r_lat = float(report["lat"])
    except (KeyError, TypeError, ValueError):
        return []
    if not (math.isfinite(r_lon) and math.isfinite(r_lat)):
        return []

    r_dt = PROV.parse_iso_utc(report.get("event_date_utc"))
    r_id = str(report.get("report_id") or "")
    r_fp = str(report.get("dedup_fingerprint") or "")

    candidates: list[dict[str, Any]] = []
    for ev in inventory_events:
        if not isinstance(ev, dict):
            continue
        try:
            e_lon = float(ev["lon"])
            e_lat = float(ev["lat"])
        except (KeyError, TypeError, ValueError):
            continue
        if not (math.isfinite(e_lon) and math.isfinite(e_lat)):
            continue

        dist_km = SZ.haversine_km(r_lon, r_lat, e_lon, e_lat)
        e_fp = str(ev.get("dedup_fingerprint") or "")
        e_dt = PROV.parse_iso_utc(ev.get("event_date_utc") or ev.get("date"))

        reason: str | None = None
        days_apart: float | None = None

        if r_fp and e_fp and r_fp == e_fp:
            reason = "exact_dedup_fingerprint_match"
            if r_dt is not None and e_dt is not None:
                days_apart = round(abs((r_dt - e_dt).total_seconds()) / 86400.0, 2)
        elif dist_km <= max_km:
            if r_dt is not None and e_dt is not None:
                days_apart = round(abs((r_dt - e_dt).total_seconds()) / 86400.0, 2)
                if days_apart <= float(max_days):
                    reason = "dated_spatiotemporal_proximity"
            else:
                if dist_km <= min(float(max_km), float(undated_max_km)):
                    reason = "undated_spatial_proximity"

        if reason is None:
            continue

        candidates.append(
            {
                "report_id": r_id,
                "inventory_event_id": str(ev.get("id") or ev.get("report_id") or "unknown"),
                "inventory_source": ev.get("source"),
                "inventory_provider_id": ev.get("provider_id"),
                "inventory_feature_type": ev.get("feature_type"),
                "inventory_title": ev.get("title"),
                "inventory_date_utc": ev.get("event_date_utc") or ev.get("date"),
                "distance_km": round(dist_km, 3),
                "days_apart": days_apart,
                "reason": reason,
                "review_status": "pending_review",
                "auto_merged": False,
            }
        )

    candidates.sort(
        key=lambda c: (
            c["distance_km"],
            c["days_apart"] if c["days_apart"] is not None else 9999.0,
            c["inventory_event_id"],
        )
    )
    return candidates


def promote_to_landslide_event_v1(
    report: dict[str, Any],
    agency_id: str,
    moderator_role: str,
) -> dict[str, Any]:
    """Promote a verified community report into a `landslide_event.v1` compatible record."""
    ev_dt = report.get("event_date_utc")
    tp = str(report.get("time_precision") or "unknown")
    if ev_dt is None:
        date_precision = "unknown"
    elif tp in ("exact_hour", "day"):
        date_precision = "day"
    elif tp in ("month", "year"):
        date_precision = tp
    else:
        date_precision = "day"

    trigger = str(report.get("trigger") or "unknown").strip() or "unknown"
    is_coseismic = bool(LS.COSEISMIC_RE.search(f"{trigger} {report.get('description_redacted') or ''}"))
    if is_coseismic:
        feature_type = "coseismic_failure"
        data_class = "observed_coseismic"
    elif ev_dt is not None:
        feature_type = "landslide_event"
        data_class = "community_report"
    else:
        feature_type = "hazard_report"
        data_class = "community_report"

    rid = str(report["report_id"])
    promoted_id = rid if rid.startswith("community_") else f"community_{rid}"
    district = report.get("district")
    province = report.get("province")
    muni = report.get("municipality_ward")
    loc_label = f"{muni}, {district}" if (muni and district) else (district or "Nepal")
    title = str(report.get("title") or "").strip() or f"Verified community landslide report ({loc_label})"

    lon_r = round(float(report["lon"]), 4)
    lat_r = round(float(report["lat"]), 4)
    legacy_date = str(ev_dt)[:10] if ev_dt else None

    promoted: dict[str, Any] = {
        "id": promoted_id,
        "feature_type": feature_type,
        "provider_id": "community_field",
        "source": f"Community Field Report (Verified: {agency_id} / {moderator_role})",
        "data_class": data_class,
        "title": title,
        "title_ne": report.get("title_ne") if isinstance(report.get("title_ne"), str) else None,
        "event_date_utc": ev_dt,
        "date_precision": date_precision,
        "lon": lon_r,
        "lat": lat_r,
        "district": district,
        "province": province,
        "trigger": trigger,
        "fatalities": report.get("fatalities"),
        "injuries": report.get("injuries"),
        "households_affected": None,
        "verified": True,
        "evidence_url": None,
        "license_ref": (
            "Community field report verified by statutory agency officer "
            "(CC-BY-4.0 / GoN DEOC moderation governance)"
        ),
        "date": legacy_date,
        "url": "",
        "admin": district or "",
        "category": "landslide",
        "size": "",
    }

    errs = LS.validate_landslide_record(promoted)
    if errs:
        raise ValueError(f"Promoted record failed landslide_event.v1 validation: {errs}")
    return promoted


def transition_moderation_state(
    report: dict[str, Any],
    target_status: str,
    moderator_role: str,
    agency_id: str,
    note: str,
) -> dict[str, Any]:
    """Execute an authenticated agency-officer moderation transition.

    Enforces:
      * `moderator_role` MUST be in `("deoc_officer", "ndrrma_verifier", "dhm_verifier")`.
      * `agency_id` MUST be a non-empty identifier (promotion strictly refused without it).
      * Transition MUST follow `ALLOWED_STATE_TRANSITIONS`.
      * Before promoting to `verified_promoted`, the report MUST pass
        `validate_community_report` with zero violations, and a validated
        `landslide_event.v1` record is attached at `promoted_landslide_record`.
    """
    if moderator_role not in AUTHORIZED_MODERATOR_ROLES:
        raise PermissionError(
            f"Unauthorized moderator_role {moderator_role!r}; "
            f"must be one of {AUTHORIZED_MODERATOR_ROLES}"
        )

    agency_clean = str(agency_id or "").strip()
    if not agency_clean:
        raise PermissionError(
            "Missing agency_id: authenticated statutory agency identifier is required "
            "for moderation actions and promotion."
        )

    if target_status not in MODERATION_STATUSES:
        raise ValueError(
            f"Invalid target_status {target_status!r}; must be one of {MODERATION_STATUSES}"
        )

    if not isinstance(report, dict):
        raise ValueError("report must be a dict")

    current_status = str(report.get("moderation_status") or "")
    allowed_next = ALLOWED_STATE_TRANSITIONS.get(current_status, ())
    if target_status not in allowed_next:
        raise ValueError(
            f"Invalid moderation transition {current_status!r} -> {target_status!r}; "
            f"allowed transitions from {current_status!r}: {allowed_next}"
        )

    if target_status == "verified_promoted":
        violations = validate_community_report(report)
        if violations:
            raise ValueError(
                f"Cannot promote invalid community report {report.get('report_id')!r}: {violations}"
            )

    note_clean, _ = redact_pii(str(note or "").strip())
    if not note_clean:
        raise ValueError("Moderation note must be a non-empty justification string")

    updated = copy.deepcopy(report)
    updated["moderation_status"] = target_status

    history = list(updated.get("moderation_history") or [])
    history.append(
        {
            "timestamp_utc": PROV.utc_now_iso(),
            "from_status": current_status,
            "to_status": target_status,
            "moderator_role": moderator_role,
            "agency_id": agency_clean,
            "note": note_clean,
        }
    )
    updated["moderation_history"] = history

    if target_status == "verified_promoted":
        updated["promoted_landslide_record"] = promote_to_landslide_event_v1(
            updated, agency_id=agency_clean, moderator_role=moderator_role
        )
    else:
        updated["promoted_landslide_record"] = None

    return updated


def _build_synthetic_uat_fixtures(
    inventory_events: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    """Construct 2 clean synthetic UAT exercise fixtures (Dolakha & Sindhupalchok)."""
    raw_fixtures: list[dict[str, Any]] = [
        {
            "report_id": "uat_cr_dolakha_001",
            "title": "[UAT Exercise] Slope debris slip near Singati–Gonggar corridor, Dolakha",
            "title_ne": "[UAT अभ्यास] दोलखाको सिँगटी–गोंगर करिडोर नजिक पहिरो अवलोकन",
            "captured_at_utc": "2026-11-23T06:15:00Z",
            "event_date_utc": "2026-11-23T05:30:00Z",
            "time_precision": "exact_hour",
            "location_source": "gps",
            "location_accuracy_m": 12.5,
            "lon": 86.1652,
            "lat": 27.7164,
            "district": "Dolakha",
            "province": "Bagmati Province",
            "municipality_ward": "Gaurishankar RM-5",
            "trigger": "rainfall",
            "road_blocked": True,
            "fatalities": None,
            "injuries": None,
            "raw_description": (
                "[SYNTHETIC UAT EXERCISE FIXTURE] Shallow debris flow across Singati–Gonggar "
                "feeder track following intense overnight shower; single-lane vehicle passage "
                "blocked (~18 m width). Ward volunteer contact +977-9800000001 redacted prior "
                "to queue entry; verify directly with Dolakha DEOC."
            ),
            "photo_attached": True,
            "photo_sha256": hashlib.sha256(
                b"traya-uat-fixture-dolakha-001-exif-stripped-placeholder"
            ).hexdigest(),
            "offline_captured": True,
        },
        {
            "report_id": "uat_cr_sindhupalchok_002",
            "title": "[UAT Exercise] Cut-slope rockfall along Araniko Highway (NH03), Sindhupalchok",
            "title_ne": "[UAT अभ्यास] सिन्धुपाल्चोकको अरनिको राजमार्ग (NH03) खण्डमा पहिरो/चट्टान खसेको",
            "captured_at_utc": "2026-11-23T09:40:00Z",
            "event_date_utc": "2026-11-23T00:00:00Z",
            "time_precision": "day",
            "location_source": "manual_pin",
            "location_accuracy_m": None,
            "lon": 85.8994,
            "lat": 27.7892,
            "district": "Sindhupalchok",
            "province": "Bagmati Province",
            "municipality_ward": "Barhabise Municipality-3",
            "trigger": "road_cut",
            "road_blocked": True,
            "fatalities": None,
            "injuries": None,
            "raw_description": (
                "[SYNTHETIC UAT EXERCISE FIXTURE] Fresh cut-slope rockfall and wet talus "
                "slump on uphill shoulder of Araniko Highway near Barhabise; traffic halted "
                "pending DoR loader clearance. Submitted via offline PWA drill by @uat_field_demo "
                "(demo.reporter@example.org) with all PII stripped."
            ),
            "photo_attached": False,
            "photo_sha256": None,
            "offline_captured": True,
        },
    ]

    fixtures: list[dict[str, Any]] = []
    for raw in raw_fixtures:
        redacted_desc, redaction_tags = redact_pii(raw["raw_description"])
        fp = compute_dedup_fingerprint(
            raw["lon"], raw["lat"], raw["event_date_utc"], raw["trigger"]
        )
        rec: dict[str, Any] = {
            "report_id": raw["report_id"],
            "feature_type": "hazard_report",
            "moderation_status": "pending_agency_review",
            "captured_at_utc": raw["captured_at_utc"],
            "event_date_utc": raw["event_date_utc"],
            "time_precision": raw["time_precision"],
            "location_source": raw["location_source"],
            "lon": raw["lon"],
            "lat": raw["lat"],
            "district": raw["district"],
            "province": raw["province"],
            "trigger": raw["trigger"],
            "road_blocked": raw["road_blocked"],
            "fatalities": raw["fatalities"],
            "injuries": raw["injuries"],
            "description_redacted": redacted_desc,
            "photo_attached": raw["photo_attached"],
            "exif_stripped": True,
            "dedup_fingerprint": fp,
            "pii_redaction_applied": True,
            "title": raw["title"],
            "title_ne": raw["title_ne"],
            "municipality_ward": raw["municipality_ward"],
            "location_accuracy_m": raw["location_accuracy_m"],
            "photo_sha256": raw["photo_sha256"],
            "pii_redaction_tags": redaction_tags,
            "offline_captured": raw["offline_captured"],
            "is_uat_fixture": True,
            "duplicate_candidates": [],
            "moderation_history": [],
            "promoted_landslide_record": None,
        }
        rec["duplicate_candidates"] = check_duplicate_against_inventory(
            rec, inventory_events, max_km=1.5, max_days=3
        )
        violations = validate_community_report(rec)
        if violations:
            raise ValueError(
                f"Synthetic UAT fixture {rec['report_id']} failed validation: {violations}"
            )
        fixtures.append(rec)

    return fixtures


def build_moderation_queue(
    repo_root: str | os.PathLike[str] = C.ROOT,
    *,
    write: bool = True,
) -> dict[str, Any]:
    """Build and atomically write `data/moderation_queue.json`."""
    root = Path(repo_root).resolve()
    now_utc = PROV.utc_now_iso()

    # Load existing landslide inventory if present for flag-only duplicate screening
    inventory_events: list[dict[str, Any]] = []
    ls_path = root / "data" / "landslides.json"
    if ls_path.is_file():
        try:
            ls_payload = json.loads(ls_path.read_text(encoding="utf-8"))
            if isinstance(ls_payload, dict) and isinstance(ls_payload.get("events"), list):
                inventory_events = ls_payload["events"]
        except Exception:
            inventory_events = []

    uat_fixtures = _build_synthetic_uat_fixtures(inventory_events)

    envelope = PROV.make_envelope(
        source="Nepal TRĀYA Community Reporting Moderation Sandbox (Pre-MOU UAT)",
        dataset="community_report_moderation_queue",
        data_class="static_assessment",
        retrieved_at_utc=now_utc,
        observation_time_utc=now_utc,
        valid_until_utc=None,
        status="available",
        fallback_used=False,
        license_ref="MIT (TRĀYA schema & moderation engine); synthetic UAT exercise fixtures (non-operational)",
        sla_hours=168,
        record_count=len(uat_fixtures),
        notes=(
            "Pre-MOU sandbox moderation queue (`public_live_endpoint_enabled: false`). "
            "Contains synthetic Dolakha & Sindhupalchok UAT exercise fixtures only; "
            "live citizen ingestion requires signed Wave D DEOC/NDRRMA/DHM MOUs."
        ),
        requires_institutional_agreement=True,
    )

    queue_payload: dict[str, Any] = {
        "schema_version": SCHEMA_VERSION,
        "generated_utc": now_utc,
        "governance_mode": "pilot_sandbox_post_mou",
        "public_live_endpoint_enabled": False,
        "requires_authenticated_moderation": True,
        "authorized_moderator_roles": list(AUTHORIZED_MODERATOR_ROLES),
        "schema_ref": REPORT_SCHEMA_REF,
        "promoted_target_schema_ref": PROMOTED_SCHEMA_REF,
        "non_operational_notice": (
            "Community landslide reporting is NOT an emergency dispatch channel. "
            "For life-safety emergencies in Nepal call DHM 1155, NEOC 1149, "
            "APF Rescue 1114, Nepal Police 100, or Ambulance 102."
        ),
        "pii_redaction_policy": {
            "deterministic_regex_redactor": "src/moderation.py::redact_pii",
            "redacted_categories": {
                "phone": "[REDACTED_PHONE] (+977/00977, 98/97/96 mobile, 01/STD landlines, Devanagari digits)",
                "email": "[REDACTED_EMAIL] (RFC-style email addresses)",
                "id": "[REDACTED_ID] (Nepal citizenship, driving license, NID, passport numeric IDs)",
                "handle": "[REDACTED_HANDLE] (@social_handles)",
            },
            "exif_stripping_mandatory": True,
            "reporter_identity_stored": False,
            "unverified_null_not_zero_casualties": True,
            "legal_alignment": "Individual Privacy Act, 2075 (2018), Government of Nepal",
        },
        "dedup_policy": {
            "mode": "flag_only_never_auto_merge",
            "max_km": 1.5,
            "max_days": 3,
            "undated_max_km": 0.35,
            "inventory_records_checked": len(inventory_events),
        },
        "queue_summary": {
            "n_live_public_submissions": 0,
            "n_uat_fixtures": len(uat_fixtures),
            "n_pending_agency_review": sum(
                1 for r in uat_fixtures if r["moderation_status"] == "pending_agency_review"
            ),
            "n_verified_promoted": 0,
            "n_rejected": 0,
        },
        "sample_redacted_uat_fixtures": uat_fixtures,
        "provenance": envelope,
    }

    if write:
        out_path = root / "data" / "moderation_queue.json"
        PROV.atomic_write_json(out_path, queue_payload, indent=2)
    return queue_payload


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(
        description="Nepal TRĀYA 2.0 community landslide reporting moderation queue builder"
    )
    ap.add_argument(
        "--repo-root",
        default=C.ROOT,
        help="Repository root directory (defaults to TRĀYA repo root)",
    )
    args = ap.parse_args(argv)

    payload = build_moderation_queue(args.repo_root, write=True)
    out_path = Path(args.repo_root).resolve() / "data" / "moderation_queue.json"
    print(
        f"[moderation] wrote {out_path}: mode={payload['governance_mode']}, "
        f"public_live={payload['public_live_endpoint_enabled']}, "
        f"uat_fixtures={payload['queue_summary']['n_uat_fixtures']}, "
        f"inventory_checked={payload['dedup_policy']['inventory_records_checked']}"
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
