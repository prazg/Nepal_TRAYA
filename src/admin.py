"""
Administrative attribution for lakes and exposure points.

The province field carried by the source lake inventory is unreliable: every
province in it spans nearly the full longitude range of Nepal, which cannot be
true of contiguous west-to-east provinces. Rather than propagate that, this
module rebuilds province and district attribution by point-in-polygon against
Nepal administrative polygons (admin_level 4 and 6).

Reads the committed ``cache/nepal_admin.json`` first (preserving inner rings /
holes and normalizing spelling variants such as ``Bagamati Province`` ->
``Bagmati Province``), and falls back to Overpass only when refreshing or when
no valid local cache exists. Empty Overpass payloads (``elements: []``) are
always rejected and never cached.

Data (c) OpenStreetMap contributors, ODbL 1.0.
"""
from __future__ import annotations
import argparse
import json
import math
import os
import sys
import time
import urllib.parse
import urllib.request

try:
    from shapely.geometry import Point, LineString, shape as shapely_shape
    from shapely.ops import polygonize, unary_union
    from shapely.strtree import STRtree
except ImportError:  # pragma: no cover - stdlib-only unit test mode
    Point = LineString = shapely_shape = polygonize = unary_union = STRtree = None

import config as C
from exposure import OVERPASS_MIRRORS

PRIMARY_CACHE = os.path.join(C.CACHE, "nepal_admin.json")
OVERPASS_CACHE = os.path.join(C.CACHE, "overpass", "admin.json")
CACHE = PRIMARY_CACHE   # backwards-compatible alias

QUERY = """
[out:json][timeout:300];
area["ISO3166-1"="NP"][admin_level=2]->.np;
(
  relation["boundary"="administrative"]["admin_level"="4"](area.np);
  relation["boundary"="administrative"]["admin_level"="6"](area.np);
);
out geom;
"""

PROVINCE_ALIASES = {
    "bagamati province": "Bagmati Province",
    "bagamati": "Bagmati Province",
    "bagmati": "Bagmati Province",
    "province no. 1": "Koshi Province",
    "province 1": "Koshi Province",
    "koshi": "Koshi Province",
    "province no. 2": "Madhesh Province",
    "province 2": "Madhesh Province",
    "madhesh": "Madhesh Province",
    "madesh province": "Madhesh Province",
    "province no. 3": "Bagmati Province",
    "province 3": "Bagmati Province",
    "province no. 4": "Gandaki Province",
    "province 4": "Gandaki Province",
    "gandaki": "Gandaki Province",
    "province no. 5": "Lumbini Province",
    "province 5": "Lumbini Province",
    "lumbini": "Lumbini Province",
    "province no. 6": "Karnali Province",
    "province 6": "Karnali Province",
    "karnali": "Karnali Province",
    "province no. 7": "Sudurpashchim Province",
    "province 7": "Sudurpashchim Province",
    "sudurpaschim province": "Sudurpashchim Province",
    "sudurpashchim": "Sudurpashchim Province",
    "sudurpaschim": "Sudurpashchim Province",
}


def normalize_province_name(name: str) -> str:
    """Normalize OSM / legacy Nepal province names to canonical spellings."""
    cleaned = " ".join((name or "").strip().split())
    if not cleaned:
        return ""
    return PROVINCE_ALIASES.get(cleaned.lower(), cleaned)


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


def _is_fresh(path: str, max_age_days: float | None) -> bool:
    if not os.path.exists(path) or os.path.getsize(path) <= 200:
        return False
    if max_age_days is None:
        return True
    age_days = (time.time() - os.path.getmtime(path)) / 86400.0
    return age_days <= max_age_days


def _load_primary_cache(path: str = PRIMARY_CACHE) -> dict | None:
    if not os.path.exists(path) or os.path.getsize(path) <= 200:
        return None
    try:
        with open(path, encoding="utf-8") as fh:
            data = json.load(fh)
        if isinstance(data, dict) and data.get("4") and data.get("6"):
            return data
    except Exception:
        return None
    return None


def _load_overpass_cache(path: str = OVERPASS_CACHE) -> dict | None:
    if not os.path.exists(path) or os.path.getsize(path) <= 1000:
        return None
    try:
        with open(path, encoding="utf-8") as fh:
            data = json.load(fh)
        if isinstance(data, dict) and data.get("elements"):
            return data
    except Exception:
        return None
    return None


def _fetch_overpass(retries: int = 3) -> dict:
    data = urllib.parse.urlencode({"data": QUERY}).encode("utf-8")
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
                elements = payload.get("elements") if isinstance(payload, dict) else None
                if not elements:
                    raise RuntimeError("empty Overpass response (elements: [])")
                provs = [e for e in elements
                         if (e.get("tags") or {}).get("admin_level") == "4"]
                if len(provs) < 7:
                    raise RuntimeError(f"incomplete Overpass admin response ({len(provs)} provinces)")
                _atomic_write_json(OVERPASS_CACHE, payload)
                return payload
            except Exception as exc:
                last = f"{url}: {exc}"
                time.sleep(5)
        if attempt < retries - 1:
            time.sleep(15 * (attempt + 1))
    raise RuntimeError(f"admin boundary query failed: {last}")


def _relation_polygon(el: dict):
    """Build a Shapely (Multi)Polygon from an Overpass relation, preserving
    both outer boundaries and inner rings (holes / enclaves)."""
    if LineString is None or polygonize is None or unary_union is None:
        raise ImportError("parsing Overpass relation geometries requires shapely")
    outer_lines = []
    inner_lines = []
    for m in el.get("members", []):
        if m.get("type") != "way":
            continue
        role = m.get("role")
        g = m.get("geometry")
        if not g or len(g) < 2:
            continue
        line = LineString([(p["lon"], p["lat"]) for p in g])
        if role == "inner":
            inner_lines.append(line)
        elif role in ("outer", "", None):
            outer_lines.append(line)
    if not outer_lines:
        return None
    outer_polys = list(polygonize(unary_union(outer_lines)))
    if not outer_polys:
        return None
    poly = unary_union(outer_polys)
    if inner_lines:
        inner_polys = list(polygonize(unary_union(inner_lines)))
        if inner_polys:
            poly = poly.difference(unary_union(inner_polys))
    return poly if (poly is not None and not poly.is_empty) else None


# ---------------------------------------------------------------------------
# Pure-Python stdlib polygon container (used when shapely is not installed)
# ---------------------------------------------------------------------------
def _point_in_ring(lon: float, lat: float, ring) -> bool:
    inside = False
    n = len(ring)
    if n < 3:
        return False
    x1, y1 = ring[-1][0], ring[-1][1]
    for pt in ring:
        x2, y2 = pt[0], pt[1]
        if (y1 > lat) != (y2 > lat):
            x_int = (x2 - x1) * (lat - y1) / (y2 - y1) + x1
            if lon < x_int:
                inside = not inside
        x1, y1 = x2, y2
    return inside


def _point_to_ring_dist(lon: float, lat: float, ring) -> float:
    best = math.inf
    n = len(ring)
    if n == 0:
        return best
    if n == 1:
        return math.hypot(lon - ring[0][0], lat - ring[0][1])
    x1, y1 = ring[0][0], ring[0][1]
    for k in range(1, n):
        x2, y2 = ring[k][0], ring[k][1]
        vx, vy = x2 - x1, y2 - y1
        l2 = vx * vx + vy * vy
        if l2 > 0.0:
            t = max(0.0, min(1.0, ((lon - x1) * vx + (lat - y1) * vy) / l2))
        else:
            t = 0.0
        d = math.hypot(lon - (x1 + t * vx), lat - (y1 + t * vy))
        if d < best:
            best = d
        x1, y1 = x2, y2
    return best


class _PureGeoPolygon:
    """Minimal GeoJSON Polygon / MultiPolygon wrapper preserving inner rings."""

    def __init__(self, geom: dict):
        gtype = geom.get("type")
        coords = geom.get("coordinates") or []
        if gtype == "Polygon":
            self.parts = [coords]
        elif gtype == "MultiPolygon":
            self.parts = list(coords)
        else:
            self.parts = []
        xs = [p[0] for part in self.parts for ring in part for p in ring]
        ys = [p[1] for part in self.parts for ring in part for p in ring]
        self.is_empty = not bool(xs)
        self.bounds = (min(xs), min(ys), max(xs), max(ys)) if xs else (0, 0, 0, 0)

    def contains_xy(self, lon: float, lat: float) -> bool:
        if self.is_empty:
            return False
        minx, miny, maxx, maxy = self.bounds
        if not (minx <= lon <= maxx and miny <= lat <= maxy):
            return False
        for rings in self.parts:
            if not rings:
                continue
            if _point_in_ring(lon, lat, rings[0]):
                if not any(_point_in_ring(lon, lat, hole) for hole in rings[1:]):
                    return True
        return False

    def distance_xy(self, lon: float, lat: float) -> float:
        if self.contains_xy(lon, lat):
            return 0.0
        best = math.inf
        for rings in self.parts:
            for ring in rings:
                d = _point_to_ring_dist(lon, lat, ring)
                if d < best:
                    best = d
        return best


def _geom_from_geojson(geom: dict):
    if shapely_shape is not None:
        return shapely_shape(geom)
    return _PureGeoPolygon(geom)


class AdminIndex:
    """Point-in-polygon lookup for Nepal's 7 provinces (level 4) and 77 districts (level 6)."""

    def __init__(self, refresh: bool = False, max_age_days: float | None = None):
        self.levels: dict[str, list[tuple[str, object]]] = {"4": [], "6": []}
        self._use_shapely = shapely_shape is not None and STRtree is not None

        # 1. Prefer committed cache/nepal_admin.json unless refresh/TTL forces update
        primary = _load_primary_cache(PRIMARY_CACHE)
        if primary is not None and not refresh and _is_fresh(PRIMARY_CACHE, max_age_days):
            self._load_geojson_levels(primary)
        else:
            # 2. Try Overpass cache or live refresh, falling back to primary if offline
            ov = None
            if not refresh and _is_fresh(OVERPASS_CACHE, max_age_days):
                ov = _load_overpass_cache(OVERPASS_CACHE)
            if ov is None:
                try:
                    ov = _fetch_overpass()
                except Exception:
                    if primary is not None:
                        self._load_geojson_levels(primary)
                    else:
                        ov = _load_overpass_cache(OVERPASS_CACHE)
                        if ov is None:
                            raise
            if not self.levels["4"] and ov is not None:
                self._load_overpass_elements(ov)
                # Persist normalized GeoJSON into cache/nepal_admin.json when shapely built it
                if self._use_shapely and self.levels["4"] and self.levels["6"]:
                    try:
                        from shapely.geometry import mapping
                        serialized = {
                            lvl: [dict(name=n, geometry=mapping(p))
                                  for n, p in items]
                            for lvl, items in self.levels.items()
                        }
                        _atomic_write_json(PRIMARY_CACHE, serialized)
                    except Exception:
                        pass

        if self._use_shapely:
            self.trees = {
                k: STRtree([p for _, p in v]) for k, v in self.levels.items()
            }
        else:
            self.trees = {}

    def _load_geojson_levels(self, data: dict) -> None:
        for lvl in ("4", "6"):
            for item in data.get(lvl, []):
                geom = item.get("geometry")
                if not geom:
                    continue
                poly = _geom_from_geojson(geom)
                if poly is None or getattr(poly, "is_empty", False):
                    continue
                raw_name = (item.get("name") or "").strip()
                name = normalize_province_name(raw_name) if lvl == "4" else raw_name
                self.levels[lvl].append((name, poly))

    def _load_overpass_elements(self, payload: dict) -> None:
        for el in payload.get("elements", []):
            tags = el.get("tags") or {}
            lvl = tags.get("admin_level")
            if lvl not in self.levels:
                continue
            poly = _relation_polygon(el)
            if poly is None or poly.is_empty:
                continue
            raw_name = (tags.get("name:en") or tags.get("name") or "").strip()
            name = normalize_province_name(raw_name) if lvl == "4" else raw_name
            self.levels[lvl].append((name, poly))

    def _lookup(self, lvl: str, lon: float, lat: float) -> str:
        items = self.levels[lvl]
        if not items:
            return ""
        if self._use_shapely:
            pt = Point(lon, lat)
            for i in self.trees[lvl].query(pt):
                name, poly = items[int(i)]
                if poly.contains(pt):
                    return name
            best, bd = "", 1e9
            for name, poly in items:
                d = poly.distance(pt)
                if d < bd:
                    best, bd = name, d
            return best if bd < 0.05 else ""

        for name, poly in items:
            if poly.contains_xy(lon, lat):
                return name
        best, bd = "", 1e9
        for name, poly in items:
            d = poly.distance_xy(lon, lat)
            if d < bd:
                best, bd = name, d
        return best if bd < 0.05 else ""

    def province(self, lon: float, lat: float) -> str:
        return self._lookup("4", lon, lat)

    def district(self, lon: float, lat: float) -> str:
        return self._lookup("6", lon, lat)


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(
        description="Build or query Nepal administrative boundaries (provinces & districts)."
    )
    ap.add_argument("--refresh", action="store_true",
                    help="Force fresh Overpass download (rejects empty payloads)")
    ap.add_argument("--max-age-days", type=float, default=None,
                    help="Re-fetch if local cache is older than this many days")
    a = ap.parse_args(argv)

    ix = AdminIndex(refresh=a.refresh, max_age_days=a.max_age_days)
    print("provinces:", sorted(n for n, _ in ix.levels["4"]))
    print("districts:", len(ix.levels["6"]))
    for name, lon, lat in [("Tsho Rolpa", 86.477, 27.861), ("Imja Tsho", 86.923, 27.899),
                           ("Thulagi Tsho", 84.485, 28.488), ("Kathmandu", 85.324, 27.717),
                           ("far west lake", 80.9, 30.0)]:
        print(f"  {name:16s} {ix.province(lon, lat):22s} {ix.district(lon, lat)}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
