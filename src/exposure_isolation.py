"""
Downstream exposure breakdown & road-cut hospital isolation screening module
for TRĀYA 2.0 (`TRAYA-009`).

Scientific & epistemic architecture:
  * Keeps all published Rounce et al. (2016) GLOF hazard classes untouched.
  * Explicitly separates 4 conceptual dimensions in `data/exposure_isolation.json`:
      1. `hazard_susceptibility_static`   : published GLOF hazard class & PFV (untouched)
      2. `corridor_exposure_screening`    : 1 km perpendicular point-to-segment screening
                                            counts (settlements, health/hospitals, bridges,
                                            hydropower & tagged MW)
      3. `road_cut_hospital_isolation`    : functional valley-corridor bridge-cut and
                                            hospital/clinic access disruption indicators
      4. `uncertainty_and_coverage_limits`: OSM completeness bounds, screening-corridor
                                            caveat, and non-hydrodynamic disclaimers
  * Uses fast spatial grid lookup against `cache/overpass/{places,health,bridges,hydropower}.json`
    in pure Python 3.12 stdlib (zero external packages).

Output: `data/exposure_isolation.json` (atomic UTF-8 JSON).
"""
from __future__ import annotations

import argparse
import datetime as dt
import json
import math
import os
import re
import sys
import tempfile
from collections import Counter, defaultdict
from typing import Any

SRC_DIR = os.path.dirname(os.path.abspath(__file__))
if SRC_DIR not in sys.path:
    sys.path.insert(0, SRC_DIR)

import config as C
import floods as FL
import hydromet as HM
import refresh_weekly as RW
import seismic as SZ

SCHEMA_VERSION = "exposure_isolation.v1"
METHODOLOGY_NOTICE = (
    "1 km screening search corridor — NOT a 2D hydrodynamic inundation boundary. "
    "Infrastructure exposure and bridge-cut isolation metrics are screening indicators "
    "for prioritization only."
)

OUT_JSON = os.path.join(C.DATA, "exposure_isolation.json")

VEHICULAR_HIGHWAYS = frozenset(
    {
        "motorway",
        "trunk",
        "primary",
        "secondary",
        "tertiary",
        "unclassified",
        "residential",
        "road",
        "service",
        "track",
        "living_street",
        "motorway_link",
        "trunk_link",
        "primary_link",
        "secondary_link",
        "tertiary_link",
    }
)
PEDESTRIAN_HIGHWAYS = frozenset({"path", "footway", "bridleway", "steps", "cycleway", "pedestrian"})
NON_HUMAN_HEALTH_RE = re.compile(
    r"(veterinar|animal|livestock|पशु|school of science|residential)", re.IGNORECASE
)
VOLTAGE_RE = re.compile(r"^\d+(\.\d+)?\s*k?v$", re.IGNORECASE)


def _atomic_write_json(path: str, obj: Any) -> None:
    os.makedirs(os.path.dirname(os.path.abspath(path)), exist_ok=True)
    fd, tmp_path = tempfile.mkstemp(
        dir=os.path.dirname(os.path.abspath(path)),
        prefix=".tmp_",
        suffix=".json",
    )
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


def _parse_mw(val: Any) -> float | None:
    if not val:
        return None
    s = str(val).strip().lower().replace(" ", "")
    if not s or s in ("yes", "no") or VOLTAGE_RE.match(s):
        return None
    try:
        if s.endswith("mw"):
            v = float(s[:-2])
        elif s.endswith("kw"):
            v = float(s[:-2]) / 1000.0
        elif s.endswith("gw"):
            v = float(s[:-2]) * 1000.0
        else:
            raw = float(s)
            # Bare watts (avoid treating small numbers like 300 kW ambiguously; follow exposure.py)
            v = raw / 1e6 if raw >= 1000.0 else None
        if v is not None and math.isfinite(v) and 0.0 < v <= 20000.0:
            return round(v, 3)
    except (TypeError, ValueError):
        return None
    return None


def _parse_int(val: Any) -> int | None:
    if val is None or val == "":
        return None
    try:
        v = int(str(val).replace(",", "").strip())
        return v if v >= 0 else None
    except (TypeError, ValueError):
        return None


def _median(vals: list[float]) -> float | None:
    if not vals:
        return None
    s = sorted(vals)
    n = len(s)
    mid = n // 2
    if n % 2 == 1:
        return s[mid]
    return 0.5 * (s[mid - 1] + s[mid])


# ---------------------------------------------------------------------------
# Overpass cache loaders (cleaned for human health, real bridges, hydro MW)
# ---------------------------------------------------------------------------
def _extract_lon_lat(el: dict[str, Any]) -> tuple[float, float] | None:
    if el.get("type") == "node":
        lon, lat = el.get("lon"), el.get("lat")
    else:
        ctr = el.get("center") or {}
        lon, lat = ctr.get("lon"), ctr.get("lat")
    if lon is None or lat is None:
        return None
    try:
        flon, flat = float(lon), float(lat)
    except (TypeError, ValueError):
        return None
    if not (math.isfinite(flon) and math.isfinite(flat)):
        return None
    return (round(flon, 5), round(flat, 5))


def _display_names(tags: dict[str, Any]) -> tuple[str, str]:
    raw_name = str(tags.get("name") or "").strip()
    name_en = str(tags.get("name:en") or "").strip()
    name_ne = str(tags.get("name:ne") or "").strip()
    if not name_ne and any("\u0900" <= ch <= "\u097f" for ch in raw_name):
        name_ne = raw_name
    disp = name_en or raw_name or str(tags.get("bridge:name") or tags.get("ref") or "").strip()
    return (disp, name_ne if name_ne and name_ne != disp else "")


def load_overpass_layers(cache_dir: str | None = None) -> dict[str, list[dict[str, Any]]]:
    """Load and clean places, health, bridges, and hydropower from Overpass caches."""
    cdir = cache_dir or os.path.join(C.CACHE, "overpass")
    layers: dict[str, list[dict[str, Any]]] = {
        "places": [],
        "health": [],
        "bridges": [],
        "hydropower": [],
    }
    for kind in ("places", "health", "bridges", "hydropower"):
        path = os.path.join(cdir, f"{kind}.json")
        if not os.path.exists(path):
            continue
        with open(path, encoding="utf-8") as fh:
            payload = json.load(fh)
        for el in payload.get("elements") or []:
            coords = _extract_lon_lat(el)
            if coords is None:
                continue
            lon, lat = coords
            tags = el.get("tags") or {}
            osm_id = f"{el['type'][0]}{el['id']}"
            name, name_ne = _display_names(tags)

            if kind == "bridges":
                if str(tags.get("bridge") or "").strip().lower() == "no":
                    continue
                hw = str(tags.get("highway") or "").strip().lower()
                rw = str(tags.get("railway") or "").strip().lower()
                is_vehicular = bool(rw) or (hw in VEHICULAR_HIGHWAYS)
                is_trail = (not is_vehicular) and (hw in PEDESTRIAN_HIGHWAYS or not hw)
                layers["bridges"].append(
                    {
                        "osm": osm_id,
                        "kind": "bridges",
                        "lon": lon,
                        "lat": lat,
                        "name": name,
                        "name_ne": name_ne,
                        "highway": hw or rw or "unknown",
                        "ref": str(tags.get("ref") or "").strip(),
                        "is_vehicular": is_vehicular,
                        "is_trail": is_trail,
                    }
                )
            elif kind == "health":
                if NON_HUMAN_HEALTH_RE.search(name):
                    continue
                amenity = str(tags.get("amenity") or "").strip().lower()
                hc = str(tags.get("healthcare") or "").strip().lower()
                is_hospital = (amenity == "hospital" or hc == "hospital") and not re.search(
                    r"\b(sub[- ]?health ?post|shp)\b", name, re.IGNORECASE
                )
                layers["health"].append(
                    {
                        "osm": osm_id,
                        "kind": "health",
                        "lon": lon,
                        "lat": lat,
                        "name": name or ("Hospital" if is_hospital else "Health Clinic / Post"),
                        "name_ne": name_ne,
                        "amenity": amenity or hc or "clinic",
                        "is_hospital": is_hospital,
                        "emergency": str(tags.get("emergency") or "").strip().lower() == "yes",
                    }
                )
            elif kind == "hydropower":
                if str(tags.get("religion") or "").lower() == "prayer_wheel":
                    continue
                if str(tags.get("man_made") or "").lower() == "watermill":
                    continue
                mw = _parse_mw(
                    tags.get("plant:output:electricity")
                    or tags.get("generator:output:electricity")
                )
                layers["hydropower"].append(
                    {
                        "osm": osm_id,
                        "kind": "hydropower",
                        "lon": lon,
                        "lat": lat,
                        "name": name,
                        "name_ne": name_ne,
                        "power_type": str(tags.get("power") or "").strip().lower(),
                        "capacity_mw": mw,
                    }
                )
            else:  # places
                layers["places"].append(
                    {
                        "osm": osm_id,
                        "kind": "places",
                        "lon": lon,
                        "lat": lat,
                        "name": name,
                        "name_ne": name_ne,
                        "place_type": str(tags.get("place") or "").strip().lower(),
                        "pop": _parse_int(tags.get("population")),
                    }
                )
    return layers


# ---------------------------------------------------------------------------
# Fast spatial grid index & exact geometry helpers (stdlib only)
# ---------------------------------------------------------------------------
class SpatialGrid:
    """Fast 2D equirectangular grid index for nearest-neighbor & corridor queries."""

    def __init__(self, items: list[dict[str, Any]], cell_deg: float = 0.05) -> None:
        self.items = items
        self.cell_deg = cell_deg
        self.cells: dict[tuple[int, int], list[int]] = defaultdict(list)
        for idx, obj in enumerate(items):
            gx = int(math.floor(obj["lon"] / cell_deg))
            gy = int(math.floor(obj["lat"] / cell_deg))
            self.cells[(gx, gy)].append(idx)

    def query_bbox(
        self, min_lon: float, min_lat: float, max_lon: float, max_lat: float
    ) -> list[int]:
        gx0 = int(math.floor(min_lon / self.cell_deg))
        gx1 = int(math.floor(max_lon / self.cell_deg))
        gy0 = int(math.floor(min_lat / self.cell_deg))
        gy1 = int(math.floor(max_lat / self.cell_deg))
        out: list[int] = []
        for gx in range(gx0, gx1 + 1):
            for gy in range(gy0, gy1 + 1):
                bucket = self.cells.get((gx, gy))
                if bucket:
                    out.extend(bucket)
        return out

    def nearest(self, lon: float, lat: float, max_ring: int = 30) -> tuple[dict[str, Any] | None, float | None]:
        """Expanding-ring exact Haversine nearest-neighbor lookup."""
        if not self.items:
            return (None, None)
        gx0 = int(math.floor(lon / self.cell_deg))
        gy0 = int(math.floor(lat / self.cell_deg))
        best_obj: dict[str, Any] | None = None
        best_km = float("inf")
        found_ring: int | None = None

        for ring in range(0, max_ring + 1):
            if found_ring is not None and ring > found_ring + 1:
                break
            for gx in range(gx0 - ring, gx0 + ring + 1):
                for gy in range(gy0 - ring, gy0 + ring + 1):
                    if ring > 0 and abs(gx - gx0) < ring and abs(gy - gy0) < ring:
                        continue
                    bucket = self.cells.get((gx, gy))
                    if not bucket:
                        continue
                    for idx in bucket:
                        obj = self.items[idx]
                        d_km = SZ.haversine_km(lon, lat, obj["lon"], obj["lat"])
                        if d_km < best_km:
                            best_km = d_km
                            best_obj = obj
                            if found_ring is None:
                                found_ring = ring
        if best_obj is None:
            # Fallback full scan for extremely remote border locations
            for obj in self.items:
                d_km = SZ.haversine_km(lon, lat, obj["lon"], obj["lat"])
                if d_km < best_km:
                    best_km = d_km
                    best_obj = obj
        return (best_obj, round(best_km, 2) if best_obj is not None else None)


def _segments_intersect(
    ax: float, ay: float, bx: float, by: float, cx: float, cy: float, dx: float, dy: float
) -> bool:
    """Return True if closed 2D segments AB and CD intersect (proper crossing)."""
    if max(ax, bx) < min(cx, dx) or max(cx, dx) < min(ax, bx):
        return False
    if max(ay, by) < min(cy, dy) or max(cy, dy) < min(ay, by):
        return False

    def _orient(px: float, py: float, qx: float, qy: float, rx: float, ry: float) -> float:
        return (qx - px) * (ry - py) - (qy - py) * (rx - px)

    o1 = _orient(ax, ay, bx, by, cx, cy)
    o2 = _orient(ax, ay, bx, by, dx, dy)
    o3 = _orient(cx, cy, dx, dy, ax, ay)
    o4 = _orient(cx, cy, dx, dy, bx, by)
    return (o1 * o2 < 0.0) and (o3 * o4 < 0.0)


def _project_point_to_polyline(
    lon: float,
    lat: float,
    pts: list[list[float]],
    xs: list[float],
    ys: list[float],
    seg_lens: list[float],
    cum_kms: list[float],
    kx: float,
    ky: float,
) -> tuple[float, float]:
    """Return `(min_perp_dist_km, along_km)` for point `(lon, lat)` to polyline."""
    px = lon * kx
    py = lat * ky
    best_d2 = float("inf")
    best_along = 0.0
    for k in range(len(pts) - 1):
        x0, y0 = xs[k], ys[k]
        x1, y1 = xs[k + 1], ys[k + 1]
        dx, dy = x1 - x0, y1 - y0
        l2 = dx * dx + dy * dy
        if l2 > 1e-12:
            t = ((px - x0) * dx + (py - y0) * dy) / l2
            t = 0.0 if t < 0.0 else (1.0 if t > 1.0 else t)
        else:
            t = 0.0
        rx = x0 + t * dx - px
        ry = y0 + t * dy - py
        d2 = rx * rx + ry * ry
        if d2 < best_d2:
            best_d2 = d2
            best_along = cum_kms[k] + t * seg_lens[k]
    return (math.sqrt(best_d2), best_along)


def _find_corridor_hits(
    pts: list[list[float]],
    xs: list[float],
    ys: list[float],
    seg_lens: list[float],
    cum_kms: list[float],
    kx: float,
    ky: float,
    grid: SpatialGrid,
    corridor_km: float = 1.0,
) -> list[tuple[dict[str, Any], float, float]]:
    """Return `[(obj, along_km, offset_m), ...]` sorted by `along_km` within `corridor_km`."""
    corridor_km2 = corridor_km * corridor_km
    pad_deg = (corridor_km / 100.0) + 0.004
    best: dict[int, tuple[float, float]] = {}  # idx -> (dist_km, along_km)

    for k in range(len(pts) - 1):
        p0, p1 = pts[k], pts[k + 1]
        x0, y0 = xs[k], ys[k]
        x1, y1 = xs[k + 1], ys[k + 1]
        dx, dy = x1 - x0, y1 - y0
        l2 = dx * dx + dy * dy
        seg_len = seg_lens[k]

        mnl = min(p0[0], p1[0]) - pad_deg
        mxl = max(p0[0], p1[0]) + pad_deg
        mna = min(p0[1], p1[1]) - pad_deg
        mxa = max(p0[1], p1[1]) + pad_deg

        for idx in grid.query_bbox(mnl, mna, mxl, mxa):
            obj = grid.items[idx]
            plon, plat = obj["lon"], obj["lat"]
            if plon < mnl or plon > mxl or plat < mna or plat > mxa:
                continue
            px = plon * kx
            py = plat * ky
            if l2 > 1e-12:
                t = ((px - x0) * dx + (py - y0) * dy) / l2
                t = 0.0 if t < 0.0 else (1.0 if t > 1.0 else t)
            else:
                t = 0.0
            rx = x0 + t * dx - px
            ry = y0 + t * dy - py
            d2 = rx * rx + ry * ry
            if d2 <= corridor_km2:
                d_km = math.sqrt(d2)
                prev = best.get(idx)
                if prev is None or d_km < prev[0]:
                    best[idx] = (d_km, cum_kms[k] + t * seg_len)

    hits = [(grid.items[idx], along_km, d_km * 1000.0) for idx, (d_km, along_km) in best.items()]
    hits.sort(key=lambda h: (h[1], h[2]))
    return hits


def _deduplicated_hydro_mw(hydro_objs: list[dict[str, Any]]) -> float:
    """Sum tagged hydropower MW while avoiding OSM plant+generator double-counting."""
    plants = [o for o in hydro_objs if o.get("power_type") == "plant" and o.get("capacity_mw")]
    gens = [o for o in hydro_objs if o.get("power_type") != "plant" and o.get("capacity_mw")]
    total = sum(float(p["capacity_mw"]) for p in plants)
    for g in gens:
        # Skip generator if within 250 m of an already-counted tagged plant
        dup_of_plant = any(
            SZ.haversine_km(g["lon"], g["lat"], p["lon"], p["lat"]) <= 0.25 for p in plants
        )
        if not dup_of_plant:
            total += float(g["capacity_mw"])
    return round(total, 2)


def _classify_corridor_disruption_risk(
    n_isolated: int,
    n_bridges: int,
    n_vehicular_bridges: int,
    nearest_hosp_med_km: float | None,
    nearest_hosp_max_km: float | None,
) -> str:
    """Transparent 3-tier corridor road-cut hospital isolation screening risk.

    Calibrated across Nepal's 120 km Himalayan valley corridors so prioritization
    distinguishes severe multi-bridge highway/hospital choke points (`high`)
    from moderate valley disruption (`moderate`) and lower-exposure corridors (`low`).
    """
    med = nearest_hosp_med_km if nearest_hosp_med_km is not None else 0.0
    mx = nearest_hosp_max_km if nearest_hosp_max_km is not None else 0.0
    if (
        (n_isolated >= 10 and n_vehicular_bridges >= 20 and mx >= 25.0)
        or (n_isolated >= 20 and n_vehicular_bridges >= 15 and med >= 8.0)
        or (n_isolated >= 40 and n_bridges >= 50 and med >= 7.0)
        or (n_isolated >= 10 and med >= 15.0 and n_bridges >= 20)
    ):
        return "high"
    if (
        (n_isolated >= 10 and n_bridges >= 20)
        or (n_isolated >= 5 and n_vehicular_bridges >= 5)
        or (n_isolated >= 1 and mx >= 20.0 and n_bridges >= 5)
    ):
        return "moderate"
    return "low"


# ---------------------------------------------------------------------------
# Main analysis builder
# ---------------------------------------------------------------------------
def build_exposure_isolation(
    lakes_path: str | None = None,
    routes_path: str | None = None,
    exposure_path: str | None = None,
    districts_path: str | None = None,
    overpass_dir: str | None = None,
    out_path: str = OUT_JSON,
    corridor_km: float = C.EXPOSURE_CORRIDOR_M / 1000.0,
) -> dict[str, Any]:
    """Compute per-lake & per-district exposure breakdown and road-cut hospital isolation."""
    lakes_p = lakes_path or os.path.join(C.DATA, "lakes_core.json")
    routes_p = routes_path or os.path.join(C.DATA, "routes.json")
    expo_p = exposure_path or os.path.join(C.DATA, "exposure.json")
    dist_p = districts_path or os.path.join(C.DATA, "districts.json")

    with open(lakes_p, encoding="utf-8") as fh:
        lakes_raw = json.load(fh)
    lakes_fc = RW.unpack_lakes_core(lakes_raw)
    lake_props: dict[str, dict[str, Any]] = {
        f["properties"]["id"]: f["properties"] for f in lakes_fc.get("features") or []
    }

    with open(routes_p, encoding="utf-8") as fh:
        routes: dict[str, dict[str, Any]] = json.load(fh)

    expo_compact_count = 0
    if os.path.exists(expo_p):
        with open(expo_p, encoding="utf-8") as fh:
            expo_compact_count = len(json.load(fh))

    with open(dist_p, encoding="utf-8") as fh:
        districts_doc = json.load(fh)

    layers = load_overpass_layers(overpass_dir)
    hospitals_only = [h for h in layers["health"] if h["is_hospital"]]

    grid_places = SpatialGrid(layers["places"], cell_deg=0.05)
    grid_health = SpatialGrid(layers["health"], cell_deg=0.05)
    grid_hospitals = SpatialGrid(hospitals_only, cell_deg=0.05)
    grid_bridges = SpatialGrid(layers["bridges"], cell_deg=0.05)
    grid_hydro = SpatialGrid(layers["hydropower"], cell_deg=0.05)

    adm = HM.StdlibAdminLookup()

    # Cache nearest health facility & nearest hospital per settlement OSM id
    nearest_health_cache: dict[str, tuple[dict[str, Any] | None, float | None]] = {}
    nearest_hosp_cache: dict[str, tuple[dict[str, Any] | None, float | None]] = {}
    dist_lookup_cache: dict[str, str | None] = {}

    def _get_district(osm_id: str, lon: float, lat: float) -> str | None:
        if osm_id not in dist_lookup_cache:
            dist_lookup_cache[osm_id] = adm.district(lon, lat) or None
        return dist_lookup_cache[osm_id]

    def _get_nearest_health(obj: dict[str, Any]) -> tuple[dict[str, Any] | None, float | None]:
        oid = obj["osm"]
        if oid not in nearest_health_cache:
            nearest_health_cache[oid] = grid_health.nearest(obj["lon"], obj["lat"])
        return nearest_health_cache[oid]

    def _get_nearest_hospital(obj: dict[str, Any]) -> tuple[dict[str, Any] | None, float | None]:
        oid = obj["osm"]
        if oid not in nearest_hosp_cache:
            nearest_hosp_cache[oid] = grid_hospitals.nearest(obj["lon"], obj["lat"])
        return nearest_hosp_cache[oid]

    # Per-district deduplicated accumulators
    dist_corridors: dict[str, set[str]] = defaultdict(set)
    dist_high_risk_corridors: dict[str, set[str]] = defaultdict(set)
    dist_places: dict[str, dict[str, dict[str, Any]]] = defaultdict(dict)
    dist_isolated_places: dict[str, dict[str, float]] = defaultdict(dict)  # osm -> nearest_hosp_km
    dist_bridges: dict[str, dict[str, dict[str, Any]]] = defaultdict(dict)
    dist_health: dict[str, dict[str, dict[str, Any]]] = defaultdict(dict)
    dist_hydro: dict[str, dict[str, dict[str, Any]]] = defaultdict(dict)

    lakes_out: dict[str, dict[str, Any]] = {}
    risk_counts: Counter[str] = Counter()
    all_unique_isolated_places: set[str] = set()
    all_unique_bridges: set[str] = set()
    all_unique_hydro: dict[str, dict[str, Any]] = {}

    for lid, r in routes.items():
        pts = r.get("path") or []
        lp = lake_props.get(lid) or {}
        if len(pts) < 2:
            continue

        lat0 = sum(p[1] for p in pts) / len(pts)
        kx = 111.320 * math.cos(math.radians(lat0))
        ky = 110.540
        xs = [p[0] * kx for p in pts]
        ys = [p[1] * ky for p in pts]
        seg_lens: list[float] = []
        cum_kms: list[float] = [0.0]
        for k in range(len(pts) - 1):
            sl = math.hypot(xs[k + 1] - xs[k], ys[k + 1] - ys[k])
            seg_lens.append(sl)
            cum_kms.append(cum_kms[-1] + sl)

        # Find all 1 km corridor hits across all 4 layers
        place_hits = _find_corridor_hits(pts, xs, ys, seg_lens, cum_kms, kx, ky, grid_places, corridor_km)
        health_hits = _find_corridor_hits(pts, xs, ys, seg_lens, cum_kms, kx, ky, grid_health, corridor_km)
        bridge_hits = _find_corridor_hits(pts, xs, ys, seg_lens, cum_kms, kx, ky, grid_bridges, corridor_km)
        hydro_hits = _find_corridor_hits(pts, xs, ys, seg_lens, cum_kms, kx, ky, grid_hydro, corridor_km)

        # Track traversed districts along route
        traversed_districts: set[str] = set()
        if lp.get("district"):
            traversed_districts.add(str(lp["district"]))
        for k, pt in enumerate(pts):
            d_hit = adm.district(pt[0], pt[1])
            if d_hit:
                traversed_districts.add(d_hit)
            if k + 1 < len(pts):
                d_mid = adm.district(0.5 * (pt[0] + pts[k + 1][0]), 0.5 * (pt[1] + pts[k + 1][1]))
                if d_mid:
                    traversed_districts.add(d_mid)

        # Bridge breakdown
        n_bridges = len(bridge_hits)
        n_veh_bridges = sum(1 for b, _, _ in bridge_hits if b["is_vehicular"])
        n_trail_bridges = n_bridges - n_veh_bridges
        n_crit_250m = sum(1 for _, _, off_m in bridge_hits if off_m <= 250.0)
        bridge_along_kms = [akm for _, akm, _ in bridge_hits]
        max_bridge_km = max(bridge_along_kms) if bridge_along_kms else -1.0

        # Health breakdown inside 1 km corridor
        n_health_corr = len(health_hits)
        n_hospitals_corr = sum(1 for h, _, _ in health_hits if h["is_hospital"])
        min_health_km = health_hits[0][1] if health_hits else None

        # Hydropower breakdown inside 1 km corridor
        hydro_objs = [h for h, _, _ in hydro_hits]
        n_hydro = len(hydro_objs)
        hydro_mw = _deduplicated_hydro_mw(hydro_objs)

        # Road-cut hospital isolation analysis for every corridor settlement
        isolated_examples: list[dict[str, Any]] = []
        n_isolated = 0
        hosp_dists_km: list[float] = []
        health_dists_km: list[float] = []

        for s_obj, s_km, _s_off in place_hits:
            nh_obj, nh_km = _get_nearest_health(s_obj)
            hosp_obj, hosp_km = _get_nearest_hospital(s_obj)
            if nh_km is not None:
                health_dists_km.append(nh_km)
            if hosp_km is not None:
                hosp_dists_km.append(hosp_km)

            mech: str | None = None
            if n_bridges > 0 and nh_obj is not None and nh_km is not None:
                # 1. Does nearest health facility lie downstream along corridor with a bridge between?
                h_perp_km, h_along_km = _project_point_to_polyline(
                    nh_obj["lon"], nh_obj["lat"], pts, xs, ys, seg_lens, cum_kms, kx, ky
                )
                if h_perp_km <= 5.0 and h_along_km > s_km + 0.2:
                    if any((s_km - 0.5) <= bk <= (h_along_km + 0.5) for bk in bridge_along_kms):
                        mech = "downstream_bridge_cut"

                # 2. Does straight access vector S -> nearest health facility cross the routed channel?
                if mech is None:
                    sx, sy = s_obj["lon"], s_obj["lat"]
                    hx, hy = nh_obj["lon"], nh_obj["lat"]
                    for k in range(len(pts) - 1):
                        if _segments_intersect(
                            sx, sy, hx, hy, pts[k][0], pts[k][1], pts[k + 1][0], pts[k + 1][1]
                        ):
                            mech = "cross_river_bridge_cut"
                            break

                # 3. Upper-valley single-egress settlement upstream of any corridor clinic/hospital
                if mech is None:
                    if (
                        (min_health_km is None or s_km < min_health_km)
                        and max_bridge_km >= (s_km - 0.5)
                        and nh_km > 2.0
                    ):
                        mech = "upper_valley_single_egress_cut"

            d_s = _get_district(s_obj["osm"], s_obj["lon"], s_obj["lat"])
            if d_s:
                dist_places[d_s][s_obj["osm"]] = s_obj
            if mech is not None:
                n_isolated += 1
                all_unique_isolated_places.add(s_obj["osm"])
                if d_s and hosp_km is not None:
                    prev_hk = dist_isolated_places[d_s].get(s_obj["osm"])
                    if prev_hk is None or hosp_km > prev_hk:
                        dist_isolated_places[d_s][s_obj["osm"]] = hosp_km
                if len(isolated_examples) < 5 and s_obj["name"]:
                    isolated_examples.append(
                        {
                            "name": s_obj["name"],
                            "along_km": round(s_km, 1),
                            "nearest_hospital_km": hosp_km,
                            "mechanism": mech,
                        }
                    )

        # Accumulate unique district-level corridor infrastructure (no double counting!)
        for b_obj, _, _ in bridge_hits:
            all_unique_bridges.add(b_obj["osm"])
            db = _get_district(b_obj["osm"], b_obj["lon"], b_obj["lat"])
            if db:
                dist_bridges[db][b_obj["osm"]] = b_obj
        for h_obj, _, _ in health_hits:
            dh = _get_district(h_obj["osm"], h_obj["lon"], h_obj["lat"])
            if dh:
                dist_health[dh][h_obj["osm"]] = h_obj
        for hp_obj in hydro_objs:
            all_unique_hydro[hp_obj["osm"]] = hp_obj
            dhp = _get_district(hp_obj["osm"], hp_obj["lon"], hp_obj["lat"])
            if dhp:
                dist_hydro[dhp][hp_obj["osm"]] = hp_obj

        nearest_hosp_med = round(_median(hosp_dists_km), 2) if hosp_dists_km else None
        nearest_hosp_max = round(max(hosp_dists_km), 2) if hosp_dists_km else None
        nearest_health_med = round(_median(health_dists_km), 2) if health_dists_km else None

        disruption_risk = _classify_corridor_disruption_risk(
            n_isolated=n_isolated,
            n_bridges=n_bridges,
            n_vehicular_bridges=n_veh_bridges,
            nearest_hosp_med_km=nearest_hosp_med,
            nearest_hosp_max_km=nearest_hosp_max,
        )
        risk_counts[disruption_risk] += 1

        for td in traversed_districts:
            dist_corridors[td].add(lid)
            if disruption_risk == "high":
                dist_high_risk_corridors[td].add(lid)

        # Top named vehicular / channel-crossing bridges (deduplicated by name;
        # prefer true bridge names over bare highway ref codes)
        raw_named_bridges = [
            {
                "name": b["name"],
                "highway": b["highway"],
                "vehicular": b["is_vehicular"],
                "along_km": round(akm, 1),
                "offset_m": int(round(off_m)),
                "_is_ref_only": bool(b["ref"] and b["name"] == b["ref"]),
            }
            for b, akm, off_m in bridge_hits
            if b["name"]
        ]
        raw_named_bridges.sort(
            key=lambda x: (x["_is_ref_only"], not x["vehicular"], x["offset_m"], x["along_km"])
        )
        named_bridges: list[dict[str, Any]] = []
        seen_bnames: set[str] = set()
        for nb in raw_named_bridges:
            bn_key = nb["name"].lower()
            if bn_key in seen_bnames:
                continue
            seen_bnames.add(bn_key)
            named_bridges.append(
                {
                    "name": nb["name"],
                    "highway": nb["highway"],
                    "vehicular": nb["vehicular"],
                    "along_km": nb["along_km"],
                    "offset_m": nb["offset_m"],
                }
            )
            if len(named_bridges) >= 5:
                break

        lakes_out[lid] = {
            "lake_id": lid,
            "name": lp.get("name") or lid,
            "district": lp.get("district"),
            "province": FL.canonical_province(lp.get("prov")) if lp.get("prov") else None,
            "route_km": round(float(r.get("km") or cum_kms[-1]), 1),
            "traversed_districts": sorted(traversed_districts),
            # Dimension 1: Published GLOF hazard class untouched
            "hazard_susceptibility_static": {
                "hazard": lp.get("hazard"),
                "hazard_enum": lp.get("hazard_enum"),
                "impact_published": lp.get("impact"),
                "risk_published": lp.get("risk"),
                "priority": bool(lp.get("priority")),
                "pfv_Mm3": lp.get("pfv_Mm3"),
                "ice_cored": bool(lp.get("ice_cored")),
            },
            # Dimension 2: 1 km screening corridor exposure
            "corridor_exposure_screening": {
                "search_corridor_m": int(round(corridor_km * 1000.0)),
                "settlements": len(place_hits),
                "health_facilities": n_health_corr,
                "hospitals": n_hospitals_corr,
                "bridges": n_bridges,
                "vehicular_bridges": n_veh_bridges,
                "trail_bridges": n_trail_bridges,
                "hydropower_facilities": n_hydro,
                "hydropower_mw_tagged": hydro_mw,
                "hydropower_named": [
                    {
                        "name": h["name"],
                        "capacity_mw": h["capacity_mw"],
                    }
                    for h in hydro_objs
                    if h["name"]
                ][:8],
            },
            # Dimension 3: Road-cut hospital isolation analysis
            "road_cut_hospital_isolation": {
                "bridges_at_corridor_crossing": n_bridges,
                "vehicular_bridges_at_crossing": n_veh_bridges,
                "trail_bridges_at_crossing": n_trail_bridges,
                "critical_channel_bridges_250m": n_crit_250m,
                "upstream_settlements_potentially_isolated": n_isolated,
                "nearest_hospital_km": nearest_hosp_med,
                "nearest_hospital_max_km": nearest_hosp_max,
                "nearest_health_facility_km": nearest_health_med,
                "corridor_disruption_risk": disruption_risk,
                "critical_bridge_examples": named_bridges[:5],
                "isolated_settlement_examples": isolated_examples,
            },
        }

    # Build 77-district isolation & exposure summary
    districts_out: list[dict[str, Any]] = []
    dist_risk_counts: Counter[str] = Counter()

    for d_rec in districts_doc.get("districts") or []:
        dname = d_rec["name"]
        c_ids = sorted(dist_corridors.get(dname, set()))
        hi_ids = sorted(dist_high_risk_corridors.get(dname, set()))
        d_pl = dist_places.get(dname, {})
        d_iso = dist_isolated_places.get(dname, {})
        d_br = dist_bridges.get(dname, {})
        d_hl = dist_health.get(dname, {})
        d_hp = dist_hydro.get(dname, {})

        n_br = len(d_br)
        n_vbr = sum(1 for b in d_br.values() if b["is_vehicular"])
        n_hosp = sum(1 for h in d_hl.values() if h["is_hospital"])
        hp_mw = _deduplicated_hydro_mw(list(d_hp.values()))
        iso_dists = list(d_iso.values())
        med_hosp = round(_median(iso_dists), 2) if iso_dists else None
        max_hosp = round(max(iso_dists), 2) if iso_dists else None

        if not c_ids:
            d_risk = "none"
        else:
            d_risk = _classify_corridor_disruption_risk(
                n_isolated=len(d_iso),
                n_bridges=n_br,
                n_vehicular_bridges=n_vbr,
                nearest_hosp_med_km=med_hosp,
                nearest_hosp_max_km=max_hosp,
            )
            if hi_ids and d_risk == "low":
                d_risk = "moderate"
        dist_risk_counts[d_risk] += 1

        # Top 5 corridors in this district by isolated settlements then PFV
        top_corrs = sorted(
            c_ids,
            key=lambda lid: (
                lakes_out[lid]["road_cut_hospital_isolation"]["upstream_settlements_potentially_isolated"],
                float(lakes_out[lid]["hazard_susceptibility_static"].get("pfv_Mm3") or 0.0),
            ),
            reverse=True,
        )[:5]

        districts_out.append(
            {
                "name": dname,
                "name_ne": d_rec.get("name_ne", dname),
                "prov": FL.canonical_province(d_rec.get("prov")),
                "prov_ne": d_rec.get("prov_ne", ""),
                "n_routed_corridors": len(c_ids),
                "n_high_disruption_corridors": len(hi_ids),
                "unique_settlements_in_1km_corridors": len(d_pl),
                "unique_health_facilities_in_corridors": len(d_hl),
                "unique_hospitals_in_corridors": n_hosp,
                "unique_bridges_at_crossings": n_br,
                "unique_vehicular_bridges_at_crossings": n_vbr,
                "unique_hydropower_in_corridors": len(d_hp),
                "hydropower_mw_exposed": hp_mw,
                "unique_settlements_potentially_isolated": len(d_iso),
                "nearest_hospital_km": med_hosp,
                "nearest_hospital_max_km": max_hosp,
                "district_isolation_risk": d_risk,
                "top_corridor_lake_ids": top_corrs,
            }
        )

    now_utc = dt.datetime.now(dt.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    top_priority_corridors = sorted(
        lakes_out.values(),
        key=lambda x: (
            1 if x["hazard_susceptibility_static"]["priority"] else 0,
            x["road_cut_hospital_isolation"]["upstream_settlements_potentially_isolated"],
            x["road_cut_hospital_isolation"]["bridges_at_corridor_crossing"],
        ),
        reverse=True,
    )[:20]

    payload: dict[str, Any] = {
        "schema_version": SCHEMA_VERSION,
        "generated_utc": now_utc,
        "data_class": "static_assessment",
        "methodology_notice": METHODOLOGY_NOTICE,
        # Explicit separation of the 4 conceptual dimensions
        "dimensions": {
            "1_hazard_susceptibility_static": (
                "Published Rounce et al. (2016) GLOF hazard classes and Fujita et al. (2013) "
                "Potential Flood Volume (PFV), preserved strictly untouched from lakes_core.json."
            ),
            "2_corridor_exposure_screening": (
                "Exact perpendicular point-to-segment screening inventory within a 1 km search "
                "corridor of HydroRIVERS/DEM routed channels (NOT a 2D inundation polygon)."
            ),
            "3_road_cut_hospital_isolation": (
                "Functional healthcare-access isolation screening identifying corridor settlements "
                "whose nearest mapped clinic/hospital lies downstream of or across impacted corridor "
                "bridges, paired with nearest mapped hospital distance and disruption tier."
            ),
            "4_uncertainty_and_coverage_limits": (
                "OpenStreetMap coverage in rural Himalayan valleys is incomplete (lower bound). "
                "Distances are straight-line geodesic km rather than road-network travel time, and "
                "bridge hydraulic scour/deck clearance is not modelled."
            ),
        },
        "uncertainty_and_coverage_limits": {
            "osm_completeness_caveat": (
                "OSM settlements, clinics, hospitals, bridges, and hydropower MW tags are lower bounds; "
                "absence of mapped facilities does not imply absence on the ground."
            ),
            "corridor_not_inundation_boundary": True,
            "published_hazard_classes_modified": False,
            "distance_metric": "geodesic_haversine_km_not_road_network_travel_time",
            "overpass_inventory_totals": {
                "places": len(layers["places"]),
                "human_health_facilities": len(layers["health"]),
                "human_hospitals": len(hospitals_only),
                "bridges": len(layers["bridges"]),
                "hydropower_facilities": len(layers["hydropower"]),
                "compact_exposure_reference_count": expo_compact_count,
            },
        },
        "summary": {
            "n_routed_lakes_analyzed": len(lakes_out),
            "n_districts_analyzed": len(districts_out),
            "corridor_disruption_risk_counts": {
                "high": int(risk_counts.get("high", 0)),
                "moderate": int(risk_counts.get("moderate", 0)),
                "low": int(risk_counts.get("low", 0)),
            },
            "district_isolation_risk_counts": {
                "high": int(dist_risk_counts.get("high", 0)),
                "moderate": int(dist_risk_counts.get("moderate", 0)),
                "low": int(dist_risk_counts.get("low", 0)),
                "none": int(dist_risk_counts.get("none", 0)),
            },
            "total_unique_settlements_potentially_isolated": len(all_unique_isolated_places),
            "total_unique_bridges_at_crossings": len(all_unique_bridges),
            "total_unique_hydropower_in_corridors": len(all_unique_hydro),
            "total_unique_hydropower_mw_in_corridors": _deduplicated_hydro_mw(
                list(all_unique_hydro.values())
            ),
            "top_corridor_ids_by_isolation": [c["lake_id"] for c in top_priority_corridors],
        },
        "districts": districts_out,
        "lakes": lakes_out,
        "provenance": {
            "schema_version": SCHEMA_VERSION,
            "generated_utc": now_utc,
            "data_class": "static_assessment",
            "mode": "offline_local_computation",
            "license_ref": "ODbL 1.0 (OpenStreetMap); HydroSHEDS; CC-BY-4.0 (TRĀYA screening layer)",
            "sources": [
                {"provider_id": "traya_lakes_core", "path": "data/lakes_core.json", "role": "Published GLOF hazard & PFV (untouched)"},
                {"provider_id": "traya_routes", "path": "data/routes.json", "role": "120 km HydroRIVERS/DEM routed GLOF channels"},
                {"provider_id": "osm_overpass", "path": "cache/overpass/places.json", "role": "Mapped Nepal settlements"},
                {"provider_id": "osm_overpass", "path": "cache/overpass/health.json", "role": "Mapped Nepal hospitals & clinics (veterinary excluded)"},
                {"provider_id": "osm_overpass", "path": "cache/overpass/bridges.json", "role": "Mapped road & trail bridges (bridge=no excluded)"},
                {"provider_id": "osm_overpass", "path": "cache/overpass/hydropower.json", "role": "Mapped hydropower plants & tagged MW"},
                {"provider_id": "osm_admin", "path": "data/districts.json", "role": "77 canonical Nepal districts & 7 provinces"},
            ],
        },
    }

    _atomic_write_json(out_path, payload)
    return payload


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(
        description="Nepal TRĀYA 2.0 downstream exposure & road-cut hospital isolation engine"
    )
    ap.add_argument("--out", default=OUT_JSON, help="Output JSON path")
    args = ap.parse_args(argv)

    res = build_exposure_isolation(out_path=args.out)
    s = res["summary"]
    print(
        f"[exposure_isolation] wrote {args.out}: lakes={s['n_routed_lakes_analyzed']}, "
        f"districts={s['n_districts_analyzed']}, "
        f"corridor_risk={s['corridor_disruption_risk_counts']}, "
        f"unique_isolated_settlements={s['total_unique_settlements_potentially_isolated']}, "
        f"unique_bridges={s['total_unique_bridges_at_crossings']}, "
        f"hydro_mw={s['total_unique_hydropower_mw_in_corridors']}"
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
