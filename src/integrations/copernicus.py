"""
Copernicus Sentinel-1 SAR (all-weather C-band GRD) & Sentinel-2 L2A optical
STAC integration via Element84 Earth Search (Wave C EO Monitoring).

Why Sentinel-1 SAR matters for Nepal glacial lakes:
  * During the June-September Himalayan monsoon, optical Sentinel-2 scenes over
    high-altitude moraine-dammed lakes (Tsho Rolpa, Imja Tsho, Lower Barun,
    Thulagi, Lumding, Chamlang North/South, Thame/Ngole Cho) are frequently
    obscured by persistent cloud cover.
  * Sentinel-1 C-band SAR (IW mode, VV+VH polarizations) penetrates monsoon
    cloud cover day and night (`all_weather_capability: True`), providing
    continuous repeat-pass observation metadata alongside Sentinel-2 optical
    quicklooks.

Pure Python 3.12 standard library only (zero third-party dependencies).
"""
from __future__ import annotations

import argparse
import datetime as dt
import json
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
        safe_url,
        utc_now_iso,
    )
else:
    from integrations.provenance import (
        atomic_write_json,
        evaluate_envelope_sla,
        format_iso_utc,
        make_envelope,
        parse_iso_utc,
        safe_url,
        utc_now_iso,
    )

USER_AGENT = "Nepal-TRAYA/2.0 (+https://prazg.github.io/Nepal_TRAYA/)"
STAC_BASE_URL = "https://earth-search.aws.element84.com/v1"
STAC_S1_ITEMS_URL = f"{STAC_BASE_URL}/collections/sentinel-1-grd/items"
STAC_S2_ITEMS_URL = f"{STAC_BASE_URL}/collections/sentinel-2-l2a/items"

COPERNICUS_SOURCE_NAME = "Copernicus Sentinel-1 SAR & Sentinel-2 L2A (Element84 Earth Search STAC)"
COPERNICUS_DATASET_NAME = "copernicus_eo_sar_optical_priority_lakes"
COPERNICUS_LICENSE_REF = "Copernicus Sentinel Open Data (ESA/EC) via Element84 Earth Search STAC"
COPERNICUS_SLA_HOURS = 288  # 12-day Sentinel-1 repeat cycle / weekly refresh SLA

CACHE_EO_SAR = os.path.join(C.CACHE, "eo_sar.json")
CACHE_STAC_S2 = os.path.join(C.CACHE, "stac_scenes.json")

# Priority Himalayan glacial lakes in Nepal (verified IDs & coordinates from Nepal Cryosphere Inventory)
PRIORITY_EO_LAKES: tuple[dict[str, Any], ...] = (
    {
        "id": "GL_27.86029_86.47725",
        "name": "Tsho Rolpa",
        "lon": 86.4772,
        "lat": 27.8603,
        "z_m": 4546,
        "district": "Dolakha",
        "prov": "Bagmati Province",
    },
    {
        "id": "GL_27.89829_86.92818",
        "name": "Imja Tsho",
        "lon": 86.9282,
        "lat": 27.8983,
        "z_m": 4990,
        "district": "Solukhumbu",
        "prov": "Koshi Province",
    },
    {
        "id": "GL_27.79788_87.09011",
        "name": "Lower Barun Tsho",
        "lon": 87.0901,
        "lat": 27.7979,
        "z_m": 4508,
        "district": "Sankhuwasabha",
        "prov": "Koshi Province",
    },
    {
        "id": "GL_28.48784_84.48656",
        "name": "Thulagi Tsho",
        "lon": 84.4866,
        "lat": 28.4878,
        "z_m": 3988,
        "district": "Manang",
        "prov": "Gandaki Province",
    },
    {
        "id": "GL_27.7789_86.60969",
        "name": "Lumding Tsho",
        "lon": 86.6097,
        "lat": 27.7789,
        "z_m": 4831,
        "district": "Solukhumbu",
        "prov": "Koshi Province",
    },
    {
        "id": "GL_27.78324_86.95824",
        "name": "Chamlang North Tsho",
        "lon": 86.9582,
        "lat": 27.7833,
        "z_m": 5206,
        "district": "Solukhumbu",
        "prov": "Koshi Province",
    },
    {
        "id": "GL_27.75484_86.95892",
        "name": "Chamlang South Tsho (West Chamjang)",
        "lon": 86.9589,
        "lat": 27.7548,
        "z_m": 4938,
        "district": "Solukhumbu",
        "prov": "Koshi Province",
    },
    {
        "id": "GL_27.83322_86.5641",
        "name": "Thame / Thyangbo (Ngole Cho)",
        "lon": 86.5641,
        "lat": 27.8332,
        "z_m": 4937,
        "district": "Solukhumbu",
        "prov": "Koshi Province",
    },
)


def _http_get_json(
    url: str,
    *,
    timeout: int = 25,
    retries: int = 3,
    backoff_base_s: float = 1.5,
) -> Any:
    headers = {
        "User-Agent": USER_AGENT,
        "Accept": "application/geo+json, application/json",
    }
    last_exc: Exception | None = None
    for attempt in range(max(1, retries)):
        try:
            req = urllib.request.Request(url, headers=headers)
            with urllib.request.urlopen(req, timeout=timeout) as resp:
                return json.loads(resp.read().decode("utf-8"))
        except urllib.error.HTTPError as exc:
            last_exc = exc
            if exc.code in (400, 404):
                break
        except Exception as exc:
            last_exc = exc
        if attempt < retries - 1:
            time.sleep(backoff_base_s * (2 ** attempt))
    raise RuntimeError(f"STAC GET {url} failed after {retries} attempt(s): {last_exc}")


def _copernicus_browser_url(lon: float, lat: float, day_iso: str, *, dataset_id: str) -> str:
    base = (
        f"https://browser.dataspace.copernicus.eu/?zoom=14"
        f"&lat={lat:.4f}&lng={lon:.4f}&datasetId={dataset_id}"
    )
    if day_iso and len(day_iso) >= 10:
        return f"{base}&toTime={day_iso[:10]}T23%3A59%3A59.999Z"
    return base


def _extract_https_thumbnail(assets: Any) -> str | None:
    if not isinstance(assets, dict):
        return None
    for key in ("thumbnail", "rendered_preview", "overview"):
        entry = assets.get(key)
        if isinstance(entry, dict):
            href = safe_url(entry.get("href"), require_https=True)
            if href:
                return href
    return None


def parse_sentinel1_item(
    item: dict[str, Any],
    *,
    lon: float | None = None,
    lat: float | None = None,
) -> dict[str, Any]:
    """Parse an Element84 Earth Search `sentinel-1-grd` STAC Item."""
    props = item.get("properties") if isinstance(item.get("properties"), dict) else {}
    assets = item.get("assets") if isinstance(item.get("assets"), dict) else {}

    dt_raw = props.get("datetime")
    dt_str = str(dt_raw).strip() if dt_raw else None
    pols_raw = props.get("sar:polarizations")
    polarizations = [str(p).upper() for p in pols_raw if p] if isinstance(pols_raw, list) else []

    out: dict[str, Any] = {
        "id": str(item.get("id") or "").strip() or None,
        "collection": "sentinel-1-grd",
        "datetime": dt_str,
        "platform": str(props.get("platform") or "").strip().lower() or None,
        "orbit_state": str(props.get("sat:orbit_state") or "").strip().lower() or None,
        "instrument_mode": str(props.get("sar:instrument_mode") or "").strip().upper() or None,
        "polarizations": polarizations,
        "thumbnail_url": _extract_https_thumbnail(assets),
        "all_weather_capability": True,
    }
    if lon is not None and lat is not None:
        out["copernicus_browser_url"] = _copernicus_browser_url(
            lon, lat, (dt_str or "")[:10], dataset_id="S1_AWS_IW_VVVH"
        )
    return out


def parse_sentinel2_item(
    item: dict[str, Any],
    *,
    lon: float | None = None,
    lat: float | None = None,
) -> dict[str, Any]:
    """Parse an Element84 Earth Search `sentinel-2-l2a` STAC Item."""
    props = item.get("properties") if isinstance(item.get("properties"), dict) else {}
    assets = item.get("assets") if isinstance(item.get("assets"), dict) else {}

    dt_raw = props.get("datetime")
    dt_str = str(dt_raw).strip() if dt_raw else None
    cloud = props.get("eo:cloud_cover")
    cloud_pct = round(float(cloud), 1) if isinstance(cloud, (int, float)) else None

    out: dict[str, Any] = {
        "id": str(item.get("id") or "").strip() or None,
        "collection": "sentinel-2-l2a",
        "datetime": dt_str,
        "platform": str(props.get("platform") or "").strip().lower() or None,
        "cloud_cover_pct": cloud_pct,
        "grid_code": str(props.get("grid:code") or "").strip() or None,
        "thumbnail_url": _extract_https_thumbnail(assets),
        "all_weather_capability": False,
    }
    if lon is not None and lat is not None:
        out["copernicus_browser_url"] = _copernicus_browser_url(
            lon, lat, (dt_str or "")[:10], dataset_id="S2_L2A_CDAS"
        )
    return out


def _normalize_legacy_s2_entry(
    entry: dict[str, Any] | None,
    lon: float,
    lat: float,
) -> dict[str, Any] | None:
    if not isinstance(entry, dict):
        return None
    dt_str = str(entry.get("datetime") or "").strip() or None
    thumb = safe_url(entry.get("thumbnail_url") or entry.get("thumbnail"), require_https=True)
    cop_url = safe_url(entry.get("copernicus_browser_url"), require_https=True) or _copernicus_browser_url(
        lon, lat, (dt_str or "")[:10], dataset_id="S2_L2A_CDAS"
    )
    cloud = entry.get("cloud_cover_pct")
    return {
        "id": str(entry.get("id") or entry.get("scene_id") or "").strip() or None,
        "collection": "sentinel-2-l2a",
        "datetime": dt_str,
        "platform": str(entry.get("platform") or "").strip().lower() or None,
        "cloud_cover_pct": round(float(cloud), 1) if isinstance(cloud, (int, float)) else None,
        "grid_code": str(entry.get("grid_code") or "").strip() or None,
        "thumbnail_url": thumb,
        "copernicus_browser_url": cop_url,
        "all_weather_capability": False,
    }


def _stac_items_url(
    base_items_url: str,
    lon: float,
    lat: float,
    *,
    pad_deg: float = 0.025,
    lookback_days: int = 90,
    limit: int = 6,
) -> str:
    now = dt.datetime.now(dt.timezone.utc)
    past = now - dt.timedelta(days=lookback_days)
    bbox = f"{lon - pad_deg:.4f},{lat - pad_deg:.4f},{lon + pad_deg:.4f},{lat + pad_deg:.4f}"
    params = {
        "bbox": bbox,
        "datetime": f"{past.strftime('%Y-%m-%dT%H:%M:%SZ')}/{now.strftime('%Y-%m-%dT%H:%M:%SZ')}",
        "limit": limit,
    }
    return f"{base_items_url}?{urllib.parse.urlencode(params)}"


def fetch_sentinel1_for_lake(
    lon: float,
    lat: float,
    *,
    lookback_days: int = 60,
    limit: int = 5,
    timeout: int = 25,
    fetcher: Callable[[str], Any] | None = None,
) -> list[dict[str, Any]]:
    """Query Element84 Earth Search STAC `sentinel-1-grd/items` for a lake point."""
    url = _stac_items_url(
        STAC_S1_ITEMS_URL, lon, lat, pad_deg=0.025, lookback_days=lookback_days, limit=limit
    )
    get_json = fetcher or (lambda u: _http_get_json(u, timeout=timeout, retries=2))
    gj = get_json(url)
    feats = [f for f in (gj.get("features") or []) if isinstance(f, dict)]
    feats.sort(key=lambda f: str((f.get("properties") or {}).get("datetime") or ""), reverse=True)
    return [parse_sentinel1_item(f, lon=lon, lat=lat) for f in feats]


def fetch_sentinel2_for_lake(
    lon: float,
    lat: float,
    *,
    lookback_days: int = 120,
    limit: int = 10,
    timeout: int = 25,
    fetcher: Callable[[str], Any] | None = None,
) -> dict[str, Any] | None:
    """Query Element84 Earth Search STAC `sentinel-2-l2a/items` and pick clearest recent pass."""
    url = _stac_items_url(
        STAC_S2_ITEMS_URL, lon, lat, pad_deg=0.025, lookback_days=lookback_days, limit=limit
    )
    get_json = fetcher or (lambda u: _http_get_json(u, timeout=timeout, retries=2))
    gj = get_json(url)
    feats = [f for f in (gj.get("features") or []) if isinstance(f, dict)]
    if not feats:
        return None
    feats.sort(key=lambda f: str((f.get("properties") or {}).get("datetime") or ""), reverse=True)
    clear = [
        f
        for f in feats
        if float((f.get("properties") or {}).get("eo:cloud_cover") or 100.0) <= 30.0
    ]
    best = clear[0] if clear else min(
        feats, key=lambda f: float((f.get("properties") or {}).get("eo:cloud_cover") or 100.0)
    )
    parsed = parse_sentinel2_item(best, lon=lon, lat=lat)
    latest_props = feats[0].get("properties") or {}
    parsed["latest_pass_datetime"] = latest_props.get("datetime")
    latest_cc = latest_props.get("eo:cloud_cover")
    parsed["latest_pass_cloud_pct"] = round(float(latest_cc), 1) if isinstance(latest_cc, (int, float)) else None
    return parsed


def _load_json_dict(path: str) -> dict[str, Any] | None:
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


def _latest_dt(values: list[str | None]) -> str | None:
    parsed = [d for v in values if v and (d := parse_iso_utc(v)) is not None]
    if not parsed:
        return None
    return format_iso_utc(max(parsed))


def _assemble_payload(
    lakes_out: list[dict[str, Any]],
    envelope: dict[str, Any],
) -> dict[str, Any]:
    s1_dates = [lk["sentinel1"]["datetime"] for lk in lakes_out if isinstance(lk.get("sentinel1"), dict)]
    s2_dates = [lk["sentinel2"]["datetime"] for lk in lakes_out if isinstance(lk.get("sentinel2"), dict)]
    return {
        "provenance": envelope,
        "sentinel1_endpoint": STAC_S1_ITEMS_URL,
        "sentinel2_endpoint": STAC_S2_ITEMS_URL,
        "all_weather_sar_capability": True,
        "n_priority_lakes": len(lakes_out),
        "n_s1_covered": sum(1 for lk in lakes_out if lk.get("sentinel1") is not None),
        "n_s2_covered": sum(1 for lk in lakes_out if lk.get("sentinel2") is not None),
        "latest_s1_datetime": _latest_dt(s1_dates),
        "latest_s2_datetime": _latest_dt(s2_dates),
        "lakes": lakes_out,
        "by_lake_id": {lk["id"]: lk for lk in lakes_out},
    }


def fetch_copernicus_eo(
    offline: bool = False,
    *,
    lakes: tuple[dict[str, Any], ...] = PRIORITY_EO_LAKES,
    cache_sar_path: str = CACHE_EO_SAR,
    cache_s2_path: str = CACHE_STAC_S2,
    timeout: int = 25,
    fetcher: Callable[[str], Any] | None = None,
) -> dict[str, Any]:
    """Fetch or offline-load Sentinel-1 SAR + Sentinel-2 L2A STAC coverage for priority lakes."""
    now_utc = utc_now_iso()
    cached_sar = _load_json_dict(cache_sar_path)
    cached_s2 = _load_json_dict(cache_s2_path) or {}

    if offline:
        if cached_sar and isinstance(cached_sar.get("lakes"), list):
            prev_prov = cached_sar.get("provenance") if isinstance(cached_sar.get("provenance"), dict) else {}
            retrieved = prev_prov.get("retrieved_at_utc") or _file_mtime_iso(cache_sar_path) or now_utc
            lakes_out = list(cached_sar["lakes"])
            obs_utc = _latest_dt(
                [
                    (lk.get("sentinel1") or {}).get("datetime")
                    for lk in lakes_out
                    if isinstance(lk, dict)
                ]
                + [
                    (lk.get("sentinel2") or {}).get("datetime")
                    for lk in lakes_out
                    if isinstance(lk, dict)
                ]
            )
            n_scenes = sum(
                (1 if lk.get("sentinel1") else 0) + (1 if lk.get("sentinel2") else 0)
                for lk in lakes_out
                if isinstance(lk, dict)
            )
            sla = evaluate_envelope_sla(
                {"status": "available", "data_class": "cached", "retrieved_at_utc": retrieved, "sla_hours": COPERNICUS_SLA_HOURS},
                ref_utc=now_utc,
            )
            env = make_envelope(
                source=COPERNICUS_SOURCE_NAME,
                dataset=COPERNICUS_DATASET_NAME,
                data_class="cached",
                retrieved_at_utc=retrieved,
                observation_time_utc=obs_utc,
                valid_until_utc=None,
                status="available" if sla["within_sla"] else "stale",
                fallback_used=True,
                license_ref=COPERNICUS_LICENSE_REF,
                sla_hours=COPERNICUS_SLA_HOURS,
                record_count=n_scenes,
                notes="Loaded Sentinel-1 SAR & Sentinel-2 L2A coverage from cache/eo_sar.json in --offline mode.",
            )
            return _assemble_payload(lakes_out, env)

        # Fallback gracefully to cache/stac_scenes.json (Sentinel-2 optical) + priority-lake coverage metadata
        lakes_out: list[dict[str, Any]] = []
        for spec in lakes:
            lid = spec["id"]
            s2 = _normalize_legacy_s2_entry(cached_s2.get(lid), float(spec["lon"]), float(spec["lat"]))
            lakes_out.append({
                "id": lid,
                "name": spec["name"],
                "lon": round(float(spec["lon"]), 4),
                "lat": round(float(spec["lat"]), 4),
                "z_m": spec.get("z_m"),
                "district": spec.get("district", ""),
                "prov": spec.get("prov", ""),
                "all_weather_capability": True,
                "sentinel1": None,
                "sentinel1_recent": [],
                "sentinel2": s2,
            })

        n_s2 = sum(1 for lk in lakes_out if lk["sentinel2"] is not None)
        obs_utc = _latest_dt([lk["sentinel2"]["datetime"] for lk in lakes_out if lk["sentinel2"]])
        if n_s2 > 0:
            retrieved = _file_mtime_iso(cache_s2_path) or obs_utc or now_utc
            sla = evaluate_envelope_sla(
                {"status": "available", "data_class": "cached", "retrieved_at_utc": retrieved, "sla_hours": COPERNICUS_SLA_HOURS},
                ref_utc=now_utc,
            )
            env = make_envelope(
                source=COPERNICUS_SOURCE_NAME,
                dataset=COPERNICUS_DATASET_NAME,
                data_class="cached",
                retrieved_at_utc=retrieved,
                observation_time_utc=obs_utc,
                valid_until_utc=None,
                status="available" if sla["within_sla"] else "stale",
                fallback_used=True,
                license_ref=COPERNICUS_LICENSE_REF,
                sla_hours=COPERNICUS_SLA_HOURS,
                record_count=n_s2,
                notes=(
                    "Offline fallback to cache/stac_scenes.json (Sentinel-2 L2A coverage for Tsho Rolpa "
                    f"& priority lakes: {n_s2}/{len(lakes_out)}); Sentinel-1 GRD SAR metadata populates on live STAC refresh."
                ),
            )
        else:
            env = make_envelope(
                source=COPERNICUS_SOURCE_NAME,
                dataset=COPERNICUS_DATASET_NAME,
                data_class="unavailable",
                retrieved_at_utc=now_utc,
                observation_time_utc=None,
                valid_until_utc=None,
                status="unavailable",
                fallback_used=True,
                license_ref=COPERNICUS_LICENSE_REF,
                sla_hours=COPERNICUS_SLA_HOURS,
                record_count=0,
                notes="Offline mode and neither cache/eo_sar.json nor cache/stac_scenes.json found.",
            )
        return _assemble_payload(lakes_out, env)

    # Live STAC refresh mode
    cached_by_id: dict[str, dict[str, Any]] = {}
    if cached_sar and isinstance(cached_sar.get("lakes"), list):
        cached_by_id = {
            str(lk["id"]): lk for lk in cached_sar["lakes"] if isinstance(lk, dict) and lk.get("id")
        }

    lakes_out = []
    live_s1_hits = 0
    live_s2_hits = 0
    errors: list[str] = []

    for spec in lakes:
        lid = spec["id"]
        lon, lat = float(spec["lon"]), float(spec["lat"])
        prev_lake = cached_by_id.get(lid) or {}

        s1_list: list[dict[str, Any]] = list(prev_lake.get("sentinel1_recent") or [])
        s1_latest: dict[str, Any] | None = prev_lake.get("sentinel1")
        try:
            fetched_s1 = fetch_sentinel1_for_lake(lon, lat, timeout=timeout, fetcher=fetcher)
            if fetched_s1:
                s1_list = fetched_s1
                s1_latest = fetched_s1[0]
                live_s1_hits += 1
        except Exception as exc:
            errors.append(f"S1:{spec['name']} ({exc})")

        s2_latest: dict[str, Any] | None = prev_lake.get("sentinel2") or _normalize_legacy_s2_entry(
            cached_s2.get(lid), lon, lat
        )
        try:
            fetched_s2 = fetch_sentinel2_for_lake(lon, lat, timeout=timeout, fetcher=fetcher)
            if fetched_s2:
                s2_latest = fetched_s2
                live_s2_hits += 1
        except Exception as exc:
            errors.append(f"S2:{spec['name']} ({exc})")

        lakes_out.append({
            "id": lid,
            "name": spec["name"],
            "lon": round(lon, 4),
            "lat": round(lat, 4),
            "z_m": spec.get("z_m"),
            "district": spec.get("district", ""),
            "prov": spec.get("prov", ""),
            "all_weather_capability": True,
            "sentinel1": s1_latest,
            "sentinel1_recent": s1_list,
            "sentinel2": s2_latest,
        })

    any_live = (live_s1_hits + live_s2_hits) > 0
    n_scenes = sum((1 if lk["sentinel1"] else 0) + (1 if lk["sentinel2"] else 0) for lk in lakes_out)
    obs_utc = _latest_dt(
        [lk["sentinel1"]["datetime"] for lk in lakes_out if lk["sentinel1"]]
        + [lk["sentinel2"]["datetime"] for lk in lakes_out if lk["sentinel2"]]
    )

    if any_live:
        env = make_envelope(
            source=COPERNICUS_SOURCE_NAME,
            dataset=COPERNICUS_DATASET_NAME,
            data_class="live_observation",
            retrieved_at_utc=now_utc,
            observation_time_utc=obs_utc,
            valid_until_utc=None,
            status="available",
            fallback_used=bool(errors),
            license_ref=COPERNICUS_LICENSE_REF,
            sla_hours=COPERNICUS_SLA_HOURS,
            record_count=n_scenes,
            notes=(
                f"Element84 STAC live refresh: S1 GRD={live_s1_hits}/{len(lakes_out)}, "
                f"S2 L2A={live_s2_hits}/{len(lakes_out)} priority lakes."
                + (f" Partial errors: {len(errors)}." if errors else "")
            ),
        )
        payload = _assemble_payload(lakes_out, env)
        atomic_write_json(cache_sar_path, payload)
        return payload

    # Zero live hits -> graceful fallback
    data_class = "cached" if n_scenes > 0 else "unavailable"
    status = "stale" if n_scenes > 0 else "unavailable"
    env = make_envelope(
        source=COPERNICUS_SOURCE_NAME,
        dataset=COPERNICUS_DATASET_NAME,
        data_class=data_class,
        retrieved_at_utc=now_utc,
        observation_time_utc=obs_utc,
        valid_until_utc=None,
        status=status,
        fallback_used=True,
        license_ref=COPERNICUS_LICENSE_REF,
        sla_hours=COPERNICUS_SLA_HOURS,
        record_count=n_scenes,
        notes=f"Element84 STAC live refresh failed ({len(errors)} error(s)); using fallback metadata.",
    )
    return _assemble_payload(lakes_out, env)


def get_provenance(
    offline: bool = True,
    cache_sar_path: str = CACHE_EO_SAR,
    cache_s2_path: str = CACHE_STAC_S2,
) -> dict[str, Any]:
    """Return the canonical ProvenanceEnvelope for Copernicus Sentinel-1/2 EO STAC."""
    return fetch_copernicus_eo(
        offline=offline, cache_sar_path=cache_sar_path, cache_s2_path=cache_s2_path
    )["provenance"]


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="Nepal TRĀYA Copernicus Sentinel-1 SAR & Sentinel-2 STAC client")
    ap.add_argument("--offline", action="store_true", help="Zero network calls; load cache/eo_sar.json or cache/stac_scenes.json")
    ap.add_argument("--refresh", action="store_true", help="Live query Element84 Earth Search STAC")
    args = ap.parse_args(argv)

    res = fetch_copernicus_eo(offline=args.offline)
    prov = res["provenance"]
    print(
        f"[copernicus] status={prov['status']} class={prov['data_class']} "
        f"lakes={res['n_priority_lakes']} s1={res['n_s1_covered']} s2={res['n_s2_covered']}"
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
