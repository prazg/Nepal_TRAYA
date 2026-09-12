"""
Assemble the Nepal Multi-Hazard Early Warning System data products.

Reads:
  raw/lakes.geojson, raw/glaciers.geojson, raw/glof.geojson  (Nepal Cryosphere Inventory)
  raw/HMAGLOFDB_v4.csv                                       (ICIMOD GLOF database)
  raw/hydro/HydroRIVERS_v10_as_shp                           (river network)
  raw/pop/npl_pop_2020*.tif                                  (WorldPop)
  cache/terrain.json                                         (build_terrain.py)
  cache/overpass/*.json                                      (exposure.py)
  cache/usgs_catalogue.json                                  (seismic.py)

Writes into data/:
  lakes.js      window.LAKES     GeoJSON of lakes with hazard attributes
  routes.js     window.ROUTES    routed flow paths, travel times, exposure
  exposure.js   window.EXPOSURE  exposure objects referenced by the routes
  eq_history.js window.EQ_HISTORY historical earthquakes
  glof_history.js window.GLOF_HISTORY  recorded GLOFs in Nepal
  summary.js    window.SUMMARY   headline statistics, model parameters, sources
  model_fit.json                 fitted model parameters and validation table
"""
from __future__ import annotations
import csv
import json
import math
import os
import time
from collections import Counter, defaultdict

import numpy as np
import rasterio
from rasterio import features as rfeatures
from rasterio.windows import from_bounds
from shapely.geometry import shape, LineString, mapping

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
def load_inputs():
    lakes = json.load(open(os.path.join(C.RAW, "lakes.geojson")))["features"]
    terr = json.load(open(os.path.join(C.CACHE, "terrain.json")))
    expo = EX.collect()
    cat = SZ.fetch_catalogue()
    net = RT.RiverNetwork()
    return lakes, terr, expo, cat, net


def hmaglofdb_nepal(path=None):
    """Recorded GLOFs with a Nepalese lake or a Nepalese impact site."""
    path = path or os.path.join(C.RAW, "HMAGLOFDB_v4.csv")
    out = []
    if not os.path.exists(path):
        print("  HMAGLOFDB_v4.csv not present; recorded-GLOF layer will be empty")
        return out
    with open(path, newline="", encoding="utf-8", errors="replace") as fh:
        for row in csv.DictReader(fh):
            if (row.get("Country") or "").strip() != "Nepal":
                continue
            try:
                lat = float(row["Lat_lake"]); lon = float(row["Lon_lake"])
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
    return out


def _num(v):
    try:
        return float(str(v).strip())
    except Exception:
        return None


# ---------------------------------------------------------------------------
class PopSampler:
    """Population in a corridor, from both WorldPop variants for Nepal 2020."""

    def __init__(self):
        self.srcs = {}
        for key, fn in (("constrained", "npl_pop_2020.tif"),
                        ("unconstrained", "npl_pop_2020_unconstrained.tif")):
            p = os.path.join(C.RAW, "pop", fn)
            if os.path.exists(p):
                self.srcs[key] = rasterio.open(p)

    def corridor_population(self, line: LineString, corridor_m: float) -> dict:
        lat0 = line.centroid.y
        dx_deg = corridor_m / (111_320.0 * math.cos(math.radians(lat0)))
        dy_deg = corridor_m / 110_540.0
        buf = line.buffer(max(dx_deg, dy_deg))
        out = {}
        for key, src in self.srcs.items():
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
def nearest_exposure_on_path(path: LineString, expo: list[dict],
                             expo_xy: np.ndarray, corridor_m: float):
    """Exposure objects within `corridor_m` of the routed path, with the
    along-path distance at which the flood would reach each one."""
    lat0 = path.centroid.y
    coords = np.asarray(path.coords)
    # cumulative along-path distance in km
    dlon = np.diff(coords[:, 0]) * 111.320 * math.cos(math.radians(lat0))
    dlat = np.diff(coords[:, 1]) * 110.540
    seg = np.hypot(dlon, dlat)
    cum = np.concatenate([[0.0], np.cumsum(seg)])

    minx, miny, maxx, maxy = path.bounds
    pad = corridor_m / 100_000.0
    sel = np.flatnonzero((expo_xy[:, 0] >= minx - pad) & (expo_xy[:, 0] <= maxx + pad) &
                         (expo_xy[:, 1] >= miny - pad) & (expo_xy[:, 1] <= maxy + pad))
    hits = []
    for i in sel:
        px, py = expo_xy[i]
        d_km = np.hypot((coords[:, 0] - px) * 111.320 * math.cos(math.radians(lat0)),
                        (coords[:, 1] - py) * 110.540)
        j = int(np.argmin(d_km))
        if d_km[j] * 1000.0 <= corridor_m:
            hits.append((int(i), float(cum[j]), float(d_km[j] * 1000.0)))
    hits.sort(key=lambda t: t[1])
    return hits


# ---------------------------------------------------------------------------
def main():
    os.makedirs(C.DATA, exist_ok=True)
    lakes, terr, expo, cat, net = load_inputs()
    post = MG.load_depth_posterior()
    fit = MG.fit_piecewise()
    pop = PopSampler()
    expo_xy = np.array([[o["lon"], o["lat"]] for o in expo], float)

    # ---- lake reach lookup and upstream-lake topology ----------------------
    lake_reach = {}
    for f in lakes:
        g = shape(f["geometry"])
        rid, _ = net.nearest_reach(g.centroid.x, g.centroid.y)
        if rid:
            lake_reach[f["properties"]["lake_id"]] = rid
    reach_lakes = defaultdict(list)
    for lid, rid in lake_reach.items():
        reach_lakes[rid].append(lid)

    upstream_glof = {}
    for lid, rid in lake_reach.items():
        ups = {r for r, _ in net.trace_up(rid, max_km=30.0)}
        upstream_glof[lid] = any(other != lid for r in ups for other in reach_lakes.get(r, []))

    # ---- per lake ----------------------------------------------------------
    ice_cored_ids = _match_ice_cored(lakes)
    named_ids = _match_named(lakes)
    adm = AD.AdminIndex()
    prov_mismatch = 0
    feats, routes, used_expo = [], {}, set()
    counts = Counter()
    t0 = time.time()

    for n, f in enumerate(lakes, 1):
        p = f["properties"]
        lid = p["lake_id"]
        g = shape(f["geometry"])
        area_km2 = float(p["l_km2"])
        area_m2 = area_km2 * 1e6
        t = terr.get(lid) or {}
        if "error" in t:
            counts["terrain_error"] += 1

        ava = bool((t.get("avalanche") or {}).get("can_reach"))
        rock = bool((t.get("rockfall") or {}).get("can_reach"))
        ups = bool(upstream_glof.get(lid))
        sla_area = float(t.get("sla_area_m2") or 0.0)
        sla_steep = sla_area > 0.0
        ice = True if lid in ice_cored_ids else None

        hz = HZ.overall_hazard(ava, rock, ups, sla_steep, ice)
        counts[f"hazard_{hz}"] += 1

        mag = MG.lake_magnitudes(area_m2, post, fit, seed=stable_seed(lid)) \
            if area_km2 >= C.MIN_LAKE_AREA_KM2 else {}
        hp = float(t.get("hp_m") or 0.0)
        pfv = TR.pfv_fujita(area_km2, hp)

        seis = SZ.nearby_seismicity(g.centroid.x, g.centroid.y, cat)
        prov = adm.province(g.centroid.x, g.centroid.y)
        dist = adm.district(g.centroid.x, g.centroid.y)
        if prov and p.get('prov') and not prov.lower().startswith(str(p['prov']).split()[0].lower()[:5]):
            prov_mismatch += 1

        props = dict(
            id=lid, name=named_ids.get(lid) or (p.get('gnm') or ''), area_km2=area_km2, z=t.get("z_lake_m") or p.get("z"),
            typ=p.get("typ"), prov=prov, district=dist,
            prov_inventory=p.get("prov"), rgi=p.get("rgi"),
            dist_glacier_m=p.get("d"), area_change_pct=p.get("chg"),
            change_class=p.get("cls"), past_glof=int(p.get("glof") or 0),
            # triggers
            avalanche=ava, rockfall=rock, upstream_glof=ups,
            sla_area_km2=round(sla_area / 1e6, 4),
            sla_max_angle=_r(t.get("sla_max_angle_deg"), 1),
            ice_cored=ice,
            ava_volume_Mm3=_r((t.get("avalanche") or {}).get("max_volume_m3", 0) / 1e6, 2),
            # magnitudes
            depth_m=_r((mag.get("depth_m") or {}).get("p50"), 0),
            depth_lo=_r((mag.get("depth_m") or {}).get("p2_5"), 0),
            depth_hi=_r((mag.get("depth_m") or {}).get("p97_5"), 0),
            volume_Mm3=_r((mag.get("volume_m3") or {}).get("p50", 0) / 1e6 if mag else None, 2),
            qp_m3s=_r(((mag.get("pooled") or {}).get("peak_discharge_m3s") or {}).get("p50"), 0),
            qp_lo=_r(((mag.get("pooled") or {}).get("peak_discharge_m3s") or {}).get("p2_5"), 0),
            qp_hi=_r(((mag.get("pooled") or {}).get("peak_discharge_m3s") or {}).get("p97_5"), 0),
            hp_m=_r(hp, 1), hp_capped=bool(hp >= C.HP_SEARCH_MAX_M - 0.5),
            pfv_Mm3=_r(pfv / 1e6, 2),
            pfv_lo_Mm3=_r(pfv * (1 - C.PFV_REPORTED_UNCERTAINTY) / 1e6, 2),
            pfv_hi_Mm3=_r(pfv * (1 + C.PFV_REPORTED_UNCERTAINTY) / 1e6, 2),
            priority=bool(pfv >= C.PFV_PRIORITY_M3),
            dm_fujita_m=_r(TR.mean_depth_fujita(area_km2), 1),
            # seismic context
            **{f"eq_{k}": v for k, v in seis.items()},
            hazard=hz,
        )

        # ---- downstream routing for lakes that could matter ---------------
        route_needed = (HZ.ORDER[hz] >= 1 and area_km2 >= 0.02) or pfv > 1e6 \
            or (props["qp_m3s"] or 0) > 500
        if route_needed and lid in lake_reach:
            r = _route(lid, g, net, pop, expo, expo_xy, props)
            if r:
                routes[lid] = r
                used_expo.update(h[0] for h in r["_hits"])
                props["impact"] = r["impact"]
                props["risk"] = HZ.risk(hz, r["impact"])
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

        feats.append(dict(type="Feature", geometry=f["geometry"], properties=props))
        if n % 200 == 0:
            print(f"  lakes {n}/{len(lakes)}  {time.time()-t0:.0f}s", flush=True)

    # ---- write outputs ----------------------------------------------------
    # keep the exposure objects worth naming on the map: anything with a name
    # that sits on a routed path, plus every hydropower plant and health facility
    interesting = {i for i in used_expo
                   if expo[i]["name"] or expo[i]["kind"] in ("hydropower", "health")}
    expo_out = [dict(o, i=i) for i, o in enumerate(expo)
                if i in interesting or o["kind"] == "hydropower"]
    keep = {o["i"] for o in expo_out}
    for lid, r in routes.items():
        hits = [[i, round(d, 1), round(off)] for i, d, off in r.pop("hits_raw")
                if i in keep]
        # nearest first, capped so the payload stays small
        r["exp"] = hits[:80]

    _write_js("lakes.js", "LAKES", dict(type="FeatureCollection", features=feats))
    _write_js("routes.js", "ROUTES", routes)
    _write_js("exposure.js", "EXPOSURE", expo_out)
    _write_js("eq_history.js", "EQ_HISTORY", cat)
    _write_js("glof_history.js", "GLOF_HISTORY", hmaglofdb_nepal())

    summary = dict(
        build=BUILD_ID,
        n_lakes=len(feats),
        n_routed=len(routes),
        province_reassigned=prov_mismatch,
        counts=dict(counts),
        hazard_counts={k: counts[f"hazard_{k}"] for k in HZ.ORDER},
        risk_counts={k: counts[f"risk_{k}"] for k in HZ.ORDER},
        seismicity=SZ.summarise(cat),
        exposure_totals=dict(Counter(o["kind"] for o in expo)),
        model=dict(depth_posterior_draws=int(post.shape[0]),
                   depth_beta0=float(post[:, 0].mean()),
                   depth_beta1=float(post[:, 1].mean()),
                   depth_sigma=float(post[:, 2].mean()),
                   qp_piecewise=fit,
                   breach_rate_lognormal=dict(zip(
                       ("meanlog", "sdlog", "kmax"), MG.breach_rate_lognormal()))),
        thresholds=dict(
            avalanche_slope=[C.AVALANCHE_SLOPE_MIN, C.AVALANCHE_SLOPE_MAX],
            rockfall_slope=C.ROCKFALL_SLOPE_MIN,
            reach_angle=[C.REACH_ANGLE_AVALANCHE, C.REACH_ANGLE_ROCKFALL],
            sla_threshold=C.SLA_THRESHOLD_DEG,
            front_velocity_ms=list(C.FRONT_VELOCITY_MS),
            routing_max_km=C.ROUTING_MAX_DISTANCE_KM,
            corridor_m=C.EXPOSURE_CORRIDOR_M),
        live_feeds=dict(usgs=C.USGS_LIVE_FEEDS, open_meteo=C.OPEN_METEO),
        sources=C.SOURCES,
    )
    _write_js("summary.js", "SUMMARY", summary)
    json.dump(dict(model=summary["model"], build=BUILD_ID),
              open(os.path.join(C.DATA, "model_fit.json"), "w"), indent=2)

    # the page itself lives in src/template.html and is copied to the repo root
    import shutil
    shutil.copyfile(os.path.join(os.path.dirname(os.path.abspath(__file__)),
                                 "template.html"),
                    os.path.join(C.ROOT, "index.html"))
    print("  wrote index.html")
    print(json.dumps({k: v for k, v in summary.items()
                      if k in ("n_lakes", "n_routed", "hazard_counts", "risk_counts")},
                     indent=2))


def _route(lid, geom, net, pop, expo, expo_xy, props):
    rid = net.nearest_reach(geom.centroid.x, geom.centroid.y)[0]
    if not rid:
        return None
    trace = net.trace_down(rid)
    if not trace:
        return None
    path = net.path_geometry(trace)
    if path is None or path.length == 0:
        return None
    hits = nearest_exposure_on_path(path, expo, expo_xy, C.EXPOSURE_CORRIDOR_M)
    n = Counter(expo[i]["kind"] for i, _, _ in hits)
    popc = pop.corridor_population(path, C.EXPOSURE_CORRIDOR_M)
    mean_q = net.mean_discharge(rid)
    qp = props.get("qp_m3s")
    impact = HZ.downstream_impact(n["places"], n["hydropower"], n["bridges"], n["health"])
    return dict(
        km=round(trace[-1][1], 1),
        path=[[round(x, 4), round(y, 4)] for x, y in path.coords],
        n=dict(places=n["places"], hydropower=n["hydropower"], bridges=n["bridges"],
               health=n["health"], borders=n["borders"]),
        pop_low=_r(min(v for v in popc.values() if v is not None), 0) if popc else None,
        pop_high=_r(max(v for v in popc.values() if v is not None), 0) if popc else None,
        impact=impact,
        travel_min_per_km={f"v{v:g}": round(1000.0 / v / 60.0, 3) for v in C.FRONT_VELOCITY_MS},
        qp_over_mean_flow=_r(qp / mean_q, 0) if (qp and mean_q and mean_q > 0) else None,
        hits_raw=hits, _hits=hits,
    )


def _match_named(lakes):
    """Attach literature names to the inventory polygons that contain them."""
    from shapely.geometry import Point
    out = {}
    for name, lon, lat in HZ.NAMED_LAKES:
        pt = Point(lon, lat)
        d, f = min(((shape(x["geometry"]).distance(pt), x) for x in lakes),
                   key=lambda t: t[0])
        if d < 0.02:
            out[f["properties"]["lake_id"]] = name
    return out


def _match_ice_cored(lakes):
    from shapely.geometry import Point
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
    with open(path, "w") as fh:
        fh.write(f"window.{var} = ")
        json.dump(obj, fh, separators=(",", ":"), allow_nan=False)
        fh.write(";\n")
    print(f"  wrote {fn}  {os.path.getsize(path)/1024:.0f} KB")


if __name__ == "__main__":
    main()
