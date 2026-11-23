"""
Terrain analysis for each glacial lake from the Copernicus DEM GLO-30.

Implements, per lake:

  * lake surface elevation and area (interior-first rasterisation to avoid bank bias)
  * slope field (true 3x3 Horn 1981 finite difference with affine cell spacing)
  * snow/ice avalanche and rockfall source areas
        Alean (1985); Bolch et al. (2011); Osti et al. (2011); Shea et al. (2015)
        as applied by Rounce et al. (2016)
  * reach-angle (Fahrboeschung) runout test with the volume-dependent avalanche
    threshold of Huggel et al. (2004, Can. Geotech. J. 41, 1068-1083), using a
    physically bounded slab-scenario thickness plus explicit 10/30/50 m scenarios
  * steep lakefront area (SLA), potential lowering height (Hp) and potential
    flood volume (PFV) exactly as defined by Fujita et al. (2013)

Mass-movement trajectories follow Rounce et al. (2016): depressions are filled
with Barnes et al. (2014) Priority-Flood+epsilon in float64 precision so filled
flats carry a strict monotonic epsilon gradient into the lake sink without
terminating single-flow-direction (D8) routing at zero-gradient flats. Only
source cells whose D8 route terminates in the lake are considered, and reach
angle is measured over routed path length rather than straight-line distance.
"""
from __future__ import annotations
from collections import deque
import heapq
import math
import os

try:
    import numpy as np
except ImportError:  # pragma: no cover - stdlib-only unit test mode
    np = None

try:
    import rasterio
    from rasterio import features
    from rasterio.merge import merge as rio_merge
    from rasterio.windows import from_bounds
except ImportError:  # pragma: no cover
    rasterio = features = rio_merge = from_bounds = None

try:
    from scipy import ndimage
except ImportError:  # pragma: no cover
    ndimage = None

try:
    from shapely.geometry import shape, box
    from shapely.strtree import STRtree
except ImportError:  # pragma: no cover
    shape = box = STRtree = None

import config as C


def _require_geo_stack():
    if np is None or rasterio is None or ndimage is None or shape is None:
        raise ImportError(
            "terrain raster analysis requires numpy, scipy, rasterio, and shapely"
        )


def _is_ndarray(obj) -> bool:
    return np is not None and isinstance(obj, np.ndarray)


# ---------------------------------------------------------------------------
# DEM access
# ---------------------------------------------------------------------------
class DemReader:
    """Reads windows from the 1x1 degree Copernicus DEM tile set, mosaicking
    across tile boundaries where necessary."""

    def __init__(self, tile_dir: str = C.DEM_DIR):
        _require_geo_stack()
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


def cell_metres(lat_deg: float, res_x_deg: float,
                res_y_deg: float | None = None) -> tuple[float, float]:
    """Approximate east-west and north-south cell size in metres for a
    geographic grid at the given latitude (WGS84)."""
    phi = math.radians(lat_deg)
    dy_per_deg = 111_132.92 - 559.82 * math.cos(2.0 * phi)
    dx_per_deg = (111_412.84 * math.cos(phi)
                  - 93.5 * math.cos(3.0 * phi))
    ry = res_x_deg if res_y_deg is None else res_y_deg
    return abs(dx_per_deg * res_x_deg), abs(dy_per_deg * ry)


def cell_metres_from_transform(transform, lat_deg: float,
                               fallback_deg: float = 1.0 / 3600.0) -> tuple[float, float]:
    """Compute metric (dx, dy) cell spacing from a rasterio Affine transform
    (or any object exposing `.a` and `.e` geographic degree steps)."""
    res_x = abs(float(getattr(transform, "a", 0.0) or 0.0)) or fallback_deg
    res_y = abs(float(getattr(transform, "e", 0.0) or 0.0)) or fallback_deg
    return cell_metres(lat_deg, res_x, res_y)


def slope_deg(dem, dx: float | None = None, dy: float | None = None, *,
              transform=None, lat_deg: float | None = None):
    """True 3x3 Horn (1981) weighted third-order finite difference slope (deg).

    Accepts explicit metric spacing ``(dx, dy)`` in metres, or computes actual
    cell spacing from a raster ``transform`` and ``lat_deg``. Works on both
    NumPy arrays and pure-Python 2D nested lists.
    """
    if transform is not None:
        if lat_deg is None:
            raise ValueError("lat_deg is required when transform is provided")
        dx, dy = cell_metres_from_transform(transform, lat_deg)
    if dx is None or dy is None:
        raise ValueError("dx and dy (or transform and lat_deg) must be provided")
    if dx <= 0 or dy <= 0:
        raise ValueError("dx and dy must be positive")

    if _is_ndarray(dem):
        z = np.asarray(dem, dtype="float64")
        if z.ndim != 2:
            raise ValueError("dem must be 2D")
        if z.size == 0:
            return np.empty_like(z, dtype="float64")
        p = np.pad(z, 1, mode="edge")
        a, b, c = p[:-2, :-2], p[:-2, 1:-1], p[:-2, 2:]
        d, f = p[1:-1, :-2], p[1:-1, 2:]
        g, h, i = p[2:, :-2], p[2:, 1:-1], p[2:, 2:]
        gx = ((c + 2.0 * f + i) - (a + 2.0 * d + g)) / (8.0 * float(dx))
        gy = ((g + 2.0 * h + i) - (a + 2.0 * b + c)) / (8.0 * float(dy))
        return np.degrees(np.arctan(np.hypot(gx, gy)))

    # Pure-Python stdlib fallback for 2D nested sequences
    nrows = len(dem)
    ncols = len(dem[0]) if nrows else 0
    inv8x = 1.0 / (8.0 * float(dx))
    inv8y = 1.0 / (8.0 * float(dy))
    out = []
    for r in range(nrows):
        r_up = 0 if r == 0 else r - 1
        r_dn = nrows - 1 if r == nrows - 1 else r + 1
        row_up = dem[r_up]
        row_md = dem[r]
        row_dn = dem[r_dn]
        out_row = []
        for c in range(ncols):
            c_lt = 0 if c == 0 else c - 1
            c_rt = ncols - 1 if c == ncols - 1 else c + 1
            a = float(row_up[c_lt]); b = float(row_up[c]); cc = float(row_up[c_rt])
            dd = float(row_md[c_lt]); ff = float(row_md[c_rt])
            gg = float(row_dn[c_lt]); hh = float(row_dn[c]); ii = float(row_dn[c_rt])
            if not (math.isfinite(a) and math.isfinite(b) and math.isfinite(cc)
                    and math.isfinite(dd) and math.isfinite(ff)
                    and math.isfinite(gg) and math.isfinite(hh) and math.isfinite(ii)):
                out_row.append(math.nan)
                continue
            gx = ((cc + 2.0 * ff + ii) - (a + 2.0 * dd + gg)) * inv8x
            gy = ((gg + 2.0 * hh + ii) - (a + 2.0 * b + cc)) * inv8y
            out_row.append(math.degrees(math.atan(math.hypot(gx, gy))))
        out.append(out_row)
    return out


# ---------------------------------------------------------------------------
# Per-lake analysis
# ---------------------------------------------------------------------------
def analyse_lake(lake_geom, lake_props, dem_reader: DemReader,
                 glacier_tree, glacier_geoms,
                 buffer_km: float = 8.0) -> dict:
    """Run the full terrain analysis for a single lake polygon."""
    _require_geo_stack()
    poly = shape(lake_geom)
    cx, cy = poly.centroid.x, poly.centroid.y
    # Rough arcsecond estimate solely to size the initial DEM window read
    res_est = 1.0 / 3600.0
    dx_est, dy_est = cell_metres(cy, res_est)
    bx = buffer_km * 1000.0 / dx_est * res_est
    by = buffer_km * 1000.0 / dy_est * res_est
    minx, miny, maxx, maxy = poly.bounds
    bounds = (minx - bx, miny - by, maxx + bx, maxy + by)

    dem, tr = dem_reader.read(bounds)
    if dem.size == 0 or not np.isfinite(dem).any():
        return dict(error="no DEM")
    h, w = dem.shape

    # Actual raster cell spacing from the DEM affine transform
    dxm, dym = cell_metres_from_transform(tr, cy)

    # Interior-first rasterisation to prevent steep bank pixels biasing z_lake
    # upward on small/narrow lakes; fall back to all_touched=True only when
    # all_touched=False yields zero pixels.
    lake_mask = features.rasterize(
        [(poly, 1)], out_shape=(h, w), transform=tr,
        dtype="uint8", all_touched=False,
    ).astype(bool)
    if not lake_mask.any():
        lake_mask = features.rasterize(
            [(poly, 1)], out_shape=(h, w), transform=tr,
            dtype="uint8", all_touched=True,
        ).astype(bool)
    if not lake_mask.any():
        # lake smaller than one cell: use the centroid cell
        r, c = rasterio.transform.rowcol(tr, cx, cy)
        if 0 <= r < h and 0 <= c < w:
            lake_mask[r, c] = True
        else:
            return dict(error="lake outside window")

    lake_vals = dem[lake_mask]
    lake_vals = lake_vals[np.isfinite(lake_vals)]
    if lake_vals.size == 0:
        return dict(error="no finite DEM on lake")
    z_lake = float(np.median(lake_vals))
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
    # Fill depressions with Barnes Priority-Flood+epsilon in float64, keeping
    # the lake itself as an internal sink at z_lake so upslope depressions
    # drain continuously into the lake rather than stalling on flat plateaus.
    dem_for_fill = np.asarray(dem, dtype="float64").copy()
    dem_for_fill[lake_mask] = z_lake
    dem_filled = fill_depressions(dem_for_fill, sink_mask=lake_mask)
    dem_filled[lake_mask] = z_lake
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


def _dilate(m, n: int = 2):
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
    near = ((dist_px > C.SLA_BUFFER_INNER_M) & (dist_px > 0)
            & (dist_px <= C.SLA_BUFFER_OUTER_M) & ~lake_mask)
    if not near.any():
        return dict(sla_area_m2=0.0, sla_max_angle_deg=None, sla_min_distance_m=None,
                    hp_m=0.0)
    drop = z_lake - dem
    with np.errstate(divide="ignore", invalid="ignore"):
        ang = np.degrees(np.arctan(np.where(near, drop, np.nan) / np.where(near, dist_px, np.nan)))
    steep = np.nan_to_num(ang, nan=-90.0) > C.SLA_THRESHOLD_DEG
    # require a contiguous patch of SLA_MIN_PATCH_CELLS cells to suppress noise
    lab, n = ndimage.label(steep)
    if n:
        sizes = ndimage.sum(np.ones_like(lab), lab, range(1, n + 1))
        keep = np.isin(lab, 1 + np.flatnonzero(sizes >= C.SLA_MIN_PATCH_CELLS))
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
                remains = (sz >= C.SLA_MIN_PATCH_CELLS).any()
            else:
                remains = False
            if remains:
                lo = mid
            else:
                hi = mid
        hp = hi
    out["hp_m"] = float(hp)
    return out


# ---------------------------------------------------------------------------
# Barnes et al. (2014) Priority-Flood+epsilon depression filling
# ---------------------------------------------------------------------------
def fill_depressions(dem, sink_mask=None, eps: float = 1e-5):
    """Fill closed depressions with Barnes et al. (2014) Priority-Flood+epsilon.

    Every filled depression cell receives a tiny strict upslope increment
    (default ``eps = 1e-5 m``) outward from its pour point in float64 precision,
    eliminating zero-gradient flats so subsequent D8 routing never terminates
    inside filled depressions (even at 5,000+ m Himalayan elevations where
    float32 ULP exceeds 1e-5 m).

    If ``sink_mask`` is supplied (e.g. a lake polygon mask), finite sink cells
    are seeded alongside domain perimeter outlets so basins draining to the
    lake preserve their inward drainage rather than filling over the moraine.

    Works on both NumPy arrays (returns float64 ndarray) and 2D Python lists
    (returns nested float lists).
    """
    as_numpy = _is_ndarray(dem)
    if as_numpy:
        h, w = dem.shape
        raw_rows = dem.astype("float64", copy=False).tolist()
        sink_rows = (sink_mask.astype(bool, copy=False).tolist()
                     if sink_mask is not None else None)
    else:
        h = len(dem)
        w = len(dem[0]) if h else 0
        raw_rows = [[float(v) for v in row] for row in dem]
        sink_rows = ([[bool(v) for v in row] for row in sink_mask]
                     if sink_mask is not None else None)

    if h == 0 or w == 0:
        return np.empty((h, w), dtype="float64") if as_numpy else []

    # 1-cell halo eliminates bounds checks inside the 8-neighbour inner loop
    H = h + 2
    W = w + 2
    closed = bytearray(H * W)
    filled = [math.nan] * (H * W)

    # Mark 1-cell outer halo closed
    for c in range(W):
        closed[c] = 1
        closed[(H - 1) * W + c] = 1
    for r in range(H):
        closed[r * W] = 1
        closed[r * W + (W - 1)] = 1

    # Load interior elevations; mark NaN/non-finite cells closed immediately
    has_finite = False
    for r in range(h):
        row = raw_rows[r]
        base = (r + 1) * W + 1
        for c in range(w):
            v = row[c]
            idx = base + c
            if math.isfinite(v):
                filled[idx] = v
                has_finite = True
            else:
                closed[idx] = 1

    if not has_finite:
        return np.asarray(raw_rows, dtype="float64") if as_numpy else raw_rows

    offs = (-W - 1, -W, -W + 1, -1, 1, W - 1, W, W + 1)
    open_heap: list[tuple[float, int]] = []

    # Seed perimeter cells, internal NaN-bordering cells, and optional sinks
    for r in range(h):
        base = (r + 1) * W + 1
        on_row_edge = (r == 0 or r == h - 1)
        srow = sink_rows[r] if sink_rows is not None else None
        for c in range(w):
            idx = base + c
            if closed[idx]:
                continue
            seed = on_row_edge or (c == 0) or (c == w - 1)
            if not seed and srow is not None and srow[c]:
                seed = True
            if not seed:
                # Seed finite cells adjacent to an internal NaN cell
                for off in offs:
                    if not math.isfinite(filled[idx + off]):
                        seed = True
                        break
            if seed:
                closed[idx] = 1
                open_heap.append((filled[idx], idx))

    heapq.heapify(open_heap)
    pit: deque[int] = deque()
    heappop = heapq.heappop
    heappush = heapq.heappush
    pit_pop = pit.popleft
    pit_push = pit.append
    eps_f = float(eps)

    while open_heap or pit:
        if pit and (not open_heap or filled[pit[0]] <= open_heap[0][0]):
            c = pit_pop()
            zc = filled[c]
        else:
            zc, c = heappop(open_heap)
        target = zc + eps_f
        for off in offs:
            n = c + off
            if closed[n]:
                continue
            closed[n] = 1
            zn = filled[n]
            if zn <= target:
                filled[n] = target
                pit_push(n)
            else:
                heappush(open_heap, (zn, n))

    out_rows = [filled[(r + 1) * W + 1:(r + 1) * W + 1 + w] for r in range(h)]
    if as_numpy:
        return np.asarray(out_rows, dtype="float64")
    return out_rows


def d8_route_to_lake(dem, lake_mask, dxm: float, dym: float):
    """Single-flow-direction (D8) routing in float64 precision.

    Returns ``(drains_to_lake, path_length_m)``:
      drains_to_lake  bool array (or 2D list), True where the steepest-descent
                      route from the cell terminates in the lake
      path_length_m   float64 array (or 2D list), routed distance to the lake
                      (inf elsewhere)

    Uses float64 elevation differences throughout so epsilon gradients created
    by ``fill_depressions()`` are preserved even at 5,000+ m elevation.
    Processing in ascending elevation order guarantees that a cell's receiver
    is resolved before the cell itself, because a receiver is always strictly
    lower.
    """
    offs = [(-1, -1), (-1, 0), (-1, 1), (0, -1), (0, 1), (1, -1), (1, 0), (1, 1)]
    steps = [math.hypot(dxm * abs(dc), dym * abs(dr)) for dr, dc in offs]

    if _is_ndarray(dem):
        h, w = dem.shape
        z = np.where(np.isfinite(dem), np.asarray(dem, dtype="float64"), np.inf)
        lm = np.asarray(lake_mask, dtype=bool)
        best_slope = np.zeros((h, w), dtype="float64")
        recv = np.full((h, w), -1, dtype="int64")
        rr0 = np.arange(h)[:, None]
        cc0 = np.arange(w)[None, :]
        for k, (dr, dc) in enumerate(offs):
            nb = np.full((h, w), np.inf, dtype="float64")
            dst = (slice(max(0, -dr), h - max(0, dr)),
                   slice(max(0, -dc), w - max(0, dc)))
            srcsl = (slice(max(0, dr), h + min(0, dr)),
                     slice(max(0, dc), w + min(0, dc)))
            nb[dst] = z[srcsl]
            with np.errstate(invalid="ignore"):
                drop = (z - nb) / steps[k]
            inb = np.zeros((h, w), bool)
            inb[dst] = True
            better = (drop > best_slope) & np.isfinite(nb) & inb
            best_slope = np.where(better, drop, best_slope)
            idx = (rr0 + dr) * w + (cc0 + dc)
            recv = np.where(better, idx, recv)

        flat_recv = recv.ravel()
        drains = lm.ravel().copy()
        plen = np.where(lm.ravel(), 0.0, np.inf).astype("float64")
        order = np.argsort(z.ravel(), kind="stable")
        rr, cc = np.divmod(np.arange(h * w), w)
        r2, c2 = np.divmod(np.maximum(flat_recv, 0), w)
        stepm = np.hypot((c2 - cc) * dxm, (r2 - rr) * dym)

        for i in order:
            if drains[i]:
                continue
            j = flat_recv[i]
            if j >= 0 and drains[j]:
                drains[i] = True
                plen[i] = plen[j] + stepm[i]

        return drains.reshape(h, w), plen.reshape(h, w)

    # Pure-Python stdlib fallback for 2D nested lists
    h = len(dem)
    w = len(dem[0]) if h else 0
    n_cells = h * w
    z_flat = [math.inf] * n_cells
    drains = [False] * n_cells
    plen = [math.inf] * n_cells
    for r in range(h):
        for c in range(w):
            i = r * w + c
            v = float(dem[r][c])
            z_flat[i] = v if math.isfinite(v) else math.inf
            if lake_mask[r][c]:
                drains[i] = True
                plen[i] = 0.0

    recv = [-1] * n_cells
    stepm = [0.0] * n_cells
    for r in range(h):
        for c in range(w):
            i = r * w + c
            zi = z_flat[i]
            if not math.isfinite(zi) or drains[i]:
                continue
            best_s = 0.0
            best_j = -1
            best_step = 0.0
            for k, (dr, dc) in enumerate(offs):
                r2, c2 = r + dr, c + dc
                if 0 <= r2 < h and 0 <= c2 < w:
                    j = r2 * w + c2
                    zj = z_flat[j]
                    if math.isfinite(zj):
                        s = (zi - zj) / steps[k]
                        if s > best_s:
                            best_s = s
                            best_j = j
                            best_step = steps[k]
            recv[i] = best_j
            stepm[i] = best_step

    order = sorted(range(n_cells), key=lambda idx: z_flat[idx])
    for i in order:
        if drains[i]:
            continue
        j = recv[i]
        if j >= 0 and drains[j]:
            drains[i] = True
            plen[i] = plen[j] + stepm[i]

    drains_2d = [drains[r * w:(r + 1) * w] for r in range(h)]
    plen_2d = [plen[r * w:(r + 1) * w] for r in range(h)]
    return drains_2d, plen_2d


def catchment_of_lake(dem, lake_mask, dxm: float, dym: float, tol: float = 0.01):
    """Cells from which the lake can be reached by a monotonically non-ascending
    path, with the length of the shortest such path.

    This is a more permissive connectivity criterion than strict D8 steepest
    descent, and closer in spirit to the modified single-flow-direction model of
    Huggel et al. (2003), which lets a trajectory diverge from the line of
    steepest descent. Implemented as a priority flood outward from the lake.
    """
    _require_geo_stack()
    h, w = dem.shape
    z = np.where(np.isfinite(dem), np.asarray(dem, dtype="float64"), np.inf).ravel()
    inside = np.zeros(h * w, bool)
    plen = np.full(h * w, np.inf, "float64")
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


def avalanche_reach_threshold_deg(volume_m3: float) -> float:
    """Volume-dependent reach-angle threshold (deg) of Huggel et al. (2004)."""
    min_tan = math.tan(math.radians(C.REACH_ANGLE_AVALANCHE))
    if volume_m3 >= C.HUGGEL_V_LIMIT:
        return float(C.REACH_ANGLE_AVALANCHE)
    tan_a = C.HUGGEL_A - C.HUGGEL_B * math.log10(max(float(volume_m3), 1.0))
    return math.degrees(math.atan(max(tan_a, min_tan)))


def _avalanche_reach_threshold_arr(vol):
    min_tan = math.tan(math.radians(C.REACH_ANGLE_AVALANCHE))
    tan_a = np.where(
        vol >= C.HUGGEL_V_LIMIT,
        min_tan,
        C.HUGGEL_A - C.HUGGEL_B * np.log10(np.maximum(vol, 1.0)),
    )
    return np.degrees(np.arctan(np.maximum(tan_a, min_tan)))


def _mass_movement(dem, slope, glacier, lake_mask, dist_px, z_lake,
                   dxm, dym, kind: str, drains=None, plen=None) -> dict:
    """Identify source areas that route into the lake and test the reach angle.

    For avalanches, coherent slab detachment area is bounded by
    ``C.AVALANCHE_SLAB_AREA_CAP_M2`` so an entire multi-km2 steep headwall is
    not multiplied uniformly by 50 m. Default screening uses the physically
    bounded representative thickness ``C.AVALANCHE_REPRESENTATIVE_DEPTH_M``,
    while all three published scenario depths in ``C.AVALANCHE_DEPTHS_M``
    (10, 30, 50 m) are explicitly evaluated and exposed under ``scenarios``.
    """
    cell_area = dxm * dym
    if kind == "avalanche":
        src = glacier & (slope > C.AVALANCHE_SLOPE_MIN) & (slope < C.AVALANCHE_SLOPE_MAX)
    else:
        src = (~glacier) & (slope > C.ROCKFALL_SLOPE_MIN)
    src &= ~lake_mask & np.isfinite(dem) & (dem > z_lake)
    empty = dict(source_area_m2=0.0, connected_area_m2=0.0, can_reach=False,
                 n_reaching_cells=0, max_volume_m3=0.0, min_reach_angle_deg=None)
    if kind == "avalanche":
        empty["representative_depth_m"] = float(C.AVALANCHE_REPRESENTATIVE_DEPTH_M)
        empty["slab_area_cap_m2"] = float(C.AVALANCHE_SLAB_AREA_CAP_M2)
        empty["scenarios"] = {
            f"{int(d)}m": dict(depth_m=float(d), can_reach=False,
                               n_reaching_cells=0, max_volume_m3=0.0,
                               min_reach_angle_deg=None)
            for d in C.AVALANCHE_DEPTHS_M
        }
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
    conn_area = ndimage.sum(connected.astype("float64"), lab,
                            range(1, n + 1)) * cell_area
    comp_area = conn_area[lab[rows, cols] - 1]

    if kind == "avalanche":
        eff_area = np.minimum(comp_area, C.AVALANCHE_SLAB_AREA_CAP_M2)
        vol = eff_area * C.AVALANCHE_REPRESENTATIVE_DEPTH_M
        thresh = _avalanche_reach_threshold_arr(vol)
        reaching = ang >= thresh

        scenarios = {}
        for d_m in C.AVALANCHE_DEPTHS_M:
            vol_s = eff_area * float(d_m)
            thr_s = _avalanche_reach_threshold_arr(vol_s)
            reach_s = ang >= thr_s
            scenarios[f"{int(d_m)}m"] = dict(
                depth_m=float(d_m),
                can_reach=bool(reach_s.any()),
                n_reaching_cells=int(reach_s.sum()),
                max_volume_m3=float(vol_s[reach_s].max()) if reach_s.any() else 0.0,
                min_reach_angle_deg=float(ang[reach_s].min()) if reach_s.any() else None,
            )

        return dict(
            source_area_m2=float(src.sum() * cell_area),
            connected_area_m2=float(connected.sum() * cell_area),
            n_reaching_cells=int(reaching.sum()),
            can_reach=bool(reaching.any()),
            max_volume_m3=float(vol[reaching].max()) if reaching.any() else 0.0,
            min_reach_angle_deg=float(ang[reaching].min()) if reaching.any() else None,
            representative_depth_m=float(C.AVALANCHE_REPRESENTATIVE_DEPTH_M),
            slab_area_cap_m2=float(C.AVALANCHE_SLAB_AREA_CAP_M2),
            scenarios=scenarios,
        )

    thresh = np.full(rows.shape, C.REACH_ANGLE_ROCKFALL, float)
    reaching = ang >= thresh
    return dict(
        source_area_m2=float(src.sum() * cell_area),
        connected_area_m2=float(connected.sum() * cell_area),
        n_reaching_cells=int(reaching.sum()),
        can_reach=bool(reaching.any()),
        max_volume_m3=0.0,
        min_reach_angle_deg=float(ang[reaching].min()) if reaching.any() else None,
    )


def mean_depth_fujita(area_km2: float) -> float:
    """Dm = 55 A^0.25, A in km2, Dm in m (Fujita et al. 2013, Eq. 1)."""
    return 55.0 * area_km2 ** 0.25


def pfv_fujita(area_km2: float, hp_m: float) -> float:
    """PFV = min[Hp, Dm] * A (Fujita et al. 2013, Eq. 2), returned in m3."""
    dm = mean_depth_fujita(area_km2)
    return min(hp_m, dm) * area_km2 * 1e6
