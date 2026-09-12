"""
Terrain analysis for each glacial lake from the Copernicus DEM GLO-30.

Implements, per lake:

  * lake surface elevation and area
  * slope field (anisotropic cell size, EPSG:4326 grid)
  * snow/ice avalanche and rockfall source areas
        Alean (1985); Bolch et al. (2011); Osti et al. (2011); Shea et al. (2015)
        as applied by Rounce et al. (2016)
  * reach-angle (Fahrboeschung) runout test with the volume-dependent avalanche
    threshold of Huggel et al. (2004b)
  * steep lakefront area (SLA), potential lowering height (Hp) and potential
    flood volume (PFV) exactly as defined by Fujita et al. (2013)

Mass-movement trajectories follow Rounce et al. (2016): a single-flow-direction
(D8) route is computed on the window DEM, only source cells whose route
terminates in the lake are considered, and the reach angle is measured over the
routed path length rather than the straight-line distance.

Documented departure from Rounce et al. (2016): avalanche-prone area is taken as
the part of the contiguous source patch that drains to the lake, rather than
their variable-kernel filter. This is a different estimator of the same quantity
and it only affects which reach-angle threshold applies (Huggel et al. 2004b),
not the routing.
"""
from __future__ import annotations
import math
import os
from functools import lru_cache

import numpy as np
import rasterio
from rasterio import features
from rasterio.merge import merge as rio_merge
from rasterio.windows import from_bounds
from scipy import ndimage
from shapely.geometry import shape, box
from shapely.strtree import STRtree

import config as C


# ---------------------------------------------------------------------------
# DEM access
# ---------------------------------------------------------------------------
class DemReader:
    """Reads windows from the 1x1 degree Copernicus DEM tile set, mosaicking
    across tile boundaries where necessary."""

    def __init__(self, tile_dir: str = C.DEM_DIR):
        self.tile_dir = tile_dir
        self.index = {}
        for fn in os.listdir(tile_dir):
            if not fn.endswith(".tif"):
                continue
            # Copernicus_DSM_COG_10_N27_00_E086_00_DEM.tif
            parts = fn.split("_")
            lat = int(parts[4][1:]) * (1 if parts[4][0] == "N" else -1)
            lon = int(parts[6][1:]) * (1 if parts[6][0] == "E" else -1)
            self.index[(lat, lon)] = os.path.join(tile_dir, fn)

    def read(self, bounds):
        """Return (array, transform) for the given (minx, miny, maxx, maxy)."""
        minx, miny, maxx, maxy = bounds
        need = []
        for lat in range(math.floor(miny), math.ceil(maxy)):
            for lon in range(math.floor(minx), math.ceil(maxx)):
                p = self.index.get((lat, lon))
                if p:
                    need.append(p)
        if not need:
            raise FileNotFoundError(f"no DEM tile covers {bounds}")
        if len(need) == 1:
            with rasterio.open(need[0]) as src:
                w = from_bounds(*bounds, src.transform).round_offsets().round_lengths()
                arr = src.read(1, window=w, boundless=True, fill_value=np.nan)
                return arr.astype("float32"), src.window_transform(w)
        srcs = [rasterio.open(p) for p in need]
        try:
            arr, tr = rio_merge(srcs, bounds=bounds, nodata=np.nan)
            return arr[0].astype("float32"), tr
        finally:
            for s in srcs:
                s.close()


def cell_metres(lat_deg: float, res_deg: float) -> tuple[float, float]:
    """Approximate east-west and north-south cell size in metres for a
    geographic grid at the given latitude (WGS84)."""
    dy = 111_132.92 - 559.82 * math.cos(2 * math.radians(lat_deg))
    dx = 111_412.84 * math.cos(math.radians(lat_deg)) \
        - 93.5 * math.cos(3 * math.radians(lat_deg))
    return abs(dx * res_deg), abs(dy * res_deg)


def slope_deg(dem: np.ndarray, dx: float, dy: float) -> np.ndarray:
    """Horn (1981) third-order finite difference slope, in degrees."""
    z = dem
    gy, gx = np.gradient(z, dy, dx)      # note: axis 0 is north-south
    return np.degrees(np.arctan(np.hypot(gx, gy)))


# ---------------------------------------------------------------------------
# Per-lake analysis
# ---------------------------------------------------------------------------
def analyse_lake(lake_geom, lake_props, dem_reader: DemReader,
                 glacier_tree: STRtree, glacier_geoms,
                 buffer_km: float = 8.0) -> dict:
    """Run the full terrain analysis for a single lake polygon."""
    poly = shape(lake_geom)
    cx, cy = poly.centroid.x, poly.centroid.y
    res = 1.0 / 3600.0
    dxm, dym = cell_metres(cy, res)
    bx = buffer_km * 1000.0 / dxm * res
    by = buffer_km * 1000.0 / dym * res
    minx, miny, maxx, maxy = poly.bounds
    bounds = (minx - bx, miny - by, maxx + bx, maxy + by)

    dem, tr = dem_reader.read(bounds)
    if dem.size == 0 or not np.isfinite(dem).any():
        return dict(error="no DEM")
    h, w = dem.shape

    lake_mask = features.rasterize([(poly, 1)], out_shape=(h, w), transform=tr,
                                  dtype="uint8", all_touched=True).astype(bool)
    if not lake_mask.any():
        # lake smaller than one cell: use the centroid cell
        r, c = rasterio.transform.rowcol(tr, cx, cy)
        if 0 <= r < h and 0 <= c < w:
            lake_mask[r, c] = True
        else:
            return dict(error="lake outside window")

    z_lake = float(np.nanmedian(dem[lake_mask]))
    slope = slope_deg(dem, dxm, dym)

    # ---- distance to the nearest lakeshore cell, in metres -----------------
    # anisotropic sampling keeps the metric distance correct
    dist_px = ndimage.distance_transform_edt(~lake_mask, sampling=(dym, dxm))

    # ---- glacier mask ------------------------------------------------------
    win_box = box(*bounds)
    idx = glacier_tree.query(win_box)
    shapes = []
    for i in np.atleast_1d(idx):
        g = glacier_geoms[int(i)]
        if g.intersects(win_box):
            shapes.append((g, 1))
    glacier = (features.rasterize(shapes, out_shape=(h, w), transform=tr,
                                 dtype="uint8", all_touched=True).astype(bool)
               if shapes else np.zeros((h, w), bool))

    # ---- steep lakefront area (Fujita et al. 2013) -------------------------
    sla = _sla(dem, lake_mask, dist_px, z_lake, dxm, dym)

    # ---- mass-movement source areas and runout -----------------------------
    dem_filled = fill_depressions(dem)
    dem_filled[lake_mask] = z_lake          # keep the lake itself as the sink
    drains, plen = d8_route_to_lake(dem_filled, lake_mask, dxm, dym)
    ava = _mass_movement(dem, slope, glacier, lake_mask, dist_px, z_lake,
                         dxm, dym, kind="avalanche", drains=drains, plen=plen)
    rock = _mass_movement(dem, slope, glacier, lake_mask, dist_px, z_lake,
                          dxm, dym, kind="rockfall", drains=drains, plen=plen)

    return dict(
        z_lake_m=z_lake,
        contributing_area_km2=float(drains.sum() * dxm * dym / 1e6),
        relief_above_m=float(np.nanmax(dem) - z_lake),
        max_slope_1km_deg=float(np.nanmax(slope[(dist_px <= 1000) & ~lake_mask]))
        if np.any((dist_px <= 1000) & ~lake_mask) else None,
        ice_contact_cells=int(np.count_nonzero(glacier & _dilate(lake_mask))),
        **sla, avalanche=ava, rockfall=rock,
    )


def _dilate(m: np.ndarray, n: int = 2) -> np.ndarray:
    return ndimage.binary_dilation(m, iterations=n)


def _sla(dem, lake_mask, dist_px, z_lake, dxm, dym) -> dict:
    """Steep lakefront area, potential lowering height and potential flood volume.

    Fujita et al. (2013): for every point within 1 km of the lake, the depression
    angle from the lake surface to that point is computed using the distance to
    the nearest section of lakeshore; the SLA is the area where that angle exceeds
    10 degrees. Hp is the lake-surface lowering that removes the SLA. With the
    mean depth Dm = 55 A^0.25 (A in km2), PFV = min[Hp, Dm] * A.
    """
    cell_area = dxm * dym
    near = (dist_px > 0) & (dist_px <= C.SLA_BUFFER_OUTER_M) & ~lake_mask
    if not near.any():
        return dict(sla_area_m2=0.0, sla_max_angle_deg=None, sla_min_distance_m=None,
                    hp_m=0.0)
    drop = z_lake - dem
    with np.errstate(divide="ignore", invalid="ignore"):
        ang = np.degrees(np.arctan(np.where(near, drop, np.nan) / np.where(near, dist_px, np.nan)))
    steep = np.nan_to_num(ang, nan=-90.0) > C.SLA_THRESHOLD_DEG
    # require a contiguous patch of at least 4 cells to suppress single-cell noise
    lab, n = ndimage.label(steep)
    if n:
        sizes = ndimage.sum(np.ones_like(lab), lab, range(1, n + 1))
        keep = np.isin(lab, 1 + np.flatnonzero(sizes >= 4))
    else:
        keep = np.zeros_like(steep)
    area = float(np.count_nonzero(keep) * cell_area)
    out = dict(sla_area_m2=area,
               sla_max_angle_deg=float(np.nanmax(ang)) if np.isfinite(ang).any() else None,
               sla_min_distance_m=float(dist_px[keep].min()) if keep.any() else None)

    # potential lowering height: bisect on the lowering that removes the SLA
    hp = 0.0
    if area > 0:
        lo, hi = 0.0, C.HP_SEARCH_MAX_M
        for _ in range(24):
            mid = 0.5 * (lo + hi)
            with np.errstate(divide="ignore", invalid="ignore"):
                a2 = np.degrees(np.arctan(np.where(near, (z_lake - mid) - dem, np.nan)
                                          / np.where(near, dist_px, np.nan)))
            s2 = np.nan_to_num(a2, nan=-90.0) > C.SLA_THRESHOLD_DEG
            l2, n2 = ndimage.label(s2)
            if n2:
                sz = ndimage.sum(np.ones_like(l2), l2, range(1, n2 + 1))
                remains = (sz >= 4).any()
            else:
                remains = False
            if remains:
                lo = mid
            else:
                hi = mid
        hp = hi
    out["hp_m"] = float(hp)
    return out


def fill_depressions(dem: np.ndarray) -> np.ndarray:
    """Fill closed depressions by morphological reconstruction by erosion
    (the Planchon-Darboux / Soille fill). Rounce et al. (2016) likewise route
    mass movements on a sink-free DEM."""
    from skimage.morphology import reconstruction
    z = np.array(dem, dtype="float64")
    bad = ~np.isfinite(z)
    if bad.all():
        return dem
    z[bad] = np.nanmin(z[~bad])
    seed = np.full_like(z, z.max())
    seed[0, :] = z[0, :]
    seed[-1, :] = z[-1, :]
    seed[:, 0] = z[:, 0]
    seed[:, -1] = z[:, -1]
    filled = reconstruction(seed, z, method="erosion")
    out = np.asarray(filled, dtype="float32")
    out[bad] = np.nan
    return out


def d8_route_to_lake(dem: np.ndarray, lake_mask: np.ndarray,
                     dxm: float, dym: float):
    """Single-flow-direction (D8) routing.

    Returns (drains_to_lake, path_length_m):
      drains_to_lake  bool array, True where the steepest-descent route from the
                      cell terminates in the lake
      path_length_m   float array, routed distance to the lake (inf elsewhere)

    Cells with no lower neighbour (pits) terminate the route and do not drain.
    Processing in ascending elevation order guarantees that a cell's receiver is
    resolved before the cell itself, because a receiver is always lower.
    """
    h, w = dem.shape
    z = np.where(np.isfinite(dem), dem, np.inf)
    offs = [(-1, -1), (-1, 0), (-1, 1), (0, -1), (0, 1), (1, -1), (1, 0), (1, 1)]
    step = np.array([math.hypot(dxm * abs(dc), dym * abs(dr)) for dr, dc in offs])

    # steepest descent receiver
    best_slope = np.zeros((h, w), "float32")
    recv = np.full((h, w), -1, "int64")
    rr0 = np.arange(h)[:, None]
    cc0 = np.arange(w)[None, :]
    for k, (dr, dc) in enumerate(offs):
        nb = np.full((h, w), np.inf, "float32")
        # nb[r, c] must hold z[r + dr, c + dc]
        dst = (slice(max(0, -dr), h - max(0, dr)), slice(max(0, -dc), w - max(0, dc)))
        srcsl = (slice(max(0, dr), h + min(0, dr)), slice(max(0, dc), w + min(0, dc)))
        nb[dst] = z[srcsl]
        with np.errstate(invalid="ignore"):
            drop = (z - nb) / step[k]
        inb = np.zeros((h, w), bool)
        inb[dst] = True
        better = (drop > best_slope) & np.isfinite(nb) & inb
        best_slope = np.where(better, drop, best_slope)
        idx = (rr0 + dr) * w + (cc0 + dc)
        recv = np.where(better, idx, recv)

    flat_recv = recv.ravel()
    drains = lake_mask.ravel().copy()
    plen = np.where(lake_mask.ravel(), 0.0, np.inf)
    order = np.argsort(z.ravel(), kind="stable")          # ascending elevation
    stepm = np.zeros(h * w, "float32")
    rr, cc = np.divmod(np.arange(h * w), w)
    r2, c2 = np.divmod(np.maximum(flat_recv, 0), w)
    stepm = np.hypot((c2 - cc) * dxm, (r2 - rr) * dym).astype("float32")

    for i in order:
        if drains[i]:
            continue
        j = flat_recv[i]
        if j >= 0 and drains[j]:
            drains[i] = True
            plen[i] = plen[j] + stepm[i]

    return drains.reshape(h, w), plen.reshape(h, w)


def catchment_of_lake(dem: np.ndarray, lake_mask: np.ndarray,
                      dxm: float, dym: float, tol: float = 0.01):
    """Cells from which the lake can be reached by a monotonically non-ascending
    path, with the length of the shortest such path.

    This is a more permissive connectivity criterion than strict D8 steepest
    descent, and closer in spirit to the modified single-flow-direction model of
    Huggel et al. (2003), which lets a trajectory diverge from the line of
    steepest descent. Implemented as a priority flood outward from the lake.
    """
    import heapq
    h, w = dem.shape
    z = np.where(np.isfinite(dem), dem, np.inf).ravel()
    inside = np.zeros(h * w, bool)
    plen = np.full(h * w, np.inf, "float32")
    offs = [(-1, -1), (-1, 0), (-1, 1), (0, -1), (0, 1), (1, -1), (1, 0), (1, 1)]

    heap = []
    for i in np.flatnonzero(lake_mask.ravel()):
        inside[i] = True
        plen[i] = 0.0
        heapq.heappush(heap, (float(z[i]), 0.0, int(i)))
    while heap:
        zi, li, i = heapq.heappop(heap)
        if li > plen[i]:
            continue
        r, c = divmod(i, w)
        for dr, dc in offs:
            r2, c2 = r + dr, c + dc
            if not (0 <= r2 < h and 0 <= c2 < w):
                continue
            j = r2 * w + c2
            if not np.isfinite(z[j]) or z[j] < zi - tol:
                continue                       # would require flowing uphill
            nl = li + math.hypot(dc * dxm, dr * dym)
            if nl < plen[j]:
                inside[j] = True
                plen[j] = nl
                heapq.heappush(heap, (float(z[j]), nl, j))
    return inside.reshape(h, w), plen.reshape(h, w)


def _mass_movement(dem, slope, glacier, lake_mask, dist_px, z_lake,
                   dxm, dym, kind: str, drains=None, plen=None) -> dict:
    """Identify source areas that route into the lake and test the reach angle."""
    cell_area = dxm * dym
    if kind == "avalanche":
        src = glacier & (slope > C.AVALANCHE_SLOPE_MIN) & (slope < C.AVALANCHE_SLOPE_MAX)
    else:
        src = (~glacier) & (slope > C.ROCKFALL_SLOPE_MIN)
    src &= ~lake_mask & np.isfinite(dem) & (dem > z_lake)
    empty = dict(source_area_m2=0.0, connected_area_m2=0.0, can_reach=False,
                 n_reaching_cells=0, max_volume_m3=0.0, min_reach_angle_deg=None)
    if not src.any():
        return empty

    connected = src & drains & np.isfinite(plen) & (plen > 0)
    if not connected.any():
        return dict(empty, source_area_m2=float(src.sum() * cell_area))

    rows, cols = np.nonzero(connected)
    dz = dem[rows, cols] - z_lake
    path = plen[rows, cols]
    with np.errstate(divide="ignore", invalid="ignore"):
        ang = np.degrees(np.arctan(dz / path))

    # contiguous source patches, restricted to the part that drains to the lake
    lab, n = ndimage.label(src)
    conn_area = ndimage.sum(connected.astype("float32"), lab,
                            range(1, n + 1)) * cell_area
    comp_area = conn_area[lab[rows, cols] - 1]

    if kind == "avalanche":
        vol = comp_area * max(C.AVALANCHE_DEPTHS_M)
        tan_a = np.where(vol >= C.HUGGEL_V_LIMIT,
                         math.tan(math.radians(C.REACH_ANGLE_AVALANCHE)),
                         C.HUGGEL_A - C.HUGGEL_B * np.log10(np.maximum(vol, 1.0)))
        thresh = np.degrees(np.arctan(np.maximum(
            tan_a, math.tan(math.radians(C.REACH_ANGLE_AVALANCHE)))))
    else:
        vol = np.zeros(rows.shape)
        thresh = np.full(rows.shape, C.REACH_ANGLE_ROCKFALL, float)

    reaching = ang >= thresh
    return dict(
        source_area_m2=float(src.sum() * cell_area),
        connected_area_m2=float(connected.sum() * cell_area),
        n_reaching_cells=int(reaching.sum()),
        can_reach=bool(reaching.any()),
        max_volume_m3=float(vol[reaching].max()) if reaching.any() and kind == "avalanche" else 0.0,
        min_reach_angle_deg=float(ang[reaching].min()) if reaching.any() else None,
    )


def mean_depth_fujita(area_km2: float) -> float:
    """Dm = 55 A^0.25, A in km2, Dm in m (Fujita et al. 2013, Eq. 1)."""
    return 55.0 * area_km2 ** 0.25


def pfv_fujita(area_km2: float, hp_m: float) -> float:
    """PFV = min[Hp, Dm] * A (Fujita et al. 2013, Eq. 2), returned in m3."""
    dm = mean_depth_fujita(area_km2)
    return min(hp_m, dm) * area_km2 * 1e6
