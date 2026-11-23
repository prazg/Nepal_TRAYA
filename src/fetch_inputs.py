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
import sys
import time
import urllib.request
import zipfile

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


def get(url: str, dest: str, force: bool = False, retries: int = 3) -> None:
    """Download ``url`` to ``dest`` atomically with exponential backoff retries."""
    os.makedirs(os.path.dirname(os.path.abspath(dest)), exist_ok=True)
    if os.path.exists(dest) and os.path.getsize(dest) > 1000 and not force:
        print(f"  have {os.path.basename(dest)}")
        return

    tmp = f"{dest}.tmp.{os.getpid()}"
    last_err = None
    for attempt in range(retries):
        print(f"  fetching {os.path.basename(dest)}"
              + (f" (retry {attempt + 1}/{retries})" if attempt else "") + " ...",
              flush=True)
        try:
            req = urllib.request.Request(
                url, headers={"User-Agent": "nepal-traya/2.0 (research)"}
            )
            nbytes = 0
            with urllib.request.urlopen(req, timeout=600) as r, open(tmp, "wb") as fh:
                while chunk := r.read(1 << 20):
                    fh.write(chunk)
                    nbytes += len(chunk)
            if nbytes == 0:
                raise RuntimeError("downloaded 0 bytes")
            os.replace(tmp, dest)
            return
        except Exception as exc:
            last_err = exc
            if os.path.exists(tmp):
                try:
                    os.remove(tmp)
                except OSError:
                    pass
            if attempt < retries - 1:
                time.sleep(5 * (2 ** attempt))
    raise RuntimeError(f"failed to fetch {url}: {last_err}")


def safe_extract_zip(zip_path: str, dest_dir: str) -> None:
    """Extract ``zip_path`` into ``dest_dir`` using stdlib zipfile with path traversal checks."""
    base = os.path.abspath(dest_dir)
    os.makedirs(base, exist_ok=True)
    with zipfile.ZipFile(zip_path, "r") as zf:
        for member in zf.infolist():
            target = os.path.abspath(os.path.join(base, member.filename))
            if not (target == base or target.startswith(base + os.sep)):
                raise RuntimeError(f"unsafe zip member path: {member.filename}")
        zf.extractall(base)


def dem_tiles(bbox=(80.3, 27.2, 88.2, 30.5), buf: float = 0.2):
    out = []
    for lat in range(math.floor(bbox[1] - buf), math.ceil(bbox[3] + buf)):
        for lon in range(math.floor(bbox[0] - buf), math.ceil(bbox[2] + buf)):
            out.append(f"N{lat:02d}_00_E{lon:03d}_00")
    return out


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(
        description="Fetch core open-access datasets and/or Copernicus DEM GLO-30 tiles."
    )
    ap.add_argument("--core", action="store_true")
    ap.add_argument("--dem", action="store_true")
    ap.add_argument("--all", action="store_true")
    ap.add_argument("--force", action="store_true",
                    help="Re-download files even if already present locally")
    a = ap.parse_args(argv)
    if not (a.core or a.dem or a.all):
        ap.print_help()
        return 1

    if a.core or a.all:
        print("core inputs")
        for url, dest in CORE + LIT:
            get(url, dest, force=a.force)
        zip_path = os.path.join(C.RAW, "hydro", "HydroRIVERS_as.zip")
        get(HYDRO_ZIP, zip_path, force=a.force)
        shp = os.path.join(C.RAW, "hydro", "HydroRIVERS_v10_as_shp",
                           "HydroRIVERS_v10_as.shp")
        if not os.path.exists(shp) or a.force:
            print("  extracting HydroRIVERS with zipfile ...")
            safe_extract_zip(zip_path, os.path.dirname(zip_path))
        print("  note: HMAGLOFDB (ICIMOD) is not redistributed. Place "
              "HMAGLOFDB_v4.csv in raw/ for the full ICIMOD database "
              "(build.py automatically falls back to raw/glof.geojson with a warning).")

    if a.dem or a.all:
        tiles = dem_tiles()
        print(f"Copernicus DEM: {len(tiles)} tiles")
        failed_tiles = []
        for t in tiles:
            fn = f"Copernicus_DSM_COG_10_{t}_DEM.tif"
            try:
                get(f"{DEM_BASE}/{fn[:-4]}/{fn}", os.path.join(C.DEM_DIR, fn),
                    force=a.force)
            except Exception as exc:
                print(f"  ERROR {t}: {exc}", file=sys.stderr)
                failed_tiles.append((t, str(exc)))
        if failed_tiles:
            print(f"error: {len(failed_tiles)}/{len(tiles)} Copernicus DEM tile downloads failed: "
                  + ", ".join(t for t, _ in failed_tiles), file=sys.stderr)
            return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
