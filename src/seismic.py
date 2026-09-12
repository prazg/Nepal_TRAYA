"""
Seismic context for the early warning system.

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
import json
import math
import os
import urllib.parse
import urllib.request

import config as C


def fetch_catalogue(bbox=C.NEPAL_BBOX, start: str = C.EQ_CATALOGUE_START,
                    min_mag: float = C.EQ_CATALOGUE_MIN_MAG,
                    cache: str | None = None) -> list[dict]:
    """Historical earthquakes from the USGS FDSN event service."""
    cache = cache or os.path.join(C.CACHE, "usgs_catalogue.json")
    os.makedirs(os.path.dirname(cache), exist_ok=True)
    if os.path.exists(cache) and os.path.getsize(cache) > 200:
        with open(cache) as fh:
            return json.load(fh)
    params = dict(format="geojson", starttime=start, minmagnitude=min_mag,
                  minlongitude=bbox[0], minlatitude=bbox[1],
                  maxlongitude=bbox[2], maxlatitude=bbox[3],
                  orderby="time", limit=20000)
    url = C.USGS_QUERY + "?" + urllib.parse.urlencode(params)
    with urllib.request.urlopen(url, timeout=180) as r:
        gj = json.load(r)
    out = []
    for f in gj.get("features", []):
        p = f["properties"]
        c = f["geometry"]["coordinates"]
        out.append(dict(id=f["id"], time=p.get("time"), mag=p.get("mag"),
                        place=p.get("place"), depth_km=c[2],
                        lon=round(c[0], 4), lat=round(c[1], 4)))
    with open(cache, "w") as fh:
        json.dump(out, fh)
    return out


def haversine_km(lon1, lat1, lon2, lat2):
    r = 6371.0088
    p1, p2 = math.radians(lat1), math.radians(lat2)
    dp = p2 - p1
    dl = math.radians(lon2 - lon1)
    a = math.sin(dp / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(dl / 2) ** 2
    return 2 * r * math.asin(math.sqrt(a))


def summarise(cat: list[dict]) -> dict:
    """Simple observed-seismicity summary for the provenance panel."""
    if not cat:
        return {}
    mags = [e["mag"] for e in cat if e.get("mag") is not None]
    years = sorted({int(e["time"] / 1000 / 31557600 + 1970) for e in cat if e.get("time")})
    return dict(n_events=len(cat), min_mag=min(mags), max_mag=max(mags),
                first_year=years[0] if years else None,
                last_year=years[-1] if years else None,
                n_m6plus=sum(1 for m in mags if m >= 6.0),
                n_m7plus=sum(1 for m in mags if m >= 7.0))


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


if __name__ == "__main__":
    cat = fetch_catalogue()
    print(json.dumps(summarise(cat), indent=2))
    print("Imja Tsho:", nearby_seismicity(86.93, 27.90, cat))
