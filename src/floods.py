"""
Fluvial flood watch for Nepal's 10 major river basins using Copernicus EMS
GloFAS discharge via the open-access Open-Meteo Flood API.

Scientific methodology:
  * Reanalysis & ensemble forecasts: Copernicus EMS GloFAS v4 via Open-Meteo
    (Harrigan et al., 2020, ESSD 12, 2043-2060; Alfieri et al., 2013, HESS 17,
    1161-1175).
  * Mainstem grid-cell snapping: On the ~0.05 deg (~5 km) GloFAS grid, raw
    gauge coordinates frequently snap onto adjacent hillslope or minor
    tributary cells (producing 100x-3000x discharge underestimates). In live
    mode, each station probes a 3x3 neighborhood (+-0.05 deg) and locks onto
    the cell with the highest discharge, flagging any remaining mismatch via
    `grid_snap_warning`.
  * Flood return levels (Q2, Q5, Q20): Gumbel Extreme Value Type I (EV1)
    method of moments fitted to annual maximum daily discharge, recording the
    TRUE number of valid reanalysis years present in the series (never
    hardcoded).

Pure Python 3.12 standard library only (zero third-party dependencies).
"""
from __future__ import annotations

import argparse
import datetime as dt
import json
import math
import os
import sys
import tempfile
import time
import urllib.error
import urllib.parse
import urllib.request
from typing import Any, Callable

SRC_DIR = os.path.dirname(os.path.abspath(__file__))
if SRC_DIR not in sys.path:
    sys.path.insert(0, SRC_DIR)

import config as C

FLOOD_API_URL = "https://flood-api.open-meteo.com/v1/flood"
EULER_MASCHERONI = 0.5772156649015329
USER_AGENT = "Nepal-TRAYA/2.1 (+https://prazg.github.io/Nepal_TRAYA/)"

CACHE_WEEKLY = os.path.join(C.CACHE, "glofas_weekly.json")
CACHE_CLIM = os.path.join(C.CACHE, "glofas_climatology.json")
LEGACY_JS = os.path.join(C.DATA, "rivers_watch.js")
OUT_JSON = os.path.join(C.DATA, "rivers_watch.json")

# Verified mainstem DHM-referenced outlet coordinates for Nepal's 10 major basins.
# `expected_min_q50_m3s` is a conservative physical lower bound on long-term
# median daily discharge (m3/s) used to flag off-mainstem hillslope grid cells.
RIVER_BASINS: list[dict[str, Any]] = [
    {
        "id": "mahakali",
        "name": "Mahakali",
        "name_ne": "महाकाली",
        "station": "Sharada Barrage / Kanchanpur mainstem",
        "dhm_ref": "DHM-170 / Banbasa",
        "lon": 80.1170,
        "lat": 28.9920,
        "district": "Kanchanpur",
        "prov": "Sudurpashchim Province",
        "expected_min_q50_m3s": 80.0,
    },
    {
        "id": "karnali",
        "name": "Karnali",
        "name_ne": "कर्णाली",
        "station": "Chisapani gorge outlet",
        "dhm_ref": "DHM-280",
        "lon": 81.2790,
        "lat": 28.6420,
        "district": "Kailali",
        "prov": "Sudurpashchim Province",
        "expected_min_q50_m3s": 250.0,
    },
    {
        "id": "bheri",
        "name": "Bheri",
        "name_ne": "भेरी",
        "station": "Jamu–Surkhet mainstem",
        "dhm_ref": "DHM-270",
        "lon": 81.3510,
        "lat": 28.7560,
        "district": "Surkhet",
        "prov": "Karnali Province",
        "expected_min_q50_m3s": 80.0,
    },
    {
        "id": "babai",
        "name": "Babai",
        "name_ne": "बबई",
        "station": "Chepang–Bardiya outlet",
        "dhm_ref": "DHM-289.95",
        "lon": 81.7130,
        "lat": 28.3530,
        "district": "Bardiya",
        "prov": "Lumbini Province",
        "expected_min_q50_m3s": 10.0,
    },
    {
        "id": "west_rapti",
        "name": "West Rapti",
        "name_ne": "पश्चिम राप्ती",
        "station": "Kusum–Banke mainstem",
        "dhm_ref": "DHM-375",
        "lon": 81.9940,
        "lat": 28.0150,
        "district": "Banke",
        "prov": "Lumbini Province",
        "expected_min_q50_m3s": 12.0,
    },
    {
        "id": "kali_gandaki",
        "name": "Kali Gandaki",
        "name_ne": "कालीगण्डकी",
        "station": "Ridi–Setibeni gorge",
        "dhm_ref": "DHM-415 / 420",
        "lon": 83.4450,
        "lat": 27.9430,
        "district": "Syangja",
        "prov": "Gandaki Province",
        "expected_min_q50_m3s": 100.0,
    },
    {
        "id": "narayani",
        "name": "Narayani (Sapta Gandaki)",
        "name_ne": "नारायणी (सप्तगण्डकी)",
        "station": "Devghat–Narayangadh (Kali Gandaki–Trishuli confluence)",
        "dhm_ref": "DHM-450",
        "lon": 84.4260,
        "lat": 27.7030,
        "district": "Chitwan",
        "prov": "Bagmati Province",
        "expected_min_q50_m3s": 350.0,
    },
    {
        "id": "bagmati",
        "name": "Bagmati",
        "name_ne": "वाग्मती",
        "station": "Karmaiya–Sarlahi outlet",
        "dhm_ref": "DHM-589",
        "lon": 85.4000,
        "lat": 27.0125,
        "district": "Sarlahi",
        "prov": "Madhesh Province",
        "expected_min_q50_m3s": 15.0,
    },
    {
        "id": "saptakoshi",
        "name": "Saptakoshi (Sun Koshi–Arun–Tamor)",
        "name_ne": "सप्तकोशी",
        "station": "Chatara–Koshi outlet",
        "dhm_ref": "DHM-695",
        "lon": 87.0327,
        "lat": 26.6536,
        "district": "Sunsari",
        "prov": "Koshi Province",
        "expected_min_q50_m3s": 500.0,
    },
    {
        "id": "kankai",
        "name": "Kankai",
        "name_ne": "कन्काई",
        "station": "Mainachuli–Jhapa outlet",
        "dhm_ref": "DHM-795",
        "lon": 87.8730,
        "lat": 26.6840,
        "district": "Jhapa",
        "prov": "Koshi Province",
        "expected_min_q50_m3s": 15.0,
    },
]

BASIN_BY_ID: dict[str, dict[str, Any]] = {b["id"]: b for b in RIVER_BASINS}


def canonical_province(name: str | None) -> str:
    """Normalize province spelling to Nepal's 7 official canonical names."""
    if not name:
        return ""
    s = str(name).strip()
    s = s.replace("Bagamati", "Bagmati")
    mapping = {
        "koshi": "Koshi Province",
        "province 1": "Koshi Province",
        "madhesh": "Madhesh Province",
        "madesh": "Madhesh Province",
        "province 2": "Madhesh Province",
        "bagmati": "Bagmati Province",
        "bagamati": "Bagmati Province",
        "province 3": "Bagmati Province",
        "gandaki": "Gandaki Province",
        "province 4": "Gandaki Province",
        "lumbini": "Lumbini Province",
        "province 5": "Lumbini Province",
        "karnali": "Karnali Province",
        "province 6": "Karnali Province",
        "sudurpashchim": "Sudurpashchim Province",
        "sudurpaschim": "Sudurpashchim Province",
        "province 7": "Sudurpashchim Province",
    }
    low = s.lower().replace(" province", "").strip()
    return mapping.get(low, s)


def _haversine_km(lon1: float, lat1: float, lon2: float, lat2: float) -> float:
    r = 6371.0088
    p1, p2 = math.radians(lat1), math.radians(lat2)
    dp = p2 - p1
    dl = math.radians(lon2 - lon1)
    a = math.sin(dp / 2.0) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(dl / 2.0) ** 2
    return 2.0 * r * math.asin(min(1.0, math.sqrt(max(0.0, a))))


def _percentile(sorted_vals: list[float], p: float) -> float:
    """Linear-interpolated percentile p in [0, 100] on a non-empty sorted list."""
    n = len(sorted_vals)
    if n == 0:
        return 0.0
    if n == 1:
        return sorted_vals[0]
    k = (p / 100.0) * (n - 1)
    lo = int(math.floor(k))
    hi = int(math.ceil(k))
    if lo == hi:
        return sorted_vals[lo]
    return sorted_vals[lo] + (k - lo) * (sorted_vals[hi] - sorted_vals[lo])


def fit_gumbel_ev1(annual_maxima: list[float]) -> dict[str, Any]:
    """Fit a Gumbel EV1 distribution by method of moments in pure stdlib Python.

    Returns dict with keys: years, q2, q5, q20, loc, scale.
    """
    vals = [float(x) for x in annual_maxima if x is not None and math.isfinite(float(x))]
    n = len(vals)
    if n == 0:
        return {"years": 0, "q2": 0.0, "q5": 0.0, "q20": 0.0, "loc": 0.0, "scale": 0.0}
    mean_x = sum(vals) / n
    if n > 1:
        var_x = sum((x - mean_x) ** 2 for x in vals) / (n - 1)
        std_x = math.sqrt(max(0.0, var_x))
    else:
        std_x = 0.0
    scale = std_x * math.sqrt(6.0) / math.pi
    loc = mean_x - EULER_MASCHERONI * scale

    def return_level(t_years: float) -> float:
        y_t = -math.log(-math.log(1.0 - 1.0 / t_years))
        return max(0.0, loc + scale * y_t)

    q2 = return_level(2.0)
    q5 = max(q2, return_level(5.0))
    q20 = max(q5, return_level(20.0))
    return {
        "years": n,
        "q2": round(q2, 1),
        "q5": round(q5, 1),
        "q20": round(q20, 1),
        "loc": round(loc, 3),
        "scale": round(scale, 3),
    }


def compute_climatology(
    dates: list[str],
    values: list[float | None],
    grid_lat: float | None = None,
    grid_lon: float | None = None,
    min_days_per_year: int = 250,
) -> dict[str, Any]:
    """Compute daily quantiles (q50, q90, q99) and Gumbel EV1 return levels.

    Records the TRUE count of valid calendar years (`years`) present in the input.
    """
    by_year: dict[int, list[float]] = {}
    valid_all: list[float] = []
    for d, v in zip(dates, values):
        if v is None or not d:
            continue
        fv = float(v)
        if not math.isfinite(fv) or fv < 0:
            continue
        valid_all.append(fv)
        try:
            yr = int(str(d)[:4])
        except ValueError:
            continue
        by_year.setdefault(yr, []).append(fv)

    valid_years = sorted(yr for yr, ys in by_year.items() if len(ys) >= min_days_per_year)
    if not valid_years and by_year:
        # Short synthetic or partial test series fallback: keep all non-empty years
        valid_years = sorted(by_year.keys())

    annual_max = [max(by_year[yr]) for yr in valid_years]
    gumbel = fit_gumbel_ev1(annual_max)
    valid_all.sort()
    q50 = round(_percentile(valid_all, 50.0), 1) if valid_all else 0.0
    q90 = round(_percentile(valid_all, 90.0), 1) if valid_all else 0.0
    q99 = round(_percentile(valid_all, 99.0), 1) if valid_all else 0.0

    # Ensure monotonic threshold hierarchy q50 <= q90 <= q2 <= q5 <= q20
    q2 = max(q90, gumbel["q2"])
    q5 = max(q2, gumbel["q5"])
    q20 = max(q5, gumbel["q20"])

    out: dict[str, Any] = {
        "years": int(gumbel["years"]),
        "year_start": valid_years[0] if valid_years else None,
        "year_end": valid_years[-1] if valid_years else None,
        "q50": q50,
        "q90": q90,
        "q99": q99,
        "q2": round(q2, 1),
        "q5": round(q5, 1),
        "q20": round(q20, 1),
    }
    if grid_lat is not None:
        out["grid_lat"] = round(float(grid_lat), 4)
    if grid_lon is not None:
        out["grid_lon"] = round(float(grid_lon), 4)
    return out


def classify_river_status(val: float | None, clim: dict[str, Any] | None) -> str:
    """Deterministic flood return-period classification.

    Returns one of: 'normal', 'elevated', 'q2_watch', 'q5_warning', 'q20_severe'.
    """
    if val is None or not clim:
        return "normal"
    try:
        v = float(val)
    except (TypeError, ValueError):
        return "normal"
    if not math.isfinite(v) or v <= 0.0:
        return "normal"

    q20 = clim.get("q20")
    q5 = clim.get("q5")
    q2 = clim.get("q2")
    q90 = clim.get("q90")

    if q20 is not None and q20 > 0 and v >= float(q20):
        return "q20_severe"
    if q5 is not None and q5 > 0 and v >= float(q5):
        return "q5_warning"
    if q2 is not None and q2 > 0 and v >= float(q2):
        return "q2_watch"
    if q90 is not None and q90 > 0 and v >= float(q90):
        return "elevated"
    return "normal"


def _http_get_json(url: str, timeout: int = 45, retries: int = 3) -> Any:
    last_exc: Exception | None = None
    for attempt in range(retries):
        try:
            req = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
            with urllib.request.urlopen(req, timeout=timeout) as resp:
                return json.loads(resp.read().decode("utf-8"))
        except Exception as exc:
            last_exc = exc
            if attempt < retries - 1:
                time.sleep(2.0 * (attempt + 1))
    raise RuntimeError(f"GET {url} failed after {retries} attempts: {last_exc}")


def _fetch_glofas_batch(
    coords: list[tuple[float, float]],
    past_days: int = 30,
    forecast_days: int = 30,
    start_date: str | None = None,
    end_date: str | None = None,
) -> list[dict[str, Any]]:
    lats = ",".join(f"{lat:.4f}" for _, lat in coords)
    lons = ",".join(f"{lon:.4f}" for lon, _ in coords)
    params: dict[str, Any] = {
        "latitude": lats,
        "longitude": lons,
    }
    if start_date and end_date:
        params["daily"] = "river_discharge"
        params["start_date"] = start_date
        params["end_date"] = end_date
    else:
        params["daily"] = (
            "river_discharge,river_discharge_median,river_discharge_mean,"
            "river_discharge_p25,river_discharge_p75,river_discharge_max"
        )
        params["past_days"] = past_days
        params["forecast_days"] = forecast_days
    url = f"{FLOOD_API_URL}?{urllib.parse.urlencode(params)}"
    payload = _http_get_json(url, timeout=60, retries=3)
    if isinstance(payload, list):
        return payload
    return [payload]


def _score_glofas_item(item: dict[str, Any]) -> float:
    """Rank candidate GloFAS 3x3 cells by peak/mean discharge so mainstems win."""
    daily = item.get("daily") or {}
    series = (
        daily.get("river_discharge_median")
        or daily.get("river_discharge")
        or daily.get("river_discharge_mean")
        or []
    )
    vals = [float(v) for v in series if v is not None and math.isfinite(float(v))]
    if not vals:
        return -1.0
    # Combine mean and max over the window (stable across dry and monsoon seasons)
    return 0.5 * (sum(vals) / len(vals)) + 0.5 * max(vals)


def snap_to_mainstem(
    lon: float,
    lat: float,
    step_deg: float = 0.05,
    fetch_fn: Callable[[list[tuple[float, float]]], list[dict[str, Any]]] | None = None,
) -> dict[str, Any]:
    """Probe the 3x3 neighborhood at +-step_deg and select the mainstem cell.

    Returns dict with: snapped_lon, snapped_lat, snap_offset_km, score, payload,
    and n_candidates_probed.
    """
    candidates: list[tuple[float, float]] = []
    for dlat in (-step_deg, 0.0, step_deg):
        for dlon in (-step_deg, 0.0, step_deg):
            candidates.append((round(lon + dlon, 4), round(lat + dlat, 4)))

    fetcher = fetch_fn or (lambda pts: _fetch_glofas_batch(pts, past_days=30, forecast_days=30))
    items = fetcher(candidates)
    if not items:
        raise RuntimeError(f"Empty GloFAS 3x3 snap response near ({lon}, {lat})")

    best_idx = 0
    best_score = -1.0
    for idx, item in enumerate(items):
        sc = _score_glofas_item(item)
        if sc > best_score:
            best_score = sc
            best_idx = idx

    best = items[best_idx]
    req_lon, req_lat = candidates[best_idx] if best_idx < len(candidates) else (lon, lat)
    grid_lat = float(best.get("latitude", req_lat))
    grid_lon = float(best.get("longitude", req_lon))
    offset_km = _haversine_km(lon, lat, grid_lon, grid_lat)
    return {
        "snapped_lon": round(grid_lon, 4),
        "snapped_lat": round(grid_lat, 4),
        "snap_offset_km": round(offset_km, 2),
        "score": round(best_score, 2),
        "payload": best,
        "n_candidates_probed": len(candidates),
    }


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


def _load_legacy_or_cache() -> tuple[dict[str, Any], dict[str, Any]]:
    weekly: dict[str, Any] = {}
    clim_map: dict[str, Any] = {}
    if os.path.exists(CACHE_WEEKLY):
        with open(CACHE_WEEKLY, encoding="utf-8") as fh:
            weekly = json.load(fh)
    elif os.path.exists(LEGACY_JS):
        txt = open(LEGACY_JS, encoding="utf-8").read()
        weekly = json.loads(txt.split("=", 1)[1].rsplit(";", 1)[0])
    if os.path.exists(CACHE_CLIM):
        with open(CACHE_CLIM, encoding="utf-8") as fh:
            clim_map = json.load(fh)
    return weekly, clim_map


def _clean_series_list(vals: list[Any] | None) -> list[float | None]:
    out: list[float | None] = []
    for v in vals or []:
        if v is None:
            out.append(None)
        else:
            fv = float(v)
            out.append(round(fv, 1) if math.isfinite(fv) else None)
    return out


def _evaluate_grid_snap_warning(
    spec: dict[str, Any], clim: dict[str, Any]
) -> tuple[bool, str | None, float | None]:
    """Return (warning_flag, warning_note, snap_offset_km)."""
    bounds = getattr(C, "GLOFAS_BASIN_SANITY_BOUNDS", {}).get(spec["id"])
    expected_q50 = float(bounds[0]) if bounds else float(spec["expected_min_q50_m3s"])
    expected_q2 = float(bounds[1]) if bounds else 0.0
    q50 = float(clim.get("q50") or 0.0)
    q2 = float(clim.get("q2") or 0.0)
    glat = clim.get("grid_lat")
    glon = clim.get("grid_lon")
    offset_km = (
        round(_haversine_km(spec["lon"], spec["lat"], float(glon), float(glat)), 1)
        if (glat is not None and glon is not None)
        else None
    )
    reasons: list[str] = []
    if q50 < expected_q50 or (expected_q2 > 0 and q2 < expected_q2):
        reasons.append(
            f"cached GloFAS cell (Q50={q50:.1f}, Q2={q2:.1f} m3/s) below physical mainstem floor "
            f"(Q50>={expected_q50:.0f}, Q2>={expected_q2:.0f} m3/s)"
        )
    if offset_km is not None and offset_km > 20.0:
        reasons.append(
            f"cached cell ({glat:.3f}N, {glon:.3f}E) is {offset_km:.1f} km from corrected gauge ({spec['lat']:.3f}N, {spec['lon']:.3f}E)"
        )
    if reasons:
        note = "; ".join(reasons) + " — auto-snaps on next live refresh."
        return True, note, offset_km
    return False, None, offset_km


def _summarize_basin_record(
    spec: dict[str, Any],
    clim: dict[str, Any],
    series: dict[str, Any],
    fetched_utc: str,
) -> dict[str, Any]:
    times = series.get("time") or []
    sim = _clean_series_list(series.get("discharge"))
    med = _clean_series_list(series.get("median"))
    mean = _clean_series_list(series.get("mean"))
    p25 = _clean_series_list(series.get("p25"))
    p75 = _clean_series_list(series.get("p75"))
    mx = _clean_series_list(series.get("max"))
    idx0 = int(series.get("today_index", min(30, max(0, len(times) - 1))))

    def _at_or_prev(arr: list[float | None], idx: int) -> float | None:
        for i in (idx, idx - 1, idx + 1):
            if 0 <= i < len(arr) and arr[i] is not None:
                return arr[i]
        return next((x for x in reversed(arr) if x is not None), None)

    cur = _at_or_prev(sim, idx0)
    if cur is None:
        cur = _at_or_prev(med, idx0)

    fc_end = min(len(times), idx0 + 14)
    fc_med = [v for v in (med[idx0:fc_end] if med else sim[idx0:fc_end]) if v is not None]
    fc_p75 = [v for v in p75[idx0:fc_end] if v is not None]
    fc_max = [v for v in mx[idx0:fc_end] if v is not None]

    peak_med = round(max(fc_med), 1) if fc_med else cur
    peak_p75 = round(max(fc_p75), 1) if fc_p75 else peak_med
    peak_max = round(max(fc_max), 1) if fc_max else peak_p75

    q50 = float(clim.get("q50") or 0.0)
    anomaly = round(cur / q50, 2) if (cur is not None and q50 > 0) else None
    status_now = classify_river_status(cur, clim)
    status_14d = classify_river_status(peak_med, clim)
    snap_warn, snap_note, snap_km = _evaluate_grid_snap_warning(spec, clim)

    out: dict[str, Any] = {
        "id": spec["id"],
        "name": spec["name"],
        "name_ne": spec["name_ne"],
        "station": spec["station"],
        "dhm_ref": spec["dhm_ref"],
        "lon": round(float(spec["lon"]), 4),
        "lat": round(float(spec["lat"]), 4),
        "district": spec["district"],
        "prov": canonical_province(spec["prov"]),
        "expected_min_q50_m3s": spec["expected_min_q50_m3s"],
        "fetched_utc": fetched_utc,
        "climatology": clim,
        "current_m3s": round(cur, 1) if cur is not None else None,
        "peak_14d_median_m3s": round(peak_med, 1) if peak_med is not None else None,
        "peak_14d_p75_m3s": round(peak_p75, 1) if peak_p75 is not None else None,
        "peak_14d_max_m3s": round(peak_max, 1) if peak_max is not None else None,
        "anomaly_ratio": anomaly,
        "status_now": status_now,
        "status_14d": status_14d,
        "grid_snap_warning": snap_warn,
        "snap_offset_km": snap_km,
        "series": {
            "today_index": idx0,
            "time": times,
            "discharge": sim,
            "median": med,
            "mean": mean,
            "p25": p25,
            "p75": p75,
            "max": mx,
        },
    }
    if snap_note:
        out["grid_snap_note"] = snap_note
    return out


def _refresh_climatology_live(
    spec: dict[str, Any], snap_lon: float, snap_lat: float
) -> dict[str, Any]:
    end_yr = dt.datetime.now(dt.timezone.utc).year - 1
    start_date = "1984-01-01"
    end_date = f"{end_yr}-12-31"
    items = _fetch_glofas_batch([(snap_lon, snap_lat)], start_date=start_date, end_date=end_date)
    item = items[0]
    daily = item.get("daily") or {}
    return compute_climatology(
        daily.get("time") or [],
        daily.get("river_discharge") or [],
        grid_lat=item.get("latitude", snap_lat),
        grid_lon=item.get("longitude", snap_lon),
    )


def build_rivers_watch(
    offline: bool = False,
    refresh_climatology: bool = False,
    out_path: str = OUT_JSON,
) -> dict[str, Any]:
    """Build Nepal 10-basin fluvial flood watch and write `data/rivers_watch.json`."""
    cached_weekly, cached_clim = _load_legacy_or_cache()
    cached_by_id = {b["id"]: b for b in cached_weekly.get("basins", []) if isinstance(b, dict) and "id" in b}
    now_utc = dt.datetime.now(dt.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")

    basins_out: list[dict[str, Any]] = []
    updated_clim = dict(cached_clim)
    any_live = False

    if offline:
        updated_utc = cached_weekly.get("updated_utc") or now_utc
        for spec in RIVER_BASINS:
            bid = spec["id"]
            cb = cached_by_id.get(bid) or {}
            clim = dict(cached_clim.get(bid) or cb.get("climatology") or {})
            series = cb.get("series") or {}
            fetched_utc = cb.get("fetched_utc") or updated_utc
            basins_out.append(_summarize_basin_record(spec, clim, series, fetched_utc))
    else:
        updated_utc = now_utc
        for spec in RIVER_BASINS:
            bid = spec["id"]
            cb = cached_by_id.get(bid) or {}
            clim = dict(cached_clim.get(bid) or cb.get("climatology") or {})
            try:
                snapped = snap_to_mainstem(spec["lon"], spec["lat"], step_deg=0.05)
                item = snapped["payload"]
                daily = item.get("daily") or {}
                times = daily.get("time") or []
                today_str = dt.datetime.now(dt.timezone.utc).strftime("%Y-%m-%d")
                idx0 = times.index(today_str) if today_str in times else min(30, max(0, len(times) - 1))
                series = {
                    "today_index": idx0,
                    "time": times,
                    "discharge": daily.get("river_discharge") or [],
                    "median": daily.get("river_discharge_median") or [],
                    "mean": daily.get("river_discharge_mean") or [],
                    "p25": daily.get("river_discharge_p25") or [],
                    "p75": daily.get("river_discharge_p75") or [],
                    "max": daily.get("river_discharge_max") or [],
                }
                bounds = getattr(C, "GLOFAS_BASIN_SANITY_BOUNDS", {}).get(bid)
                min_q50 = float(bounds[0]) if bounds else float(spec["expected_min_q50_m3s"])
                min_q2 = float(bounds[1]) if bounds else 0.0
                need_clim = (
                    refresh_climatology
                    or not clim
                    or float(clim.get("q50") or 0.0) < min_q50
                    or (min_q2 > 0 and float(clim.get("q2") or 0.0) < min_q2)
                    or clim.get("grid_lat") is None
                    or _haversine_km(
                        snapped["snapped_lon"],
                        snapped["snapped_lat"],
                        float(clim.get("grid_lon", 0.0)),
                        float(clim.get("grid_lat", 0.0)),
                    )
                    > 3.0
                )
                if need_clim:
                    clim = _refresh_climatology_live(spec, snapped["snapped_lon"], snapped["snapped_lat"])
                    updated_clim[bid] = clim
                basins_out.append(_summarize_basin_record(spec, clim, series, now_utc))
                any_live = True
            except Exception as exc:
                print(f"  [floods] live fetch failed for {bid} ({exc}); falling back to cache", file=sys.stderr)
                series = cb.get("series") or {}
                fetched_utc = cb.get("fetched_utc") or cached_weekly.get("updated_utc") or now_utc
                basins_out.append(_summarize_basin_record(spec, clim, series, fetched_utc))

    # Derive honest forecast expiration date from series horizon
    last_dates = [
        (b.get("series") or {}).get("time", [])[-1]
        for b in basins_out
        if (b.get("series") or {}).get("time")
    ]
    forecast_expires_utc = f"{max(last_dates)}T23:59:59Z" if last_dates else None
    n_snap_warn = sum(1 for b in basins_out if b.get("grid_snap_warning"))
    years_set = sorted({int((b.get("climatology") or {}).get("years") or 0) for b in basins_out if (b.get("climatology") or {}).get("years")})

    payload = {
        "updated_utc": updated_utc,
        "forecast_expires_utc": forecast_expires_utc,
        "mode": "offline" if offline else ("live" if any_live else "cached_fallback"),
        "source": "Copernicus EMS GloFAS via Open-Meteo Flood API",
        "endpoint": FLOOD_API_URL,
        "climatology_years": years_set[0] if len(years_set) == 1 else years_set,
        "n_basins": len(basins_out),
        "n_grid_snap_warnings": n_snap_warn,
        "status_tiers": ["normal", "elevated", "q2_watch", "q5_warning", "q20_severe"],
        "basins": basins_out,
    }

    _atomic_write_json(out_path, payload)
    if any_live:
        _atomic_write_json(CACHE_WEEKLY, payload)
        _atomic_write_json(CACHE_CLIM, updated_clim)
    return payload


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="Nepal TRĀYA GloFAS 10-basin fluvial flood watch")
    ap.add_argument("--offline", action="store_true", help="Zero network calls; normalize cached data")
    ap.add_argument("--refresh", action="store_true", help="Live fetch from Open-Meteo Flood API")
    ap.add_argument("--refresh-climatology", action="store_true", help="Force reanalysis climatology refit")
    args = ap.parse_args(argv)

    res = build_rivers_watch(offline=args.offline, refresh_climatology=args.refresh_climatology)
    print(
        f"[floods] wrote {OUT_JSON}: {res['n_basins']} basins, "
        f"updated={res['updated_utc']}, snap_warnings={res['n_grid_snap_warnings']}"
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
