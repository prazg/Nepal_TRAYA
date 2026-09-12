"""
Sensitivity of the results to the choices this implementation had to make where
the published methods were ambiguous or where our data differ from theirs.

Four experiments:

  A. SLA threshold angle (8, 10, 12, 15 degrees). Fujita et al. (2013) derived
     10 degrees from pre-GLOF topography and themselves report a threshold
     sensitivity analysis; we repeat it on the Copernicus DEM.
  B. SLA inner buffer (0 m, as Fujita et al. define it, against the 100 m buffer
     Rounce et al. applied to suppress GDEM artefacts) and the minimum patch size.
  C. DEM window half-width (6, 8, 10 km), which bounds how far upslope a mass
     movement source can be found.
  D. The two readings of the Rounce et al. (2016) hazard flow chart, over the
     whole inventory.

A, B and C are run on every lake of at least 0.05 km2, which contains all lakes
that reach the potential-flood-volume priority threshold.

Writes data/sensitivity.js and prints a summary.
"""
from __future__ import annotations
import json
import os
import time

import numpy as np
from shapely.geometry import shape
from shapely.strtree import STRtree

import config as C
import hazard as HZ
import terrain as TR

SAMPLE_MIN_AREA_KM2 = 0.05


def _read_js(fn):
    txt = open(os.path.join(C.DATA, fn)).read()
    return json.loads(txt.split("=", 1)[1].rsplit(";", 1)[0])


def run_variants(lakes, dem, tree, ggeoms, variants):
    """Recompute the terrain products for each configuration variant."""
    out = {name: {} for name in variants}
    base = dict(sla_thr=C.SLA_THRESHOLD_DEG, sla_inner=C.SLA_BUFFER_INNER_M,
                sla_patch=C.SLA_MIN_PATCH_CELLS)
    t0 = time.time()
    for n, f in enumerate(lakes, 1):
        lid = f["properties"]["lake_id"]
        for name, cfg in variants.items():
            C.SLA_THRESHOLD_DEG = cfg.get("sla_thr", base["sla_thr"])
            C.SLA_BUFFER_INNER_M = cfg.get("sla_inner", base["sla_inner"])
            C.SLA_MIN_PATCH_CELLS = cfg.get("sla_patch", base["sla_patch"])
            try:
                r = TR.analyse_lake(f["geometry"], f["properties"], dem, tree, ggeoms,
                                    buffer_km=cfg.get("buffer_km", 8.0))
            except Exception as exc:
                r = {"error": str(exc)}
            a = float(f["properties"]["l_km2"])
            out[name][lid] = dict(
                sla_km2=round((r.get("sla_area_m2") or 0.0) / 1e6, 4),
                hp_m=round(r.get("hp_m") or 0.0, 1),
                pfv_Mm3=round(TR.pfv_fujita(a, r.get("hp_m") or 0.0) / 1e6, 3),
                avalanche=bool((r.get("avalanche") or {}).get("can_reach")),
                rockfall=bool((r.get("rockfall") or {}).get("can_reach")),
            )
        if n % 25 == 0:
            print(f"  {n}/{len(lakes)} lakes, {time.time()-t0:.0f}s", flush=True)
    C.SLA_THRESHOLD_DEG, C.SLA_BUFFER_INNER_M, C.SLA_MIN_PATCH_CELLS = (
        base["sla_thr"], base["sla_inner"], base["sla_patch"])
    return out


def summarise(res, ref_key):
    ref = res[ref_key]
    rows = []
    for name, d in res.items():
        pfv = np.array([v["pfv_Mm3"] for v in d.values()])
        refp = np.array([ref[k]["pfv_Mm3"] for k in d])
        both = (pfv > 0) & (refp > 0)
        rows.append(dict(
            variant=name,
            n_with_sla=int(sum(v["sla_km2"] > 0 for v in d.values())),
            n_priority=int((pfv >= C.PFV_PRIORITY_M3 / 1e6).sum()),
            total_pfv_Mm3=round(float(pfv.sum()), 1),
            median_ratio_to_reference=round(float(np.median(pfv[both] / refp[both])), 3)
            if both.any() else None,
            n_avalanche=int(sum(v["avalanche"] for v in d.values())),
            n_rockfall=int(sum(v["rockfall"] for v in d.values())),
            priority_set_changed=int(sum(
                (d[k]["pfv_Mm3"] >= 10) != (ref[k]["pfv_Mm3"] >= 10) for k in d)),
        ))
    return rows


def main():
    lakes_all = json.load(open(os.path.join(C.RAW, "lakes.geojson")))["features"]
    glac = json.load(open(os.path.join(C.RAW, "glaciers.geojson")))["features"]
    ggeoms = [shape(f["geometry"]) for f in glac]
    tree = STRtree(ggeoms)
    dem = TR.DemReader()
    sample = [f for f in lakes_all
              if float(f["properties"]["l_km2"]) >= SAMPLE_MIN_AREA_KM2]
    print(f"sensitivity sample: {len(sample)} lakes of at least "
          f"{SAMPLE_MIN_AREA_KM2} km2")

    variants = {
        "reference (10 deg, 0 m buffer, 4 cells, 8 km window)": {},
        "SLA threshold 8 deg": dict(sla_thr=8.0),
        "SLA threshold 12 deg": dict(sla_thr=12.0),
        "SLA threshold 15 deg": dict(sla_thr=15.0),
        "SLA inner buffer 100 m (Rounce et al.)": dict(sla_inner=100.0),
        "SLA minimum patch 1 cell": dict(sla_patch=1),
        "SLA minimum patch 12 cells": dict(sla_patch=12),
        "DEM window 6 km": dict(buffer_km=6.0),
        "DEM window 10 km": dict(buffer_km=10.0),
    }
    res = run_variants(sample, dem, tree, ggeoms, variants)
    ref_key = "reference (10 deg, 0 m buffer, 4 cells, 8 km window)"
    rows = summarise(res, ref_key)

    # D. the two readings of the hazard flow chart, over the whole inventory
    built = _read_js("lakes.js")["features"]
    from collections import Counter
    gen, enu, diff = Counter(), Counter(), 0
    for f in built:
        p = f["properties"]
        args = (p["avalanche"], p["rockfall"], p["upstream_glof"],
                (p["sla_area_km2"] or 0) > 0, p["ice_cored"])
        g = HZ.overall_hazard(*args)
        e = HZ.overall_hazard_enumerated(*args)
        gen[g] += 1
        enu[e] += 1
        diff += g != e

    out = dict(
        sample_size=len(sample), sample_min_area_km2=SAMPLE_MIN_AREA_KM2,
        variants=rows, reference=ref_key,
        hazard_reading=dict(general=dict(gen), enumerated=dict(enu),
                            n_lakes_differing=diff, n_lakes=len(built)),
    )
    with open(os.path.join(C.DATA, "sensitivity.js"), "w") as fh:
        fh.write("window.SENSITIVITY = ")
        json.dump(out, fh, separators=(",", ":"), allow_nan=False)
        fh.write(";\n")

    print(f"\n{'variant':46s} {'SLA>0':>6s} {'priority':>9s} {'sum PFV':>9s} "
          f"{'med ratio':>10s} {'ava':>5s} {'rock':>5s} {'prio flips':>11s}")
    for r in rows:
        print(f"{r['variant'][:46]:46s} {r['n_with_sla']:6d} {r['n_priority']:9d} "
              f"{r['total_pfv_Mm3']:9.1f} "
              f"{(r['median_ratio_to_reference'] if r['median_ratio_to_reference'] is not None else float('nan')):10.3f} "
              f"{r['n_avalanche']:5d} {r['n_rockfall']:5d} {r['priority_set_changed']:11d}")
    print(f"\nhazard flow chart readings over all {len(built)} lakes:")
    print(f"  general    {dict(gen)}")
    print(f"  enumerated {dict(enu)}")
    print(f"  {diff} lakes ({100*diff/len(built):.1f}%) are classed differently")


if __name__ == "__main__":
    main()
