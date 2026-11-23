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
import argparse
import json
import os
import sys
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


def _atomic_write_json(path: str, payload: dict) -> None:
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


def _load_valid_cache(cache_path: str) -> dict | None:
    if not os.path.exists(cache_path) or os.path.getsize(cache_path) <= 200:
        return None
    try:
        with open(cache_path, encoding="utf-8") as fh:
            payload = json.load(fh)
        if isinstance(payload, dict) and payload.get("elements"):
            return payload
    except Exception:
        return None
    return None


def _is_fresh(cache_path: str, max_age_days: float | None) -> bool:
    if not os.path.exists(cache_path):
        return False
    if max_age_days is None:
        return True
    age_days = (time.time() - os.path.getmtime(cache_path)) / 86400.0
    return age_days <= max_age_days


def _fetch(name: str, query: str, retries: int = 3,
           refresh: bool = False, max_age_days: float | None = None,
           allow_stale_fallback: bool = True) -> dict:
    """Fetch an Overpass query with caching, TTL, and strict non-empty validation.

    Empty responses (``elements: []``) are rejected on EVERY retry attempt and
    are never written to disk.
    """
    os.makedirs(CACHE_DIR, exist_ok=True)
    cache = os.path.join(CACHE_DIR, f"{name}.json")
    existing = _load_valid_cache(cache)
    if existing is not None and not refresh and _is_fresh(cache, max_age_days):
        return existing

    data = urllib.parse.urlencode({"data": query}).encode("utf-8")
    last = None
    for attempt in range(retries):
        for url in OVERPASS_MIRRORS:
            try:
                req = urllib.request.Request(
                    url, data=data,
                    headers={"User-Agent": "nepal-traya/2.0 (research)"},
                )
                with urllib.request.urlopen(req, timeout=400) as r:
                    payload = json.loads(r.read().decode("utf-8"))
                # Reject empty responses on ALL attempts -- never cache empty!
                if not isinstance(payload, dict) or not payload.get("elements"):
                    raise RuntimeError("empty Overpass response (0 elements)")
                _atomic_write_json(cache, payload)
                return payload
            except Exception as exc:        # rate limit, gateway timeout, mirror down
                last = f"{url}: {exc}"
                time.sleep(5)
        if attempt < retries - 1:
            time.sleep(15 * (attempt + 1))

    if existing is not None and allow_stale_fallback:
        print(f"  WARNING: Overpass refresh for '{name}' failed ({last}); "
              "using existing valid cache.", file=sys.stderr)
        return existing
    raise RuntimeError(f"Overpass query {name} failed: {last}")


def collect(refresh: bool = False,
            max_age_days: float | None = None) -> list[dict]:
    """Return a flat list of exposure objects with lon, lat, kind, name, tags."""
    out = []
    for name, q in QUERIES.items():
        payload = _fetch(name, q, refresh=refresh, max_age_days=max_age_days)
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


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(
        description="Collect Nepal OpenStreetMap downstream exposure via Overpass."
    )
    ap.add_argument("--refresh", action="store_true",
                    help="Force fresh Overpass download for all layers")
    ap.add_argument("--max-age-days", type=float, default=None,
                    help="Re-fetch cached layers older than this many days")
    a = ap.parse_args(argv)

    objs = collect(refresh=a.refresh, max_age_days=a.max_age_days)
    from collections import Counter
    print(Counter(o["kind"] for o in objs))
    print("named places with population tag:",
          sum(1 for o in objs if o["kind"] == "places" and o["pop"]))
    return 0


if __name__ == "__main__":
    sys.exit(main())
