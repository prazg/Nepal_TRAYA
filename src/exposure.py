"""
Downstream exposure from OpenStreetMap via the Overpass API.

Collects, for Nepal: populated places, hospitals and clinics, hydropower plants,
road and rail bridges, and border control posts. These are the object classes that
Rounce et al. (2016) use to grade downstream impact (loss of life without warning,
loss of costly infrastructure, disruptive damage).

OpenStreetMap coverage in Nepal is uneven: settlements are well mapped, bridges
and clinics much less so. An absence of objects in this layer is not evidence that
nothing is there. Counts are a lower bound.

Data (c) OpenStreetMap contributors, ODbL 1.0.
"""
from __future__ import annotations
import json
import os
import time
import urllib.parse
import urllib.request

import config as C

OVERPASS_MIRRORS = (
    "https://overpass-api.de/api/interpreter",
    "https://overpass.kumi.systems/api/interpreter",
    "https://overpass.private.coffee/api/interpreter",
)
CACHE_DIR = os.path.join(C.CACHE, "overpass")

QUERIES = {
    "places": """
      [out:json][timeout:180];
      area["ISO3166-1"="NP"][admin_level=2]->.np;
      (
        node["place"~"^(city|town|village|hamlet)$"]["name"](area.np);
      );
      out body;
    """,
    "health": """
      [out:json][timeout:180];
      area["ISO3166-1"="NP"][admin_level=2]->.np;
      (
        node["amenity"~"^(hospital|clinic)$"](area.np);
        way["amenity"~"^(hospital|clinic)$"](area.np);
      );
      out center tags;
    """,
    "hydropower": """
      [out:json][timeout:180];
      area["ISO3166-1"="NP"][admin_level=2]->.np;
      (
        node["power"="plant"]["plant:source"="hydro"](area.np);
        way["power"="plant"]["plant:source"="hydro"](area.np);
        relation["power"="plant"]["plant:source"="hydro"](area.np);
        node["power"="generator"]["generator:source"="hydro"](area.np);
        way["power"="generator"]["generator:source"="hydro"](area.np);
      );
      out center tags;
    """,
    "bridges": """
      [out:json][timeout:300];
      area["ISO3166-1"="NP"][admin_level=2]->.np;
      (
        way["bridge"]["highway"](area.np);
        way["bridge"]["railway"](area.np);
      );
      out center tags;
    """,
    "borders": """
      [out:json][timeout:180];
      area["ISO3166-1"="NP"][admin_level=2]->.np;
      (
        node["barrier"="border_control"](area.np);
        way["barrier"="border_control"](area.np);
      );
      out center tags;
    """,
}

KIND_WEIGHT = {          # used only to order the exposure table, not a risk score
    "hydropower": 4, "health": 3, "places": 2, "bridges": 1, "borders": 1,
}


def _fetch(name: str, query: str, retries: int = 3) -> dict:
    os.makedirs(CACHE_DIR, exist_ok=True)
    cache = os.path.join(CACHE_DIR, f"{name}.json")
    if os.path.exists(cache) and os.path.getsize(cache) > 200:
        with open(cache) as fh:
            return json.load(fh)
    data = urllib.parse.urlencode({"data": query}).encode()
    last = None
    for attempt in range(retries):
        for url in OVERPASS_MIRRORS:
            try:
                req = urllib.request.Request(url, data=data,
                                             headers={"User-Agent": "nepal-ews/1.0 (research)"})
                with urllib.request.urlopen(req, timeout=400) as r:
                    payload = json.load(r)
                if not payload.get("elements") and attempt < retries - 1:
                    raise RuntimeError("empty response")
                with open(cache, "w") as fh:
                    json.dump(payload, fh)
                return payload
            except Exception as exc:        # rate limit, gateway timeout, mirror down
                last = f"{url}: {exc}"
                time.sleep(5)
        time.sleep(15 * (attempt + 1))
    raise RuntimeError(f"Overpass query {name} failed: {last}")


def collect() -> list[dict]:
    """Return a flat list of exposure objects with lon, lat, kind, name, tags."""
    out = []
    for name, q in QUERIES.items():
        payload = _fetch(name, q)
        for el in payload.get("elements", []):
            if el["type"] == "node":
                lon, lat = el.get("lon"), el.get("lat")
            else:
                ctr = el.get("center") or {}
                lon, lat = ctr.get("lon"), ctr.get("lat")
            if lon is None or lat is None:
                continue
            tags = el.get("tags", {}) or {}
            out.append(dict(
                kind=name,
                lon=round(float(lon), 5),
                lat=round(float(lat), 5),
                name=tags.get("name") or tags.get("ref") or "",
                sub=tags.get("place") or tags.get("amenity") or tags.get("power")
                    or tags.get("highway") or tags.get("railway") or tags.get("barrier") or "",
                pop=_int(tags.get("population")),
                capacity_mw=_mw(tags.get("plant:output:electricity")
                               or tags.get("generator:output:electricity")),
                osm=f"{el['type'][0]}{el['id']}",
            ))
    return out


def _int(v):
    try:
        return int(str(v).replace(",", "").strip())
    except Exception:
        return None


def _mw(v):
    if not v:
        return None
    s = str(v).strip().lower().replace(" ", "")
    try:
        if s.endswith("mw"):
            return float(s[:-2])
        if s.endswith("kw"):
            return float(s[:-2]) / 1000.0
        if s.endswith("gw"):
            return float(s[:-2]) * 1000.0
        return float(s) / 1e6          # bare watts
    except Exception:
        return None


if __name__ == "__main__":
    objs = collect()
    from collections import Counter
    print(Counter(o["kind"] for o in objs))
    print("named places with population tag:",
          sum(1 for o in objs if o["kind"] == "places" and o["pop"]))
