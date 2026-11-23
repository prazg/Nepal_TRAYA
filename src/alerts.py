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

# Regional Hindu Kush Himalaya bbox for GDACS; Nepal-focused bbox for USGS FDSN
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


def fetch_usgs_recent_nepal(days: int = 7, min_mag: float = 2.5) -> list[dict[str, Any]]:
    """Fetch recent Nepal-region earthquakes (M>=2.5 past 7d) from USGS FDSN."""
    url = usgs_nepal_fdsn_url(days=days, min_mag=min_mag)
    raw = _http_request(url, timeout=35, retries=3)
    gj = json.loads(raw.decode("utf-8"))
    out: list[dict[str, Any]] = []
    for f in gj.get("features") or []:
        p = f.get("properties") or {}
        c = (f.get("geometry") or {}).get("coordinates") or []
        if len(c) < 2:
            continue
        out.append({
            "id": str(f.get("id") or ""),
            "time": p.get("time"),
            "mag": round(float(p["mag"]), 1) if p.get("mag") is not None else None,
            "place": str(p.get("place") or "").strip(),
            "depth_km": round(float(c[2]), 1) if len(c) > 2 and c[2] is not None else None,
            "lon": round(float(c[0]), 4),
            "lat": round(float(c[1]), 4),
            "url": _safe_url(p.get("url")),
            "in_nepal": _in_bbox(float(c[0]), float(c[1]), NEPAL_BBOX),
        })
    return out


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

    if offline:
        updated_utc = cached.get("updated_utc") or now_utc
        events = list(cached.get("events") or [])
        recent_quakes: list[dict[str, Any]] = list(cached.get("recent_quakes") or [])
        usgs_updated_utc = cached.get("usgs_updated_utc") or updated_utc
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
            recent_quakes = fetch_usgs_recent_nepal(days=7, min_mag=2.5)
            usgs_updated_utc = now_utc
            any_live = True
        except Exception as exc:
            print(f"  [alerts] USGS Nepal FDSN fetch failed ({exc})", file=sys.stderr)
            recent_quakes = list(cached.get("recent_quakes") or [])
            usgs_updated_utc = cached.get("usgs_updated_utc") or updated_utc
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
            "window_days": 7,
            "min_mag": 2.5,
            "bbox": list(USGS_NEPAL_BBOX),
            "fdsn_query_template": (
                f"{USGS_FDSN_URL}?format=geojson&minmagnitude=2.5"
                f"&minlatitude={USGS_NEPAL_BBOX[1]}&maxlatitude={USGS_NEPAL_BBOX[3]}"
                f"&minlongitude={USGS_NEPAL_BBOX[0]}&maxlongitude={USGS_NEPAL_BBOX[2]}"
                "&orderby=time"
            ),
            "n_events": len(recent_quakes),
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
