"""
Administrative attribution for lakes and exposure points.

The province field carried by the source lake inventory is unreliable: every
province in it spans nearly the full longitude range of Nepal, which cannot be
true of contiguous west-to-east provinces. Rather than propagate that, this
module rebuilds province and district attribution by point-in-polygon against
OpenStreetMap administrative relations (admin_level 4 and 6) for Nepal.

Data (c) OpenStreetMap contributors, ODbL 1.0.
"""
from __future__ import annotations
import json
import os
import time
import urllib.parse
import urllib.request

from shapely.geometry import Point, LineString
from shapely.ops import polygonize, unary_union
from shapely.strtree import STRtree

import config as C
from exposure import OVERPASS_MIRRORS

CACHE = os.path.join(C.CACHE, "overpass", "admin.json")

QUERY = """
[out:json][timeout:300];
area["ISO3166-1"="NP"][admin_level=2]->.np;
(
  relation["boundary"="administrative"]["admin_level"="4"](area.np);
  relation["boundary"="administrative"]["admin_level"="6"](area.np);
);
out geom;
"""


def _fetch() -> dict:
    if os.path.exists(CACHE) and os.path.getsize(CACHE) > 1000:
        with open(CACHE) as fh:
            return json.load(fh)
    os.makedirs(os.path.dirname(CACHE), exist_ok=True)
    data = urllib.parse.urlencode({"data": QUERY}).encode()
    last = None
    for url in OVERPASS_MIRRORS:
        try:
            req = urllib.request.Request(url, data=data,
                                         headers={"User-Agent": "nepal-ews/1.0 (research)"})
            with urllib.request.urlopen(req, timeout=400) as r:
                payload = json.load(r)
            with open(CACHE, "w") as fh:
                json.dump(payload, fh)
            return payload
        except Exception as exc:
            last = exc
            time.sleep(5)
    raise RuntimeError(f"admin boundary query failed: {last}")


def _relation_polygon(el: dict):
    lines = []
    for m in el.get("members", []):
        if m.get("type") != "way" or m.get("role") not in ("outer", "", None):
            continue
        g = m.get("geometry")
        if g and len(g) > 1:
            lines.append(LineString([(p["lon"], p["lat"]) for p in g]))
    if not lines:
        return None
    polys = list(polygonize(unary_union(lines)))
    if not polys:
        return None
    return unary_union(polys)


class AdminIndex:
    def __init__(self):
        payload = _fetch()
        self.levels = {"4": [], "6": []}
        for el in payload.get("elements", []):
            lvl = (el.get("tags") or {}).get("admin_level")
            if lvl not in self.levels:
                continue
            poly = _relation_polygon(el)
            if poly is None or poly.is_empty:
                continue
            name = (el["tags"].get("name:en") or el["tags"].get("name") or "").strip()
            self.levels[lvl].append((name, poly))
        self.trees = {k: STRtree([p for _, p in v]) for k, v in self.levels.items()}

    def _lookup(self, lvl: str, lon: float, lat: float) -> str:
        pt = Point(lon, lat)
        items = self.levels[lvl]
        for i in self.trees[lvl].query(pt):
            name, poly = items[int(i)]
            if poly.contains(pt):
                return name
        # fall back to the nearest boundary, for points just outside the polygons
        best, bd = "", 1e9
        for name, poly in items:
            d = poly.distance(pt)
            if d < bd:
                best, bd = name, d
        return best if bd < 0.05 else ""

    def province(self, lon: float, lat: float) -> str:
        return self._lookup("4", lon, lat)

    def district(self, lon: float, lat: float) -> str:
        return self._lookup("6", lon, lat)


if __name__ == "__main__":
    ix = AdminIndex()
    print("provinces:", sorted(n for n, _ in ix.levels["4"]))
    print("districts:", len(ix.levels["6"]))
    for name, lon, lat in [("Tsho Rolpa", 86.477, 27.861), ("Imja Tsho", 86.923, 27.899),
                           ("Thulagi Tsho", 84.485, 28.488), ("Kathmandu", 85.324, 27.717),
                           ("far west lake", 80.9, 30.0)]:
        print(f"  {name:16s} {ix.province(lon, lat):22s} {ix.district(lon, lat)}")
