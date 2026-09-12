"""
Download every input this pipeline needs that is not kept in the repository.

  --core   lake, glacier and GLOF layers; HydroRIVERS; WorldPop  (about 100 MB)
  --dem    the 36 Copernicus DEM GLO-30 tiles covering Nepal     (about 1.4 GB)
  --all    both

Only --dem is needed to regenerate cache/terrain.json from scratch; the cached
terrain product is small enough to keep in the repository, so a routine refresh
needs only --core.

Nothing here is redistributed: each file is fetched from its original provider.
"""
from __future__ import annotations
import argparse
import math
import os
import subprocess
import sys
import urllib.request

import config as C

INVENTORY = "https://prazg.github.io/Nepal_Cryosphere_Inventory/data"
CORE = [
    (f"{INVENTORY}/lakes.geojson", os.path.join(C.RAW, "lakes.geojson")),
    (f"{INVENTORY}/glaciers.geojson", os.path.join(C.RAW, "glaciers.geojson")),
    (f"{INVENTORY}/glof.geojson", os.path.join(C.RAW, "glof.geojson")),
    ("https://data.worldpop.org/GIS/Population/Global_2000_2020_Constrained/2020/BSGM/NPL/"
     "npl_ppp_2020_UNadj_constrained.tif", os.path.join(C.RAW, "pop", "npl_pop_2020.tif")),
    ("https://data.worldpop.org/GIS/Population/Global_2000_2020/2020/NPL/npl_ppp_2020_UNadj.tif",
     os.path.join(C.RAW, "pop", "npl_pop_2020_unconstrained.tif")),
]
HYDRO_ZIP = "https://data.hydrosheds.org/file/HydroRIVERS/HydroRIVERS_v10_as_shp.zip"
# Veh et al. (2020) supplementary data, CC-BY-4.0
ZENODO = "https://zenodo.org/records/3523213/files"
LIT = [
    (f"{ZENODO}/mcmcChain.rds?download=1", os.path.join(C.LIT, "mcmcChain.rds")),
    (f"{ZENODO}/beebee-oconnor-2009-data.rds?download=1",
     os.path.join(C.LIT, "beebee-oconnor-2009-data.rds")),
]
DEM_BASE = "https://copernicus-dem-30m.s3.amazonaws.com"


def get(url: str, dest: str, force: bool = False):
    os.makedirs(os.path.dirname(dest), exist_ok=True)
    if os.path.exists(dest) and os.path.getsize(dest) > 1000 and not force:
        print(f"  have {os.path.basename(dest)}")
        return
    print(f"  fetching {os.path.basename(dest)} …", flush=True)
    req = urllib.request.Request(url, headers={"User-Agent": "nepal-ews/1.0 (research)"})
    with urllib.request.urlopen(req, timeout=600) as r, open(dest, "wb") as fh:
        while chunk := r.read(1 << 20):
            fh.write(chunk)


def dem_tiles(bbox=(80.3, 27.2, 88.2, 30.5), buf: float = 0.2):
    out = []
    for lat in range(math.floor(bbox[1] - buf), math.ceil(bbox[3] + buf)):
        for lon in range(math.floor(bbox[0] - buf), math.ceil(bbox[2] + buf)):
            out.append(f"N{lat:02d}_00_E{lon:03d}_00")
    return out


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--core", action="store_true")
    ap.add_argument("--dem", action="store_true")
    ap.add_argument("--all", action="store_true")
    a = ap.parse_args()
    if not (a.core or a.dem or a.all):
        ap.print_help()
        return 1

    if a.core or a.all:
        print("core inputs")
        for url, dest in CORE + LIT:
            get(url, dest)
        zip_path = os.path.join(C.RAW, "hydro", "HydroRIVERS_as.zip")
        get(HYDRO_ZIP, zip_path)
        shp = os.path.join(C.RAW, "hydro", "HydroRIVERS_v10_as_shp",
                           "HydroRIVERS_v10_as.shp")
        if not os.path.exists(shp):
            print("  unzipping HydroRIVERS …")
            subprocess.run(["unzip", "-o", "-q", zip_path,
                            "-d", os.path.dirname(zip_path)], check=True)
        print("  note: HMAGLOFDB (ICIMOD) is not redistributed. Place "
              "HMAGLOFDB_v4.csv in raw/ to enable the recorded-GLOF layer.")

    if a.dem or a.all:
        tiles = dem_tiles()
        print(f"Copernicus DEM: {len(tiles)} tiles")
        for t in tiles:
            fn = f"Copernicus_DSM_COG_10_{t}_DEM.tif"
            try:
                get(f"{DEM_BASE}/{fn[:-4]}/{fn}", os.path.join(C.DEM_DIR, fn))
            except Exception as exc:
                print(f"  skip {t}: {exc}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
