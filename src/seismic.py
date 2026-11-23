"""
Seismic context for the Nepal Multi-Hazard Risk Observatory & Screening Platform.

Two roles:

 1. A historical catalogue (USGS FDSN event service) giving the observed
    seismicity of the Nepal region. This is context, not a forecast: no
    probabilistic seismic hazard model is fitted here.

 2. The coupling to the glacial-lake and landslide modules. Rather than fitting
    our own shaking or triggering model, the live layer consumes the USGS's own
    operational products for each event:

      * ShakeMap MMI contours (download/cont_mmi.json), giving observed and
        modelled shaking intensity as a small GeoJSON the browser can read
      * the ground-failure product, which is the USGS operational run of the
        Nowicki Jessee et al. (2018) seismically induced landslide model and the
        Zhu et al. (2017) liquefaction model, including an aggregate hazard
        value, an alert level and a population-exposure estimate with
        uncertainty bands

    For static context, each lake carries descriptive statistics of observed
    seismicity nearby (counts and distances from the USGS catalogue). These are
    observations, not a probabilistic seismic hazard assessment, and no
    magnitude-distance triggering threshold is asserted.
"""
from __future__ import annotations
import argparse
from datetime import datetime, timedelta, timezone
import json
import math
import os
import sys
import time
import urllib.parse
import urllib.request

import config as C


def _atomic_write_json(path: str, payload) -> None:
    os.makedirs(os.path.dirname(os.path.abspath(path)), exist_ok=True)
    tmp = f"{path}.tmp.{os.getpid()}"
    try:
        with open(tmp, "w", encoding="utf-8") as fh:
            json.dump(payload, fh, ensure_ascii=False)
        os.replace(tmp, path)
    except Exception:
        if os.path.exists(tmp):
            try:
                os.remove(tmp)
            except OSError:
                pass
        raise


def _load_valid_cache(cache: str) -> list[dict] | None:
    if not os.path.exists(cache) or os.path.getsize(cache) <= 200:
        return None
    try:
        with open(cache, encoding="utf-8") as fh:
            data = json.load(fh)
        if isinstance(data, list) and len(data) > 0:
            return data
    except Exception:
        return None
    return None


def _is_fresh(cache: str, max_age_days: float | None) -> bool:
    if not os.path.exists(cache):
        return False
    if max_age_days is None:
        return True
    age_days = (time.time() - os.path.getmtime(cache)) / 86400.0
    return age_days <= max_age_days


def fetch_catalogue(bbox=C.NEPAL_BBOX, start: str = C.EQ_CATALOGUE_START,
                    min_mag: float = C.EQ_CATALOGUE_MIN_MAG,
                    cache: str | None = None,
                    refresh: bool = False,
                    max_age_days: float | None = None,
                    retries: int = 3) -> list[dict]:
    """Historical earthquakes from the USGS FDSN event service."""
    cache = cache or os.path.join(C.CACHE, "usgs_catalogue.json")
    os.makedirs(os.path.dirname(os.path.abspath(cache)), exist_ok=True)

    existing = _load_valid_cache(cache)
    if existing is not None and not refresh and _is_fresh(cache, max_age_days):
        return existing

    params = dict(format="geojson", starttime=start, minmagnitude=min_mag,
                  minlongitude=bbox[0], minlatitude=bbox[1],
                  maxlongitude=bbox[2], maxlatitude=bbox[3],
                  orderby="time", limit=20000)
    url = C.USGS_QUERY + "?" + urllib.parse.urlencode(params)
    last_err = None
    for attempt in range(retries):
        try:
            req = urllib.request.Request(
                url, headers={"User-Agent": "nepal-traya/2.0 (research)"}
            )
            with urllib.request.urlopen(req, timeout=180) as r:
                gj = json.loads(r.read().decode("utf-8"))
            feats = gj.get("features") or []
            if not feats:
                raise RuntimeError("USGS FDSN query returned 0 features")
            out = []
            for f in feats:
                p = f["properties"]
                c = f["geometry"]["coordinates"]
                out.append(dict(id=f["id"], time=p.get("time"), mag=p.get("mag"),
                                place=p.get("place"), depth_km=c[2],
                                lon=round(c[0], 4), lat=round(c[1], 4)))
            _atomic_write_json(cache, out)
            return out
        except Exception as exc:
            last_err = exc
            if attempt < retries - 1:
                time.sleep(5 * (attempt + 1))

    if existing is not None:
        print(f"  WARNING: USGS refresh failed ({last_err}); using cached catalogue.",
              file=sys.stderr)
        return existing
    raise RuntimeError(f"USGS FDSN catalogue fetch failed: {last_err}")


def haversine_km(lon1: float, lat1: float, lon2: float, lat2: float) -> float:
    """Great-circle distance (km) with domain clamping for antipodal stability."""
    r = 6371.0088
    p1, p2 = math.radians(lat1), math.radians(lat2)
    dp = p2 - p1
    dl = math.radians(lon2 - lon1)
    a = math.sin(dp / 2.0) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(dl / 2.0) ** 2
    a = min(1.0, max(0.0, a))
    return 2.0 * r * math.asin(math.sqrt(a))


def utc_year_from_ms(ms: float) -> int:
    """Exact UTC Gregorian calendar year from epoch milliseconds (handles pre-1970 on Windows)."""
    try:
        return datetime.fromtimestamp(ms / 1000.0, tz=timezone.utc).year
    except (OSError, OverflowError, ValueError):
        return (datetime(1970, 1, 1, tzinfo=timezone.utc) + timedelta(milliseconds=ms)).year


def summarise(cat: list[dict]) -> dict:
    """Simple observed-seismicity summary for the provenance panel."""
    if not cat:
        return {}
    mags = [e["mag"] for e in cat if e.get("mag") is not None]
    times = [e["time"] for e in cat if e.get("time") is not None]
    years = sorted({utc_year_from_ms(t) for t in times})
    now_ms = time.time() * 1000.0
    cutoff_30d_ms = now_ms - 30.0 * 86400.0 * 1000.0
    n_30d = sum(
        1 for e in cat
        if e.get("time") is not None and e.get("mag") is not None
        and e["time"] >= cutoff_30d_ms and e["mag"] >= 4.0
    )
    return dict(n_events=len(cat),
                min_mag=min(mags) if mags else None,
                max_mag=max(mags) if mags else None,
                first_year=years[0] if years else None,
                last_year=years[-1] if years else None,
                n_m6plus=sum(1 for m in mags if m >= 6.0),
                n_m7plus=sum(1 for m in mags if m >= 7.0),
                n_past_30d_m4plus=n_30d)


def nearby_seismicity(lon: float, lat: float, cat: list[dict]) -> dict:
    """Descriptive statistics of observed seismicity around a point.

    Purely observational: counts of catalogued events within fixed radii and the
    distance to the nearest large event. No recurrence model is fitted.
    """
    n50_m5 = n100_m6 = 0
    d_m6 = None
    for e in cat:
        m = e.get("mag")
        if m is None:
            continue
        d = haversine_km(lon, lat, e["lon"], e["lat"])
        if m >= 5.0 and d <= 50:
            n50_m5 += 1
        if m >= 6.0:
            if d <= 100:
                n100_m6 += 1
            if d_m6 is None or d < d_m6:
                d_m6 = d
    return dict(n_m5_within_50km=n50_m5, n_m6_within_100km=n100_m6,
                nearest_m6_km=round(d_m6, 1) if d_m6 is not None else None)


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(
        description="Fetch and summarise the USGS earthquake catalogue for Nepal."
    )
    ap.add_argument("--refresh", action="store_true",
                    help="Force fresh download from the USGS FDSN event service")
    ap.add_argument("--max-age-days", type=float, default=None,
                    help="Re-fetch if local cache is older than this many days")
    a = ap.parse_args(argv)

    cat = fetch_catalogue(refresh=a.refresh, max_age_days=a.max_age_days)
    print(json.dumps(summarise(cat), indent=2))
    print("Imja Tsho:", nearby_seismicity(86.93, 27.90, cat))
    return 0


if __name__ == "__main__":
    sys.exit(main())
