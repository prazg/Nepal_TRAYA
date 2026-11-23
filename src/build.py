"""
Assemble the Nepal Multi-Hazard Risk Observatory & Screening Platform data products.

Reads:
  raw/lakes.geojson, raw/glaciers.geojson, raw/glof.geojson  (Nepal Cryosphere Inventory)
  raw/HMAGLOFDB_v4.csv                                       (ICIMOD GLOF database; falls back to raw/glof.geojson)
  raw/hydro/HydroRIVERS_v10_as_shp                           (river network)
  raw/pop/npl_pop_2020*.tif                                  (WorldPop)
  cache/terrain.json                                         (build_terrain.py)
  cache/overpass/*.json                                      (exposure.py)
  cache/usgs_catalogue.json                                  (seismic.py)

Writes into data/:
  lakes.js        window.LAKES         GeoJSON of lakes with hazard attributes
  routes.js       window.ROUTES        routed flow paths, travel times, exposure
  exposure.js     window.EXPOSURE      exposure objects referenced by the routes
  eq_history.js   window.EQ_HISTORY    historical earthquakes
  glof_history.js window.GLOF_HISTORY  recorded GLOFs in Nepal
  summary.js      window.SUMMARY       headline statistics, model parameters, sources
  model_fit.json                       fitted model parameters and validation table
"""
from __future__ import annotations
import argparse
import csv
import datetime
import json
import math
import os
import shutil
import time
import warnings
from collections import Counter, defaultdict

try:
    import numpy as np
except ImportError:  # pragma: no cover - stdlib-only unit test mode
    np = None

try:
    import rasterio
    from rasterio import features as rfeatures
    from rasterio.windows import from_bounds
except ImportError:  # pragma: no cover
    rasterio = rfeatures = from_bounds = None

try:
    from shapely.geometry import shape, LineString, Point
    from shapely.ops import transform as shapely_transform
except ImportError:  # pragma: no cover
    shape = LineString = Point = shapely_transform = None

try:
    from pyproj import Transformer
except ImportError:  # pragma: no cover
    Transformer = None

import config as C
import admin as AD
import hazard as HZ
import models_glof as MG
from models_glof import stable_seed
import routing as RT
import seismic as SZ
import terrain as TR
import exposure as EX

BUILD_ID = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())


# ---------------------------------------------------------------------------
# Atomic UTF-8 file helpers
# ---------------------------------------------------------------------------
def _atomic_write_text(path: str, text: str) -> None:
    os.makedirs(os.path.dirname(os.path.abspath(path)), exist_ok=True)
    tmp = f"{path}.tmp.{os.getpid()}"
    try:
        with open(tmp, "w", encoding="utf-8", newline="\n") as fh:
            fh.write(text)
        os.replace(tmp, path)
    except Exception:
        if os.path.exists(tmp):
            try:
                os.remove(tmp)
            except OSError:
                pass
        raise


def _read_json(path: str):
    with open(path, encoding="utf-8") as fh:
        return json.load(fh)


# ---------------------------------------------------------------------------
def load_inputs():
    lakes = _read_json(os.path.join(C.RAW, "lakes.geojson"))["features"]
    terr = _read_json(os.path.join(C.CACHE, "terrain.json"))
    expo = EX.collect()
    cat = SZ.fetch_catalogue()
    net = RT.RiverNetwork()
    return lakes, terr, expo, cat, net


def load_glof_history(csv_path: str | None = None,
                      fallback_geojson: str | None = None) -> tuple[list[dict], dict]:
    """Recorded GLOFs in Nepal from HMAGLOFDB_v4.csv, with explicit warning and
    automatic fallback to raw/glof.geojson if HMAGLOFDB_v4.csv is missing.

    Fails loudly if neither source exists so the build never silently writes an
    empty GLOF history layer.
    """
    csv_path = csv_path or os.path.join(C.RAW, "HMAGLOFDB_v4.csv")
    fallback_geojson = fallback_geojson or os.path.join(C.RAW, "glof.geojson")

    if os.path.exists(csv_path):
        out = []
        with open(csv_path, newline="", encoding="utf-8", errors="replace") as fh:
            for row in csv.DictReader(fh):
                if (row.get("Country") or "").strip() != "Nepal":
                    continue
                try:
                    lat = float(row["Lat_lake"])
                    lon = float(row["Lon_lake"])
                except (TypeError, ValueError):
                    continue
                out.append(dict(
                    gf_id=row.get("GF_ID"), year=_num(row.get("Year_approx")),
                    lake=row.get("Lake_name") or "Unknown",
                    glacier=row.get("Glacier_name") or "",
                    basin=row.get("River_Basin") or "",
                    lake_type=row.get("Lake_type") or "",
                    mechanism=row.get("Mechanism") or "",
                    driver=row.get("Driver_GLOF") or "",
                    lives=_num(row.get("Lives_total")),
                    discharge=_num(row.get("Discharge_water")),
                    volume=_num(row.get("Volume")),
                    lon=round(lon, 4), lat=round(lat, 4),
                ))
        if not out:
            raise ValueError(f"{csv_path} yielded 0 Nepal GLOF records")
        return out, dict(
            source="HMAGLOFDB_v4.csv",
            fallback_used=False,
            warning=None,
            n_records=len(out),
        )

    if os.path.exists(fallback_geojson):
        warn_msg = (
            f"HMAGLOFDB_v4.csv not found at {csv_path}; falling back to "
            f"{os.path.basename(fallback_geojson)} (Nepal Cryosphere Inventory GLOF layer)"
        )
        warnings.warn(warn_msg, RuntimeWarning, stacklevel=2)
        print(f"  WARNING: {warn_msg}")
        gj = _read_json(fallback_geojson)
        out = []
        for idx, feat in enumerate(gj.get("features", []), 1):
            geom = feat.get("geometry") or {}
            coords = geom.get("coordinates") or []
            if len(coords) < 2:
                continue
            try:
                lon = float(coords[0])
                lat = float(coords[1])
            except (TypeError, ValueError):
                continue
            p = feat.get("properties") or {}
            out.append(dict(
                gf_id=str(p.get("gf_id") or f"NCI-{idx}"),
                year=_num(p.get("yr") if "yr" in p else p.get("year")),
                lake=(p.get("nm") or p.get("lake") or "Unknown").strip() or "Unknown",
                glacier=(p.get("glacier") or "").strip(),
                basin=(p.get("basin") or "").strip(),
                lake_type=(p.get("typ") or p.get("lake_type") or "").strip(),
                mechanism=(p.get("mechanism") or "Unknown").strip(),
                driver=(p.get("driver") or "Unknown").strip(),
                lives=_num(p.get("lives")),
                discharge=_num(p.get("discharge")),
                volume=_num(p.get("volume")),
                lon=round(lon, 4), lat=round(lat, 4),
            ))
        if not out:
            raise ValueError(f"Fallback GLOF file {fallback_geojson} yielded 0 records")
        return out, dict(
            source=os.path.basename(fallback_geojson),
            fallback_used=True,
            warning=warn_msg,
            n_records=len(out),
        )

    raise FileNotFoundError(
        f"Neither {csv_path} nor fallback {fallback_geojson} exists; "
        "refusing to write an empty recorded-GLOF layer."
    )


def hmaglofdb_nepal(path: str | None = None,
                    fallback_geojson: str | None = None) -> list[dict]:
    """Recorded GLOFs with a Nepalese lake or impact site."""
    records, _ = load_glof_history(csv_path=path, fallback_geojson=fallback_geojson)
    return records


def _num(v):
    if v is None or v == "":
        return None
    try:
        val = float(str(v).strip())
        return val if math.isfinite(val) else None
    except Exception:
        return None


# ---------------------------------------------------------------------------
# Metric UTM buffering for WorldPop corridor population
# ---------------------------------------------------------------------------
def utm_epsg_for_lon(lon: float) -> int:
    """Return Nepal metric UTM zone EPSG code: 32644 (44N, lon < 84) or 32645 (45N, lon >= 84)."""
    return 32644 if float(lon) < 84.0 else 32645


class PopSampler:
    """Population in a metric UTM-buffered corridor, from both WorldPop variants
    for Nepal 2020. Use as a context manager to close raster handles cleanly."""

    def __init__(self):
        if rasterio is None:
            raise ImportError("PopSampler requires rasterio")
        self.srcs = {}
        self._transformers = {}
        for key, fn in (("constrained", "npl_pop_2020.tif"),
                        ("unconstrained", "npl_pop_2020_unconstrained.tif")):
            p = os.path.join(C.RAW, "pop", fn)
            if os.path.exists(p):
                self.srcs[key] = rasterio.open(p)

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, tb):
        self.close()
        return False

    def close(self):
        for src in self.srcs.values():
            try:
                src.close()
            except Exception:
                pass
        self.srcs.clear()

    def _utm_buffer_geom(self, line, corridor_m: float, target_crs: str = "EPSG:4326"):
        """Project line to UTM 44N/45N, buffer in true metres, and project back."""
        epsg = utm_epsg_for_lon(line.centroid.x)
        if Transformer is not None and shapely_transform is not None:
            fwd_key = ("EPSG:4326", f"EPSG:{epsg}")
            inv_key = (f"EPSG:{epsg}", target_crs)
            if fwd_key not in self._transformers:
                self._transformers[fwd_key] = Transformer.from_crs(
                    fwd_key[0], fwd_key[1], always_xy=True
                )
            if inv_key not in self._transformers:
                self._transformers[inv_key] = Transformer.from_crs(
                    inv_key[0], inv_key[1], always_xy=True
                )
            line_utm = shapely_transform(self._transformers[fwd_key].transform, line)
            buf_utm = line_utm.buffer(float(corridor_m))
            return shapely_transform(self._transformers[inv_key].transform, buf_utm)

        # Fallback only if pyproj is unavailable: ellipsoidal local scaling
        lat0 = line.centroid.y
        dx_m_per_deg, dy_m_per_deg = TR.cell_metres(lat0, 1.0)
        return line.buffer(max(corridor_m / dx_m_per_deg, corridor_m / dy_m_per_deg))

    def corridor_population(self, line, corridor_m: float) -> dict:
        out = {}
        for key, src in self.srcs.items():
            target_crs = src.crs.to_string() if src.crs else "EPSG:4326"
            buf = self._utm_buffer_geom(line, corridor_m, target_crs=target_crs)
            b = buf.bounds
            try:
                win = from_bounds(*b, src.transform).round_offsets().round_lengths()
                arr = src.read(1, window=win, boundless=True, fill_value=0.0)
                tr = src.window_transform(win)
                if arr.size == 0:
                    out[key] = 0.0
                    continue
                mask = rfeatures.rasterize([(buf, 1)], out_shape=arr.shape,
                                           transform=tr, dtype="uint8",
                                           all_touched=True).astype(bool)
                a = np.where(arr == src.nodata, 0.0, arr)
                out[key] = float(np.nansum(a[mask]))
            except Exception:
                out[key] = None
        return out


# ---------------------------------------------------------------------------
# Perpendicular point-to-segment distance & projected along-channel chainage
# ---------------------------------------------------------------------------
def point_to_polyline_km(px: float, py: float,
                         coords: list[tuple[float, float]]) -> tuple[float, float]:
    """Return ``(chainage_km, perp_dist_km)`` from point ``(px, py)`` to an
    unsimplified geographic polyline ``coords`` (lon, lat pairs).

    Uses local WGS84 metric scaling at the polyline's mean latitude and clamps
    orthogonal projection parameter ``t`` to ``[0, 1]`` on every segment.
    Pure Python stdlib implementation for exact unit verification.
    """
    n = len(coords)
    if n == 0:
        return 0.0, math.inf
    lat0 = sum(c[1] for c in coords) / n
    dx_m, dy_m = TR.cell_metres(lat0, 1.0)
    kx = dx_m / 1000.0
    ky = dy_m / 1000.0
    qx, qy = px * kx, py * ky

    if n == 1:
        ax, ay = coords[0][0] * kx, coords[0][1] * ky
        return 0.0, math.hypot(qx - ax, qy - ay)

    best_d = math.inf
    best_chain = 0.0
    cum = 0.0
    ax, ay = coords[0][0] * kx, coords[0][1] * ky
    for k in range(1, n):
        bx, by = coords[k][0] * kx, coords[k][1] * ky
        vx, vy = bx - ax, by - ay
        seg_len2 = vx * vx + vy * vy
        seg_len = math.sqrt(seg_len2)
        wx, wy = qx - ax, qy - ay
        if seg_len2 > 0.0:
            t = (wx * vx + wy * vy) / seg_len2
            if t < 0.0:
                t = 0.0
            elif t > 1.0:
                t = 1.0
        else:
            t = 0.0
        dx = wx - t * vx
        dy = wy - t * vy
        d = math.hypot(dx, dy)
        if d < best_d:
            best_d = d
            best_chain = cum + t * seg_len
        cum += seg_len
        ax, ay = bx, by
    return best_chain, best_d


def nearest_exposure_on_coords(coords: list[tuple[float, float]],
                               expo: list[dict],
                               corridor_m: float) -> list[tuple[int, float, float]]:
    """Pure-Python stdlib point-to-segment exposure matching along ``coords``."""
    if not coords or not expo:
        return []
    xs = [c[0] for c in coords]
    ys = [c[1] for c in coords]
    minx, maxx = min(xs), max(xs)
    miny, maxy = min(ys), max(ys)
    lat0 = sum(ys) / len(ys)
    dx_m, dy_m = TR.cell_metres(lat0, 1.0)
    pad_x = corridor_m / dx_m + 1e-4
    pad_y = corridor_m / dy_m + 1e-4

    hits = []
    for i, obj in enumerate(expo):
        px, py = float(obj["lon"]), float(obj["lat"])
        if not (minx - pad_x <= px <= maxx + pad_x and miny - pad_y <= py <= maxy + pad_y):
            continue
        chain_km, dist_km = point_to_polyline_km(px, py, coords)
        dist_m = dist_km * 1000.0
        if dist_m <= corridor_m:
            hits.append((i, chain_km, dist_m))
    hits.sort(key=lambda t: t[1])
    return hits


def nearest_exposure_on_path(path, expo: list[dict],
                             expo_xy, corridor_m: float):
    """Exposure objects within ``corridor_m`` of an UNSIMPLIFIED routed path,
    using true perpendicular point-to-segment distance and projected
    along-channel chainage (km)."""
    raw_coords = list(path.coords)
    if not raw_coords or not expo:
        return []
    if np is None:
        return nearest_exposure_on_coords(raw_coords, expo, corridor_m)

    coords = np.asarray(raw_coords, dtype="float64")
    lat0 = float(coords[:, 1].mean())
    dx_m, dy_m = TR.cell_metres(lat0, 1.0)
    kx = dx_m / 1000.0
    ky = dy_m / 1000.0

    minx, miny, maxx, maxy = path.bounds
    pad_x = corridor_m / dx_m + 1e-4
    pad_y = corridor_m / dy_m + 1e-4
    sel = np.flatnonzero(
        (expo_xy[:, 0] >= minx - pad_x) & (expo_xy[:, 0] <= maxx + pad_x)
        & (expo_xy[:, 1] >= miny - pad_y) & (expo_xy[:, 1] <= maxy + pad_y)
    )
    if sel.size == 0:
        return []

    px_arr = coords[:, 0] * kx
    py_arr = coords[:, 1] * ky
    if coords.shape[0] == 1:
        hits = []
        for i in sel:
            d_m = math.hypot(expo_xy[i, 0] * kx - px_arr[0],
                             expo_xy[i, 1] * ky - py_arr[0]) * 1000.0
            if d_m <= corridor_m:
                hits.append((int(i), 0.0, float(d_m)))
        return hits

    ax, ay = px_arr[:-1], py_arr[:-1]
    vx, vy = px_arr[1:] - ax, py_arr[1:] - ay
    seg_len2 = vx * vx + vy * vy
    seg_len = np.sqrt(seg_len2)
    safe_len2 = np.where(seg_len2 > 0.0, seg_len2, 1.0)
    cum = np.concatenate([[0.0], np.cumsum(seg_len)])

    hits = []
    for i in sel:
        qx = float(expo_xy[i, 0]) * kx
        qy = float(expo_xy[i, 1]) * ky
        wx = qx - ax
        wy = qy - ay
        t = np.where(seg_len2 > 0.0,
                     np.clip((wx * vx + wy * vy) / safe_len2, 0.0, 1.0),
                     0.0)
        d_km = np.hypot(wx - t * vx, wy - t * vy)
        k = int(np.argmin(d_km))
        dist_m = float(d_km[k] * 1000.0)
        if dist_m <= corridor_m:
            chain_km = float(cum[k] + t[k] * seg_len[k])
            hits.append((int(i), chain_km, dist_m))
    hits.sort(key=lambda t: t[1])
    return hits


# ---------------------------------------------------------------------------
# Same-reach + upstream-reach GLOF cascade detection
# ---------------------------------------------------------------------------
def detect_upstream_glof(lake_reach: dict[str, int],
                         lake_elev: dict[str, float | None],
                         trace_up_fn,
                         min_same_reach_dz_m: float = C.SAME_REACH_UPSTREAM_MIN_DZ_M) -> dict[str, bool]:
    """Identify lakes that have another glacial lake upstream of them, either:
      1. on a strictly upstream HydroRIVERS reach within ``trace_up_fn(rid)``, OR
      2. sharing the SAME HydroRIVERS reach at a higher elevation
         (``z_other > z_lake + min_same_reach_dz_m``), catching twin-lake
         cascades such as the Aug 2024 Thame (Upper/Lower Ngole Cho) GLOF.
    """
    reach_lakes = defaultdict(list)
    for lid, rid in lake_reach.items():
        reach_lakes[rid].append(lid)

    upstream_glof = {}
    for lid, rid in lake_reach.items():
        ups = {r for r, _ in trace_up_fn(rid)}
        has_up_reach = any(
            other != lid for r in ups for other in reach_lakes.get(r, ())
        )
        if has_up_reach:
            upstream_glof[lid] = True
            continue
        z_self = lake_elev.get(lid)
        has_same_reach = False
        if z_self is not None and math.isfinite(float(z_self)):
            zf = float(z_self)
            for other in reach_lakes.get(rid, ()):
                if other == lid:
                    continue
                z_other = lake_elev.get(other)
                if z_other is not None and math.isfinite(float(z_other)):
                    if float(z_other) > zf + min_same_reach_dz_m:
                        has_same_reach = True
                        break
        upstream_glof[lid] = has_same_reach
    return upstream_glof


# ---------------------------------------------------------------------------
def main(argv=None):
    ap = argparse.ArgumentParser(
        description="Assemble Nepal TRAYA deterministic data/*.js bundles."
    )
    ap.add_argument(
        "--sync-html", action="store_true",
        help="Explicitly copy src/template.html to index.html (disabled by default "
             "to prevent accidental overwrite of index.html).",
    )
    args = ap.parse_args(argv)

    os.makedirs(C.DATA, exist_ok=True)
    lakes, terr, expo, cat, net = load_inputs()
    glof_hist, glof_meta = load_glof_history()
    post = MG.load_depth_posterior()
    fit = MG.fit_piecewise()
    expo_xy = np.array([[o["lon"], o["lat"]] for o in expo], float)

    # ---- lake reach lookup and upstream-lake topology ----------------------
    lake_reach = {}
    lake_elev = {}
    for f in lakes:
        p = f["properties"]
        lid = p["lake_id"]
        g = shape(f["geometry"])
        rid, _ = net.nearest_reach(g.centroid.x, g.centroid.y)
        if rid:
            lake_reach[lid] = rid
        t = terr.get(lid) or {}
        z_val = t.get("z_lake_m")
        if z_val is None:
            z_val = p.get("z")
        lake_elev[lid] = z_val

    upstream_glof = detect_upstream_glof(
        lake_reach,
        lake_elev,
        lambda r: net.trace_up(r, max_km=30.0),
    )

    # ---- per lake ----------------------------------------------------------
    ice_cored_ids = _match_ice_cored(lakes)
    named_ids = _match_named(lakes)
    adm = AD.AdminIndex()
    prov_mismatch = 0
    feats, routes, used_expo = [], {}, set()
    counts = Counter()
    t0 = time.time()

    with PopSampler() as pop:
        for n, f in enumerate(lakes, 1):
            p = f["properties"]
            lid = p["lake_id"]
            g = shape(f["geometry"])
            area_km2 = float(p["l_km2"])
            area_m2 = area_km2 * 1e6
            t = terr.get(lid) or {}
            if "error" in t:
                counts["terrain_error"] += 1

            ava_dict = t.get("avalanche") or {}
            rock_dict = t.get("rockfall") or {}
            ava = bool(ava_dict.get("can_reach"))
            rock = bool(rock_dict.get("can_reach"))
            ups = bool(upstream_glof.get(lid))
            sla_area = float(t.get("sla_area_m2") or 0.0)
            sla_steep = sla_area > 0.0
            ice = True if lid in ice_cored_ids else None

            hz = HZ.overall_hazard(ava, rock, ups, sla_steep, ice)
            hz_enum = HZ.overall_hazard_enumerated(ava, rock, ups, sla_steep, ice)
            counts[f"hazard_{hz}"] += 1

            mag = MG.lake_magnitudes(area_m2, post, fit, seed=stable_seed(lid)) \
                if area_km2 >= C.MIN_LAKE_AREA_KM2 else {}
            hp = float(t.get("hp_m") or 0.0)
            pfv = TR.pfv_fujita(area_km2, hp)

            seis = SZ.nearby_seismicity(g.centroid.x, g.centroid.y, cat)
            prov = adm.province(g.centroid.x, g.centroid.y)
            dist = adm.district(g.centroid.x, g.centroid.y)
            if prov and p.get("prov") and not prov.lower().startswith(str(p["prov"]).split()[0].lower()[:5]):
                prov_mismatch += 1

            z_lake = t.get("z_lake_m") if t.get("z_lake_m") is not None else p.get("z")
            sc = mag.get("scenarios") or {}
            props = dict(
                id=lid,
                name=named_ids.get(lid) or (p.get("gnm") or ""),
                area_km2=area_km2,
                z=z_lake,
                typ=p.get("typ"),
                prov=prov,
                district=dist,
                prov_inventory=p.get("prov"),
                rgi=p.get("rgi"),
                dist_glacier_m=p.get("d"),
                area_change_pct=p.get("chg"),
                change_class=p.get("cls"),
                past_glof=int(p.get("glof") or 0),
                contrib_km2=_r(t.get("contributing_area_km2"), 2),
                relief_m=_r(t.get("relief_above_m"), 0),
                slope1k_deg=_r(t.get("max_slope_1km_deg"), 1),
                ice_contact=bool((t.get("ice_contact_cells") or 0) > 0),
                permafrost_belt=bool(z_lake is not None and float(z_lake) >= C.PERMAFROST_LOWER_M),
                # triggers
                avalanche=ava, rockfall=rock, upstream_glof=ups,
                sla_area_km2=round(sla_area / 1e6, 4),
                sla_max_angle=_r(t.get("sla_max_angle_deg"), 1),
                ice_cored=ice,
                ava_volume_Mm3=_r(ava_dict.get("max_volume_m3", 0) / 1e6, 2),
                ava_reach_deg=_r(ava_dict.get("min_reach_angle_deg"), 1),
                rock_reach_deg=_r(rock_dict.get("min_reach_angle_deg"), 1),
                # magnitudes
                depth_m=_r((mag.get("depth_m") or {}).get("p50"), 0),
                depth_lo=_r((mag.get("depth_m") or {}).get("p2_5"), 0),
                depth_hi=_r((mag.get("depth_m") or {}).get("p97_5"), 0),
                volume_Mm3=_r((mag.get("volume_m3") or {}).get("p50", 0) / 1e6 if mag else None, 2),
                qp_m3s=_r(((mag.get("pooled") or {}).get("peak_discharge_m3s") or {}).get("p50"), 0),
                qp_lo=_r(((mag.get("pooled") or {}).get("peak_discharge_m3s") or {}).get("p2_5"), 0),
                qp_hi=_r(((mag.get("pooled") or {}).get("peak_discharge_m3s") or {}).get("p97_5"), 0),
                qp_10=_r(((sc.get("10pct") or {}).get("peak_discharge_m3s") or {}).get("p50"), 0),
                qp_30=_r(((sc.get("30pct") or {}).get("peak_discharge_m3s") or {}).get("p50"), 0),
                qp_50=_r(((sc.get("50pct") or {}).get("peak_discharge_m3s") or {}).get("p50"), 0),
                qp_100=_r(((sc.get("100pct") or {}).get("peak_discharge_m3s") or {}).get("p50"), 0),
                hp_m=_r(hp, 1), hp_capped=bool(hp >= C.HP_SEARCH_MAX_M - 0.5),
                pfv_Mm3=_r(pfv / 1e6, 2),
                pfv_lo_Mm3=_r(pfv * (1 - C.PFV_REPORTED_UNCERTAINTY) / 1e6, 2),
                pfv_hi_Mm3=_r(pfv * (1 + C.PFV_REPORTED_UNCERTAINTY) / 1e6, 2),
                priority=bool(pfv >= C.PFV_PRIORITY_M3),
                dm_fujita_m=_r(TR.mean_depth_fujita(area_km2), 1),
                # seismic context
                **{f"eq_{k}": v for k, v in seis.items()},
                hazard=hz,
                hazard_enum=hz_enum,
            )

            # ---- downstream routing for lakes that could matter ------------
            route_needed = (HZ.ORDER[hz] >= 1 and area_km2 >= 0.02) or pfv > 1e6 \
                or (props["qp_m3s"] or 0) > 500
            if route_needed and lid in lake_reach:
                r = _route(lid, g, net, pop, expo, expo_xy, props)
                if r:
                    routes[lid] = r
                    used_expo.update(h[0] for h in r["_hits"])
                    props["impact"] = r["impact"]
                    props["risk"] = HZ.risk(hz, r["impact"])
                    props["risk_enum"] = HZ.risk(hz_enum, r["impact"])
                    props["route_km"] = r["km"]
                    props["pop_low"] = r["pop_low"]
                    props["pop_high"] = r["pop_high"]
                    props["n_settlements"] = r["n"]["places"]
                    props["n_hydropower"] = r["n"]["hydropower"]
                    props["n_bridges"] = r["n"]["bridges"]
                    props["n_health"] = r["n"]["health"]
                    props["qp_over_mean_flow"] = r["qp_over_mean_flow"]
                    del r["_hits"]
                    counts[f"impact_{r['impact']}"] += 1
                    counts[f"risk_{props['risk']}"] += 1
            else:
                props["impact"] = None
                props["risk"] = None
                props["risk_enum"] = None

            feats.append(dict(type="Feature", geometry=f["geometry"], properties=props))
            if n % 200 == 0:
                print(f"  lakes {n}/{len(lakes)}  {time.time()-t0:.0f}s", flush=True)

    # ---- write outputs ----------------------------------------------------
    interesting = {i for i in used_expo
                   if expo[i]["name"] or expo[i]["kind"] in ("hydropower", "health")}
    expo_out = [dict(o, i=i) for i, o in enumerate(expo)
                if i in interesting or o["kind"] == "hydropower"]
    keep = {o["i"] for o in expo_out}
    for r in routes.values():
        hits = [[i, round(d, 1), round(off)] for i, d, off in r.pop("hits_raw")
                if i in keep]
        r["exp"] = hits[:80]

    _write_js("lakes.js", "LAKES", dict(type="FeatureCollection", features=feats))
    _write_js("routes.js", "ROUTES", routes)
    _write_js("exposure.js", "EXPOSURE", expo_out)
    _write_js("eq_history.js", "EQ_HISTORY", cat)
    _write_js("glof_history.js", "GLOF_HISTORY", glof_hist)

    next_refresh = (
        datetime.datetime.now(datetime.timezone.utc)
        + datetime.timedelta(days=C.REFRESH_INTERVAL_DAYS)
    ).strftime("%Y-%m-%dT%H:%M:%SZ")

    summary = dict(
        build=BUILD_ID,
        platform=C.PLATFORM_TITLE,
        refresh_interval_days=C.REFRESH_INTERVAL_DAYS,
        next_scheduled_refresh=next_refresh,
        n_lakes=len(feats),
        n_routed=len(routes),
        n_priority=sum(1 for f in feats if f["properties"].get("priority")),
        province_reassigned=prov_mismatch,
        counts=dict(counts),
        hazard_counts={k: counts[f"hazard_{k}"] for k in HZ.ORDER},
        risk_counts={k: counts[f"risk_{k}"] for k in HZ.ORDER},
        seismicity=SZ.summarise(cat),
        glof_history=glof_meta,
        exposure_totals=dict(Counter(o["kind"] for o in expo)),
        model=dict(depth_posterior_draws=int(post.shape[0]),
                   depth_beta0=float(post[:, 0].mean()),
                   depth_beta1=float(post[:, 1].mean()),
                   depth_sigma=float(post[:, 2].mean()),
                   qp_piecewise=fit,
                   breach_rate_lognormal=dict(zip(
                       ("meanlog", "sdlog", "kmax"), MG.breach_rate_lognormal(),
                       strict=True))),
        thresholds=dict(
            avalanche_slope=[C.AVALANCHE_SLOPE_MIN, C.AVALANCHE_SLOPE_MAX],
            avalanche_depths_m=list(C.AVALANCHE_DEPTHS_M),
            avalanche_representative_depth_m=C.AVALANCHE_REPRESENTATIVE_DEPTH_M,
            avalanche_slab_area_cap_m2=C.AVALANCHE_SLAB_AREA_CAP_M2,
            rockfall_slope=C.ROCKFALL_SLOPE_MIN,
            reach_angle=[C.REACH_ANGLE_AVALANCHE, C.REACH_ANGLE_ROCKFALL],
            sla_threshold=C.SLA_THRESHOLD_DEG,
            front_velocity_ms=list(C.FRONT_VELOCITY_MS),
            routing_max_km=C.ROUTING_MAX_DISTANCE_KM,
            corridor_m=C.EXPOSURE_CORRIDOR_M,
            dahal_hasegawa=list(C.DAHAL_HASEGAWA),
            permafrost_lower_m=C.PERMAFROST_LOWER_M,
            freezing_level_margin_m=C.FREEZING_LEVEL_MARGIN_M),
        live_feeds=dict(
            usgs=C.USGS_LIVE_FEEDS,
            open_meteo=C.OPEN_METEO,
            open_meteo_flood=C.OPEN_METEO_FLOOD,
            stac_earth_search=C.STAC_EARTH_SEARCH,
            nasa_gibs_wmts=C.NASA_GIBS_WMTS,
            eox_s2_cloudless=C.EOX_S2_CLOUDLESS,
            gdacs=C.GDACS_API,
        ),
        sources=C.SOURCES,
    )
    _write_js("summary.js", "SUMMARY", summary)
    _atomic_write_text(
        os.path.join(C.DATA, "model_fit.json"),
        json.dumps(dict(model=summary["model"], build=BUILD_ID), indent=2) + "\n",
    )

    if args.sync_html:
        tpl = os.path.join(os.path.dirname(os.path.abspath(__file__)), "template.html")
        dst = os.path.join(C.ROOT, "index.html")
        if not os.path.exists(tpl):
            raise FileNotFoundError(f"--sync-html requested but {tpl} does not exist")
        shutil.copyfile(tpl, dst)
        print("  synced index.html from src/template.html")
    else:
        print("  left index.html unchanged (pass --sync-html to copy src/template.html)")

    print(json.dumps({k: v for k, v in summary.items()
                      if k in ("n_lakes", "n_routed", "n_priority",
                               "hazard_counts", "risk_counts", "glof_history")},
                     indent=2))


def _route(lid, geom, net, pop, expo, expo_xy, props):
    rid = net.nearest_reach(geom.centroid.x, geom.centroid.y)[0]
    if not rid:
        return None
    trace = net.trace_down(rid)
    if not trace:
        return None
    # Keep full unsimplified river geometry for metric exposure matching & UTM buffering
    raw_path = net.raw_path_geometry(trace)
    if raw_path is None or raw_path.length == 0:
        return None
    # Apply simplification strictly to the web display polyline
    display_path = raw_path.simplify(0.004, preserve_topology=False)
    if display_path is None or display_path.is_empty:
        display_path = raw_path

    hits = nearest_exposure_on_path(raw_path, expo, expo_xy, C.EXPOSURE_CORRIDOR_M)
    n = Counter(expo[i]["kind"] for i, _, _ in hits)
    popc = pop.corridor_population(raw_path, C.EXPOSURE_CORRIDOR_M)
    mean_q = net.mean_discharge(rid)
    qp = props.get("qp_m3s")
    impact = HZ.downstream_impact(n["places"], n["hydropower"], n["bridges"], n["health"])
    return dict(
        km=round(trace[-1][1], 1),
        path=[[round(x, 4), round(y, 4)] for x, y in display_path.coords],
        n=dict(places=n["places"], hydropower=n["hydropower"], bridges=n["bridges"],
               health=n["health"], borders=n["borders"]),
        pop_low=_r(min(_popvals), 0) if (_popvals := [v for v in popc.values() if v is not None]) else None,
        pop_high=_r(max(_popvals), 0) if _popvals else None,
        impact=impact,
        travel_min_per_km={f"v{v:g}": round(1000.0 / v / 60.0, 3) for v in C.FRONT_VELOCITY_MS},
        qp_over_mean_flow=_r(qp / mean_q, 0) if (qp and mean_q and mean_q > 0) else None,
        hits_raw=hits, _hits=hits,
    )


def _match_named(lakes):
    """Attach literature names to the inventory polygons that contain them."""
    out = {}
    for name, lon, lat in HZ.NAMED_LAKES:
        pt = Point(lon, lat)
        d, f = min(((shape(x["geometry"]).distance(pt), x) for x in lakes),
                   key=lambda t: t[0])
        if d < 0.02:
            out[f["properties"]["lake_id"]] = name
    return out


def _match_ice_cored(lakes):
    out = {}
    for name, lon, lat, note in HZ.DOCUMENTED_ICE_CORED:
        p = Point(lon, lat)
        best = min(((shape(f["geometry"]).distance(p), f) for f in lakes),
                   key=lambda t: t[0])
        if best[0] < 0.03:
            out[best[1]["properties"]["lake_id"]] = (name, note)
    return out


def _r(v, nd=2):
    if v is None or (isinstance(v, float) and not math.isfinite(v)):
        return None
    return round(float(v), nd)


def _write_js(fn, var, obj):
    path = os.path.join(C.DATA, fn)
    payload = f"window.{var} = " + json.dumps(obj, separators=(",", ":"), allow_nan=False) + ";\n"
    _atomic_write_text(path, payload)
    print(f"  wrote {fn}  {os.path.getsize(path)/1024:.0f} KB")


if __name__ == "__main__":
    main()
