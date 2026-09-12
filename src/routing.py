"""
Downstream routing along the HydroRIVERS v1.0 network.

For each source lake we find the nearest river reach, follow the NEXT_DOWN
topology downstream, and report:

  * the routed flow path as a polyline (for mapping)
  * cumulative distance and elevation drop
  * travel time to each point for a bracket of surge-front velocities
  * the ratio of the estimated GLOF peak discharge to the reach's long-term mean
    discharge (HydroRIVERS DIS_AV_CMS), which is a blunt but communicable measure
    of how far outside normal conditions the flood would be

Travel times are distance / velocity with a constant velocity. They are not
hydrodynamic routing: no attenuation, no channel storage, no backwater. They are
intended for triage - who is minutes away and who is hours away - not for
operational lead-time guarantees.
"""
from __future__ import annotations
import os
from collections import defaultdict

import geopandas as gpd
import numpy as np
from shapely.geometry import LineString, Point
from shapely.ops import linemerge

import config as C

SHP = os.path.join(C.RAW, "hydro", "HydroRIVERS_v10_as_shp", "HydroRIVERS_v10_as.shp")
# generous window: floods from Nepal drain south into the Ganges plain
ROUTE_BBOX = (78.0, 22.0, 92.0, 31.5)


class RiverNetwork:
    def __init__(self, shp: str = SHP, bbox=ROUTE_BBOX):
        self.gdf = gpd.read_file(shp, bbox=bbox).set_index("HYRIV_ID")
        self.next_down = self.gdf["NEXT_DOWN"].to_dict()
        self.length_km = self.gdf["LENGTH_KM"].to_dict()
        self.dis_av = self.gdf["DIS_AV_CMS"].to_dict()
        self.geom = self.gdf.geometry.to_dict()
        self.sindex = self.gdf.sindex
        self.ids = self.gdf.index.to_numpy()
        # upstream adjacency, for finding lakes that could flood into a lake
        self.up = defaultdict(list)
        for rid, nd in self.next_down.items():
            if nd:
                self.up[nd].append(rid)

    # -- lookup ------------------------------------------------------------
    def nearest_reach(self, lon: float, lat: float, max_deg: float = 0.05):
        p = Point(lon, lat)
        cand = list(self.sindex.nearest(p, max_distance=max_deg, return_all=False)[1]) \
            if hasattr(self.sindex, "nearest") else []
        if not cand:
            cand = list(self.sindex.query(p.buffer(max_deg)))
        if not cand:
            return None, None
        best, bd = None, 1e9
        for i in cand:
            rid = int(self.ids[int(i)])
            d = self.geom[rid].distance(p)
            if d < bd:
                best, bd = rid, d
        return best, bd

    # -- traversal ---------------------------------------------------------
    def trace_down(self, rid: int, max_km: float = C.ROUTING_MAX_DISTANCE_KM):
        """Return [(reach_id, cumulative_km_at_reach_end)] going downstream."""
        out, seen, cum = [], set(), 0.0
        while rid and rid not in seen and cum < max_km:
            seen.add(rid)
            cum += float(self.length_km.get(rid, 0.0) or 0.0)
            out.append((rid, cum))
            rid = int(self.next_down.get(rid, 0) or 0)
        return out

    def trace_up(self, rid: int, max_km: float = 30.0):
        """Reaches upstream of `rid` within max_km (breadth-first)."""
        out, stack = [], [(rid, 0.0)]
        seen = {rid}
        while stack:
            r, d = stack.pop()
            for u in self.up.get(r, []):
                if u in seen:
                    continue
                seen.add(u)
                d2 = d + float(self.length_km.get(u, 0.0) or 0.0)
                if d2 <= max_km:
                    out.append((u, d2))
                    stack.append((u, d2))
        return out

    def path_geometry(self, trace, simplify_deg: float = 0.004) -> LineString | None:
        parts = [self.geom[r] for r, _ in trace if r in self.geom]
        if not parts:
            return None
        merged = linemerge(parts)
        if merged.geom_type == "MultiLineString":
            merged = max(merged.geoms, key=lambda g: g.length)
        return merged.simplify(simplify_deg, preserve_topology=False)

    def mean_discharge(self, rid: int) -> float | None:
        v = self.dis_av.get(rid)
        return float(v) if v is not None and v >= 0 else None


def travel_times_min(distance_km: float) -> dict:
    """Travel time in minutes for each velocity in config.FRONT_VELOCITY_MS."""
    return {f"v{v:g}": round(distance_km * 1000.0 / v / 60.0, 1)
            for v in C.FRONT_VELOCITY_MS}
