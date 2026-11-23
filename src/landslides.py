"""
Canonical multi-source landslide & slope-failure inventory builder for TRĀYA 2.0
(`TRAYA-007`), conforming to `schemas/landslide_event.v1.schema.json`.

Scientific & epistemic safeguards:
  * Strictly partitions all records into 5 canonical feature types:
      - `landslide_event`     : dated confirmed/reported landslide event (BIPAD NDRRMA, NASA COOLR)
      - `landslide_scar`      : undated geomorphic scar (OSM `natural=landslide` / `hazard=landslide`)
      - `susceptibility_zone` : static terrain susceptibility point/zone
      - `hazard_report`       : unverified community/field observation
      - `coseismic_failure`   : earthquake-triggered slope failure
  * Strict `null`-not-`0` rule: unknown `event_date_utc`, `fatalities`,
    `injuries`, and `households_affected` MUST be `null` (NEVER `0`), reserving
    `0` strictly for verified zero-casualty official records (e.g., BIPAD
    `loss.peopleDeathCount == 0` when `verified == True`).
  * Transparent Duplicate-Candidate Detection (`find_duplicate_candidates`):
    flags record pairs within `1.5 km` and `<= 3 days` (both dated) OR within
    `<= 0.35 km` across distinct sources (when at least one is undated) into
    `data/landslide_review_queue.json` with `review_status: "pending_review"`
    and NEVER auto-merges uncertain duplicates.
  * Emits three atomic outputs:
      1. `data/landslides.json` (backward-compatible enriched inventory)
      2. `data/landslide_review_queue.json` (human-review duplicate queue)
      3. `data/landslide_inventory.geojson` (RFC 7946 FeatureCollection for GIS/QGIS)

Pure Python 3.12 standard library only (zero third-party dependencies).
"""
from __future__ import annotations

import argparse
import datetime as dt
import difflib
import json
import math
import os
import re
import sys
import tempfile
import time
import urllib.parse
import urllib.request
from collections import defaultdict
from typing import Any

SRC_DIR = os.path.dirname(os.path.abspath(__file__))
if SRC_DIR not in sys.path:
    sys.path.insert(0, SRC_DIR)

import config as C
import floods as FL
import hydromet as HM
import seismic as SZ

USER_AGENT = "Nepal-TRAYA/2.1 (+https://prazg.github.io/Nepal_TRAYA/)"
SCHEMA_VERSION = "landslide_event.v1"
SCHEMA_PATH = os.path.join(C.ROOT, "schemas", "landslide_event.v1.schema.json")

CACHE_JSON = os.path.join(C.CACHE, "landslides.json")
CACHE_BIPAD = os.path.join(C.CACHE, "bipad_snapshot.json")
DATA_BIPAD = os.path.join(C.DATA, "bipad_official.json")
LEGACY_JS = os.path.join(C.DATA, "landslides.js")

OUT_JSON = os.path.join(C.DATA, "landslides.json")
OUT_REVIEW_QUEUE = os.path.join(C.DATA, "landslide_review_queue.json")
OUT_GEOJSON = os.path.join(C.DATA, "landslide_inventory.geojson")

FEATURE_TYPES: tuple[str, ...] = (
    "landslide_event",
    "landslide_scar",
    "susceptibility_zone",
    "hazard_report",
    "coseismic_failure",
)

PROVIDER_IDS: tuple[str, ...] = (
    "bipad_ndrrma",
    "nasa_coolr",
    "osm_overpass",
    "usgs_ground_failure",
    "traya_static",
    "community_field",
)

DATA_CLASSES: tuple[str, ...] = (
    "official_observed",
    "observed_catalog",
    "mapped_inventory",
    "community_report",
    "static_assessment",
    "observed_coseismic",
)

DATE_PRECISIONS: tuple[str, ...] = ("day", "month", "year", "unknown")

ISO_DATE_RE = re.compile(
    r"^\d{4}-\d{2}-\d{2}(T\d{2}:\d{2}:\d{2}(\.\d+)?(Z|[+-]\d{2}:\d{2}))?$"
)
COSEISMIC_RE = re.compile(r"\b(earthquake|seismic|coseismic|shaking|tremor)\b", re.IGNORECASE)

# Upstream endpoints
BIPAD_LANDSLIDE_URL = (
    "https://bipadportal.gov.np/api/v1/incident/"
    "?hazard=17&expand=loss&ordering=-incident_on&limit=100"
)
NASA_COOLR_ENDPOINTS = (
    "https://maps.nccs.nasa.gov/mapping/rest/services/global_landslide_catalog/Global_Landslide_Catalog_Export/FeatureServer/0/query",
    "https://maps.nccs.nasa.gov/server/rest/services/global_landslide_catalog/Global_Landslide_Catalog_Export/FeatureServer/0/query",
)
OVERPASS_MIRRORS = (
    "https://overpass-api.de/api/interpreter",
    "https://overpass.kumi.systems/api/interpreter",
)

THRESHOLDS: dict[str, Any] = {
    "dahal_hasegawa_2008": {
        "alpha": 73.9,
        "beta": -0.79,
        "ec_24h_mm": 144.0,
        "ec_72h_mm": 181.4,
        "ec_168h_mm": 216.8,
        "citation": "Dahal & Hasegawa (2008), Geomorphology 100, 429-443, doi:10.1016/j.geomorph.2008.01.014",
    },
    "guzzetti_2008": {
        "alpha": 2.2,
        "beta": -0.44,
        "ec_24h_mm": 13.0,
        "ec_72h_mm": 24.1,
        "ec_168h_mm": 38.8,
        "citation": "Guzzetti et al. (2008), Landslides 5, 3-17, doi:10.1007/s10346-007-0112-1",
    },
}


# ---------------------------------------------------------------------------
# Low-level helpers
# ---------------------------------------------------------------------------
def _safe_https_url(url: Any) -> str | None:
    """Return a valid HTTPS URL or None (strictly enforces schema pattern ^https://)."""
    s = str(url or "").strip()
    if s.startswith("https://") and len(s) > len("https://"):
        return s
    return None


def _safe_url(url: Any) -> str:
    """Legacy string URL helper (empty string if invalid)."""
    s = str(url or "").strip()
    if s.startswith("https://") or s.startswith("http://"):
        return s
    return ""


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


def _http_get_json(url: str, timeout: int = 35, retries: int = 3) -> Any:
    last_exc: Exception | None = None
    for attempt in range(retries):
        try:
            req = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
            with urllib.request.urlopen(req, timeout=timeout) as resp:
                return json.loads(resp.read().decode("utf-8"))
        except Exception as exc:
            last_exc = exc
            if attempt < retries - 1:
                time.sleep(2.0 * (attempt + 1))
    raise RuntimeError(f"GET {url} failed: {last_exc}")


def _strict_count(v: Any, verified: bool) -> int | None:
    """Enforce strict null-not-0 rule for casualty and impact counts.

    * Unknown / blank / negative / non-finite values ALWAYS become `None` (`null`).
    * `0` is preserved ONLY when `verified` is `True` (e.g., official BIPAD
      audited zero-casualty record); when `verified` is `False`, `0` becomes `None`.
    """
    if v is None or v == "" or isinstance(v, bool):
        return None
    try:
        f = float(v)
    except (TypeError, ValueError):
        return None
    if not math.isfinite(f) or f < 0:
        return None
    iv = int(round(f))
    if iv == 0 and not verified:
        return None
    return iv


def _parse_iso_datetime(v: Any) -> tuple[str | None, str]:
    """Normalize epoch ms or ISO string to `(event_date_utc, date_precision)`."""
    if v is None or v == "":
        return (None, "unknown")
    if isinstance(v, (int, float)) and math.isfinite(v):
        try:
            # Epoch milliseconds vs seconds heuristic
            sec = float(v) / 1000.0 if abs(float(v)) > 1e11 else float(v)
            d = dt.datetime.fromtimestamp(sec, tz=dt.timezone.utc)
            return (d.strftime("%Y-%m-%dT%H:%M:%SZ"), "day")
        except (OverflowError, OSError, ValueError):
            return (None, "unknown")
    s = str(v).strip()
    if not s:
        return (None, "unknown")
    # Year only (YYYY)
    if re.fullmatch(r"\d{4}", s):
        return (f"{s}-01-01T00:00:00Z", "year")
    # Year-month (YYYY-MM)
    if re.fullmatch(r"\d{4}-\d{2}", s):
        return (f"{s}-01T00:00:00Z", "month")
    # Date only (YYYY-MM-DD)
    if re.fullmatch(r"\d{4}-\d{2}-\d{2}", s):
        return (f"{s}T00:00:00Z", "day")
    try:
        iso_s = s[:-1] + "+00:00" if s.endswith("Z") else s
        parsed = dt.datetime.fromisoformat(iso_s)
        if parsed.tzinfo is None:
            parsed = parsed.replace(tzinfo=dt.timezone.utc)
        utc_dt = parsed.astimezone(dt.timezone.utc)
        return (utc_dt.strftime("%Y-%m-%dT%H:%M:%SZ"), "day")
    except ValueError:
        return (None, "unknown")


def _parse_dt_obj(iso_str: str | None) -> dt.datetime | None:
    if not iso_str:
        return None
    try:
        s = iso_str[:-1] + "+00:00" if iso_str.endswith("Z") else iso_str
        d = dt.datetime.fromisoformat(s)
        if d.tzinfo is None:
            d = d.replace(tzinfo=dt.timezone.utc)
        return d.astimezone(dt.timezone.utc)
    except ValueError:
        return None


def _canonical_province_or_none(prov: Any) -> str | None:
    s = str(prov or "").strip()
    if not s:
        return None
    canon = FL.canonical_province(s)
    return canon if canon in C.CANONICAL_PROVINCES else None


def _in_nepal_region(lon: float, lat: float) -> bool:
    return 79.5 <= lon <= 88.8 and 26.0 <= lat <= 31.0


def _normalize_title_for_sim(title: str) -> str:
    return re.sub(r"[^a-z0-9\u0900-\u097f]+", " ", str(title or "").lower()).strip()


# ---------------------------------------------------------------------------
# Record normalization & schema validation
# ---------------------------------------------------------------------------
def _infer_provider_and_class(
    raw: dict[str, Any],
    verified: bool,
    event_date_utc: str | None,
    trigger: str,
) -> tuple[str, str, str, str]:
    """Infer `(provider_id, feature_type, data_class, license_ref)` consistently."""
    src_l = str(raw.get("source") or "").lower()
    pid = str(raw.get("provider_id") or "").strip().lower()
    rid = str(raw.get("id") or "").strip().lower()

    if pid not in PROVIDER_IDS:
        if "bipad" in src_l or "ndrrma" in src_l or rid.startswith("bipad_"):
            pid = "bipad_ndrrma"
        elif "nasa" in src_l or "coolr" in src_l or rid.startswith("coolr_"):
            pid = "nasa_coolr"
        elif "usgs" in src_l or rid.startswith("usgs_"):
            pid = "usgs_ground_failure"
        elif "osm" in src_l or "openstreetmap" in src_l or rid.startswith("osm_"):
            pid = "osm_overpass"
        elif "static" in src_l or "suscept" in src_l:
            pid = "traya_static"
        else:
            pid = "community_field" if event_date_utc else "osm_overpass"

    explicit_ft = str(raw.get("feature_type") or "").strip()
    text_for_coseismic = f"{trigger} {raw.get('title') or ''} {raw.get('cause') or ''}"
    is_coseismic = bool(COSEISMIC_RE.search(text_for_coseismic))

    if explicit_ft in FEATURE_TYPES:
        ft = explicit_ft
    elif pid == "osm_overpass":
        ft = "landslide_scar"
    elif pid == "traya_static":
        ft = "susceptibility_zone"
    elif is_coseismic or pid == "usgs_ground_failure":
        ft = "coseismic_failure"
    elif pid == "bipad_ndrrma":
        if verified and event_date_utc:
            ft = "landslide_event"
        else:
            ft = "hazard_report"
    elif pid == "nasa_coolr":
        ft = "landslide_event" if event_date_utc else "hazard_report"
    else:
        ft = "hazard_report"

    # Enforce schema invariants between feature_type and dating
    if ft == "landslide_event" and event_date_utc is None:
        ft = "hazard_report"

    explicit_dc = str(raw.get("data_class") or "").strip()
    if explicit_dc in DATA_CLASSES:
        dc = explicit_dc
    elif pid == "bipad_ndrrma":
        dc = "official_observed" if verified else "community_report"
    elif pid == "nasa_coolr":
        dc = "observed_coseismic" if ft == "coseismic_failure" else "observed_catalog"
    elif pid == "osm_overpass":
        dc = "mapped_inventory"
    elif pid == "usgs_ground_failure":
        dc = "observed_coseismic"
    elif pid == "traya_static":
        dc = "static_assessment"
    else:
        dc = "community_report"

    lic = str(raw.get("license_ref") or "").strip()
    if not lic:
        lic_defaults = {
            "bipad_ndrrma": "Government of Nepal NDRRMA BIPAD Portal public data",
            "nasa_coolr": "NASA Open Data (public domain)",
            "osm_overpass": "ODbL 1.0",
            "usgs_ground_failure": "USGS public domain",
            "traya_static": "TRĀYA screening model (CC-BY-4.0)",
            "community_field": "Community/field observation (unverified)",
        }
        lic = lic_defaults[pid]

    return (pid, ft, dc, lic)


def normalize_record(
    raw: dict[str, Any],
    adm: HM.StdlibAdminLookup | None = None,
) -> dict[str, Any] | None:
    """Normalize any upstream landslide record into canonical v1 schema format."""
    try:
        lon = float(raw["lon"])
        lat = float(raw["lat"])
    except (KeyError, TypeError, ValueError):
        return None
    if not (math.isfinite(lon) and math.isfinite(lat)):
        return None
    if not _in_nepal_region(lon, lat):
        return None

    lon_r = round(lon, 4)
    lat_r = round(lat, 4)

    raw_date = raw.get("event_date_utc")
    if raw_date is None:
        raw_date = raw.get("date")
    event_date_utc, inferred_prec = _parse_iso_datetime(raw_date)
    date_precision = str(raw.get("date_precision") or "").strip()
    if event_date_utc is None:
        date_precision = "unknown"
    elif date_precision not in ("day", "month", "year"):
        date_precision = inferred_prec

    verified = bool(raw.get("verified", False))
    trigger = str(raw.get("trigger") or "unknown").strip() or "unknown"

    provider_id, feature_type, data_class, license_ref = _infer_provider_and_class(
        raw, verified, event_date_utc, trigger
    )

    # Strict invariants for undated geomorphic scars
    if feature_type == "landslide_scar":
        event_date_utc = None
        date_precision = "unknown"
        verified = False
        if trigger == "unknown":
            trigger = "mapped scar"

    fatalities = _strict_count(raw.get("fatalities"), verified=verified)
    injuries = _strict_count(raw.get("injuries"), verified=verified)
    households_affected = _strict_count(raw.get("households_affected"), verified=verified)

    if feature_type == "landslide_scar":
        fatalities = None
        injuries = None
        households_affected = None

    district = str(raw.get("district") or "").strip() or None
    province = _canonical_province_or_none(raw.get("province"))
    if adm is not None and (district is None or province is None):
        if district is None:
            district = adm.district(lon_r, lat_r) or None
        if province is None:
            province = _canonical_province_or_none(adm.province(lon_r, lat_r))

    source_default = {
        "bipad_ndrrma": "BIPAD Portal (NDRRMA)",
        "nasa_coolr": "NASA COOLR",
        "osm_overpass": "OpenStreetMap",
        "usgs_ground_failure": "USGS Ground Failure",
        "traya_static": "TRĀYA Susceptibility Screening",
        "community_field": "Community Report",
    }[provider_id]
    source = str(raw.get("source") or source_default).strip() or source_default

    title = str(raw.get("title") or "").strip()
    if not title:
        title = (
            "Mapped landslide scar / hazard zone"
            if feature_type == "landslide_scar"
            else "Landslide record"
        )
    raw_title_ne = str(raw.get("title_ne") or "").strip()
    title_ne: str | None = raw_title_ne if raw_title_ne else None

    evidence_url = _safe_https_url(raw.get("evidence_url") or raw.get("url"))
    legacy_url = evidence_url or _safe_url(raw.get("url"))
    legacy_date = event_date_utc[:10] if event_date_utc else None

    rid = str(raw.get("id") or "").strip()
    if not rid:
        rid = f"{provider_id}_{lon_r}_{lat_r}"

    admin_str = str(raw.get("admin") or "").strip() or (district or "")
    category = str(raw.get("category") or "landslide").strip() or "landslide"
    size = str(raw.get("size") or "").strip()

    return {
        "id": rid,
        "feature_type": feature_type,
        "provider_id": provider_id,
        "source": source,
        "data_class": data_class,
        "title": title,
        "title_ne": title_ne,
        "event_date_utc": event_date_utc,
        "date_precision": date_precision,
        "lon": lon_r,
        "lat": lat_r,
        "district": district,
        "province": province,
        "trigger": trigger,
        "fatalities": fatalities,
        "injuries": injuries,
        "households_affected": households_affected,
        "verified": verified,
        "evidence_url": evidence_url,
        "license_ref": license_ref,
        # Backward-compatible fields for existing frontend & pipeline consumers
        "date": legacy_date,
        "url": legacy_url,
        "admin": admin_str,
        "category": category,
        "size": size,
    }


def validate_landslide_record(rec: dict[str, Any]) -> list[str]:
    """Pure-stdlib validator matching `schemas/landslide_event.v1.schema.json`."""
    errs: list[str] = []
    req_fields = (
        "id",
        "feature_type",
        "provider_id",
        "source",
        "data_class",
        "title",
        "title_ne",
        "event_date_utc",
        "date_precision",
        "lon",
        "lat",
        "district",
        "province",
        "trigger",
        "fatalities",
        "injuries",
        "households_affected",
        "verified",
        "evidence_url",
        "license_ref",
    )
    for k in req_fields:
        if k not in rec:
            errs.append(f"missing required field: {k}")

    allowed = set(req_fields) | {"date", "url", "admin", "category", "size"}
    extra = set(rec.keys()) - allowed
    if extra:
        errs.append(f"unexpected fields: {sorted(extra)}")

    ft = rec.get("feature_type")
    if ft not in FEATURE_TYPES:
        errs.append(f"invalid feature_type: {ft!r}")
    if rec.get("provider_id") not in PROVIDER_IDS:
        errs.append(f"invalid provider_id: {rec.get('provider_id')!r}")
    if rec.get("data_class") not in DATA_CLASSES:
        errs.append(f"invalid data_class: {rec.get('data_class')!r}")
    if not isinstance(rec.get("verified"), bool):
        errs.append("verified must be bool")

    lon, lat = rec.get("lon"), rec.get("lat")
    if not isinstance(lon, (int, float)) or isinstance(lon, bool) or not (79.5 <= lon <= 88.8):
        errs.append(f"invalid lon: {lon!r}")
    if not isinstance(lat, (int, float)) or isinstance(lat, bool) or not (26.0 <= lat <= 31.0):
        errs.append(f"invalid lat: {lat!r}")

    prov = rec.get("province")
    if prov is not None and prov not in C.CANONICAL_PROVINCES:
        errs.append(f"non-canonical province: {prov!r}")

    ev_dt = rec.get("event_date_utc")
    dp = rec.get("date_precision")
    if ev_dt is None:
        if dp != "unknown":
            errs.append(f"null event_date_utc requires date_precision='unknown', got {dp!r}")
    else:
        if not isinstance(ev_dt, str) or not ISO_DATE_RE.match(ev_dt):
            errs.append(f"invalid ISO-8601 event_date_utc: {ev_dt!r}")
        if dp not in ("day", "month", "year"):
            errs.append(f"dated record requires day|month|year date_precision, got {dp!r}")

    if ft == "landslide_scar":
        if ev_dt is not None or dp != "unknown":
            errs.append("landslide_scar must have null event_date_utc and date_precision='unknown'")
        if rec.get("verified") is not False:
            errs.append("landslide_scar must have verified=False")
        for ck in ("fatalities", "injuries", "households_affected"):
            if rec.get(ck) is not None:
                errs.append(f"landslide_scar must have {ck}=null")
    elif ft == "landslide_event":
        if ev_dt is None:
            errs.append("landslide_event must have non-null event_date_utc")

    verified = rec.get("verified") is True
    for ck in ("fatalities", "injuries", "households_affected"):
        val = rec.get(ck)
        if val is not None:
            if not isinstance(val, int) or isinstance(val, bool) or val < 0:
                errs.append(f"{ck} must be non-negative int or null, got {val!r}")
            elif val == 0 and not verified:
                errs.append(f"{ck}=0 violates null-not-0 rule when verified=False")

    eurl = rec.get("evidence_url")
    if eurl is not None and (not isinstance(eurl, str) or not eurl.startswith("https://")):
        errs.append(f"evidence_url must be https:// URL or null, got {eurl!r}")

    return errs


# ---------------------------------------------------------------------------
# Upstream adapters (BIPAD NDRRMA, NASA COOLR, OpenStreetMap Overpass)
# ---------------------------------------------------------------------------
def parse_bipad_incident(
    raw: dict[str, Any],
    adm: HM.StdlibAdminLookup | None = None,
) -> dict[str, Any] | None:
    """Convert a live or cached BIPAD Portal incident dict into a canonical v1 record."""
    if not isinstance(raw, dict):
        return None
    # Filter to landslides if mixed hazard payload
    hazard_id = raw.get("hazard")
    hazard_title = str(raw.get("hazard_name") or raw.get("hazardTitle") or "").lower()
    if hazard_id is not None and hazard_id != 17 and "landslide" not in hazard_title:
        return None

    lon = raw.get("lon")
    lat = raw.get("lat")
    if lon is None or lat is None:
        pt = raw.get("point") or {}
        coords = pt.get("coordinates") or []
        if len(coords) >= 2:
            lon, lat = coords[0], coords[1]
    if lon is None or lat is None:
        return None

    verified = bool(raw.get("verified", False))
    loss = raw.get("loss") if isinstance(raw.get("loss"), dict) else {}

    # Strict null-not-0: 0 is ONLY kept when verified=True and loss explicitly reports 0
    raw_deaths = (
        loss.get("peopleDeathCount")
        if "peopleDeathCount" in loss
        else (raw.get("peopleDeathCount") if "peopleDeathCount" in raw else raw.get("fatalities"))
    )
    raw_inj = (
        loss.get("peopleInjuredCount")
        if "peopleInjuredCount" in loss
        else (raw.get("peopleInjuredCount") if "peopleInjuredCount" in raw else raw.get("injuries"))
    )
    raw_hh = (
        loss.get("familyAffectedCount")
        if "familyAffectedCount" in loss
        else (raw.get("familyAffectedCount") if "familyAffectedCount" in raw else raw.get("households_affected"))
    )

    inc_id = raw.get("id")
    rid = str(inc_id) if str(inc_id or "").startswith("bipad_") else f"bipad_{inc_id}"
    cause = str(raw.get("cause") or "").strip()
    title = str(raw.get("title") or "BIPAD reported landslide").strip()
    title_ne = raw.get("titleNe") or raw.get("title_ne") or None
    event_on = raw.get("incidentOn") or raw.get("event_date_utc") or raw.get("reportedOn")

    is_coseismic = bool(COSEISMIC_RE.search(f"{cause} {title}"))
    trigger = cause if cause else ("earthquake" if is_coseismic else "rainfall / slope failure")
    if is_coseismic:
        ft = "coseismic_failure"
    elif verified and event_on:
        ft = "landslide_event"
    else:
        ft = "hazard_report"

    eurl = raw.get("evidence_url")
    if not eurl and inc_id is not None:
        clean_num = str(inc_id).replace("bipad_", "")
        eurl = f"https://bipadportal.gov.np/api/v1/incident/{clean_num}/"

    return normalize_record(
        {
            "id": rid,
            "feature_type": ft,
            "provider_id": "bipad_ndrrma",
            "source": "BIPAD Portal (NDRRMA)",
            "data_class": "official_observed" if verified else "community_report",
            "title": title,
            "title_ne": title_ne,
            "event_date_utc": event_on,
            "lon": lon,
            "lat": lat,
            "district": raw.get("district") if isinstance(raw.get("district"), str) else None,
            "province": raw.get("province") if isinstance(raw.get("province"), str) else None,
            "trigger": trigger,
            "fatalities": raw_deaths,
            "injuries": raw_inj,
            "households_affected": raw_hh,
            "verified": verified,
            "evidence_url": eurl,
            "license_ref": "Government of Nepal NDRRMA BIPAD Portal public data",
            "category": "landslide",
        },
        adm=adm,
    )


def load_bipad_landslides_from_disk(
    adm: HM.StdlibAdminLookup | None = None,
) -> list[dict[str, Any]]:
    """Read BIPAD landslide incidents from `data/bipad_official.json` or `cache/bipad_snapshot.json`."""
    for path in (DATA_BIPAD, CACHE_BIPAD):
        if not os.path.exists(path):
            continue
        try:
            with open(path, encoding="utf-8") as fh:
                payload = json.load(fh)
        except Exception:
            continue
        raw_items: list[dict[str, Any]] = []
        if isinstance(payload, dict):
            for key in ("landslide_incidents", "landslides", "incidents", "results"):
                val = payload.get(key)
                if isinstance(val, list):
                    raw_items.extend(val)
                elif isinstance(val, dict) and isinstance(val.get("results"), list):
                    raw_items.extend(val["results"])
                elif isinstance(val, dict) and isinstance(val.get("samples"), list):
                    raw_items.extend(val["samples"])
        elif isinstance(payload, list):
            raw_items = payload
        parsed = [
            rec
            for item in raw_items
            if (rec := parse_bipad_incident(item, adm=adm)) is not None
        ]
        if parsed:
            return parsed
    return []


def fetch_bipad_landslides(
    adm: HM.StdlibAdminLookup | None = None,
) -> list[dict[str, Any]]:
    """Query live BIPAD Portal NDRRMA landslide incidents (`hazard=17`)."""
    payload = _http_get_json(BIPAD_LANDSLIDE_URL, timeout=30, retries=2)
    results = payload.get("results") if isinstance(payload, dict) else []
    out: list[dict[str, Any]] = []
    for item in results or []:
        rec = parse_bipad_incident(item, adm=adm)
        if rec is not None:
            out.append(rec)
    return out


def fetch_nasa_coolr(
    bbox: tuple[float, float, float, float] = C.NEPAL_BBOX,
    adm: HM.StdlibAdminLookup | None = None,
) -> list[dict[str, Any]]:
    """Query NASA COOLR ArcGIS FeatureServer for Nepal bbox with timeout/retry."""
    lon_min, lat_min, lon_max, lat_max = bbox
    params = {
        "where": "1=1",
        "geometry": f"{lon_min},{lat_min},{lon_max},{lat_max}",
        "geometryType": "esriGeometryEnvelope",
        "inSR": "4326",
        "spatialRel": "esriSpatialRelIntersects",
        "outFields": "*",
        "f": "geojson",
        "resultRecordCount": "2000",
    }
    qs = urllib.parse.urlencode(params)
    last_exc: Exception | None = None
    for endpoint in NASA_COOLR_ENDPOINTS:
        try:
            gj = _http_get_json(f"{endpoint}?{qs}", timeout=30, retries=2)
            feats = gj.get("features") or []
            records: list[dict[str, Any]] = []
            for f in feats:
                geom = f.get("geometry") or {}
                coords = geom.get("coordinates") or []
                if len(coords) < 2:
                    continue
                lon, lat = float(coords[0]), float(coords[1])
                if not (math.isfinite(lon) and math.isfinite(lat)):
                    continue
                p = f.get("properties") or {}
                eid = p.get("event_id") or p.get("OBJECTID") or f.get("id")
                trigger = str(p.get("landslide_trigger") or "unknown").strip() or "unknown"
                rec = normalize_record(
                    {
                        "id": f"coolr_{eid}",
                        "provider_id": "nasa_coolr",
                        "source": "NASA COOLR",
                        "event_date_utc": p.get("event_date"),
                        "title": str(
                            p.get("event_title")
                            or p.get("location_description")
                            or "NASA COOLR landslide"
                        ).strip(),
                        "title_ne": None,
                        "category": str(p.get("landslide_category") or "landslide").strip(),
                        "trigger": trigger,
                        "size": str(p.get("landslide_size") or "").strip(),
                        "fatalities": p.get("fatality_count"),
                        "injuries": p.get("injury_count"),
                        "households_affected": None,
                        "verified": False,
                        "admin": str(p.get("admin_division_name") or "").strip(),
                        "lon": lon,
                        "lat": lat,
                        "evidence_url": p.get("source_link"),
                        "url": p.get("source_link"),
                        "license_ref": "NASA Open Data (public domain)",
                    },
                    adm=adm,
                )
                if rec is not None:
                    records.append(rec)
            return records
        except Exception as exc:
            last_exc = exc
    raise RuntimeError(f"All NASA COOLR endpoints failed: {last_exc}")


def fetch_osm_landslides(adm: HM.StdlibAdminLookup | None = None) -> list[dict[str, Any]]:
    """Query OpenStreetMap Overpass for mapped landslide scars in Nepal."""
    query = """
    [out:json][timeout:180];
    area["ISO3166-1"="NP"][admin_level=2]->.np;
    (
      node["hazard"="landslide"](area.np);
      way["hazard"="landslide"](area.np);
      node["geological"="landslide"](area.np);
      way["geological"="landslide"](area.np);
      node["natural"="landslide"](area.np);
      way["natural"="landslide"](area.np);
    );
    out center tags;
    """
    data = urllib.parse.urlencode({"data": query}).encode("utf-8")
    last_exc: Exception | None = None
    for url in OVERPASS_MIRRORS:
        try:
            req = urllib.request.Request(url, data=data, headers={"User-Agent": USER_AGENT})
            with urllib.request.urlopen(req, timeout=200) as resp:
                payload = json.loads(resp.read().decode("utf-8"))
            out: list[dict[str, Any]] = []
            for el in payload.get("elements") or []:
                if el.get("type") == "node":
                    lon, lat = el.get("lon"), el.get("lat")
                else:
                    ctr = el.get("center") or {}
                    lon, lat = ctr.get("lon"), ctr.get("lat")
                if lon is None or lat is None:
                    continue
                tags = el.get("tags") or {}
                el_type = el.get("type", "node")
                el_id = el.get("id")
                raw_name = str(tags.get("name") or "").strip()
                name_ne = str(tags.get("name:ne") or "").strip()
                if not name_ne and any("\u0900" <= ch <= "\u097f" for ch in raw_name):
                    name_ne = raw_name
                rec = normalize_record(
                    {
                        "id": f"osm_{el_type[0]}{el_id}",
                        "feature_type": "landslide_scar",
                        "provider_id": "osm_overpass",
                        "source": "OpenStreetMap",
                        "data_class": "mapped_inventory",
                        "event_date_utc": None,
                        "date_precision": "unknown",
                        "title": str(
                            tags.get("name:en")
                            or raw_name
                            or "Mapped landslide scar / hazard zone"
                        ).strip(),
                        "title_ne": name_ne or None,
                        "category": str(tags.get("natural") or tags.get("geological") or "landslide"),
                        "trigger": "mapped scar",
                        "fatalities": None,
                        "injuries": None,
                        "households_affected": None,
                        "verified": False,
                        "lon": float(lon),
                        "lat": float(lat),
                        "evidence_url": f"https://www.openstreetmap.org/{el_type}/{el_id}",
                        "license_ref": "ODbL 1.0",
                    },
                    adm=adm,
                )
                if rec is not None:
                    out.append(rec)
            return out
        except Exception as exc:
            last_exc = exc
            time.sleep(3.0)
    raise RuntimeError(f"Overpass landslide query failed: {last_exc}")


# ---------------------------------------------------------------------------
# Duplicate-Candidate Detection (Flag-Only, NEVER Auto-Merges)
# ---------------------------------------------------------------------------
def find_duplicate_candidates(
    records: list[dict[str, Any]],
    max_km: float = 1.5,
    max_days: int = 3,
    undated_cross_source_max_km: float = 0.35,
) -> list[dict[str, Any]]:
    """Detect potential duplicate landslide record pairs without auto-merging.

    Rules:
      1. Both records dated (`event_date_utc` present):
         flagged when Haversine distance <= `max_km` (default 1.5 km) AND
         temporal separation <= `max_days` (default 3 days).
      2. At least one record undated:
         flagged ONLY across distinct providers (`provider_id` differs) when
         Haversine distance <= `undated_cross_source_max_km` (default 0.35 km).

    Every flagged pair carries `distance_km`, `days_apart`, `title_similarity`,
    `reason`, `review_status: "pending_review"`, and `auto_merged: False`.
    """
    if not records:
        return []

    cell_deg = max(0.02, (max_km / 110.0) * 1.25)
    grid: dict[tuple[int, int], list[int]] = defaultdict(list)
    parsed_dts: list[dt.datetime | None] = []
    norm_titles: list[str] = []

    for idx, rec in enumerate(records):
        gx = int(math.floor(float(rec["lon"]) / cell_deg))
        gy = int(math.floor(float(rec["lat"]) / cell_deg))
        grid[(gx, gy)].append(idx)
        parsed_dts.append(_parse_dt_obj(rec.get("event_date_utc")))
        norm_titles.append(_normalize_title_for_sim(rec.get("title") or ""))

    candidates: list[dict[str, Any]] = []
    seen_pairs: set[tuple[str, str]] = set()

    for i, rec_a in enumerate(records):
        lon_a, lat_a = float(rec_a["lon"]), float(rec_a["lat"])
        gx0 = int(math.floor(lon_a / cell_deg))
        gy0 = int(math.floor(lat_a / cell_deg))
        id_a = str(rec_a["id"])
        dt_a = parsed_dts[i]

        for dx in (-1, 0, 1):
            for dy in (-1, 0, 1):
                for j in grid.get((gx0 + dx, gy0 + dy), ()):
                    if j <= i:
                        continue
                    rec_b = records[j]
                    id_b = str(rec_b["id"])
                    if id_a == id_b:
                        continue
                    pair_key = (id_a, id_b) if id_a < id_b else (id_b, id_a)
                    if pair_key in seen_pairs:
                        continue

                    dist_km = SZ.haversine_km(
                        lon_a, lat_a, float(rec_b["lon"]), float(rec_b["lat"])
                    )
                    if dist_km > max_km:
                        continue

                    dt_b = parsed_dts[j]
                    distinct_sources = rec_a.get("provider_id") != rec_b.get("provider_id")
                    reason: str | None = None
                    days_apart: float | None = None

                    if dt_a is not None and dt_b is not None:
                        days_apart = round(abs((dt_a - dt_b).total_seconds()) / 86400.0, 2)
                        if days_apart <= float(max_days):
                            reason = (
                                "dated_cross_source_spatiotemporal_proximity"
                                if distinct_sources
                                else "dated_same_source_spatiotemporal_proximity"
                            )
                    else:
                        if distinct_sources and dist_km <= undated_cross_source_max_km:
                            reason = "undated_cross_source_spatial_proximity"

                    if reason is None:
                        continue

                    seen_pairs.add(pair_key)
                    # Canonical deterministic order (a < b by id)
                    first, second = (rec_a, rec_b) if id_a < id_b else (rec_b, rec_a)
                    t_a = norm_titles[i] if id_a < id_b else norm_titles[j]
                    t_b = norm_titles[j] if id_a < id_b else norm_titles[i]
                    sim = round(difflib.SequenceMatcher(None, t_a, t_b).ratio(), 3)

                    candidates.append(
                        {
                            "candidate_id": f"dup_{first['id']}__{second['id']}",
                            "record_a_id": first["id"],
                            "record_b_id": second["id"],
                            "record_a_provider": first.get("provider_id"),
                            "record_b_provider": second.get("provider_id"),
                            "record_a_source": first.get("source"),
                            "record_b_source": second.get("source"),
                            "record_a_feature_type": first.get("feature_type"),
                            "record_b_feature_type": second.get("feature_type"),
                            "record_a_title": first.get("title"),
                            "record_b_title": second.get("title"),
                            "record_a_date_utc": first.get("event_date_utc"),
                            "record_b_date_utc": second.get("event_date_utc"),
                            "distance_km": round(dist_km, 3),
                            "days_apart": days_apart,
                            "title_similarity": sim,
                            "reason": reason,
                            "review_status": "pending_review",
                            "auto_merged": False,
                        }
                    )

    candidates.sort(
        key=lambda c: (
            c["distance_km"],
            c["days_apart"] if c["days_apart"] is not None else 9999.0,
            c["candidate_id"],
        )
    )
    return candidates


def to_geojson_feature_collection(
    records: list[dict[str, Any]],
    updated_utc: str,
    provenance: dict[str, Any],
) -> dict[str, Any]:
    """Build RFC 7946 GeoJSON FeatureCollection for GIS/QGIS import."""
    features: list[dict[str, Any]] = []
    for rec in records:
        props = {
            k: v
            for k, v in rec.items()
            if k not in ("lon", "lat")
        }
        features.append(
            {
                "type": "Feature",
                "id": rec["id"],
                "geometry": {
                    "type": "Point",
                    "coordinates": [rec["lon"], rec["lat"]],
                },
                "properties": props,
            }
        )
    return {
        "type": "FeatureCollection",
        "name": "nepal_traya_landslide_inventory_v1",
        "updated_utc": updated_utc,
        "schema_version": SCHEMA_VERSION,
        "n_features": len(features),
        "provenance": provenance,
        "features": features,
    }


def _load_cached() -> dict[str, Any]:
    if os.path.exists(CACHE_JSON):
        with open(CACHE_JSON, encoding="utf-8") as fh:
            return json.load(fh)
    if os.path.exists(LEGACY_JS):
        txt = open(LEGACY_JS, encoding="utf-8").read()
        return json.loads(txt.split("=", 1)[1].rsplit(";", 1)[0])
    return {}


def _load_admin_lookup() -> HM.StdlibAdminLookup | None:
    try:
        return HM.StdlibAdminLookup()
    except Exception:
        return None


def build_landslides(
    offline: bool = False,
    refresh_osm: bool = False,
    out_path: str = OUT_JSON,
    review_queue_path: str = OUT_REVIEW_QUEUE,
    geojson_path: str = OUT_GEOJSON,
    extra_records: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    """Assemble canonical landslide inventory, review queue, and GIS GeoJSON."""
    adm = _load_admin_lookup()
    cached = _load_cached()
    cached_events = [
        ne
        for e in (cached.get("events") or [])
        if (ne := normalize_record(e, adm=adm)) is not None
    ]
    now_utc = dt.datetime.now(dt.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")

    bipad_events = [e for e in cached_events if e["provider_id"] == "bipad_ndrrma"]
    coolr_events = [e for e in cached_events if e["provider_id"] == "nasa_coolr"]
    osm_events = [e for e in cached_events if e["provider_id"] == "osm_overpass"]
    other_events = [
        e
        for e in cached_events
        if e["provider_id"] not in ("bipad_ndrrma", "nasa_coolr", "osm_overpass")
    ]

    # Pick up any BIPAD records written to data/bipad_official.json or cache/bipad_snapshot.json
    disk_bipad = load_bipad_landslides_from_disk(adm=adm)
    if disk_bipad:
        bipad_events = disk_bipad

    any_live = False
    if offline:
        updated_utc = cached.get("updated_utc") or now_utc
    else:
        updated_utc = now_utc
        try:
            fetched_bipad = fetch_bipad_landslides(adm=adm)
            if fetched_bipad:
                disk_by_id = {e["id"]: e for e in disk_bipad}
                enriched_bipad: list[dict[str, Any]] = []
                for rec in fetched_bipad:
                    if (
                        rec.get("fatalities") is None
                        and rec.get("injuries") is None
                        and rec.get("households_affected") is None
                        and rec["id"] in disk_by_id
                    ):
                        prev = disk_by_id[rec["id"]]
                        if any(
                            prev.get(k) is not None
                            for k in ("fatalities", "injuries", "households_affected")
                        ):
                            rec = prev
                    enriched_bipad.append(rec)
                bipad_events = enriched_bipad
                any_live = True
        except Exception as exc:
            print(
                f"  [landslides] BIPAD NDRRMA unavailable ({exc}); keeping {len(bipad_events)} cached records",
                file=sys.stderr,
            )
        try:
            fetched_coolr = fetch_nasa_coolr(adm=adm)
            coolr_events = fetched_coolr
            any_live = True
        except Exception as exc:
            print(
                f"  [landslides] NASA COOLR unavailable ({exc}); keeping {len(coolr_events)} cached records",
                file=sys.stderr,
            )
        if refresh_osm or not osm_events:
            try:
                osm_events = fetch_osm_landslides(adm=adm)
                any_live = True
            except Exception as exc:
                print(
                    f"  [landslides] OSM Overpass refresh failed ({exc}); keeping {len(osm_events)} cached records",
                    file=sys.stderr,
                )
        if not any_live:
            updated_utc = cached.get("updated_utc") or now_utc

    if extra_records:
        for raw_ex in extra_records:
            norm = normalize_record(raw_ex, adm=adm)
            if norm is not None:
                if norm["provider_id"] == "bipad_ndrrma":
                    bipad_events.append(norm)
                elif norm["provider_id"] == "nasa_coolr":
                    coolr_events.append(norm)
                elif norm["provider_id"] == "osm_overpass":
                    osm_events.append(norm)
                else:
                    other_events.append(norm)

    # Deduplicate strictly by exact record `id` ONLY (uncertain spatial/temporal
    # duplicates are NEVER auto-merged; they go into `landslide_review_queue.json`).
    def _event_sort_key(x: dict[str, Any]) -> tuple[str, int, int, int, str]:
        fat = x.get("fatalities")
        has_loss_detail = (
            int(fat is not None)
            + int(x.get("injuries") is not None)
            + int(x.get("households_affected") is not None)
        )
        return (
            x.get("event_date_utc") or "",
            fat if isinstance(fat, int) else -1,
            has_loss_detail,
            int(bool(x.get("verified"))),
            x["id"],
        )

    seen: set[str] = set()
    merged: list[dict[str, Any]] = []
    ordered_inputs = (
        sorted(
            bipad_events,
            key=_event_sort_key,
            reverse=True,
        )
        + sorted(
            coolr_events,
            key=_event_sort_key,
            reverse=True,
        )
        + sorted(
            other_events,
            key=lambda x: (x.get("event_date_utc") or "", x["id"]),
            reverse=True,
        )
        + osm_events
    )
    for ev in ordered_inputs:
        eid = ev["id"]
        if eid in seen:
            continue
        seen.add(eid)
        merged.append(ev)

    # Validate every emitted record against v1 schema invariants
    validation_errors = 0
    for rec in merged:
        errs = validate_landslide_record(rec)
        if errs:
            validation_errors += 1
            raise ValueError(f"Schema validation failed for {rec.get('id')}: {errs}")

    # Run transparent duplicate-candidate detection (flag-only)
    dup_candidates = find_duplicate_candidates(merged, max_km=1.5, max_days=3)

    n_bipad = sum(1 for e in merged if e["provider_id"] == "bipad_ndrrma")
    n_coolr = sum(1 for e in merged if e["provider_id"] == "nasa_coolr")
    n_osm = sum(1 for e in merged if e["provider_id"] == "osm_overpass")
    counts_by_type = {ft: sum(1 for e in merged if e["feature_type"] == ft) for ft in FEATURE_TYPES}

    coolr_available = n_coolr > 0
    bipad_available = n_bipad > 0
    total_fatalities = sum(
        int(e["fatalities"])
        for e in merged
        if isinstance(e.get("fatalities"), int) and e["fatalities"] > 0
    )

    parts: list[str] = []
    if bipad_available:
        parts.append(f"{n_bipad} BIPAD NDRRMA official incident records")
    if coolr_available:
        parts.append(f"{n_coolr} dated NASA COOLR/GLC event reports")
    if n_osm > 0:
        parts.append(f"{n_osm} undated OpenStreetMap mapped landslide scars")

    if bipad_available or coolr_available:
        coverage_note = (
            "Combines " + ", ".join(parts) + " in Nepal (strictly partitioned across 5 canonical feature types). "
            "Inventories are incomplete and represent lower bounds."
        )
    else:
        coverage_note = (
            f"0 NASA COOLR and 0 BIPAD records currently loaded (offline cache or upstream endpoints "
            f"unavailable); displaying {n_osm} undated OpenStreetMap mapped landslide scars only."
        )

    mode_str = "offline" if offline else ("live" if any_live else "cached_fallback")
    provenance: dict[str, Any] = {
        "schema_version": SCHEMA_VERSION,
        "schema_ref": "schemas/landslide_event.v1.schema.json",
        "generated_utc": now_utc,
        "updated_utc": updated_utc,
        "mode": mode_str,
        "data_class": (
            "mixed_official_and_mapped"
            if (bipad_available or coolr_available)
            else "mapped_inventory"
        ),
        "license_ref": "ODbL 1.0 (OSM); NASA Open Data (COOLR); Government of Nepal NDRRMA BIPAD Portal public data",
        "sources": [
            {
                "provider_id": "bipad_ndrrma",
                "name": "BIPAD Portal (NDRRMA, Government of Nepal)",
                "endpoint": BIPAD_LANDSLIDE_URL,
                "records_loaded": n_bipad,
                "available": bipad_available,
                "license_ref": "Government of Nepal NDRRMA BIPAD Portal public data",
            },
            {
                "provider_id": "nasa_coolr",
                "name": "NASA COOLR / Global Landslide Catalog",
                "endpoint": NASA_COOLR_ENDPOINTS[0],
                "records_loaded": n_coolr,
                "available": coolr_available,
                "license_ref": "NASA Open Data (public domain)",
            },
            {
                "provider_id": "osm_overpass",
                "name": "OpenStreetMap Overpass mapped landslide scars",
                "endpoint": OVERPASS_MIRRORS[0],
                "records_loaded": n_osm,
                "available": n_osm > 0,
                "license_ref": "ODbL 1.0",
            },
        ],
    }

    payload: dict[str, Any] = {
        "updated_utc": updated_utc,
        "mode": mode_str,
        "schema_version": SCHEMA_VERSION,
        "n_total": len(merged),
        "n_nasa_coolr": n_coolr,
        "n_bipad": n_bipad,
        "n_osm": n_osm,
        "nasa_coolr_available": coolr_available,
        "bipad_available": bipad_available,
        "total_reported_fatalities": total_fatalities,
        "counts_by_type": counts_by_type,
        "duplicate_candidates_count": len(dup_candidates),
        "coverage_note": coverage_note,
        "null_semantics_note": (
            "Unknown dates, fatalities, injuries, and households_affected are encoded strictly as null "
            "(never 0); 0 is reserved strictly for verified zero-casualty official records (verified=true)."
        ),
        "provenance": provenance,
        "thresholds": THRESHOLDS,
        "events": merged,
    }

    review_queue_payload: dict[str, Any] = {
        "updated_utc": updated_utc,
        "generated_utc": now_utc,
        "schema_version": "landslide_review_queue.v1",
        "policy": "flag_only_never_auto_merge",
        "parameters": {
            "max_km": 1.5,
            "max_days": 3,
            "undated_cross_source_max_km": 0.35,
        },
        "n_records_scanned": len(merged),
        "n_candidates": len(dup_candidates),
        "n_pending_review": sum(1 for c in dup_candidates if c["review_status"] == "pending_review"),
        "candidates": dup_candidates,
        "provenance": provenance,
    }

    geojson_payload = to_geojson_feature_collection(merged, updated_utc, provenance)

    _atomic_write_json(out_path, payload)
    _atomic_write_json(review_queue_path, review_queue_payload)
    _atomic_write_json(geojson_path, geojson_payload)
    if any_live:
        _atomic_write_json(CACHE_JSON, payload)
    return payload


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="Nepal TRĀYA 2.0 canonical landslide inventory builder")
    ap.add_argument("--offline", action="store_true", help="Zero network calls; normalize cached data")
    ap.add_argument("--refresh", action="store_true", help="Query BIPAD & NASA COOLR live")
    ap.add_argument("--refresh-osm", action="store_true", help="Also refresh OSM landslide scars")
    args = ap.parse_args(argv)

    res = build_landslides(offline=args.offline, refresh_osm=args.refresh_osm)
    print(
        f"[landslides] wrote {OUT_JSON}, {OUT_REVIEW_QUEUE}, {OUT_GEOJSON}: "
        f"total={res['n_total']} (BIPAD={res['n_bipad']}, NASA COOLR={res['n_nasa_coolr']}, "
        f"OSM={res['n_osm']}, types={res['counts_by_type']}, "
        f"dup_candidates={res['duplicate_candidates_count']})"
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
