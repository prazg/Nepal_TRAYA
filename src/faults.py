"""
Active tectonic faults layer from the GEM Global Active Faults Database
(Styron & Pagani, 2020; incorporating HimaTibetMap; CC-BY-SA-4.0).

Key scientific & honesty safeguards:
  * Filters out non-fault fold structures (`syncline`, `anticline`, `fold`,
    `monocline`) so only genuine active fault traces are mapped and used for
    per-lake fault-proximity calculations.
  * Preserves an explicit `coverage_note` disclosing that GEM's surface-trace
    compilation covers Quaternary Tibetan grabens and selected MFT reverse
    segments, and does NOT include continuous mapped traces of the Main
    Boundary Thrust (MBT), Main Central Thrust (MCT), or the buried 3D Main
    Himalayan Thrust (MHT) megathrust décollement underlying all of Nepal.

Pure Python 3.12 standard library only (zero third-party dependencies).
"""
from __future__ import annotations

import argparse
import json
import math
import os
import sys
import tempfile
import time
import urllib.request
from collections import Counter
from typing import Any

SRC_DIR = os.path.dirname(os.path.abspath(__file__))
if SRC_DIR not in sys.path:
    sys.path.insert(0, SRC_DIR)

import config as C

USER_AGENT = "Nepal-TRAYA/2.1 (+https://prazg.github.io/Nepal_TRAYA/)"
GEM_RAW_URL = (
    "https://raw.githubusercontent.com/GEMScienceTools/"
    "gem-global-active-faults/master/geojson/gem_active_faults_harmonized.geojson"
)
FAULT_BBOX = (79.5, 25.8, 88.7, 31.0)
CACHE_JSON = os.path.join(C.CACHE, "gem_faults.json")
LEGACY_JS = os.path.join(C.DATA, "faults.js")
OUT_JSON = os.path.join(C.DATA, "faults.json")

FOLD_KEYWORDS = ("syncline", "anticline", "monocline", "fold")


def is_non_fault_fold(props: dict[str, Any] | None) -> bool:
    """Return True if a GEM feature represents a fold rather than a fault trace."""
    if not props:
        return False
    slip = str(props.get("slip_type") or "").lower()
    name = str(props.get("name") or "").lower()
    return any(kw in slip or kw in name for kw in FOLD_KEYWORDS)


def _round_coords(coords: Any, nd: int = 4) -> Any:
    if not isinstance(coords, list):
        return coords
    if coords and isinstance(coords[0], (int, float)):
        return [round(float(coords[0]), nd), round(float(coords[1]), nd)]
    return [_round_coords(c, nd) for c in coords]


def filter_active_faults(features: list[dict[str, Any]]) -> tuple[list[dict[str, Any]], int]:
    """Filter out non-fault folds and round line coordinates to 4 decimals.

    Returns (active_fault_features, n_folds_excluded).
    """
    active: list[dict[str, Any]] = []
    n_excluded = 0
    for feat in features:
        if not isinstance(feat, dict):
            continue
        props = dict(feat.get("properties") or {})
        if is_non_fault_fold(props):
            n_excluded += 1
            continue
        geom = dict(feat.get("geometry") or {})
        if "coordinates" in geom:
            geom["coordinates"] = _round_coords(geom["coordinates"], 4)
        active.append({
            "type": "Feature",
            "geometry": geom,
            "properties": props,
        })
    return active, n_excluded


def _extract_lines(geom: dict[str, Any]) -> list[list[list[float]]]:
    gt = geom.get("type")
    coords = geom.get("coordinates") or []
    if gt == "LineString":
        return [coords]
    if gt == "MultiLineString":
        return list(coords)
    return []


def nearest_fault(
    lon: float, lat: float, fault_features: list[dict[str, Any]]
) -> tuple[float | None, str, str]:
    """Compute true point-to-segment distance (km) to nearest active fault trace.

    Returns (distance_km, fault_name, slip_type).
    """
    if not fault_features:
        return None, "", ""
    kx = 111.320 * math.cos(math.radians(lat))
    ky = 110.540
    px, py = lon * kx, lat * ky

    best_d2 = float("inf")
    best_name = ""
    best_slip = ""

    for feat in fault_features:
        geom = feat.get("geometry") or {}
        props = feat.get("properties") or {}
        for line in _extract_lines(geom):
            if len(line) < 2:
                continue
            for i in range(len(line) - 1):
                x0, y0 = line[i][0] * kx, line[i][1] * ky
                x1, y1 = line[i + 1][0] * kx, line[i + 1][1] * ky
                dx, dy = x1 - x0, y1 - y0
                l2 = dx * dx + dy * dy
                if l2 > 1e-12:
                    t = ((px - x0) * dx + (py - y0) * dy) / l2
                    if t < 0.0:
                        t = 0.0
                    elif t > 1.0:
                        t = 1.0
                else:
                    t = 0.0
                rx = x0 + t * dx - px
                ry = y0 + t * dy - py
                d2 = rx * rx + ry * ry
                if d2 < best_d2:
                    best_d2 = d2
                    best_name = str(props.get("name") or "")
                    best_slip = str(props.get("slip_type") or "")

    if not math.isfinite(best_d2):
        return None, "", ""
    return round(math.sqrt(best_d2), 1), best_name, best_slip


def _atomic_write_json(path: str, obj: Any) -> None:
    os.makedirs(os.path.dirname(path), exist_ok=True)
    fd, tmp_path = tempfile.mkstemp(dir=os.path.dirname(path), prefix=".tmp_", suffix=".json")
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


def _load_cached_raw() -> list[dict[str, Any]]:
    if os.path.exists(CACHE_JSON):
        with open(CACHE_JSON, encoding="utf-8") as fh:
            data = json.load(fh)
        if isinstance(data, list):
            return data
        if isinstance(data, dict):
            return list(data.get("features") or [])
    if os.path.exists(LEGACY_JS):
        txt = open(LEGACY_JS, encoding="utf-8").read()
        data = json.loads(txt.split("=", 1)[1].rsplit(";", 1)[0])
        return list(data.get("features") or [])
    return []


def _fetch_gem_live() -> list[dict[str, Any]]:
    req = urllib.request.Request(GEM_RAW_URL, headers={"User-Agent": USER_AGENT})
    with urllib.request.urlopen(req, timeout=60) as resp:
        gj = json.loads(resp.read().decode("utf-8"))
    lon_min, lat_min, lon_max, lat_max = FAULT_BBOX
    out: list[dict[str, Any]] = []
    for f in gj.get("features") or []:
        geom = f.get("geometry") or {}
        lines = _extract_lines(geom)
        if not any(
            lon_min <= c[0] <= lon_max and lat_min <= c[1] <= lat_max
            for ln in lines
            for c in ln
        ):
            continue
        p = f.get("properties") or {}
        out.append({
            "type": "Feature",
            "geometry": geom,
            "properties": {
                "fid": p.get("catalog_id") or p.get("fid") or "",
                "name": p.get("name") or f"Active {p.get('slip_type') or 'Fault'} ({p.get('catalog_name') or 'GEM'})",
                "slip_type": p.get("slip_type") or "Unknown",
                "dip_deg": p.get("average_dip"),
                "slip_rate_mm_yr": p.get("net_slip_rate"),
                "dip_dir": p.get("dip_dir"),
                "catalog": p.get("catalog_name") or "GEM",
            },
        })
    return out


def build_faults(offline: bool = False, refresh: bool = False, out_path: str = OUT_JSON) -> dict[str, Any]:
    """Process GEM active faults, filter out folds, and write `data/faults.json`."""
    raw = _load_cached_raw()
    if refresh and not offline:
        try:
            raw = _fetch_gem_live()
            _atomic_write_json(CACHE_JSON, raw)
        except Exception as exc:
            print(f"  [faults] live GEM fetch failed ({exc}); using cached traces", file=sys.stderr)

    active, n_excluded = filter_active_faults(raw)
    slip_counts = dict(Counter(str((f.get("properties") or {}).get("slip_type") or "Unknown") for f in active))

    coverage_note = (
        f"GEM Global Active Faults Database (Styron & Pagani, 2020; incorporating HimaTibetMap) "
        f"maps {len(active)} Quaternary surface fault traces in the Nepal region "
        f"({n_excluded} non-fault syncline/anticline folds excluded). "
        "It does NOT include continuous mapped surface traces of the Main Boundary Thrust (MBT), "
        "Main Central Thrust (MCT), or the buried 3D Main Himalayan Thrust (MHT) megathrust "
        "décollement that underlies all of Nepal and generates great Himalayan earthquakes "
        "(e.g., 1934 M8.0, 2015 M7.8). Absence of a mapped surface trace does not imply low seismic hazard."
    )

    payload = {
        "type": "FeatureCollection",
        "source": "GEM Global Active Faults Database (Styron & Pagani, 2020; CC-BY-SA-4.0)",
        "n_traces": len(active),
        "n_folds_excluded": n_excluded,
        "slip_type_counts": slip_counts,
        "coverage_note": coverage_note,
        "features": active,
    }
    _atomic_write_json(out_path, payload)
    return payload


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="Nepal TRĀYA active faults builder")
    ap.add_argument("--offline", action="store_true", help="Zero network calls; use cache")
    ap.add_argument("--refresh", action="store_true", help="Re-download GEM active faults from GitHub")
    args = ap.parse_args(argv)

    res = build_faults(offline=args.offline, refresh=args.refresh)
    print(
        f"[faults] wrote {OUT_JSON}: {res['n_traces']} active fault traces "
        f"({res['n_folds_excluded']} non-fault folds excluded)"
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
