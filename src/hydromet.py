"""
Hydrometeorological & cryosphere watch across Nepal's 24 physiographic
rainfall-landslide sentinel nodes and 20 priority / ice-cored glacial lakes.

Scientific methodology:
  * Rainfall-landslide screening: Dahal & Hasegawa (2008), Geomorphology 100,
    429-443, doi:10.1016/j.geomorph.2008.01.014 — empirical Nepal Himalaya
    Intensity-Duration threshold I = 73.90 * D^(-0.79) mm/h, giving cumulative
    liquid-rain thresholds E_c(24h)=144.0 mm, E_c(72h)=181.4 mm, E_c(168h)=216.8 mm.
    Evaluated strictly on LIQUID RAIN (`rain_sum`), not high-alpine snowfall.
  * Cryosphere thermal regime: 0 deg C atmospheric freezing-level height vs.
    lake elevation (`freezing_margin_m = freezing_level_max_m - z_m`) and
    transparent `warm_rain_on_ice` flag (`liquid_rain_12d_mm >= 10.0` AND
    `freezing_margin_m >= 300.0 m`).
  * Satellite EO: Copernicus Sentinel-2 L2A STAC scene metadata from
    `cache/stac_scenes.json` (refreshed via Element84 Earth Search when live).

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
from typing import Any

SRC_DIR = os.path.dirname(os.path.abspath(__file__))
if SRC_DIR not in sys.path:
    sys.path.insert(0, SRC_DIR)

import config as C
from floods import canonical_province

OPEN_METEO_URL = C.OPEN_METEO
USER_AGENT = "Nepal-TRAYA/2.1 (+https://prazg.github.io/Nepal_TRAYA/)"

CACHE_HYDROMET = os.path.join(C.CACHE, "hydromet_weekly.json")
CACHE_STAC = os.path.join(C.CACHE, "stac_scenes.json")
CACHE_ADMIN = os.path.join(C.CACHE, "nepal_admin.json")
LEGACY_JS = os.path.join(C.DATA, "hydromet_weekly.js")
OUT_JSON = os.path.join(C.DATA, "hydromet_weekly.json")

# Dahal & Hasegawa (2008) Nepal Himalaya I-D constants: I = ALPHA * D^BETA
DH_ALPHA = 73.90
DH_BETA = -0.79
WARM_RAIN_MIN_MM = 10.0
WARM_RAIN_FREEZING_MARGIN_M = 300.0

# 24 physiographic rainfall-landslide sentinel nodes spanning High Himalaya,
# Trans-Himalaya, Middle Mountains/Mahabharat, and Siwalik/Churia belts.
SENTINEL_NODES: list[dict[str, Any]] = [
    {"id": "darchula", "name": "Darchula (Api–Byas)", "zone": "High Himalaya", "prov": "Sudurpashchim Province", "lon": 80.55, "lat": 29.85, "elev_m": 2150},
    {"id": "bajhang", "name": "Chainpur, Bajhang", "zone": "Middle Mountains", "prov": "Sudurpashchim Province", "lon": 81.20, "lat": 29.55, "elev_m": 1320},
    {"id": "dipayal", "name": "Dipayal–Dadeldhura", "zone": "Middle Mountains", "prov": "Sudurpashchim Province", "lon": 80.94, "lat": 29.26, "elev_m": 620},
    {"id": "humla", "name": "Simikot, Humla", "zone": "High Himalaya", "prov": "Karnali Province", "lon": 81.82, "lat": 29.97, "elev_m": 2910},
    {"id": "mugu", "name": "Rara–Gamgadhi, Mugu", "zone": "High Himalaya", "prov": "Karnali Province", "lon": 82.15, "lat": 29.53, "elev_m": 2990},
    {"id": "jumla", "name": "Jumla–Tila Valley", "zone": "High Mountains", "prov": "Karnali Province", "lon": 82.18, "lat": 29.27, "elev_m": 2370},
    {"id": "dolpa", "name": "Dunai, Dolpa", "zone": "High Himalaya", "prov": "Karnali Province", "lon": 82.90, "lat": 28.95, "elev_m": 2140},
    {"id": "surkhet", "name": "Birendranagar, Surkhet", "zone": "Siwalik / Dun", "prov": "Karnali Province", "lon": 81.63, "lat": 28.60, "elev_m": 720},
    {"id": "rukum", "name": "Rukumkot–Jajarkot", "zone": "Middle Mountains", "prov": "Karnali Province", "lon": 82.35, "lat": 28.65, "elev_m": 1560},
    {"id": "butwal", "name": "Butwal–Tinau (Churia)", "zone": "Siwalik / Churia", "prov": "Lumbini Province", "lon": 83.46, "lat": 27.70, "elev_m": 190},
    {"id": "mustang", "name": "Jomsom, Mustang", "zone": "Trans-Himalaya", "prov": "Gandaki Province", "lon": 83.73, "lat": 28.78, "elev_m": 2740},
    {"id": "myagdi", "name": "Beni–Dana, Myagdi", "zone": "Middle / High Mountains", "prov": "Gandaki Province", "lon": 83.57, "lat": 28.35, "elev_m": 890},
    {"id": "pokhara", "name": "Pokhara–Lumle (Annapurna S)", "zone": "Middle Mountains", "prov": "Gandaki Province", "lon": 83.95, "lat": 28.25, "elev_m": 1150},
    {"id": "manang", "name": "Chame–Manang", "zone": "High Himalaya", "prov": "Gandaki Province", "lon": 84.15, "lat": 28.60, "elev_m": 3100},
    {"id": "gorkha", "name": "Barpak–Arughat, Gorkha", "zone": "High / Middle Mountains", "prov": "Gandaki Province", "lon": 84.75, "lat": 28.20, "elev_m": 1850},
    {"id": "narayangadh", "name": "Mugling–Narayangadh", "zone": "Siwalik / Mahabharat", "prov": "Bagmati Province", "lon": 84.56, "lat": 27.85, "elev_m": 280},
    {"id": "rasuwa", "name": "Syaphrubesi–Langtang", "zone": "High Himalaya", "prov": "Bagmati Province", "lon": 85.38, "lat": 28.18, "elev_m": 1950},
    {"id": "kathmandu", "name": "Kathmandu Valley", "zone": "Middle Mountains", "prov": "Bagmati Province", "lon": 85.32, "lat": 27.71, "elev_m": 1330},
    {"id": "sindhupalchok", "name": "Melamchi–Bahrabise", "zone": "High / Middle Mountains", "prov": "Bagmati Province", "lon": 85.76, "lat": 27.86, "elev_m": 1450},
    {"id": "dolakha", "name": "Singati–Rolwaling", "zone": "High Himalaya", "prov": "Bagmati Province", "lon": 86.22, "lat": 27.82, "elev_m": 1980},
    {"id": "khumbu", "name": "Namche–Dingboche (Khumbu)", "zone": "High Himalaya", "prov": "Koshi Province", "lon": 86.76, "lat": 27.84, "elev_m": 3850},
    {"id": "makalu", "name": "Num–Barun, Sankhuwasabha", "zone": "High / Middle Mountains", "prov": "Koshi Province", "lon": 87.25, "lat": 27.58, "elev_m": 1650},
    {"id": "taplejung", "name": "Taplejung–Ghunsa", "zone": "High Himalaya", "prov": "Koshi Province", "lon": 87.75, "lat": 27.48, "elev_m": 2100},
    {"id": "ilam", "name": "Ilam–Dhankuta", "zone": "Middle Mountains", "prov": "Koshi Province", "lon": 87.92, "lat": 26.91, "elev_m": 1210},
]


# ---------------------------------------------------------------------------
# Pure-stdlib point-in-polygon admin lookup against cache/nepal_admin.json
# ---------------------------------------------------------------------------
def _ring_bbox(ring: list[list[float]]) -> tuple[float, float, float, float]:
    xs = [p[0] for p in ring]
    ys = [p[1] for p in ring]
    return (min(xs), min(ys), max(xs), max(ys))


def _pip_ring(lon: float, lat: float, ring: list[list[float]]) -> bool:
    inside = False
    n = len(ring)
    j = n - 1
    for i in range(n):
        xi, yi = ring[i][0], ring[i][1]
        xj, yj = ring[j][0], ring[j][1]
        if ((yi > lat) != (yj > lat)) and (
            lon < (xj - xi) * (lat - yi) / (yj - yi) + xi
        ):
            inside = not inside
        j = i
    return inside


def _pip_geom(lon: float, lat: float, geom: dict[str, Any]) -> bool:
    gtype = geom.get("type")
    coords = geom.get("coordinates") or []
    if gtype == "Polygon":
        if not coords or not _pip_ring(lon, lat, coords[0]):
            return False
        for hole in coords[1:]:
            if _pip_ring(lon, lat, hole):
                return False
        return True
    if gtype == "MultiPolygon":
        for poly in coords:
            if poly and _pip_ring(lon, lat, poly[0]) and not any(
                _pip_ring(lon, lat, h) for h in poly[1:]
            ):
                return True
    return False


class StdlibAdminLookup:
    """Zero-dependency point-in-polygon lookup against `cache/nepal_admin.json`."""

    def __init__(self, path: str = CACHE_ADMIN):
        self.levels: dict[str, list[tuple[str, tuple[float, float, float, float], dict[str, Any]]]] = {
            "4": [],
            "6": [],
        }
        if not os.path.exists(path):
            return
        with open(path, encoding="utf-8") as fh:
            raw = json.load(fh)
        for lvl in ("4", "6"):
            for item in raw.get(lvl, []):
                geom = item.get("geometry") or {}
                coords = geom.get("coordinates") or []
                if not coords:
                    continue
                ring = coords[0] if geom.get("type") == "Polygon" else coords[0][0]
                name = canonical_province(item.get("name")) if lvl == "4" else str(item.get("name") or "").strip()
                self.levels[lvl].append((name, _ring_bbox(ring), geom))

    def lookup(self, lvl: str, lon: float, lat: float, max_fallback_deg: float = 0.5) -> str:
        items = self.levels.get(lvl, [])
        for name, bb, geom in items:
            if bb[0] <= lon <= bb[2] and bb[1] <= lat <= bb[3]:
                if _pip_geom(lon, lat, geom):
                    return name
        best_name, best_d = "", 1e9
        for name, _, geom in items:
            rings = geom.get("coordinates") or []
            outer = rings[0] if geom.get("type") == "Polygon" else (rings[0][0] if rings else [])
            for x, y in outer:
                d = math.hypot(x - lon, y - lat)
                if d < best_d:
                    best_d, best_name = d, name
        return best_name if best_d <= max_fallback_deg else ""

    def province(self, lon: float, lat: float) -> str:
        return self.lookup("4", lon, lat)

    def district(self, lon: float, lat: float) -> str:
        return self.lookup("6", lon, lat)


# ---------------------------------------------------------------------------
# Scientific threshold & thermal functions
# ---------------------------------------------------------------------------
def dahal_hasegawa_ec_mm(duration_h: float) -> float:
    """Critical cumulative rainfall E_c(D) = I(D)*D = 73.90 * D^(1 - 0.79) mm."""
    return DH_ALPHA * (float(duration_h) ** (1.0 + DH_BETA))


def evaluate_dahal_hasegawa(
    rain_24h_mm: float,
    rain_72h_mm: float,
    rain_168h_mm: float,
) -> dict[str, Any]:
    """Evaluate liquid rainfall against Dahal & Hasegawa (2008) I-D thresholds."""
    ec24 = round(dahal_hasegawa_ec_mm(24.0), 1)
    ec72 = round(dahal_hasegawa_ec_mm(72.0), 1)
    ec168 = round(dahal_hasegawa_ec_mm(168.0), 1)
    r24 = max(0.0, float(rain_24h_mm or 0.0)) / ec24
    r72 = max(0.0, float(rain_72h_mm or 0.0)) / ec72
    r168 = max(0.0, float(rain_168h_mm or 0.0)) / ec168
    mr = max(r24, r72, r168)
    if mr >= 1.0:
        level = "exceeded"
    elif mr >= 0.7:
        level = "watch"
    elif mr >= 0.4:
        level = "elevated"
    else:
        level = "low"
    return {
        "ec_24h_mm": ec24,
        "ec_72h_mm": ec72,
        "ec_168h_mm": ec168,
        "ratio_24h": round(r24, 3),
        "ratio_72h": round(r72, 3),
        "ratio_168h": round(r168, 3),
        "max_ratio": round(mr, 3),
        "level": level,
    }


def compute_warm_rain_on_ice(
    liquid_rain_12d_mm: float | None,
    freezing_level_max_m: float | None,
    lake_elev_m: float | None,
    min_rain_mm: float = WARM_RAIN_MIN_MM,
    margin_m: float = WARM_RAIN_FREEZING_MARGIN_M,
) -> tuple[float | None, bool]:
    """Transparent cryosphere warm-rain-on-ice screening rule.

    Returns (freezing_margin_m, warm_rain_on_ice).
    Triggered iff 12-day liquid rain >= min_rain_mm AND 0 deg C isotherm rises
    at least `margin_m` above the lake elevation.
    """
    if freezing_level_max_m is None or lake_elev_m is None:
        return None, False
    margin = round(float(freezing_level_max_m) - float(lake_elev_m), 1)
    rain = float(liquid_rain_12d_mm or 0.0)
    flag = bool(rain >= min_rain_mm and margin >= margin_m)
    return margin, flag


def _rolling_max(values: list[float], window: int) -> float:
    if not values:
        return 0.0
    w = min(window, len(values))
    best = 0.0
    cur = sum(values[:w])
    best = max(best, cur)
    for i in range(w, len(values)):
        cur += values[i] - values[i - w]
        if cur > best:
            best = cur
    return round(best, 1)


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


def _http_get_json(url: str, timeout: int = 45, retries: int = 3) -> Any:
    last_exc: Exception | None = None
    for attempt in range(retries):
        try:
            req = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
            with urllib.request.urlopen(req, timeout=timeout) as resp:
                return json.loads(resp.read().decode("utf-8"))
        except urllib.error.HTTPError as exc:
            if exc.code == 400:
                raise
            last_exc = exc
            if attempt < retries - 1:
                time.sleep(2.0 * (attempt + 1))
        except Exception as exc:
            last_exc = exc
            if attempt < retries - 1:
                time.sleep(2.0 * (attempt + 1))
    raise RuntimeError(f"GET {url} failed after {retries} attempts: {last_exc}")


def _fetch_open_meteo_batch(coords: list[tuple[float, float]]) -> list[dict[str, Any]]:
    """Query Open-Meteo Weather API with retry/backoff and graceful variable fallback."""
    lats = ",".join(f"{lat:.4f}" for _, lat in coords)
    lons = ",".join(f"{lon:.4f}" for lon, _ in coords)
    base_params = {
        "latitude": lats,
        "longitude": lons,
        "past_days": 7,
        "forecast_days": 5,
        "timezone": "Asia/Kathmandu",
    }
    # Primary query requests valid Open-Meteo Forecast API variables directly
    # (freezing level and topsoil moisture are hourly variables, avoiding HTTP 400).
    primary = dict(
        base_params,
        daily="rain_sum,snowfall_sum,precipitation_sum,temperature_2m_max",
        hourly="rain,freezinglevel_height,soil_moisture_0_to_7cm",
    )
    fallback = dict(
        base_params,
        daily="rain_sum,snowfall_sum,precipitation_sum,temperature_2m_max",
        hourly="rain,freezinglevel_height",
    )
    try:
        url = f"{OPEN_METEO_URL}?{urllib.parse.urlencode(primary)}"
        payload = _http_get_json(url, timeout=60, retries=3)
    except urllib.error.HTTPError:
        url = f"{OPEN_METEO_URL}?{urllib.parse.urlencode(fallback)}"
        payload = _http_get_json(url, timeout=60, retries=3)
    if isinstance(payload, list):
        return payload
    return [payload]


def _extract_freezing_and_soil(item: dict[str, Any]) -> tuple[float | None, float | None, float | None]:
    """Return (freezing_now_m, freezing_max_m, soil_moisture_m3m3) from daily or hourly fields."""
    daily = item.get("daily") or {}
    hourly = item.get("hourly") or {}

    fl_daily = [float(x) for x in (daily.get("freezing_level_height_max") or []) if x is not None]
    fl_hourly = [float(x) for x in (hourly.get("freezinglevel_height") or []) if x is not None]
    fl_vals = fl_daily or fl_hourly
    fl_max = round(max(fl_vals), 1) if fl_vals else None
    if fl_daily:
        idx = min(7, len(fl_daily) - 1)
        fl_now = round(fl_daily[idx], 1)
    elif fl_hourly:
        idx = min(7 * 24, len(fl_hourly) - 1)
        fl_now = round(fl_hourly[idx], 1)
    else:
        fl_now = None

    sm_daily = [float(x) for x in (daily.get("soil_moisture_0_to_7cm_mean") or []) if x is not None]
    sm_hourly = [float(x) for x in (hourly.get("soil_moisture_0_to_7cm") or []) if x is not None]
    sm_vals = sm_daily or sm_hourly
    if sm_daily:
        idx = min(7, len(sm_daily) - 1)
        sm_now = round(sm_daily[idx], 3)
    elif sm_hourly:
        idx = min(7 * 24, len(sm_hourly) - 1)
        sm_now = round(sm_hourly[idx], 3)
    else:
        sm_now = None

    return fl_now, fl_max, sm_now


def _load_cached_hydromet() -> dict[str, Any]:
    if os.path.exists(CACHE_HYDROMET):
        with open(CACHE_HYDROMET, encoding="utf-8") as fh:
            return json.load(fh)
    if os.path.exists(LEGACY_JS):
        txt = open(LEGACY_JS, encoding="utf-8").read()
        return json.loads(txt.split("=", 1)[1].rsplit(";", 1)[0])
    return {}


def _load_stac_cache() -> dict[str, Any]:
    if os.path.exists(CACHE_STAC):
        with open(CACHE_STAC, encoding="utf-8") as fh:
            return json.load(fh)
    return {}


def _normalize_offline_node(
    spec: dict[str, Any], cached: dict[str, Any], adm: StdlibAdminLookup
) -> dict[str, Any]:
    lon = float(spec["lon"])
    lat = float(spec["lat"])
    pip_dist = adm.district(lon, lat)
    pip_prov = adm.province(lon, lat)
    prov = canonical_province(pip_prov or spec["prov"])
    district = pip_dist or str(cached.get("district") or "").strip()

    daily_time = list(cached.get("daily_time") or [])
    daily_precip = [round(float(x or 0.0), 1) for x in (cached.get("daily_precip") or [])]
    snow_7d_cm = round(float(cached.get("snow_past_7d_cm") or 0.0), 1)

    if cached.get("daily_rain") is not None:
        daily_rain = [round(float(x or 0.0), 1) for x in cached["daily_rain"]]
        rain_basis = "daily_rain_sum"
    else:
        # Offline cache predates separate `daily_rain`; deduct SWE (1 cm snow ~ 1 mm water)
        # across past 7d so high-alpine snowfall is not miscounted as triggering rain.
        daily_rain = list(daily_precip)
        if snow_7d_cm > 0 and daily_rain:
            rem = snow_7d_cm
            for i in range(min(7, len(daily_rain))):
                deduct = min(daily_rain[i], rem)
                daily_rain[i] = round(daily_rain[i] - deduct, 1)
                rem = max(0.0, rem - deduct)
        rain_basis = "cached_precip_minus_swe"

    past_rain = daily_rain[:7]
    fc_rain = daily_rain[7:]
    rain_past_7d = round(sum(past_rain), 1)
    rain_next_5d = round(sum(fc_rain), 1)
    max_24h_obs = _rolling_max(past_rain, 1)
    max_72h_obs = _rolling_max(past_rain, 3)
    max_24h_fc = _rolling_max(fc_rain, 1)
    max_24h_comb = _rolling_max(daily_rain, 1)
    max_72h_comb = _rolling_max(daily_rain, 3)
    max_168h_comb = _rolling_max(daily_rain, 7)

    dh_obs = evaluate_dahal_hasegawa(max_24h_obs, max_72h_obs, rain_past_7d)
    dh_comb = evaluate_dahal_hasegawa(max_24h_comb, max_72h_comb, max_168h_comb)

    return {
        "id": spec["id"],
        "name": spec["name"],
        "zone": spec["zone"],
        "district": district,
        "prov": prov,
        "lon": round(lon, 4),
        "lat": round(lat, 4),
        "elev_m": spec["elev_m"],
        "model_elev_m": cached.get("model_elev_m"),
        "rain_basis": rain_basis,
        "rain_past_7d_mm": rain_past_7d,
        "rain_next_5d_mm": rain_next_5d,
        "max_24h_obs_mm": max_24h_obs,
        "max_72h_obs_mm": max_72h_obs,
        "max_24h_fc_mm": max_24h_fc,
        "snow_past_7d_cm": snow_7d_cm,
        "temp_max_today_c": cached.get("temp_max_today_c"),
        "soil_moisture_m3m3": cached.get("soil_moisture_m3m3"),
        "freezing_level_m": cached.get("freezing_level_m"),
        "dh_obs": dh_obs,
        "dh_combined": dh_comb,
        "daily_time": daily_time,
        "daily_precip": daily_precip,
        "daily_rain": daily_rain,
    }


def _build_live_node(
    spec: dict[str, Any], item: dict[str, Any], adm: StdlibAdminLookup
) -> dict[str, Any]:
    lon = float(spec["lon"])
    lat = float(spec["lat"])
    pip_dist = adm.district(lon, lat)
    pip_prov = adm.province(lon, lat)
    prov = canonical_province(pip_prov or spec["prov"])
    district = pip_dist or ""

    daily = item.get("daily") or {}
    daily_time = list(daily.get("time") or [])
    daily_precip = [round(float(x or 0.0), 1) for x in (daily.get("precipitation_sum") or [])]
    daily_snow = [round(float(x or 0.0), 1) for x in (daily.get("snowfall_sum") or [])]
    raw_rain = daily.get("rain_sum")
    has_rain_sum = isinstance(raw_rain, list) and any(x is not None for x in raw_rain)
    if has_rain_sum:
        daily_rain = [round(max(0.0, float(x or 0.0)), 1) for x in raw_rain]
        rain_basis = "daily_rain_sum"
    else:
        daily_rain = [
            round(max(0.0, p - (daily_snow[i] if i < len(daily_snow) else 0.0)), 1)
            for i, p in enumerate(daily_precip)
        ]
        rain_basis = "live_precip_minus_swe"
    daily_tmax = daily.get("temperature_2m_max") or []

    past_rain = daily_rain[:7]
    fc_rain = daily_rain[7:]
    rain_past_7d = round(sum(past_rain), 1)
    rain_next_5d = round(sum(fc_rain), 1)
    snow_7d = round(sum(daily_snow[:7]), 1)
    max_24h_obs = _rolling_max(past_rain, 1)
    max_72h_obs = _rolling_max(past_rain, 3)
    max_24h_fc = _rolling_max(fc_rain, 1)
    max_24h_comb = _rolling_max(daily_rain, 1)
    max_72h_comb = _rolling_max(daily_rain, 3)
    max_168h_comb = _rolling_max(daily_rain, 7)

    fl_now, _, sm_now = _extract_freezing_and_soil(item)
    tmax_today = round(float(daily_tmax[min(7, len(daily_tmax) - 1)]), 1) if daily_tmax else None

    return {
        "id": spec["id"],
        "name": spec["name"],
        "zone": spec["zone"],
        "district": district,
        "prov": prov,
        "lon": round(lon, 4),
        "lat": round(lat, 4),
        "elev_m": spec["elev_m"],
        "model_elev_m": round(float(item["elevation"]), 1) if item.get("elevation") is not None else None,
        "rain_basis": rain_basis,
        "rain_past_7d_mm": rain_past_7d,
        "rain_next_5d_mm": rain_next_5d,
        "max_24h_obs_mm": max_24h_obs,
        "max_72h_obs_mm": max_72h_obs,
        "max_24h_fc_mm": max_24h_fc,
        "snow_past_7d_cm": snow_7d,
        "temp_max_today_c": tmax_today,
        "soil_moisture_m3m3": sm_now,
        "freezing_level_m": fl_now,
        "dh_obs": evaluate_dahal_hasegawa(max_24h_obs, max_72h_obs, rain_past_7d),
        "dh_combined": evaluate_dahal_hasegawa(max_24h_comb, max_72h_comb, max_168h_comb),
        "daily_time": daily_time,
        "daily_precip": daily_precip,
        "daily_rain": daily_rain,
    }


def _normalize_priority_lake(
    rec: dict[str, Any],
    adm: StdlibAdminLookup,
    stac_cache: dict[str, Any],
    live_item: dict[str, Any] | None = None,
) -> dict[str, Any]:
    lon = float(rec["lon"])
    lat = float(rec["lat"])
    z_m = round(float(rec["z_m"]), 1) if rec.get("z_m") is not None else None
    pip_prov = adm.province(lon, lat)
    pip_dist = adm.district(lon, lat)
    prov = canonical_province(pip_prov or rec.get("prov"))
    district = pip_dist or str(rec.get("district") or "").strip()

    if live_item is not None:
        daily = live_item.get("daily") or {}
        pr = [float(x or 0.0) for x in (daily.get("precipitation_sum") or [])]
        rn = [float(x or 0.0) for x in (daily.get("rain_sum") or [])]
        sn = [float(x or 0.0) for x in (daily.get("snowfall_sum") or [])]
        precip_past_7d = round(sum(pr[:7]), 1)
        precip_next_5d = round(sum(pr[7:]), 1)
        liquid_rain_12d = round(sum(rn), 1)
        snowfall_12d = round(sum(sn), 1)
        fl_now, fl_max, _ = _extract_freezing_and_soil(live_item)
    else:
        precip_past_7d = round(float(rec.get("precip_past_7d_mm") or 0.0), 1)
        precip_next_5d = round(float(rec.get("precip_next_5d_mm") or 0.0), 1)
        liquid_rain_12d = round(float(rec.get("liquid_rain_12d_mm") or 0.0), 1)
        snowfall_12d = round(float(rec.get("snowfall_12d_cm") or 0.0), 1)
        fl_now = round(float(rec["freezing_level_now_m"]), 1) if rec.get("freezing_level_now_m") is not None else None
        fl_max = round(float(rec["freezing_level_max_m"]), 1) if rec.get("freezing_level_max_m") is not None else None

    margin, warm_flag = compute_warm_rain_on_ice(liquid_rain_12d, fl_max, z_m)
    s2 = stac_cache.get(rec["id"]) or rec.get("sentinel2")

    return {
        "id": rec["id"],
        "name": rec.get("name") or rec["id"],
        "district": district,
        "prov": prov,
        "lon": round(lon, 4),
        "lat": round(lat, 4),
        "z_m": z_m,
        "pfv_Mm3": round(float(rec.get("pfv_Mm3") or 0.0), 2),
        "ice_cored": bool(rec.get("ice_cored")),
        "precip_past_7d_mm": precip_past_7d,
        "precip_next_5d_mm": precip_next_5d,
        "liquid_rain_12d_mm": liquid_rain_12d,
        "snowfall_12d_cm": snowfall_12d,
        "freezing_level_now_m": fl_now,
        "freezing_level_max_m": fl_max,
        "freezing_margin_m": margin,
        "warm_rain_on_ice": warm_flag,
        "sentinel2": s2,
    }


def build_hydromet_weekly(
    offline: bool = False,
    stac_scenes: dict[str, Any] | None = None,
    out_path: str = OUT_JSON,
) -> dict[str, Any]:
    """Build 24-node Dahal-Hasegawa + 20-priority-lake hydromet watch JSON."""
    cached = _load_cached_hydromet()
    adm = StdlibAdminLookup()
    stac = stac_scenes if stac_scenes is not None else _load_stac_cache()
    now_utc = dt.datetime.now(dt.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")

    cached_nodes = {n["id"]: n for n in cached.get("nodes", []) if isinstance(n, dict) and "id" in n}
    cached_lakes = list(cached.get("priority_lakes") or [])

    nodes_out: list[dict[str, Any]] = []
    lakes_out: list[dict[str, Any]] = []
    any_live = False
    priority_lakes_updated_utc = cached.get("priority_lakes_updated_utc") or cached.get("updated_utc") or now_utc

    if offline:
        updated_utc = cached.get("updated_utc") or now_utc
        for spec in SENTINEL_NODES:
            nodes_out.append(_normalize_offline_node(spec, cached_nodes.get(spec["id"]) or {}, adm))
        for lk in cached_lakes:
            lakes_out.append(_normalize_priority_lake(lk, adm, stac, live_item=None))
    else:
        updated_utc = now_utc
        try:
            node_coords = [(float(s["lon"]), float(s["lat"])) for s in SENTINEL_NODES]
            live_nodes = _fetch_open_meteo_batch(node_coords)
            for spec, item in zip(SENTINEL_NODES, live_nodes):
                nodes_out.append(_build_live_node(spec, item, adm))
            any_live = True
        except Exception as exc:
            print(f"  [hydromet] live node fetch failed ({exc}); using cache", file=sys.stderr)
            updated_utc = cached.get("updated_utc") or now_utc
            for spec in SENTINEL_NODES:
                nodes_out.append(_normalize_offline_node(spec, cached_nodes.get(spec["id"]) or {}, adm))

        if cached_lakes:
            try:
                lake_coords = [(float(lk["lon"]), float(lk["lat"])) for lk in cached_lakes]
                live_lakes = _fetch_open_meteo_batch(lake_coords)
                for lk, item in zip(cached_lakes, live_lakes):
                    lakes_out.append(_normalize_priority_lake(lk, adm, stac, live_item=item))
                priority_lakes_updated_utc = now_utc
                any_live = True
            except Exception as exc:
                print(f"  [hydromet] live priority-lake fetch failed ({exc}); using cache", file=sys.stderr)
                for lk in cached_lakes:
                    lakes_out.append(_normalize_priority_lake(lk, adm, stac, live_item=None))

    # Derive explicit forecast expiration timestamp from node forecast horizon
    last_dates = [n["daily_time"][-1] for n in nodes_out if n.get("daily_time")]
    forecast_expires_utc = f"{max(last_dates)}T23:59:59Z" if last_dates else None

    payload = {
        "updated_utc": updated_utc,
        "priority_lakes_updated_utc": priority_lakes_updated_utc,
        "forecast_expires_utc": forecast_expires_utc,
        "refresh_interval_days": 7,
        "mode": "offline" if offline else ("live" if any_live else "cached_fallback"),
        "source": "Open-Meteo Weather API & Element84 Sentinel-2 L2A STAC",
        "dh_liquid_rain_only": True,
        "warm_rain_on_ice_rule": (
            f"liquid_rain_12d_mm >= {WARM_RAIN_MIN_MM:.1f} and "
            f"(freezing_level_max_m - z_m) >= {WARM_RAIN_FREEZING_MARGIN_M:.0f}"
        ),
        "n_nodes": len(nodes_out),
        "n_priority_lakes": len(lakes_out),
        "nodes": nodes_out,
        "priority_lakes": lakes_out,
    }

    _atomic_write_json(out_path, payload)
    if any_live:
        _atomic_write_json(CACHE_HYDROMET, payload)
    return payload


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="Nepal TRĀYA 24-node hydromet & cryosphere watch")
    ap.add_argument("--offline", action="store_true", help="Zero network calls; normalize cached data")
    ap.add_argument("--refresh", action="store_true", help="Live fetch from Open-Meteo Weather API")
    args = ap.parse_args(argv)

    res = build_hydromet_weekly(offline=args.offline)
    print(
        f"[hydromet] wrote {OUT_JSON}: {res['n_nodes']} nodes, "
        f"{res['n_priority_lakes']} priority lakes, "
        f"updated={res['updated_utc']}, expires={res['forecast_expires_utc']}"
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
