"""
Step 1 of the pipeline: per-lake terrain analysis over the Copernicus DEM.

This is the expensive step (a windowed DEM read, depression fill, D8 routing and
two mass-movement tests per lake), so its output is cached to
cache/terrain.json and the rest of the pipeline reads that.

Run:  python3 build_terrain.py [--limit N] [--workers K]
"""
from __future__ import annotations
import argparse
import json
import os
import time
from multiprocessing import Pool

from shapely.geometry import shape
from shapely.strtree import STRtree

import config as C
import terrain as T

CACHE = os.path.join(C.CACHE, "terrain.json")

_G = {}


def _init():
    lakes = json.load(open(os.path.join(C.RAW, "lakes.geojson")))["features"]
    glac = json.load(open(os.path.join(C.RAW, "glaciers.geojson")))["features"]
    geoms = [shape(f["geometry"]) for f in glac]
    _G["lakes"] = lakes
    _G["ggeoms"] = geoms
    _G["tree"] = STRtree(geoms)
    _G["dem"] = T.DemReader()


def _one(i: int):
    f = _G["lakes"][i]
    lid = f["properties"]["lake_id"]
    try:
        r = T.analyse_lake(f["geometry"], f["properties"], _G["dem"],
                           _G["tree"], _G["ggeoms"])
    except Exception as exc:                       # keep the run going
        r = dict(error=f"{type(exc).__name__}: {exc}")
    return lid, r


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--limit", type=int, default=0)
    ap.add_argument("--workers", type=int, default=2)
    ap.add_argument("--out", default=CACHE)
    a = ap.parse_args()

    os.makedirs(os.path.dirname(a.out), exist_ok=True)
    _init()
    n = len(_G["lakes"]) if not a.limit else min(a.limit, len(_G["lakes"]))
    print(f"terrain analysis for {n} lakes on {a.workers} workers", flush=True)

    done = {}
    if os.path.exists(a.out):
        try:
            done = json.load(open(a.out))
            print(f"  resuming: {len(done)} already cached", flush=True)
        except Exception:
            done = {}
    todo = [i for i in range(n)
            if _G["lakes"][i]["properties"]["lake_id"] not in done]

    t0 = time.time()
    with Pool(a.workers, initializer=_init) as pool:
        for k, (lid, r) in enumerate(pool.imap_unordered(_one, todo, chunksize=4), 1):
            done[lid] = r
            if k % 50 == 0 or k == len(todo):
                el = time.time() - t0
                rate = k / el
                print(f"  {k}/{len(todo)}  {el:.0f}s  {rate:.2f} lakes/s  "
                      f"eta {(len(todo)-k)/max(rate,1e-6)/60:.1f} min", flush=True)
                json.dump(done, open(a.out, "w"))
    json.dump(done, open(a.out, "w"))
    errs = sum(1 for v in done.values() if "error" in v)
    print(f"done: {len(done)} lakes, {errs} errors, {time.time()-t0:.0f}s")


if __name__ == "__main__":
    main()
