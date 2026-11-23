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

Because >50% of SLA-positive lakes are capped by the Fujita mean depth Dm
(Hp >= Dm), the all-lake median PFV ratio sits identically at 1.0 across
variants. This module therefore reports mean and IQR PFV ratios both overall
and specifically on Hp-limited lakes (Hp < Dm) so true sensitivity is visible.

Writes data/sensitivity.js and prints a summary.
"""
from __future__ import annotations
from collections import Counter
import json
import math
import os
import time

try:
    import numpy as np
except ImportError:  # pragma: no cover - stdlib-only unit test mode
    np = None

try:
    from shapely.geometry import shape
    from shapely.strtree import STRtree
except ImportError:  # pragma: no cover
    shape = STRtree = None

import config as C
import hazard as HZ
import terrain as TR

SAMPLE_MIN_AREA_KM2 = 0.05


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


def _read_js(fn: str):
    with open(os.path.join(C.DATA, fn), encoding="utf-8") as fh:
        txt = fh.read()
    return json.loads(txt.split("=", 1)[1].rsplit(";", 1)[0])


def _quantile(vals: list[float], q: float) -> float:
    """Linear-interpolated quantile matching numpy.percentile (pure stdlib)."""
    s = sorted(vals)
    n = len(s)
    if n == 1:
        return s[0]
    pos = q * (n - 1)
    lo = int(math.floor(pos))
    hi = int(math.ceil(pos))
    if lo == hi:
        return s[lo]
    frac = pos - lo
    return s[lo] + frac * (s[hi] - s[lo])


def _ratio_stats(ratios: list[float]) -> dict:
    if not ratios:
        return dict(median=None, mean=None, iqr=None)
    q25 = _quantile(ratios, 0.25)
    q50 = _quantile(ratios, 0.50)
    q75 = _quantile(ratios, 0.75)
    mean = sum(ratios) / len(ratios)
    return dict(
        median=round(q50, 3),
        mean=round(mean, 3),
        iqr=[round(q25, 3), round(q75, 3)],
    )


def run_variants(lakes, dem, tree, ggeoms, variants):
    """Recompute the terrain products for each configuration variant."""
    out = {name: {} for name in variants}
    base = dict(sla_thr=C.SLA_THRESHOLD_DEG, sla_inner=C.SLA_BUFFER_INNER_M,
                sla_patch=C.SLA_MIN_PATCH_CELLS)
    t0 = time.time()
    try:
        for n, f in enumerate(lakes, 1):
            lid = f["properties"]["lake_id"]
            a = float(f["properties"]["l_km2"])
            dm_m = TR.mean_depth_fujita(a)
            for name, cfg in variants.items():
                C.SLA_THRESHOLD_DEG = cfg.get("sla_thr", base["sla_thr"])
                C.SLA_BUFFER_INNER_M = cfg.get("sla_inner", base["sla_inner"])
                C.SLA_MIN_PATCH_CELLS = cfg.get("sla_patch", base["sla_patch"])
                try:
                    r = TR.analyse_lake(f["geometry"], f["properties"], dem, tree, ggeoms,
                                        buffer_km=cfg.get("buffer_km", 8.0))
                except Exception as exc:
                    r = {"error": str(exc)}
                hp_m = float(r.get("hp_m") or 0.0)
                out[name][lid] = dict(
                    sla_km2=round((r.get("sla_area_m2") or 0.0) / 1e6, 4),
                    hp_m=round(hp_m, 1),
                    dm_m=round(dm_m, 1),
                    hp_limited=bool(0.0 < hp_m < dm_m),
                    pfv_Mm3=round(TR.pfv_fujita(a, hp_m) / 1e6, 3),
                    avalanche=bool((r.get("avalanche") or {}).get("can_reach")),
                    rockfall=bool((r.get("rockfall") or {}).get("can_reach")),
                )
            if n % 25 == 0:
                print(f"  {n}/{len(lakes)} lakes, {time.time()-t0:.0f}s", flush=True)
    finally:
        C.SLA_THRESHOLD_DEG = base["sla_thr"]
        C.SLA_BUFFER_INNER_M = base["sla_inner"]
        C.SLA_MIN_PATCH_CELLS = base["sla_patch"]
    return out


def _is_hp_limited(entry: dict) -> bool:
    if "hp_limited" in entry:
        return bool(entry["hp_limited"])
    hp = entry.get("hp_m")
    dm = entry.get("dm_m")
    if hp is not None and dm is not None:
        return 0.0 < float(hp) < float(dm)
    return False


def summarise(res: dict, ref_key: str) -> list[dict]:
    """Summarise each sensitivity variant against ``ref_key``, reporting mean
    and IQR PFV ratios both across all positive-PFV lakes and specifically on
    Hp-limited lakes (Hp < Dm) where sensitivity is not masked by the Dm cap."""
    ref = res[ref_key]
    prio_thr = C.PFV_PRIORITY_M3 / 1e6
    rows = []
    for name, d in res.items():
        all_ratios = []
        hp_ratios = []
        total_pfv = 0.0
        n_sla = 0
        n_prio = 0
        n_ava = 0
        n_rock = 0
        prio_flips = 0

        for k, v in d.items():
            pfv = float(v["pfv_Mm3"])
            refp = float(ref[k]["pfv_Mm3"])
            total_pfv += pfv
            if v["sla_km2"] > 0:
                n_sla += 1
            if pfv >= prio_thr:
                n_prio += 1
            if v["avalanche"]:
                n_ava += 1
            if v["rockfall"]:
                n_rock += 1
            if (pfv >= prio_thr) != (refp >= prio_thr):
                prio_flips += 1
            if pfv > 0.0 and refp > 0.0:
                ratio = pfv / refp
                all_ratios.append(ratio)
                if _is_hp_limited(v) or _is_hp_limited(ref[k]):
                    hp_ratios.append(ratio)

        all_s = _ratio_stats(all_ratios)
        hp_s = _ratio_stats(hp_ratios)
        rows.append(dict(
            variant=name,
            n_with_sla=n_sla,
            n_priority=n_prio,
            total_pfv_Mm3=round(total_pfv, 1),
            median_ratio_to_reference=all_s["median"],
            mean_ratio_to_reference=all_s["mean"],
            iqr_ratio_to_reference=all_s["iqr"],
            n_hp_limited=len(hp_ratios),
            hp_limited_median_ratio=hp_s["median"],
            hp_limited_mean_ratio=hp_s["mean"],
            hp_limited_iqr_ratio=hp_s["iqr"],
            n_avalanche=n_ava,
            n_rockfall=n_rock,
            priority_set_changed=prio_flips,
        ))
    return rows


def main():
    if shape is None or STRtree is None:
        raise ImportError("sensitivity.main() requires shapely")
    with open(os.path.join(C.RAW, "lakes.geojson"), encoding="utf-8") as fh:
        lakes_all = json.load(fh)["features"]
    with open(os.path.join(C.RAW, "glaciers.geojson"), encoding="utf-8") as fh:
        glac = json.load(fh)["features"]
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
    _atomic_write_text(
        os.path.join(C.DATA, "sensitivity.js"),
        "window.SENSITIVITY = " + json.dumps(out, separators=(",", ":"), allow_nan=False) + ";\n",
    )

    print(f"\n{'variant':42s} {'SLA>0':>5s} {'prio':>4s} {'sumPFV':>7s} "
          f"{'med':>6s} {'Hp-mean':>7s} {'Hp-IQR':>13s} {'ava':>4s} {'rock':>4s} {'flips':>5s}")
    for r in rows:
        iqr = r["hp_limited_iqr_ratio"]
        iqr_s = f"[{iqr[0]:.2f},{iqr[1]:.2f}]" if iqr else "n/a"
        med = r["median_ratio_to_reference"]
        hpm = r["hp_limited_mean_ratio"]
        print(f"{r['variant'][:42]:42s} {r['n_with_sla']:5d} {r['n_priority']:4d} "
              f"{r['total_pfv_Mm3']:7.1f} "
              f"{(med if med is not None else float('nan')):6.3f} "
              f"{(hpm if hpm is not None else float('nan')):7.3f} "
              f"{iqr_s:>13s} {r['n_avalanche']:4d} {r['n_rockfall']:4d} "
              f"{r['priority_set_changed']:5d}")
    print(f"\nhazard flow chart readings over all {len(built)} lakes:")
    print(f"  general    {dict(gen)}")
    print(f"  enumerated {dict(enu)}")
    print(f"  {diff} lakes ({100*diff/len(built):.1f}%) are classed differently")


if __name__ == "__main__":
    main()
