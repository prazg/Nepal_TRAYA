"""
Regional multi-hazard alerts (UN OCHA / EC JRC GDACS), Nepal-bbox USGS FDSN
recent seismicity (M>=2.5 past 7 days), and Copernicus Sentinel-2 L2A STAC
scene index (Element84 Earth Search).

Pure Python 3.12 standard library only (zero third-party dependencies).
"""
from __future__ import annotations

import argparse
import datetime as dt
import json
import math
import os
import sys
import tempfile
import time
import urllib.parse
import urllib.request
import xml.etree.ElementTree as ET
from typing import Any

SRC_DIR = os.path.dirname(os.path.abspath(__file__))
if SRC_DIR not in sys.path:
    sys.path.insert(0, SRC_DIR)

import config as C

USER_AGENT = "Nepal-TRAYA/2.1 (+https://prazg.github.io/Nepal_TRAYA/)"

GDACS_API_URL = "https://www.gdacs.org/gdacsapi/api/events/geteventlist/SEARCH"
GDACS_RSS_URL = "https://www.gdacs.org/xml/rss.xml"
STAC_SEARCH_URL = "https://earth-search.aws.element84.com/v1/search"
USGS_FDSN_URL = C.USGS_QUERY
USGS_CDN_BASE = "https://earthquake.usgs.gov/earthquakes/feed/v1.0/summary"
EMSC_FDSN_URL = "https://www.seismicportal.eu/fdsnws/event/1/query"

# Regional Hindu Kush Himalaya bbox for GDACS; Nepal-focused bbox for USGS / EMSC FDSN
HKH_BBOX = (73.0, 21.0, 95.0, 35.5)
NEPAL_BBOX = C.NEPAL_BBOX
USGS_NEPAL_BBOX = (77.9, 24.2, 90.3, 32.6)  # minlon, minlat, maxlon, maxlat

CACHE_GDACS = os.path.join(C.CACHE, "gdacs_alerts.json")
CACHE_STAC = os.path.join(C.CACHE, "stac_scenes.json")
CACHE_USGS = os.path.join(C.CACHE, "usgs_catalogue.json")
CACHE_HYDROMET = os.path.join(C.CACHE, "hydromet_weekly.json")
LEGACY_JS = os.path.join(C.DATA, "gdacs_alerts.js")
OUT_JSON = os.path.join(C.DATA, "gdacs_alerts.json")


def _safe_url(url: Any) -> str:
    s = str(url or "").strip()
    if s.startswith("https://") or s.startswith("http://"):
        return s
    return ""


def _in_bbox(lon: float, lat: float, bbox: tuple[float, float, float, float]) -> bool:
    return bbox[0] <= lon <= bbox[2] and bbox[1] <= lat <= bbox[3]


def _atomic_write_json(path: str, obj: Any) -> None:
    os.makedirs(os.path.dirname(path), exist_ok=True)
    fd, tmp_path = tempfile.mkstemp(dir=os.path.dirname(path), prefix=".tmp_", suffix=".json")
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


def _http_request(url: str, data: bytes | None = None, headers: dict[str, str] | None = None, timeout: int = 35, retries: int = 3) -> bytes:
    hdrs = {"User-Agent": USER_AGENT}
    if headers:
        hdrs.update(headers)
    last_exc: Exception | None = None
    for attempt in range(retries):
        try:
            req = urllib.request.Request(url, data=data, headers=hdrs)
            with urllib.request.urlopen(req, timeout=timeout) as resp:
                return resp.read()
        except Exception as exc:
            last_exc = exc
            if attempt < retries - 1:
                time.sleep(2.0 * (attempt + 1))
    raise RuntimeError(f"Request {url} failed after {retries} attempts: {last_exc}")


def _haversine_km(lon1: float, lat1: float, lon2: float, lat2: float) -> float:
    r = 6371.0088
    p1, p2 = math.radians(lat1), math.radians(lat2)
    dp = math.radians(lat2 - lat1)
    dl = math.radians(lon2 - lon1)
    a = math.sin(dp / 2.0) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(dl / 2.0) ** 2
    return 2.0 * r * math.asin(min(1.0, math.sqrt(max(0.0, a))))


def _iso_to_epoch_ms(val: Any) -> int | None:
    if isinstance(val, (int, float)) and not isinstance(val, bool):
        v = float(val)
        return int(v if v > 1e11 else v * 1000.0)
    s = str(val or "").strip()
    if not s:
        return None
    if s.endswith("Z"):
        s = s[:-1] + "+00:00"
    try:
        parsed = dt.datetime.fromisoformat(s)
        if parsed.tzinfo is None:
            parsed = parsed.replace(tzinfo=dt.timezone.utc)
        return int(parsed.timestamp() * 1000.0)
    except ValueError:
        return None


def _title_case_region(region: str) -> str:
    s = str(region or "").strip()
    if not s:
        return "Nepal Region"
    if s.isupper():
        words = []
        for part in s.split():
            if part in ("OF", "AND", "IN", "NEAR"):
                words.append(part.lower())
            else:
                words.append("-".join(seg.capitalize() for seg in part.split("-")))
        return " ".join(words).replace("Reg.", "Region")
    return s


def usgs_nepal_fdsn_url(days: int = 7, min_mag: float = 2.5) -> str:
    """Build the Nepal-bbox USGS FDSN query URL (avoids 2 MB global feeds)."""
    start = (dt.datetime.now(dt.timezone.utc) - dt.timedelta(days=days)).strftime("%Y-%m-%dT%H:%M:%SZ")
    params = {
        "format": "geojson",
        "starttime": start,
        "minmagnitude": min_mag,
        "minlatitude": USGS_NEPAL_BBOX[1],
        "maxlatitude": USGS_NEPAL_BBOX[3],
        "minlongitude": USGS_NEPAL_BBOX[0],
        "maxlongitude": USGS_NEPAL_BBOX[2],
        "orderby": "time",
        "limit": 200,
    }
    return f"{USGS_FDSN_URL}?{urllib.parse.urlencode(params)}"


def emsc_nepal_fdsn_url(days: int = 30, min_mag: float = 2.5) -> str:
    """Build the Nepal-bbox EMSC SeismicPortal FDSN JSON query URL."""
    start = (dt.datetime.now(dt.timezone.utc) - dt.timedelta(days=days)).strftime("%Y-%m-%dT%H:%M:%SZ")
    params = {
        "format": "json",
        "start": start,
        "minmag": min_mag,
        "minlat": USGS_NEPAL_BBOX[1],
        "maxlat": USGS_NEPAL_BBOX[3],
        "minlon": USGS_NEPAL_BBOX[0],
        "maxlon": USGS_NEPAL_BBOX[2],
        "limit": 200,
    }
    return f"{EMSC_FDSN_URL}?{urllib.parse.urlencode(params)}"


def normalize_usgs_feature(f: dict[str, Any]) -> dict[str, Any] | None:
    p = f.get("properties") or {}
    c = (f.get("geometry") or {}).get("coordinates") or []
    if len(c) < 2:
        return None
    try:
        lon, lat = float(c[0]), float(c[1])
    except (TypeError, ValueError):
        return None
    if not _in_bbox(lon, lat, USGS_NEPAL_BBOX):
        return None
    t_ms = _iso_to_epoch_ms(p.get("time"))
    mag = round(float(p["mag"]), 1) if p.get("mag") is not None else None
    depth = round(abs(float(c[2])), 1) if len(c) > 2 and c[2] is not None else None
    return {
        "id": str(f.get("id") or ""),
        "time": t_ms,
        "mag": mag,
        "place": str(p.get("place") or "Nepal region").strip(),
        "depth_km": depth,
        "lon": round(lon, 4),
        "lat": round(lat, 4),
        "url": _safe_url(p.get("url")),
        "source": "USGS",
        "sources": ["USGS"],
        "agency": str(p.get("net") or "USGS").upper(),
        "in_nepal": _in_bbox(lon, lat, NEPAL_BBOX),
    }


def normalize_emsc_feature(f: dict[str, Any]) -> dict[str, Any] | None:
    """Normalize an EMSC SeismicPortal GeoJSON feature (note: z coordinate is -depth_km!)."""
    p = f.get("properties") or {}
    c = (f.get("geometry") or {}).get("coordinates") or []
    lon_raw = p.get("lon") if p.get("lon") is not None else (c[0] if len(c) >= 2 else None)
    lat_raw = p.get("lat") if p.get("lat") is not None else (c[1] if len(c) >= 2 else None)
    if lon_raw is None or lat_raw is None:
        return None
    try:
        lon, lat = float(lon_raw), float(lat_raw)
    except (TypeError, ValueError):
        return None
    if not _in_bbox(lon, lat, USGS_NEPAL_BBOX):
        return None
    t_ms = _iso_to_epoch_ms(p.get("time"))
    mag = round(float(p["mag"]), 1) if p.get("mag") is not None else None
    raw_depth = p.get("depth") if p.get("depth") is not None else (c[2] if len(c) > 2 else None)
    depth = round(abs(float(raw_depth)), 1) if raw_depth is not None else None
    src_id = str(p.get("source_id") or "").strip()
    emsc_url = (
        f"https://www.emsc-csem.org/Earthquake_information/earthquake.php?id={urllib.parse.quote(src_id)}"
        if src_id
        else ""
    )
    auth = str(p.get("auth") or "EMSC").strip().upper()
    return {
        "id": f"emsc_{f.get('id') or p.get('unid') or src_id}",
        "time": t_ms,
        "mag": mag,
        "place": _title_case_region(str(p.get("flynn_region") or "Nepal Region")),
        "depth_km": depth,
        "lon": round(lon, 4),
        "lat": round(lat, 4),
        "url": _safe_url(emsc_url),
        "source": "EMSC",
        "sources": ["EMSC"],
        "agency": auth,
        "in_nepal": _in_bbox(lon, lat, NEPAL_BBOX),
    }


def merge_seismic_events(
    usgs_events: list[dict[str, Any]],
    emsc_events: list[dict[str, Any]],
    *,
    max_dt_sec: float = 90.0,
    max_km: float = 65.0,
) -> list[dict[str, Any]]:
    """Deduplicate cross-agency USGS + EMSC earthquakes within 90 s & 65 km.

    Prefers USGS as canonical record when both report the same event (retaining
    USGS event page & ShakeMap linkage) while tagging `sources: ["USGS", "EMSC"]`,
    and preserves all regional EMSC/NDI detections not in the USGS feed.
    """
    merged: list[dict[str, Any]] = [dict(e) for e in usgs_events]
    for ev in merged:
        ev.setdefault("source", "USGS")
        ev.setdefault("sources", [ev["source"]])

    for em in emsc_events:
        em_t = em.get("time")
        em_lon = em.get("lon")
        em_lat = em.get("lat")
        matched = False
        for existing in merged:
            ex_t = existing.get("time")
            ex_lon = existing.get("lon")
            ex_lat = existing.get("lat")
            if None in (em_t, ex_t, em_lon, ex_lon, em_lat, ex_lat):
                continue
            if abs(float(em_t) - float(ex_t)) / 1000.0 <= max_dt_sec:
                if _haversine_km(float(em_lon), float(em_lat), float(ex_lon), float(ex_lat)) <= max_km:
                    srcs = list(existing.get("sources") or [existing.get("source") or "USGS"])
                    if "EMSC" not in srcs:
                        srcs.append("EMSC")
                    existing["sources"] = srcs
                    if not existing.get("url") and em.get("url"):
                        existing["url"] = em["url"]
                    matched = True
                    break
        if not matched:
            merged.append(dict(em))

    merged.sort(key=lambda e: int(e.get("time") or 0), reverse=True)
    return merged


def fetch_gdacs_alerts(window_days: int = 90) -> list[dict[str, Any]]:
    """Fetch regional GDACS alerts via JSON API with XML RSS fallback."""
    now = dt.datetime.now(dt.timezone.utc)
    from_date = (now - dt.timedelta(days=window_days)).strftime("%Y-%m-%d")
    to_date = now.strftime("%Y-%m-%d")
    params = {
        "eventlist": "EQ,FL,TC,VO,DR,WF",
        "fromDate": from_date,
        "toDate": to_date,
        "alertlevel": "Green;Orange;Red",
    }
    try:
        raw = _http_request(f"{GDACS_API_URL}?{urllib.parse.urlencode(params)}", timeout=35, retries=2)
        gj = json.loads(raw.decode("utf-8"))
        events: list[dict[str, Any]] = []
        for f in gj.get("features") or []:
            geom = f.get("geometry") or {}
            coords = geom.get("coordinates") or []
            if len(coords) < 2:
                continue
            lon, lat = float(coords[0]), float(coords[1])
            if not _in_bbox(lon, lat, HKH_BBOX):
                continue
            p = f.get("properties") or {}
            ev_type = str(p.get("eventtype") or "").strip()
            ev_id = str(p.get("eventid") or "").strip()
            country = str(p.get("country") or "").strip()
            in_np = _in_bbox(lon, lat, NEPAL_BBOX) or ("nepal" in country.lower())
            url_obj = p.get("url")
            report_url = url_obj.get("report") if isinstance(url_obj, dict) else str(url_obj or "")
            events.append({
                "id": f"{ev_type}_{ev_id}" if ev_type and ev_id else str(p.get("name") or ""),
                "type": ev_type,
                "name": str(p.get("name") or p.get("htmldescription") or "GDACS event").strip(),
                "country": country,
                "alert_level": str(p.get("alertlevel") or "Green").strip(),
                "alert_score": p.get("alertscore"),
                "severity_text": str((p.get("severitydata") or {}).get("severitytext") or p.get("description") or "").strip(),
                "from_date": str(p.get("fromdate") or "")[:10],
                "to_date": str(p.get("todate") or "")[:10],
                "lon": round(lon, 4),
                "lat": round(lat, 4),
                "in_nepal": bool(in_np),
                "url": _safe_url(report_url),
            })
        return events
    except Exception:
        # Fallback to GDACS XML RSS feed
        raw_xml = _http_request(GDACS_RSS_URL, timeout=35, retries=2)
        root = ET.fromstring(raw_xml)
        ns = {
            "geo": "http://www.w3.org/2003/01/geo/wgs84_pos#",
            "gdacs": "http://www.gdacs.org",
        }
        events = []
        for item in root.findall(".//item"):
            lat_el = item.find("geo:lat", ns)
            lon_el = item.find("geo:long", ns)
            if lat_el is None or lon_el is None:
                continue
            try:
                lat = float(lat_el.text or "")
                lon = float(lon_el.text or "")
            except ValueError:
                continue
            if not _in_bbox(lon, lat, HKH_BBOX):
                continue
            ev_type = (item.findtext("gdacs:eventtype", "", ns) or "").strip()
            ev_id = (item.findtext("gdacs:eventid", "", ns) or "").strip()
            country = (item.findtext("gdacs:country", "", ns) or "").strip()
            in_np = _in_bbox(lon, lat, NEPAL_BBOX) or ("nepal" in country.lower())
            events.append({
                "id": f"{ev_type}_{ev_id}" if ev_type and ev_id else (item.findtext("guid") or ""),
                "type": ev_type,
                "name": (item.findtext("title") or "GDACS alert").strip(),
                "country": country,
                "alert_level": (item.findtext("gdacs:alertlevel", "Green", ns) or "Green").strip(),
                "alert_score": None,
                "severity_text": (item.findtext("description") or "").strip()[:240],
                "from_date": (item.findtext("gdacs:fromdate", "", ns) or "")[:10],
                "to_date": (item.findtext("gdacs:todate", "", ns) or "")[:10],
                "lon": round(lon, 4),
                "lat": round(lat, 4),
                "in_nepal": bool(in_np),
                "url": _safe_url(item.findtext("link")),
            })
        return events


def fetch_usgs_cdn_nepal(days: int = 30, min_mag: float = 2.5) -> list[dict[str, Any]]:
    """Fallback to USGS edge-cached GeoJSON summary feeds filtered to Nepal bbox."""
    feed = "2.5_day.geojson" if days <= 1 else ("2.5_week.geojson" if days <= 7 else "2.5_month.geojson")
    raw = _http_request(f"{USGS_CDN_BASE}/{feed}", timeout=25, retries=2)
    gj = json.loads(raw.decode("utf-8"))
    cutoff_ms = int((dt.datetime.now(dt.timezone.utc) - dt.timedelta(days=days)).timestamp() * 1000.0)
    out: list[dict[str, Any]] = []
    for f in gj.get("features") or []:
        ev = normalize_usgs_feature(f)
        if not ev:
            continue
        if ev.get("mag") is not None and float(ev["mag"]) < min_mag:
            continue
        if ev.get("time") is not None and int(ev["time"]) < cutoff_ms:
            continue
        out.append(ev)
    return out


def fetch_emsc_recent_nepal(days: int = 30, min_mag: float = 2.5) -> list[dict[str, Any]]:
    """Fetch recent Nepal-region earthquakes from EMSC SeismicPortal FDSN."""
    url = emsc_nepal_fdsn_url(days=days, min_mag=min_mag)
    raw = _http_request(url, timeout=25, retries=2)
    if not raw.strip():
        return []
    gj = json.loads(raw.decode("utf-8"))
    out: list[dict[str, Any]] = []
    for f in gj.get("features") or []:
        ev = normalize_emsc_feature(f)
        if ev:
            out.append(ev)
    return out


def fetch_usgs_recent_nepal(days: int = 30, min_mag: float = 2.5) -> list[dict[str, Any]]:
    """Fetch recent Nepal-region earthquakes from USGS (FDSN -> CDN fallback) + EMSC fusion."""
    usgs_events: list[dict[str, Any]] = []
    emsc_events: list[dict[str, Any]] = []
    usgs_err: Exception | None = None
    emsc_err: Exception | None = None

    try:
        url = usgs_nepal_fdsn_url(days=days, min_mag=min_mag)
        raw = _http_request(url, timeout=25, retries=2)
        gj = json.loads(raw.decode("utf-8"))
        for f in gj.get("features") or []:
            ev = normalize_usgs_feature(f)
            if ev:
                usgs_events.append(ev)
    except Exception as exc:
        usgs_err = exc
        try:
            usgs_events = fetch_usgs_cdn_nepal(days=days, min_mag=min_mag)
            usgs_err = None
        except Exception as cdn_exc:
            usgs_err = cdn_exc

    try:
        emsc_events = fetch_emsc_recent_nepal(days=days, min_mag=min_mag)
    except Exception as exc:
        emsc_err = exc

    if usgs_err is not None and emsc_err is not None:
        raise RuntimeError(f"Both USGS ({usgs_err}) and EMSC ({emsc_err}) seismic queries failed")

    return merge_seismic_events(usgs_events, emsc_events)


def fetch_stac_scene_for_point(lon: float, lat: float, lookback_days: int = 120) -> dict[str, Any] | None:
    """Query Element84 Earth Search STAC for clearest recent Sentinel-2 L2A scene."""
    now = dt.datetime.now(dt.timezone.utc)
    past = now - dt.timedelta(days=lookback_days)
    body = json.dumps({
        "collections": ["sentinel-2-l2a"],
        "bbox": [round(lon - 0.025, 4), round(lat - 0.025, 4), round(lon + 0.025, 4), round(lat + 0.025, 4)],
        "datetime": f"{past.strftime('%Y-%m-%dT%H:%M:%SZ')}/{now.strftime('%Y-%m-%dT%H:%M:%SZ')}",
        "limit": 12,
    }).encode("utf-8")
    raw = _http_request(STAC_SEARCH_URL, data=body, headers={"Content-Type": "application/json"}, timeout=30, retries=2)
    gj = json.loads(raw.decode("utf-8"))
    feats = gj.get("features") or []
    if not feats:
        return None
    feats.sort(key=lambda f: (f.get("properties") or {}).get("datetime") or "", reverse=True)
    clear = [f for f in feats if float((f.get("properties") or {}).get("eo:cloud_cover") or 100.0) <= 30.0]
    best = clear[0] if clear else min(feats, key=lambda f: float((f.get("properties") or {}).get("eo:cloud_cover") or 100.0))
    bp = best.get("properties") or {}
    assets = best.get("assets") or {}
    thumb = (assets.get("thumbnail") or {}).get("href") or (assets.get("rendered_preview") or {}).get("href")
    dt_str = str(bp.get("datetime") or "")
    day = dt_str[:10]
    cop_url = (
        f"https://browser.dataspace.copernicus.eu/?zoom=14&lat={lat:.4f}&lng={lon:.4f}"
        f"&datasetId=S2_L2A_CDAS"
        + (f"&toTime={day}T23%3A59%3A59.999Z" if day else "")
    )
    latest_p = feats[0].get("properties") or {}
    return {
        "scene_id": best.get("id"),
        "datetime": dt_str,
        "cloud_cover_pct": round(float(bp.get("eo:cloud_cover") or 0.0), 1),
        "platform": bp.get("platform") or "",
        "grid_code": bp.get("grid:code") or "",
        "thumbnail": _safe_url(thumb) or None,
        "latest_pass_datetime": latest_p.get("datetime"),
        "latest_pass_cloud_pct": round(float(latest_p.get("eo:cloud_cover") or 0.0), 1),
        "copernicus_browser_url": cop_url,
    }


def refresh_stac_scenes(offline: bool = False) -> dict[str, Any]:
    """Load or live-refresh Element84 Sentinel-2 L2A STAC cache for priority lakes."""
    cached: dict[str, Any] = {}
    if os.path.exists(CACHE_STAC):
        with open(CACHE_STAC, encoding="utf-8") as fh:
            cached = json.load(fh)
    if offline:
        return cached
    if not os.path.exists(CACHE_HYDROMET):
        return cached
    with open(CACHE_HYDROMET, encoding="utf-8") as fh:
        hm = json.load(fh)
    updated = dict(cached)
    changed = False
    for lk in hm.get("priority_lakes") or []:
        lid = lk.get("id")
        if not lid or lk.get("lon") is None or lk.get("lat") is None:
            continue
        try:
            sc = fetch_stac_scene_for_point(float(lk["lon"]), float(lk["lat"]))
            if sc:
                updated[lid] = sc
                changed = True
        except Exception as exc:
            print(f"  [alerts] STAC refresh skipped for {lid}: {exc}", file=sys.stderr)
    if changed:
        _atomic_write_json(CACHE_STAC, updated)
    return updated


def _load_cached_gdacs() -> dict[str, Any]:
    if os.path.exists(CACHE_GDACS):
        with open(CACHE_GDACS, encoding="utf-8") as fh:
            return json.load(fh)
    if os.path.exists(LEGACY_JS):
        txt = open(LEGACY_JS, encoding="utf-8").read()
        return json.loads(txt.split("=", 1)[1].rsplit(";", 1)[0])
    return {}


def build_alerts(offline: bool = False, out_path: str = OUT_JSON) -> dict[str, Any]:
    """Build `data/gdacs_alerts.json` with GDACS alerts, USGS Nepal bbox quakes & STAC summary."""
    cached = _load_cached_gdacs()
    now_utc = dt.datetime.now(dt.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    any_live = False

    cached_usgs_block = cached.get("usgs_recent") if isinstance(cached.get("usgs_recent"), dict) else {}
    cached_quakes = list(cached_usgs_block.get("events") or cached.get("recent_quakes") or [])
    cached_usgs_utc = cached_usgs_block.get("updated_utc") or cached.get("usgs_updated_utc") or cached.get("updated_utc") or now_utc

    if offline:
        updated_utc = cached.get("updated_utc") or now_utc
        events = list(cached.get("events") or [])
        recent_quakes: list[dict[str, Any]] = cached_quakes
        usgs_updated_utc = cached_usgs_utc
        stac_scenes = refresh_stac_scenes(offline=True)
    else:
        updated_utc = now_utc
        try:
            events = fetch_gdacs_alerts(window_days=90)
            any_live = True
        except Exception as exc:
            print(f"  [alerts] GDACS fetch failed ({exc}); keeping cached alerts", file=sys.stderr)
            events = list(cached.get("events") or [])
            updated_utc = cached.get("updated_utc") or now_utc
        try:
            recent_quakes = fetch_usgs_recent_nepal(days=30, min_mag=2.5)
            usgs_updated_utc = now_utc
            any_live = True
        except Exception as exc:
            print(f"  [alerts] USGS + EMSC Nepal seismic fetch failed ({exc}); keeping cached snapshot", file=sys.stderr)
            recent_quakes = cached_quakes
            usgs_updated_utc = cached_usgs_utc
        stac_scenes = refresh_stac_scenes(offline=False)

    # Normalize & sanitize event URLs
    clean_events: list[dict[str, Any]] = []
    for e in events:
        if not isinstance(e, dict):
            continue
        ce = dict(e)
        ce["url"] = _safe_url(ce.get("url"))
        if ce.get("lon") is not None:
            ce["lon"] = round(float(ce["lon"]), 4)
        if ce.get("lat") is not None:
            ce["lat"] = round(float(ce["lat"]), 4)
        ce["in_nepal"] = bool(
            ce.get("in_nepal")
            or ("nepal" in str(ce.get("country") or "").lower())
            or (
                ce.get("lon") is not None
                and ce.get("lat") is not None
                and _in_bbox(float(ce["lon"]), float(ce["lat"]), NEPAL_BBOX)
            )
        )
        clean_events.append(ce)

    stac_dates = sorted(
        str(v.get("datetime") or "")
        for v in stac_scenes.values()
        if isinstance(v, dict) and v.get("datetime")
    )

    cutoff_7d_ms = int((dt.datetime.now(dt.timezone.utc) - dt.timedelta(days=7)).timestamp() * 1000.0)
    sources_active = sorted({
        s
        for e in recent_quakes
        for s in (e.get("sources") or ([e.get("source")] if e.get("source") else ["USGS"]))
    })

    payload = {
        "updated_utc": updated_utc,
        "mode": "offline" if offline else ("live" if any_live else "cached_fallback"),
        "window_days": int(cached.get("window_days") or 90),
        "bbox": list(HKH_BBOX),
        "n_events": len(clean_events),
        "n_in_nepal": sum(1 for e in clean_events if e["in_nepal"]),
        "events": clean_events,
        "usgs_recent": {
            "updated_utc": usgs_updated_utc,
            "window_days": 30,
            "min_mag": 2.5,
            "bbox": list(USGS_NEPAL_BBOX),
            "sources_active": sources_active or ["USGS", "EMSC"],
            "fdsn_query_template": (
                f"{USGS_FDSN_URL}?format=geojson&minmagnitude=2.5"
                f"&minlatitude={USGS_NEPAL_BBOX[1]}&maxlatitude={USGS_NEPAL_BBOX[3]}"
                f"&minlongitude={USGS_NEPAL_BBOX[0]}&maxlongitude={USGS_NEPAL_BBOX[2]}"
                "&orderby=time"
            ),
            "emsc_query_template": (
                f"{EMSC_FDSN_URL}?format=json&minmag=2.5"
                f"&minlat={USGS_NEPAL_BBOX[1]}&maxlat={USGS_NEPAL_BBOX[3]}"
                f"&minlon={USGS_NEPAL_BBOX[0]}&maxlon={USGS_NEPAL_BBOX[2]}"
            ),
            "n_events": len(recent_quakes),
            "n_events_7d": sum(1 for e in recent_quakes if int(e.get("time") or 0) >= cutoff_7d_ms),
            "events": recent_quakes,
        },
        "stac_summary": {
            "n_priority_scenes": len(stac_scenes),
            "latest_scene_datetime": stac_dates[-1] if stac_dates else None,
            "endpoint": STAC_SEARCH_URL,
        },
    }

    _atomic_write_json(out_path, payload)
    if any_live:
        _atomic_write_json(CACHE_GDACS, payload)
    return payload


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="Nepal TRĀYA GDACS, USGS FDSN & STAC alerts builder")
    ap.add_argument("--offline", action="store_true", help="Zero network calls; normalize cached data")
    ap.add_argument("--refresh", action="store_true", help="Live fetch GDACS, USGS FDSN & STAC")
    args = ap.parse_args(argv)

    res = build_alerts(offline=args.offline)
    print(
        f"[alerts] wrote {OUT_JSON}: gdacs={res['n_events']} (in_nepal={res['n_in_nepal']}), "
        f"usgs_7d={res['usgs_recent']['n_events']}, stac_scenes={res['stac_summary']['n_priority_scenes']}"
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
