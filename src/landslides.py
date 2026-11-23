"""
Documented landslide inventory (NASA COOLR / Global Landslide Catalog +
OpenStreetMap mapped landslide scars) and rainfall I-D threshold metadata.

Key scientific & honesty safeguards:
  * Reports exact `n_nasa_coolr`, `n_osm`, and `nasa_coolr_available` boolean
    plus an explicit `coverage_note`, so the interface NEVER claims NASA COOLR
    records are displayed when `n_nasa_coolr == 0`.
  * Live mode queries the NASA COOLR ArcGIS FeatureServer with timeout and
    exponential backoff, merging with OpenStreetMap mapped landslide scars.
  * Offline mode normalizes `cache/landslides.json` (fallback `data/landslides.js`)
    without any network calls and writes `data/landslides.json` atomically.

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
from typing import Any

SRC_DIR = os.path.dirname(os.path.abspath(__file__))
if SRC_DIR not in sys.path:
    sys.path.insert(0, SRC_DIR)

import config as C

USER_AGENT = "Nepal-TRAYA/2.1 (+https://prazg.github.io/Nepal_TRAYA/)"
CACHE_JSON = os.path.join(C.CACHE, "landslides.json")
LEGACY_JS = os.path.join(C.DATA, "landslides.js")
OUT_JSON = os.path.join(C.DATA, "landslides.json")

# NASA COOLR / Global Landslide Catalog ArcGIS FeatureServer endpoints
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


def _safe_url(url: Any) -> str:
    s = str(url or "").strip()
    if s.startswith("https://") or s.startswith("http://"):
        return s
    return ""


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


def _to_int_or_none(v: Any) -> int | None:
    if v is None or v == "":
        return None
    try:
        f = float(v)
        return int(round(f)) if math.isfinite(f) and f >= 0 else None
    except (TypeError, ValueError):
        return None


def _epoch_ms_to_iso_date(v: Any) -> str | None:
    if v is None or v == "":
        return None
    if isinstance(v, (int, float)) and math.isfinite(v):
        try:
            return dt.datetime.fromtimestamp(v / 1000.0, tz=dt.timezone.utc).strftime("%Y-%m-%d")
        except (OverflowError, OSError, ValueError):
            return None
    s = str(v).strip()
    return s[:10] if len(s) >= 10 else (s or None)


def fetch_nasa_coolr(bbox: tuple[float, float, float, float] = C.NEPAL_BBOX) -> list[dict[str, Any]]:
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
                records.append({
                    "id": f"coolr_{eid}",
                    "source": "NASA COOLR",
                    "date": _epoch_ms_to_iso_date(p.get("event_date")),
                    "title": str(p.get("event_title") or p.get("location_description") or "NASA COOLR landslide").strip(),
                    "category": str(p.get("landslide_category") or "landslide").strip(),
                    "trigger": str(p.get("landslide_trigger") or "unknown").strip(),
                    "size": str(p.get("landslide_size") or "").strip(),
                    "fatalities": _to_int_or_none(p.get("fatality_count")),
                    "injuries": _to_int_or_none(p.get("injury_count")),
                    "admin": str(p.get("admin_division_name") or "").strip(),
                    "lon": round(lon, 4),
                    "lat": round(lat, 4),
                    "url": _safe_url(p.get("source_link")),
                })
            return records
        except Exception as exc:
            last_exc = exc
    raise RuntimeError(f"All NASA COOLR endpoints failed: {last_exc}")


def fetch_osm_landslides() -> list[dict[str, Any]]:
    """Query OpenStreetMap Overpass for mapped landslide scars in Nepal."""
    query = """
    [out:json][timeout:180];
    area["ISO3166-1"="NP"][admin_level=2]->.np;
    (
      node["hazard"="landslide"](area.np);
      way["hazard"="landslide"](area.np);
      node["geological"="landslide"](area.np);
      way["geological"="landslide"](area.np);
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
                out.append({
                    "id": f"osm_{el_type[0]}{el_id}",
                    "source": "OpenStreetMap",
                    "date": None,
                    "title": str(tags.get("name:en") or tags.get("name") or "Mapped landslide scar / hazard zone").strip(),
                    "category": "landslide",
                    "trigger": "mapped scar",
                    "size": "",
                    "fatalities": None,
                    "injuries": None,
                    "admin": "",
                    "lon": round(float(lon), 4),
                    "lat": round(float(lat), 4),
                    "url": f"https://www.openstreetmap.org/{el_type}/{el_id}",
                })
            return out
        except Exception as exc:
            last_exc = exc
            time.sleep(3.0)
    raise RuntimeError(f"Overpass landslide query failed: {last_exc}")


def _load_cached() -> dict[str, Any]:
    if os.path.exists(CACHE_JSON):
        with open(CACHE_JSON, encoding="utf-8") as fh:
            return json.load(fh)
    if os.path.exists(LEGACY_JS):
        txt = open(LEGACY_JS, encoding="utf-8").read()
        return json.loads(txt.split("=", 1)[1].rsplit(";", 1)[0])
    return {}


def _normalize_event(ev: dict[str, Any]) -> dict[str, Any] | None:
    try:
        lon = float(ev["lon"])
        lat = float(ev["lat"])
    except (KeyError, TypeError, ValueError):
        return None
    if not (math.isfinite(lon) and math.isfinite(lat)):
        return None
    return {
        "id": str(ev.get("id") or ""),
        "source": str(ev.get("source") or "OpenStreetMap"),
        "date": ev.get("date") or None,
        "title": str(ev.get("title") or "Mapped landslide scar / hazard zone").strip(),
        "category": str(ev.get("category") or "landslide").strip(),
        "trigger": str(ev.get("trigger") or "unknown").strip(),
        "size": str(ev.get("size") or "").strip(),
        "fatalities": _to_int_or_none(ev.get("fatalities")),
        "injuries": _to_int_or_none(ev.get("injuries")),
        "admin": str(ev.get("admin") or "").strip(),
        "lon": round(lon, 4),
        "lat": round(lat, 4),
        "url": _safe_url(ev.get("url")),
    }


def build_landslides(
    offline: bool = False,
    refresh_osm: bool = False,
    out_path: str = OUT_JSON,
) -> dict[str, Any]:
    """Assemble honest landslide inventory JSON (`data/landslides.json`)."""
    cached = _load_cached()
    cached_events = [
        ne for e in (cached.get("events") or []) if (ne := _normalize_event(e)) is not None
    ]
    now_utc = dt.datetime.now(dt.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")

    coolr_events = [e for e in cached_events if "nasa" in e["source"].lower() or "coolr" in e["source"].lower()]
    osm_events = [e for e in cached_events if e not in coolr_events]
    any_live = False

    if offline:
        updated_utc = cached.get("updated_utc") or now_utc
    else:
        updated_utc = now_utc
        try:
            fetched_coolr = fetch_nasa_coolr()
            coolr_events = fetched_coolr
            any_live = True
        except Exception as exc:
            print(f"  [landslides] NASA COOLR unavailable ({exc}); keeping {len(coolr_events)} cached records", file=sys.stderr)
        if refresh_osm or not osm_events:
            try:
                osm_events = fetch_osm_landslides()
                any_live = True
            except Exception as exc:
                print(f"  [landslides] OSM Overpass refresh failed ({exc}); keeping {len(osm_events)} cached records", file=sys.stderr)
        if not any_live:
            updated_utc = cached.get("updated_utc") or now_utc

    # Deduplicate by id, dated/NASA COOLR events first
    seen: set[str] = set()
    merged: list[dict[str, Any]] = []
    for ev in sorted(coolr_events, key=lambda x: (x.get("date") or "", x.get("fatalities") or 0), reverse=True) + osm_events:
        eid = ev["id"] or f"{ev['lon']}_{ev['lat']}"
        if eid in seen:
            continue
        seen.add(eid)
        merged.append(ev)

    n_coolr = sum(1 for e in merged if "nasa" in e["source"].lower() or "coolr" in e["source"].lower())
    n_osm = len(merged) - n_coolr
    coolr_available = n_coolr > 0
    total_fatalities = sum(int(e["fatalities"]) for e in merged if e.get("fatalities"))

    if coolr_available:
        coverage_note = (
            f"Combines {n_coolr} dated NASA COOLR/GLC event reports and "
            f"{n_osm} undated OpenStreetMap mapped landslide scars in Nepal. "
            "Inventories are incomplete and represent lower bounds."
        )
    else:
        coverage_note = (
            f"0 NASA COOLR records currently loaded (upstream ArcGIS endpoint "
            f"returned no records or was unreachable); displaying {n_osm} undated "
            "OpenStreetMap mapped landslide scars only."
        )

    payload = {
        "updated_utc": updated_utc,
        "mode": "offline" if offline else ("live" if any_live else "cached_fallback"),
        "n_total": len(merged),
        "n_nasa_coolr": n_coolr,
        "n_osm": n_osm,
        "nasa_coolr_available": coolr_available,
        "total_reported_fatalities": total_fatalities,
        "coverage_note": coverage_note,
        "thresholds": THRESHOLDS,
        "events": merged,
    }

    _atomic_write_json(out_path, payload)
    if any_live:
        _atomic_write_json(CACHE_JSON, payload)
    return payload


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="Nepal TRĀYA landslide inventory builder")
    ap.add_argument("--offline", action="store_true", help="Zero network calls; normalize cached data")
    ap.add_argument("--refresh", action="store_true", help="Query NASA COOLR live")
    ap.add_argument("--refresh-osm", action="store_true", help="Also refresh OSM landslide scars")
    args = ap.parse_args(argv)

    res = build_landslides(offline=args.offline, refresh_osm=args.refresh_osm)
    print(
        f"[landslides] wrote {OUT_JSON}: total={res['n_total']} "
        f"(NASA COOLR={res['n_nasa_coolr']}, OSM={res['n_osm']}, "
        f"coolr_available={res['nasa_coolr_available']})"
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
