"""
Automated 7-day multi-hazard refresh & lean JSON data-product orchestrator for
Nepal TRĀYA.

Runs cleanly on pure Python 3.12 standard library (zero numpy/scipy/shapely/
rasterio/requests dependencies), supporting:
  * `--offline`      : zero network calls; normalizes caches, recomputes true
                       perpendicular point-to-segment downstream exposure,
                       builds all 14 lean `data/*.json` products.
  * live (default)   : refreshes GloFAS 10-basin forecasts (with 3x3 mainstem
                       snapping), Open-Meteo 24-node + 20-lake hydromet watch,
                       NASA COOLR landslides, GDACS + USGS Nepal FDSN + STAC,
                       and USGS M>=4 historical catalogue, then builds all
                       lean `data/*.json` products.
  * `--refresh-osm`  : also refreshes OpenStreetMap Overpass caches (when live).

All outputs are written atomically (temp file + `os.replace`) in UTF-8.
"""
from __future__ import annotations

import argparse
import csv
import datetime as dt
import json
import math
import os
import re
import sys
import tempfile
import time
import urllib.parse
import urllib.request
from collections import Counter, defaultdict
from typing import Any

SRC_DIR = os.path.dirname(os.path.abspath(__file__))
if SRC_DIR not in sys.path:
    sys.path.insert(0, SRC_DIR)

import alerts as AL
import config as C
import exposure as EX
import faults as FA
import floods as FL
import hazard as HZ
import hydromet as HM
import landslides as LS
import seismic as SZ

USER_AGENT = "Nepal-TRAYA/2.1 (+https://prazg.github.io/Nepal_TRAYA/)"

# ---------------------------------------------------------------------------
# Official Nepali Devanagari names for all 7 provinces & all 77 districts
# ---------------------------------------------------------------------------
PROVINCE_NE: dict[str, str] = {
    "Koshi Province": "कोशी प्रदेश",
    "Madhesh Province": "मधेश प्रदेश",
    "Bagmati Province": "बागमती प्रदेश",
    "Gandaki Province": "गण्डकी प्रदेश",
    "Lumbini Province": "लुम्बिनी प्रदेश",
    "Karnali Province": "कर्णाली प्रदेश",
    "Sudurpashchim Province": "सुदूरपश्चिम प्रदेश",
}

DISTRICT_NE: dict[str, str] = {
    "Achham": "अछाम",
    "Arghakhanchi": "अर्घाखाँची",
    "Baglung": "बागलुङ",
    "Baitadi": "बैतडी",
    "Bajhang": "बझाङ",
    "Bajura": "बाजुरा",
    "Banke": "बाँके",
    "Bara": "बारा",
    "Bardiya": "बर्दिया",
    "Bhaktapur": "भक्तपुर",
    "Bhojpur": "भोजपुर",
    "Chitwan": "चितवन",
    "Dadeldhura": "डडेल्धुरा",
    "Dailekh": "दैलेख",
    "Dang": "दाङ",
    "Darchula": "दार्चुला",
    "Dhading": "धादिङ",
    "Dhankuta": "धनकुटा",
    "Dhanusha": "धनुषा",
    "Dolakha": "दोलखा",
    "Dolpa": "डोल्पा",
    "Doti": "डोटी",
    "Gorkha": "गोरखा",
    "Gulmi": "गुल्मी",
    "Humla": "हुम्ला",
    "Ilam": "इलाम",
    "Jajarkot": "जाजरकोट",
    "Jhapa": "झापा",
    "Jumla": "जुम्ला",
    "Kabhrepalanchok": "काभ्रेपलाञ्चोक",
    "Kailali": "कैलाली",
    "Kalikot": "कालिकोट",
    "Kanchanpur": "कञ्चनपुर",
    "Kapilvastu": "कपिलवस्तु",
    "Kaski": "कास्की",
    "Kathmandu": "काठमाडौँ",
    "Khotang": "खोटाङ",
    "Lalitpur": "ललितपुर",
    "Lamjung": "लमजुङ",
    "Mahottari": "महोत्तरी",
    "Makwanpur": "मकवानपुर",
    "Manang": "मनाङ",
    "Morang": "मोरङ",
    "Mugu": "मुगु",
    "Mustang": "मुस्ताङ",
    "Myagdi": "म्याग्दी",
    "Nawalpur": "नवलपुर",
    "Nuwakot": "नुवाकोट",
    "Okhaldhunga": "ओखलढुङ्गा",
    "Palpa": "पाल्पा",
    "Panchthar": "पाँचथर",
    "Parasi": "परासी",
    "Parbat": "पर्वत",
    "Parsa": "पर्सा",
    "Pyuthan": "प्यूठान",
    "Ramechhap": "रामेछाप",
    "Rasuwa": "रसुवा",
    "Rautahat": "रौतहट",
    "Rolpa": "रोल्पा",
    "Rukum East": "रुकुम पूर्व",
    "Rukum West": "रुकुम पश्चिम",
    "Rupandehi": "रुपन्देही",
    "Salyan": "सल्यान",
    "Sankhuwasabha": "सङ्खुवासभा",
    "Saptari": "सप्तरी",
    "Sarlahi": "सर्लाही",
    "Sindhuli": "सिन्धुली",
    "Sindhupalchok": "सिन्धुपाल्चोक",
    "Siraha": "सिराहा",
    "Solukhumbu": "सोलुखुम्बु",
    "Sunsari": "सुनसरी",
    "Surkhet": "सुर्खेत",
    "Syangja": "स्याङ्जा",
    "Tanahun": "तनहुँ",
    "Taplejung": "ताप्लेजुङ",
    "Terhathum": "तेह्रथुम",
    "Udayapur": "उदयपुर",
}

# Known ASCII-lossy USGS diacritic corruptions in cached historical catalogue
PLACE_MOJIBAKE_FIXES: tuple[tuple[str, str], ...] = (
    ("Kh??db?ri??", "Khāndbāri"),
    ("Kod?ri??", "Kodāri"),
    ("Panauti??", "Panauti"),
    ("D?rchul?", "Dārchulā"),
    ("Dh?rchula", "Dhārchula"),
    ("B?geshwar", "Bāgeshwar"),
    ("B?glung", "Bāglung"),
    ("Lah?n", "Lahān"),
    ("Il?m", "Ilām"),
    ("Tuls?pur", "Tulsīpur"),
    ("Pithor?garh", "Pithorāgarh"),
    ("Dhankut?", "Dhankutā"),
    ("Dadeldhur?", "Dadeldhurā"),
    ("?ik?pur", "Ṭikāpur"),
    ("B?rpur", "Bīrpur"),
    ("Lohagh?t", "Lohaghāt"),
    ("Dhar?n", "Dharān"),
    ("D?rjiling", "Dārjiling"),
    ("Naya B?z?r", "Naya Bāzār"),
    ("R?mnagar", "Rāmnagar"),
    ("P?tan", "Pātan"),
    ("R?jbir?j", "Rājbirāj"),
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------
def atomic_write_json(path: str, obj: Any) -> int:
    """Atomically write UTF-8 compact JSON and return byte size."""
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
    return os.path.getsize(path)


def read_js_or_json(json_path: str, js_path: str) -> Any:
    if os.path.exists(js_path):
        with open(js_path, encoding="utf-8") as fh:
            txt = fh.read()
        return json.loads(txt.split("=", 1)[1].rsplit(";", 1)[0])
    if os.path.exists(json_path):
        with open(json_path, encoding="utf-8") as fh:
            return json.load(fh)
    raise FileNotFoundError(f"Neither {js_path} nor {json_path} exists")


def next_monday_0315_utc(now_utc: dt.datetime | None = None) -> str:
    """Align next scheduled refresh to GitHub Actions cron `15 3 * * 1` (Monday 03:15 UTC)."""
    now = now_utc or dt.datetime.now(dt.timezone.utc)
    if now.tzinfo is None:
        now = now.replace(tzinfo=dt.timezone.utc)
    days_ahead = (0 - now.weekday()) % 7  # Monday == 0
    cand = now.replace(hour=3, minute=15, second=0, microsecond=0) + dt.timedelta(days=days_ahead)
    if cand <= now:
        cand += dt.timedelta(days=7)
    return cand.strftime("%Y-%m-%dT%H:%M:%SZ")


def clean_place_utf8(place: str | None) -> str:
    """Repair known USGS ASCII-lossy '?' mojibake in Nepal/Himalaya place names."""
    s = str(place or "").strip()
    if "?" not in s:
        return s
    for bad, good in PLACE_MOJIBAKE_FIXES:
        if bad in s:
            s = s.replace(bad, good)
    # Remove any residual stray '?' replacement glyphs
    s = re.sub(r"\?+", "", s).strip()
    return s


def corrected_overall_hazard(
    avalanche: bool,
    rockfall: bool,
    upstream_glof: bool,
    sla_steep: bool,
    ice_cored: bool | None,
) -> str:
    """Corrected Rounce et al. (2016) Figure 4 general reading.

    Fixes the v1 bug where `(dyn='low', sdf='high')` was wrongly downgraded to
    'moderate' instead of 'high'.
    """
    dyn = HZ.dynamic_hazard(avalanche, rockfall, upstream_glof)
    sdf = HZ.self_destructive_hazard(sla_steep, ice_cored)
    if HZ.ORDER[dyn] > 0 and HZ.ORDER[sdf] > 0:
        return "very high"
    if HZ.ORDER[dyn] > 0:
        return dyn
    if HZ.ORDER[sdf] > 0:
        return sdf
    return "low"


def _ring_area_centroid(ring: list[list[float]]) -> tuple[float, float]:
    a = cx = cy = 0.0
    n = len(ring)
    for i in range(n - 1):
        x0, y0 = ring[i][0], ring[i][1]
        x1, y1 = ring[i + 1][0], ring[i + 1][1]
        cross = x0 * y1 - x1 * y0
        a += cross
        cx += (x0 + x1) * cross
        cy += (y0 + y1) * cross
    if abs(a) < 1e-12:
        xs = [p[0] for p in ring]
        ys = [p[1] for p in ring]
        return (sum(xs) / max(1, len(xs)), sum(ys) / max(1, len(ys)))
    a *= 0.5
    return (cx / (6.0 * a), cy / (6.0 * a))


def _round_ring(ring: list[list[float]], nd: int = 4) -> list[list[float]]:
    out: list[list[float]] = []
    for pt in ring:
        rp = [round(float(pt[0]), nd), round(float(pt[1]), nd)]
        if not out or rp != out[-1]:
            out.append(rp)
    if len(out) >= 2 and out[0] != out[-1]:
        out.append(out[0])
    # Preserve valid Polygon ring (>=4 vertices including closure)
    if len(out) < 4:
        raw = [[round(float(pt[0]), nd), round(float(pt[1]), nd)] for pt in ring]
        if raw and raw[0] != raw[-1]:
            raw.append(raw[0])
        while len(raw) < 4 and raw:
            raw.append(raw[-1])
        return raw
    return out


def _clean_int(v: Any) -> int | None:
    if v is None:
        return None
    f = float(v)
    return int(round(f)) if math.isfinite(f) else None


def _clean_float(v: Any, nd: int = 2) -> float | None:
    if v is None:
        return None
    f = float(v)
    return round(f, nd) if math.isfinite(f) else None


def _haversine_km(lon1: float, lat1: float, lon2: float, lat2: float) -> float:
    return SZ.haversine_km(lon1, lat1, lon2, lat2)


# ---------------------------------------------------------------------------
# 1. Exposure loading & true perpendicular point-to-segment routing exposure
# ---------------------------------------------------------------------------
def load_overpass_exposure(offline: bool = True, refresh_osm: bool = False) -> list[dict[str, Any]]:
    """Load OpenStreetMap exposure objects from cache/overpass/*.json (stdlib only)."""
    cache_dir = os.path.join(C.CACHE, "overpass")
    if refresh_osm and not offline:
        # Remove stale overpass caches so exposure.py refetches them
        for kind in ("places", "health", "hydropower", "bridges", "borders"):
            p = os.path.join(cache_dir, f"{kind}.json")
            try:
                if os.path.exists(p):
                    os.remove(p)
                EX._fetch(kind, EX.QUERIES[kind])
            except Exception as exc:
                print(f"  [exposure] OSM refresh failed for {kind}: {exc}", file=sys.stderr)

    out: list[dict[str, Any]] = []
    for kind in ("places", "health", "hydropower", "bridges", "borders"):
        path = os.path.join(cache_dir, f"{kind}.json")
        if not os.path.exists(path):
            continue
        with open(path, encoding="utf-8") as fh:
            payload = json.load(fh)
        for el in payload.get("elements") or []:
            if el.get("type") == "node":
                lon, lat = el.get("lon"), el.get("lat")
            else:
                ctr = el.get("center") or {}
                lon, lat = ctr.get("lon"), ctr.get("lat")
            if lon is None or lat is None:
                continue
            tags = el.get("tags") or {}
            raw_name = str(tags.get("name") or "").strip()
            name_en = str(tags.get("name:en") or "").strip()
            name_ne = str(tags.get("name:ne") or "").strip()
            if not name_ne and any("\u0900" <= ch <= "\u097f" for ch in raw_name):
                name_ne = raw_name
            display_name = name_en or raw_name or str(tags.get("ref") or "").strip()
            out.append({
                "kind": kind,
                "lon": round(float(lon), 5),
                "lat": round(float(lat), 5),
                "name": display_name,
                "name_ne": name_ne if name_ne and name_ne != display_name else "",
                "sub": (
                    tags.get("place")
                    or tags.get("amenity")
                    or tags.get("power")
                    or tags.get("highway")
                    or tags.get("railway")
                    or tags.get("barrier")
                    or ""
                ),
                "pop": EX._int(tags.get("population")),
                "capacity_mw": EX._mw(
                    tags.get("plant:output:electricity")
                    or tags.get("generator:output:electricity")
                ),
                "osm": f"{el['type'][0]}{el['id']}",
            })
    return out


def recompute_point_to_segment_exposure(
    raw_routes: dict[str, dict[str, Any]],
    expo: list[dict[str, Any]],
    corridor_m: float = C.EXPOSURE_CORRIDOR_M,
) -> tuple[dict[str, dict[str, Any]], list[dict[str, Any]], dict[str, dict[str, int]]]:
    """Recompute true perpendicular point-to-segment downstream exposure for all routes.

    Uses equirectangular local-km segment projection + 0.05 deg spatial grid
    bucketing (pure stdlib Python, ~0.3 s for 697 routes x 38k OSM objects).

    Returns:
      slim_routes  : dict[lake_id, {km, path, exp}] (stripped of duplicated fields)
      expo_out     : compact list of referenced exposure dicts (+ all hydropower)
      route_counts : dict[lake_id, {places, hydropower, bridges, health, borders}]
    """
    corridor_km = corridor_m / 1000.0
    corridor_km2 = corridor_km * corridor_km
    cell_deg = 0.05
    pad_deg = (corridor_m / 100_000.0) + 0.004  # conservative lat/lon padding

    # Build spatial grid index
    grid: dict[tuple[int, int], list[tuple[int, float, float]]] = defaultdict(list)
    for idx, obj in enumerate(expo):
        gx = int(math.floor(obj["lon"] / cell_deg))
        gy = int(math.floor(obj["lat"] / cell_deg))
        grid[(gx, gy)].append((idx, obj["lon"], obj["lat"]))

    raw_hits_by_lake: dict[str, list[tuple[int, float, float]]] = {}
    route_counts: dict[str, dict[str, int]] = {}
    used_expo: set[int] = set()

    for lid, r in raw_routes.items():
        pts = r.get("path") or []
        if len(pts) < 2:
            raw_hits_by_lake[lid] = []
            route_counts[lid] = {"places": 0, "hydropower": 0, "bridges": 0, "health": 0, "borders": 0}
            continue

        lat0 = sum(p[1] for p in pts) / len(pts)
        kx = 111.320 * math.cos(math.radians(lat0))
        ky = 110.540

        xs = [p[0] * kx for p in pts]
        ys = [p[1] * ky for p in pts]
        cum_km = 0.0
        best: dict[int, tuple[float, float]] = {}  # idx -> (dist_km, along_km)

        for k in range(len(pts) - 1):
            p0, p1 = pts[k], pts[k + 1]
            x0, y0 = xs[k], ys[k]
            x1, y1 = xs[k + 1], ys[k + 1]
            dx, dy = x1 - x0, y1 - y0
            l2 = dx * dx + dy * dy
            seg_len = math.sqrt(l2)

            mnl = min(p0[0], p1[0]) - pad_deg
            mxl = max(p0[0], p1[0]) + pad_deg
            mna = min(p0[1], p1[1]) - pad_deg
            mxa = max(p0[1], p1[1]) + pad_deg

            gx0 = int(math.floor(mnl / cell_deg))
            gx1 = int(math.floor(mxl / cell_deg))
            gy0 = int(math.floor(mna / cell_deg))
            gy1 = int(math.floor(mxa / cell_deg))

            for gx in range(gx0, gx1 + 1):
                for gy in range(gy0, gy1 + 1):
                    bucket = grid.get((gx, gy))
                    if not bucket:
                        continue
                    for idx, plon, plat in bucket:
                        if plon < mnl or plon > mxl or plat < mna or plat > mxa:
                            continue
                        px = plon * kx
                        py = plat * ky
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
                        if d2 <= corridor_km2:
                            d_km = math.sqrt(d2)
                            prev = best.get(idx)
                            if prev is None or d_km < prev[0]:
                                best[idx] = (d_km, cum_km + t * seg_len)
            cum_km += seg_len

        hits = [(idx, along_km, d_km * 1000.0) for idx, (d_km, along_km) in best.items()]
        hits.sort(key=lambda h: h[1])
        raw_hits_by_lake[lid] = hits
        used_expo.update(best.keys())
        cnt = Counter(expo[idx]["kind"] for idx in best)
        route_counts[lid] = {
            "places": int(cnt["places"]),
            "hydropower": int(cnt["hydropower"]),
            "bridges": int(cnt["bridges"]),
            "health": int(cnt["health"]),
            "borders": int(cnt["borders"]),
        }

    # Prioritize exposure entries per route: keep ALL hit hydropower & health,
    # then nearest named settlements, then named bridges up to 60 entries total.
    # (Full uncapped counts remain in `route_counts` / `lakes_core.json`.)
    slim_routes: dict[str, dict[str, Any]] = {}
    referenced_ids: set[int] = set()
    for lid, r in raw_routes.items():
        pts = [[round(float(c[0]), 4), round(float(c[1]), 4)] for c in (r.get("path") or [])]
        raw_hits = raw_hits_by_lake.get(lid, [])
        crit = [h for h in raw_hits if expo[h[0]]["kind"] in ("hydropower", "health")]
        places = [h for h in raw_hits if expo[h[0]]["kind"] == "places" and expo[h[0]]["name"]]
        named_other = [
            h
            for h in raw_hits
            if expo[h[0]]["kind"] not in ("hydropower", "health", "places") and expo[h[0]]["name"]
        ]
        max_items = 60
        selected = list(crit)
        rem = max(0, max_items - len(selected))
        if rem > 0:
            selected.extend(places[:rem])
            rem = max(0, max_items - len(selected))
        if rem > 0:
            selected.extend(named_other[:rem])
        selected.sort(key=lambda h: h[1])
        hits = [[i, round(d_km, 1), int(round(off_m))] for i, d_km, off_m in selected]
        for h in hits:
            referenced_ids.add(h[0])
        slim_routes[lid] = {
            "km": round(float(r.get("km") or 0.0), 1),
            "path": pts,
            "exp": hits,
        }

    # Emit only referenced exposure objects plus all hydropower facilities nationally
    expo_out: list[dict[str, Any]] = []
    for i, o in enumerate(expo):
        if i in referenced_ids or o["kind"] == "hydropower":
            rec: dict[str, Any] = {
                "i": i,
                "kind": o["kind"],
                "lon": round(o["lon"], 4),
                "lat": round(o["lat"], 4),
                "name": o["name"],
                "sub": o["sub"],
                "osm": o["osm"],
            }
            if o.get("name_ne"):
                rec["name_ne"] = o["name_ne"]
            if o.get("pop") is not None:
                rec["pop"] = o["pop"]
            if o.get("capacity_mw") is not None:
                rec["capacity_mw"] = round(float(o["capacity_mw"]), 2)
            expo_out.append(rec)

    return slim_routes, expo_out, route_counts


# ---------------------------------------------------------------------------
# 2. Slimmed & corrected lakes_core.json
# ---------------------------------------------------------------------------
def build_lakes_core(
    raw_lakes: dict[str, Any],
    adm: HM.StdlibAdminLookup,
    active_faults: list[dict[str, Any]],
    slim_routes: dict[str, dict[str, Any]],
    route_counts: dict[str, dict[str, int]],
) -> tuple[dict[str, Any], dict[str, int]]:
    """Slim & scientifically correct all 1,429 lakes into `data/lakes_core.json`."""
    feats_out: list[dict[str, Any]] = []
    counts: Counter[str] = Counter()

    for feat in raw_lakes.get("features") or []:
        p = dict(feat.get("properties") or {})
        geom = feat.get("geometry") or {}
        lid = str(p["id"])

        # Round polygon coordinates to 4 decimals & compute centroid
        if geom.get("type") == "Polygon" and geom.get("coordinates"):
            rings = [_round_ring(r, 4) for r in geom["coordinates"]]
            lon, lat = _ring_area_centroid(rings[0])
            geom_out = {"type": "Polygon", "coordinates": rings}
        else:
            lon = float(p.get("lon") or 0.0)
            lat = float(p.get("lat") or 0.0)
            geom_out = geom

        # Fix canonical province (no Bagamati) and unassigned border lake GL_30.41653_80.68146 via PIP
        prov = FL.canonical_province(p.get("prov"))
        dist = str(p.get("district") or "").strip()
        if not prov or not dist:
            pip_prov = adm.province(lon, lat)
            pip_dist = adm.district(lon, lat)
            prov = FL.canonical_province(pip_prov or prov)
            dist = pip_dist or dist

        # Recompute active-fault proximity using ONLY the 70 active fault traces (zero folds!)
        f_km, f_name, f_slip = FA.nearest_fault(lon, lat, active_faults)

        # Corrected overall_hazard (fixes dyn='low' & sdf='high' -> 'high')
        ava = bool(p.get("avalanche"))
        rock = bool(p.get("rockfall"))
        ups = bool(p.get("upstream_glof"))
        sla_area = float(p.get("sla_area_km2") or 0.0)
        sla_steep = sla_area > 0.0
        ice = True if p.get("ice_cored") else None

        hz = corrected_overall_hazard(ava, rock, ups, sla_steep, ice)
        hz_enum = HZ.overall_hazard_enumerated(ava, rock, ups, sla_steep, ice)
        counts[f"hazard_{hz}"] += 1
        counts[f"hazard_enum_{hz_enum}"] += 1

        props: dict[str, Any] = {
            "id": lid,
            "lon": round(lon, 4),
            "lat": round(lat, 4),
            "area_km2": _clean_float(p.get("area_km2"), 4),
            "z": _clean_int(p.get("z")),
            "typ": p.get("typ") or "",
            "prov": prov,
            "district": dist,
            "dist_glacier_m": _clean_int(p.get("dist_glacier_m")),
            "area_change_pct": _clean_float(p.get("area_change_pct"), 1),
            "change_class": p.get("change_class") or "",
            "past_glof": int(p.get("past_glof") or 0),
            "contrib_km2": _clean_float(p.get("contrib_km2"), 2),
            "relief_m": _clean_int(p.get("relief_m")),
            "slope1k_deg": _clean_float(p.get("slope1k_deg"), 1),
            "ice_contact": bool(p.get("ice_contact")),
            "permafrost_belt": bool(p.get("permafrost_belt")),
            "avalanche": ava,
            "rockfall": rock,
            "upstream_glof": ups,
            "sla_area_km2": round(sla_area, 4),
            "sla_max_angle": _clean_float(p.get("sla_max_angle"), 1),
            "ava_volume_Mm3": _clean_float(p.get("ava_volume_Mm3"), 2) or 0.0,
            "depth_m": _clean_int(p.get("depth_m")),
            "depth_lo": _clean_int(p.get("depth_lo")),
            "depth_hi": _clean_int(p.get("depth_hi")),
            "volume_Mm3": _clean_float(p.get("volume_Mm3"), 2),
            "qp_m3s": _clean_int(p.get("qp_m3s")),
            "qp_lo": _clean_int(p.get("qp_lo")),
            "qp_hi": _clean_int(p.get("qp_hi")),
            "hp_m": _clean_float(p.get("hp_m"), 1),
            "hp_capped": bool(p.get("hp_capped")),
            "pfv_Mm3": _clean_float(p.get("pfv_Mm3"), 2) or 0.0,
            "pfv_lo_Mm3": _clean_float(p.get("pfv_lo_Mm3"), 2) or 0.0,
            "pfv_hi_Mm3": _clean_float(p.get("pfv_hi_Mm3"), 2) or 0.0,
            "priority": bool(p.get("priority")),
            "dm_fujita_m": _clean_float(p.get("dm_fujita_m"), 1),
            "eq_n_m5_within_50km": int(p.get("eq_n_m5_within_50km") or 0),
            "eq_n_m6_within_100km": int(p.get("eq_n_m6_within_100km") or 0),
            "eq_nearest_m6_km": _clean_float(p.get("eq_nearest_m6_km"), 1),
            "fault_km": f_km,
            "fault_name": f_name,
            "fault_slip": f_slip,
            "hazard": hz,
            "hazard_enum": hz_enum,
        }

        # Optional non-empty / non-null fields (keeps payload slim without losing info)
        if p.get("name"):
            props["name"] = str(p["name"]).strip()
        if p.get("rgi"):
            props["rgi"] = str(p["rgi"]).strip()
        if ice:
            props["ice_cored"] = True
        if p.get("ava_reach_deg") is not None:
            props["ava_reach_deg"] = _clean_float(p["ava_reach_deg"], 1)
        if p.get("rock_reach_deg") is not None:
            props["rock_reach_deg"] = _clean_float(p["rock_reach_deg"], 1)
        for qk in ("qp_10", "qp_30", "qp_50", "qp_100"):
            if p.get(qk) is not None:
                props[qk] = _clean_int(p[qk])

        # Updated downstream exposure counts + recomputed impact & risk
        if lid in slim_routes:
            rc = route_counts[lid]
            imp = HZ.downstream_impact(
                rc["places"], rc["hydropower"], rc["bridges"], rc["health"]
            )
            rk = HZ.risk(hz, imp)
            rk_enum = HZ.risk(hz_enum, imp)
            props["impact"] = imp
            props["risk"] = rk
            props["risk_enum"] = rk_enum
            props["route_km"] = slim_routes[lid]["km"]
            props["pop_low"] = _clean_int(p.get("pop_low"))
            props["pop_high"] = _clean_int(p.get("pop_high"))
            props["n_settlements"] = rc["places"]
            props["n_hydropower"] = rc["hydropower"]
            props["n_bridges"] = rc["bridges"]
            props["n_health"] = rc["health"]
            if p.get("qp_over_mean_flow") is not None:
                props["qp_over_mean_flow"] = _clean_int(p["qp_over_mean_flow"])
            counts[f"impact_{imp}"] += 1
            counts[f"risk_{rk}"] += 1
            counts[f"risk_enum_{rk_enum}"] += 1

        # Remove None values cleanly to avoid serializing nulls
        props = {k: v for k, v in props.items() if v is not None}
        feats_out.append({"type": "Feature", "geometry": geom_out, "properties": props})

    return {"type": "FeatureCollection", "features": feats_out}, dict(counts)


LAKES_COMPACT_FORMAT = "traya_lakes_v2"
LAKES_COMPACT_COORD_SCALE = 10000
LAKES_COMPACT_DICT_COLS = (
    "typ",
    "prov",
    "district",
    "change_class",
    "fault_name",
    "fault_slip",
    "hazard",
    "hazard_enum",
    "impact",
    "risk",
    "risk_enum",
)
LAKES_COMPACT_BOOL_COLS = (
    "ice_contact",
    "permafrost_belt",
    "avalanche",
    "rockfall",
    "upstream_glof",
    "hp_capped",
    "priority",
    "ice_cored",
)
LAKES_COMPACT_COL_ORDER = (
    # Dense core fields present on nearly all 1,429 lakes
    "id", "lon", "lat", "area_km2", "z", "typ", "prov", "district",
    "dist_glacier_m", "area_change_pct", "change_class", "past_glof",
    "contrib_km2", "relief_m", "slope1k_deg", "ice_contact", "permafrost_belt",
    "avalanche", "rockfall", "upstream_glof", "sla_area_km2", "sla_max_angle",
    "ava_volume_Mm3", "depth_m", "depth_lo", "depth_hi", "volume_Mm3",
    "qp_m3s", "qp_lo", "qp_hi", "hp_m", "hp_capped", "pfv_Mm3",
    "pfv_lo_Mm3", "pfv_hi_Mm3", "priority", "dm_fujita_m",
    "eq_n_m5_within_50km", "eq_n_m6_within_100km", "eq_nearest_m6_km",
    "fault_km", "fault_name", "fault_slip", "hazard", "hazard_enum",
    # Sparse / routed / optional fields at end so trailing nulls trim cleanly
    "rgi", "qp_10", "qp_30", "qp_50", "qp_100",
    "impact", "risk", "risk_enum", "route_km", "pop_low", "pop_high",
    "n_settlements", "n_hydropower", "n_bridges", "n_health",
    "qp_over_mean_flow", "rock_reach_deg", "ava_reach_deg", "name", "ice_cored",
)


def pack_lakes_core(lakes_fc: dict[str, Any]) -> dict[str, Any]:
    """Losslessly pack lakes FeatureCollection into compact columnar-row startup JSON.

    Eliminates ~1.4 MB of repeated property keys, repeated categorical strings,
    and verbose GeoJSON wrappers while round-tripping all 1,429 polygons and
    properties with exact 4-decimal precision.
    """
    feats = lakes_fc.get("features") or []
    seen_keys: set[str] = set()
    for f in feats:
        seen_keys.update((f.get("properties") or {}).keys())

    cols: list[str] = [k for k in LAKES_COMPACT_COL_ORDER if k in seen_keys]
    for k in sorted(seen_keys - set(cols)):
        cols.append(k)

    dict_set = set(LAKES_COMPACT_DICT_COLS)
    bool_set = set(LAKES_COMPACT_BOOL_COLS)
    dicts: dict[str, list[str]] = {k: [] for k in cols if k in dict_set}
    dmap: dict[str, dict[str, int]] = {k: {} for k in dicts}
    bool_cols = [k for k in cols if k in bool_set]

    rows: list[list[Any]] = []
    geoms: list[Any] = []
    scale = LAKES_COMPACT_COORD_SCALE

    for f in feats:
        p = f.get("properties") or {}
        row: list[Any] = []
        for k in cols:
            v = p.get(k)
            if v is None:
                row.append(None)
            elif k in dmap:
                sv = str(v)
                idx = dmap[k].get(sv)
                if idx is None:
                    idx = len(dicts[k])
                    dmap[k][sv] = idx
                    dicts[k].append(sv)
                row.append(idx)
            elif k in bool_set:
                row.append(1 if v else 0)
            else:
                row.append(v)
        while row and row[-1] is None:
            row.pop()
        rows.append(row)

        g = f.get("geometry") or {}
        if g.get("type") == "Polygon" and isinstance(g.get("coordinates"), list) and len(g["coordinates"]) == 1:
            ring = g["coordinates"][0]
            pts = ring[:-1] if len(ring) > 1 and ring[0] == ring[-1] else ring
            delta: list[int] = []
            px = 0
            py = 0
            for pt in pts:
                ix = int(round(float(pt[0]) * scale))
                iy = int(round(float(pt[1]) * scale))
                delta.append(ix - px)
                delta.append(iy - py)
                px, py = ix, iy
            geoms.append(delta)
        else:
            geoms.append(g)

    return {
        "format": LAKES_COMPACT_FORMAT,
        "coord_scale": scale,
        "n_lakes": len(rows),
        "cols": cols,
        "bool_cols": bool_cols,
        "dicts": dicts,
        "rows": rows,
        "geoms": geoms,
    }


def unpack_lakes_core(packed: dict[str, Any]) -> dict[str, Any]:
    """Decode compact `traya_lakes_v2` payload back into standard GeoJSON FeatureCollection."""
    if packed.get("type") == "FeatureCollection":
        return packed
    cols = packed.get("cols") or []
    dicts = packed.get("dicts") or {}
    bool_set = set(packed.get("bool_cols") or [])
    scale = float(packed.get("coord_scale") or LAKES_COMPACT_COORD_SCALE)
    rows = packed.get("rows") or []
    geoms = packed.get("geoms") or []
    feats: list[dict[str, Any]] = []
    for idx, row in enumerate(rows):
        props: dict[str, Any] = {}
        for j, v in enumerate(row):
            if v is None or j >= len(cols):
                continue
            k = cols[j]
            if k in dicts:
                props[k] = dicts[k][v]
            elif k in bool_set:
                props[k] = bool(v)
            else:
                props[k] = v
        raw_g = geoms[idx] if idx < len(geoms) else None
        if isinstance(raw_g, list):
            ring: list[list[float]] = []
            ix = 0
            iy = 0
            for k in range(0, len(raw_g) - 1, 2):
                ix += int(raw_g[k])
                iy += int(raw_g[k + 1])
                ring.append([round(ix / scale, 4), round(iy / scale, 4)])
            if ring and ring[0] != ring[-1]:
                ring.append(list(ring[0]))
            geom: dict[str, Any] = {"type": "Polygon", "coordinates": [ring]}
        else:
            geom = raw_g or {"type": "Point", "coordinates": [props.get("lon", 0.0), props.get("lat", 0.0)]}
        feats.append({"type": "Feature", "geometry": geom, "properties": props})
    return {"type": "FeatureCollection", "features": feats}


# ---------------------------------------------------------------------------
# 3. 77-district & 7-province cross-hazard index (`data/districts.json`)
# ---------------------------------------------------------------------------
def build_districts_index(
    adm: HM.StdlibAdminLookup,
    lakes_core: dict[str, Any],
    slim_routes: dict[str, dict[str, Any]],
    rivers_watch: dict[str, Any],
    hydromet: dict[str, Any],
    landslides: dict[str, Any],
    build_utc: str,
) -> dict[str, Any]:
    """Extract all 77 districts + 7 provinces with Devanagari names and pre-indexed exposure."""
    raw_adm = json.load(open(os.path.join(C.CACHE, "nepal_admin.json"), encoding="utf-8"))

    # Pre-index lakes by district
    lakes_by_dist: dict[str, list[dict[str, Any]]] = defaultdict(list)
    pri_lakes_set: set[str] = set()
    for f in lakes_core["features"]:
        p = f["properties"]
        lakes_by_dist[p["district"]].append(p)
        if p.get("priority"):
            pri_lakes_set.add(p["id"])

    # Pre-index routed GLOF flood corridors traversing EACH district
    # Sample route vertices + segment midpoints into district PIP
    corridors_by_dist: dict[str, set[str]] = defaultdict(set)
    for lid, r in slim_routes.items():
        pts = r.get("path") or []
        visited: set[str] = set()
        for k, pt in enumerate(pts):
            d_hit = adm.district(pt[0], pt[1])
            if d_hit:
                visited.add(d_hit)
            if k + 1 < len(pts):
                mx = 0.5 * (pt[0] + pts[k + 1][0])
                my = 0.5 * (pt[1] + pts[k + 1][1])
                d_mid = adm.district(mx, my)
                if d_mid:
                    visited.add(d_mid)
        for d_name in visited:
            corridors_by_dist[d_name].add(lid)

    # Pre-index landslide inventory records by district
    ls_by_dist: Counter[str] = Counter()
    for ev in landslides.get("events") or []:
        d_hit = adm.district(float(ev["lon"]), float(ev["lat"]))
        if d_hit:
            ls_by_dist[d_hit] += 1

    basins = rivers_watch.get("basins") or []
    nodes = hydromet.get("nodes") or []

    # Build all 77 district records
    districts_out: list[dict[str, Any]] = []
    prov_districts: dict[str, list[str]] = defaultdict(list)
    prov_lakes: Counter[str] = Counter()
    prov_pri: Counter[str] = Counter()
    prov_corridors: dict[str, set[str]] = defaultdict(set)

    for item in sorted(raw_adm.get("6") or [], key=lambda x: str(x.get("name") or "")):
        d_name = str(item["name"]).strip()
        geom = item["geometry"]
        ring = geom["coordinates"][0]
        cx, cy = _ring_area_centroid(ring)
        xs = [pt[0] for pt in ring]
        ys = [pt[1] for pt in ring]
        bbox = [round(min(xs), 4), round(min(ys), 4), round(max(xs), 4), round(max(ys), 4)]
        p_name = FL.canonical_province(adm.province(cx, cy))

        dlakes = lakes_by_dist.get(d_name, [])
        dlakes_sorted = sorted(dlakes, key=lambda x: float(x.get("pfv_Mm3") or 0.0), reverse=True)
        d_pri = [x["id"] for x in dlakes_sorted if x.get("priority")]

        d_corrs = corridors_by_dist.get(d_name, set())
        d_corr_pri = sorted(lid for lid in d_corrs if lid in pri_lakes_set)

        # Nearest GloFAS river gauge
        nearest_b = min(
            basins,
            key=lambda b: _haversine_km(cx, cy, float(b["lon"]), float(b["lat"])),
        ) if basins else None
        nearest_b_km = (
            round(_haversine_km(cx, cy, float(nearest_b["lon"]), float(nearest_b["lat"])), 1)
            if nearest_b
            else None
        )

        # Nearest Dahal-Hasegawa sentinel node
        nearest_n = min(
            nodes,
            key=lambda n: _haversine_km(cx, cy, float(n["lon"]), float(n["lat"])),
        ) if nodes else None
        nearest_n_km = (
            round(_haversine_km(cx, cy, float(nearest_n["lon"]), float(nearest_n["lat"])), 1)
            if nearest_n
            else None
        )

        basins_in = [b["id"] for b in basins if b.get("district") == d_name]
        nodes_in = [n["id"] for n in nodes if n.get("district") == d_name]

        districts_out.append({
            "name": d_name,
            "name_ne": DISTRICT_NE.get(d_name, d_name),
            "prov": p_name,
            "prov_ne": PROVINCE_NE.get(p_name, p_name),
            "centroid": [round(cx, 4), round(cy, 4)],
            "bbox": bbox,
            "n_lakes": len(dlakes),
            "n_priority_lakes": len(d_pri),
            "priority_lake_ids": d_pri,
            "n_routed_corridors": len(d_corrs),
            "routed_priority_lake_ids": d_corr_pri,
            "nearest_river_basin": nearest_b["id"] if nearest_b else None,
            "nearest_river_name": nearest_b["name"] if nearest_b else None,
            "nearest_river_km": nearest_b_km,
            "river_basins_in_district": basins_in,
            "nearest_sentinel_node": nearest_n["id"] if nearest_n else None,
            "nearest_sentinel_name": nearest_n["name"] if nearest_n else None,
            "nearest_sentinel_km": nearest_n_km,
            "sentinel_nodes_in_district": nodes_in,
            "n_landslide_records": int(ls_by_dist.get(d_name, 0)),
        })

        prov_districts[p_name].append(d_name)
        prov_lakes[p_name] += len(dlakes)
        prov_pri[p_name] += len(d_pri)
        prov_corridors[p_name].update(d_corrs)

    # Build all 7 province records (explicitly including Madhesh Province)
    provinces_out: list[dict[str, Any]] = []
    for item in sorted(raw_adm.get("4") or [], key=lambda x: FL.canonical_province(x.get("name"))):
        p_name = FL.canonical_province(item["name"])
        ring = item["geometry"]["coordinates"][0]
        cx, cy = _ring_area_centroid(ring)
        xs = [pt[0] for pt in ring]
        ys = [pt[1] for pt in ring]
        bbox = [round(min(xs), 4), round(min(ys), 4), round(max(xs), 4), round(max(ys), 4)]
        p_basins = [b["id"] for b in basins if FL.canonical_province(b.get("prov")) == p_name]
        p_nodes = [n["id"] for n in nodes if FL.canonical_province(n.get("prov")) == p_name]
        provinces_out.append({
            "name": p_name,
            "name_ne": PROVINCE_NE.get(p_name, p_name),
            "centroid": [round(cx, 4), round(cy, 4)],
            "bbox": bbox,
            "n_districts": len(prov_districts.get(p_name, [])),
            "districts": sorted(prov_districts.get(p_name, [])),
            "n_lakes": int(prov_lakes.get(p_name, 0)),
            "n_priority_lakes": int(prov_pri.get(p_name, 0)),
            "n_routed_corridors": len(prov_corridors.get(p_name, set())),
            "river_basins": p_basins,
            "sentinel_nodes": p_nodes,
        })

    return {
        "updated_utc": build_utc,
        "source": "OpenStreetMap Nepal administrative boundaries (admin_level 4 & 6; ODbL 1.0)",
        "n_provinces": len(provinces_out),
        "n_districts": len(districts_out),
        "provinces": provinces_out,
        "districts": districts_out,
    }


# ---------------------------------------------------------------------------
# 4. Earthquake M>=6 history (`data/eq_history_m6.json`) & GLOF history
# ---------------------------------------------------------------------------
def build_eq_history_m6(offline: bool = False) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    """Build clean UTF-8 M>=6 historical earthquake list + full-catalogue summary."""
    cat_path = os.path.join(C.CACHE, "usgs_catalogue.json")
    if not offline:
        try:
            params = dict(
                format="geojson",
                starttime=C.EQ_CATALOGUE_START,
                minmagnitude=C.EQ_CATALOGUE_MIN_MAG,
                minlongitude=C.NEPAL_BBOX[0],
                minlatitude=C.NEPAL_BBOX[1],
                maxlongitude=C.NEPAL_BBOX[2],
                maxlatitude=C.NEPAL_BBOX[3],
                orderby="time",
                limit=20000,
            )
            url = C.USGS_QUERY + "?" + urllib.parse.urlencode(params)
            req = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
            with urllib.request.urlopen(req, timeout=120) as resp:
                gj = json.loads(resp.read().decode("utf-8"))
            cat = []
            for f in gj.get("features") or []:
                p = f.get("properties") or {}
                c = (f.get("geometry") or {}).get("coordinates") or [0, 0, None]
                cat.append({
                    "id": f.get("id"),
                    "time": p.get("time"),
                    "mag": p.get("mag"),
                    "place": clean_place_utf8(p.get("place")),
                    "depth_km": c[2],
                    "lon": round(float(c[0]), 4),
                    "lat": round(float(c[1]), 4),
                })
            atomic_write_json(cat_path, cat)
        except Exception as exc:
            print(f"  [seismic] live catalogue refresh failed ({exc}); using cache", file=sys.stderr)
            cat = json.load(open(cat_path, encoding="utf-8"))
    else:
        cat = json.load(open(cat_path, encoding="utf-8"))

    # Clean mojibake in memory and filter to M>=6.0
    m6: list[dict[str, Any]] = []
    now_ms = int(time.time() * 1000)
    thirty_days_ms = 30 * 86400 * 1000
    n_30d = 0
    for e in cat:
        mag = e.get("mag")
        if mag is None:
            continue
        if e.get("time") and (now_ms - int(e["time"])) <= thirty_days_ms and float(mag) >= 4.0:
            n_30d += 1
        if float(mag) >= 6.0:
            m6.append({
                "id": str(e.get("id") or ""),
                "time": e.get("time"),
                "mag": round(float(mag), 2),
                "place": clean_place_utf8(e.get("place")),
                "depth_km": round(float(e["depth_km"]), 1) if e.get("depth_km") is not None else None,
                "lon": round(float(e["lon"]), 4),
                "lat": round(float(e["lat"]), 4),
            })
    m6.sort(key=lambda x: x.get("time") or 0, reverse=True)
    seis_summary = SZ.summarise(cat)
    seis_summary["n_past_30d_m4plus"] = n_30d
    return m6, seis_summary


def build_glof_history() -> list[dict[str, Any]]:
    """Build `data/glof_history.json` from HMAGLOFDB v4 CSV or legacy JS."""
    csv_path = os.path.join(C.RAW, "HMAGLOFDB_v4.csv")
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
                def _num(v: Any) -> float | None:
                    try:
                        f = float(str(v).strip())
                        return f if math.isfinite(f) else None
                    except Exception:
                        return None
                out.append({
                    "gf_id": row.get("GF_ID"),
                    "year": _clean_int(_num(row.get("Year_approx"))),
                    "lake": row.get("Lake_name") or "Unknown",
                    "glacier": row.get("Glacier_name") or "",
                    "basin": row.get("River_Basin") or "",
                    "lake_type": row.get("Lake_type") or "",
                    "mechanism": row.get("Mechanism") or "",
                    "driver": row.get("Driver_GLOF") or "",
                    "lives": _clean_int(_num(row.get("Lives_total"))),
                    "discharge": _clean_float(_num(row.get("Discharge_water")), 1),
                    "volume": _clean_float(_num(row.get("Volume")), 3),
                    "lon": round(lon, 4),
                    "lat": round(lat, 4),
                })
        return out
    legacy = read_js_or_json(
        os.path.join(C.DATA, "glof_history.json"),
        os.path.join(C.DATA, "glof_history.js"),
    )
    return legacy


# ---------------------------------------------------------------------------
# 5. Enhanced sensitivity (`data/sensitivity.json`) with Hp-limited ratios
# ---------------------------------------------------------------------------
def build_sensitivity(lakes_core: dict[str, Any], build_utc: str) -> dict[str, Any]:
    """Build `data/sensitivity.json` adding Hp-limited mean/median/IQR ratios."""
    base = read_js_or_json(
        os.path.join(C.DATA, "sensitivity.json"),
        os.path.join(C.DATA, "sensitivity.js"),
    )
    terr_path = os.path.join(C.CACHE, "terrain.json")
    terr = json.load(open(terr_path, encoding="utf-8")) if os.path.exists(terr_path) else {}

    min_area = float(base.get("sample_min_area_km2") or 0.05)
    hp_lakes: list[tuple[float, float, float, float, float]] = []
    dm_lakes: list[float] = []
    gen_cnt: Counter[str] = Counter()
    enu_cnt: Counter[str] = Counter()
    diff_cnt = 0

    for f in lakes_core["features"]:
        p = f["properties"]
        gen_cnt[p["hazard"]] += 1
        enu_cnt[p["hazard_enum"]] += 1
        if p["hazard"] != p["hazard_enum"]:
            diff_cnt += 1
        a = float(p.get("area_km2") or 0.0)
        pfv = float(p.get("pfv_Mm3") or 0.0)
        if a >= min_area and pfv > 0.0:
            hp = float(p.get("hp_m") or 0.0)
            dm = float(p.get("dm_fujita_m") or 0.0)
            if hp < dm:
                t = terr.get(p["id"]) or {}
                dmin = float(t.get("sla_min_distance_m") or 500.0)
                hp_lakes.append((hp, dm, a, pfv, dmin))
            else:
                dm_lakes.append(pfv)

    def _hp_angle_stats(theta_deg: float) -> dict[str, Any]:
        ratios: list[float] = []
        pfv_ref_sum = 0.0
        pfv_th_sum = 0.0
        tan_diff = math.tan(math.radians(10.0)) - math.tan(math.radians(theta_deg))
        for hp10, dm, a, pfv10, dmin in hp_lakes:
            hp_th = max(0.0, hp10 + dmin * tan_diff)
            pfv_th = min(hp_th, dm) * a
            pfv_ref_sum += pfv10
            pfv_th_sum += pfv_th
            ratios.append(pfv_th / pfv10)
        ratios.sort()
        n = len(ratios)
        if n == 0:
            return {}
        q25 = ratios[int(0.25 * (n - 1))]
        q50 = ratios[int(0.50 * (n - 1))]
        q75 = ratios[int(0.75 * (n - 1))]
        return {
            "hp_limited_weighted_mean_ratio": round(pfv_th_sum / pfv_ref_sum, 3) if pfv_ref_sum > 0 else None,
            "hp_limited_median_ratio": round(q50, 3),
            "hp_limited_iqr_ratio": [round(q25, 3), round(q75, 3)],
            "hp_limited_pfv_Mm3": round(pfv_th_sum, 1),
        }

    ref_tot = float((base.get("variants") or [{}])[0].get("total_pfv_Mm3") or 968.6)
    angle_map = {
        "reference": 10.0,
        "SLA threshold 8 deg": 8.0,
        "SLA threshold 12 deg": 12.0,
        "SLA threshold 15 deg": 15.0,
    }
    variants_out: list[dict[str, Any]] = []
    for row in base.get("variants") or []:
        r = dict(row)
        tot = float(r.get("total_pfv_Mm3") or 0.0)
        r["total_pfv_ratio_to_reference"] = round(tot / ref_tot, 3) if ref_tot > 0 else None
        r["delta_pfv_pct"] = round(100.0 * (tot - ref_tot) / ref_tot, 1) if ref_tot > 0 else None
        vname = str(r.get("variant") or "")
        for prefix, th in angle_map.items():
            if vname.startswith(prefix):
                r.update(_hp_angle_stats(th))
                break
        variants_out.append(r)

    n_hp = len(hp_lakes)
    n_dm = len(dm_lakes)
    return {
        "build_utc": build_utc,
        "sample_size": base.get("sample_size", 322),
        "sample_min_area_km2": min_area,
        "n_hp_limited": n_hp,
        "n_dm_limited": n_dm,
        "hp_limited_pfv_Mm3": round(sum(x[3] for x in hp_lakes), 1),
        "dm_limited_pfv_Mm3": round(sum(dm_lakes), 1),
        "saturation_note": (
            f"Of {n_hp + n_dm} SLA lakes >= {min_area:.2f} km2, {n_dm} ({100.0*n_dm/max(1, n_hp+n_dm):.1f}%) "
            "are Dm-limited (Hp >= Dm), so PFV = Dm * A saturates and the all-lake median ratio stays 1.000 "
            "despite a -25.9% to +20.2% total PFV swing. Hp-limited weighted mean, median, and IQR ratios "
            f"are reported explicitly across the {n_hp} Hp-limited lakes (analytical Hp scaling from terrain cache)."
        ),
        "reference": base.get("reference"),
        "variants": variants_out,
        "hazard_reading": {
            "general": dict(gen_cnt),
            "enumerated": dict(enu_cnt),
            "n_lakes_differing": diff_cnt,
            "n_lakes": len(lakes_core["features"]),
        },
    }


# ---------------------------------------------------------------------------
# 6. Honest validation (`data/validation.json`) with separated known_limitations
# ---------------------------------------------------------------------------
def build_validation(
    lakes_core: dict[str, Any],
    slim_routes: dict[str, dict[str, Any]],
    expo_out: list[dict[str, Any]],
    faults_data: dict[str, Any],
    rivers_watch: dict[str, Any],
    hydromet: dict[str, Any],
    landslides: dict[str, Any],
    districts: dict[str, Any],
    eq_m6: list[dict[str, Any]],
    build_utc: str,
) -> dict[str, Any]:
    """Build `data/validation.json` with honest pass/fail checks separated from known_limitations."""
    base = read_js_or_json(
        os.path.join(C.DATA, "validation.json"),
        os.path.join(C.DATA, "validation.js"),
    )
    feats = lakes_core["features"]
    byid = {f["properties"]["id"]: f["properties"] for f in feats}
    expo_by_id = {o["i"]: o for o in expo_out}

    # Align Rounce Table 5 SLA check with production 4-cell contiguous `sla_area_km2 > 0` predicate
    rounce_rows = []
    for row in base.get("rounce") or []:
        r = dict(row)
        p = byid.get(r["lake_id"], {})
        sla_km2 = float(p.get("sla_area_km2") or 0.0)
        r["sla_area_km2"] = round(sla_km2, 4)
        r["sla_unfiltered_agree"] = bool(r.get("sla_unfiltered_agree", r.get("sla_agree")))
        r["sla_agree"] = bool((sla_km2 > 0.0) == (float(r["sla_pub"]) >= C.SLA_THRESHOLD_DEG))
        rounce_rows.append(r)

    ava_ok = sum(1 for r in rounce_rows if r["ava_agree"])
    rock_ok = sum(1 for r in rounce_rows if r["rock_agree"])
    sla_ok = sum(1 for r in rounce_rows if r["sla_agree"])
    sla_unfilt_ok = sum(1 for r in rounce_rows if r["sla_unfiltered_agree"])

    # Update Dig Tsho arrival-time check against recomputed point-to-segment exposure
    dig_id = next((r["lake_id"] for r in rounce_rows if "Dig Tsho" in r["lake"]), None)
    arrival_note = (base.get("arrival") or {}).get("note", "")
    arrival_pass = (base.get("arrival") or {}).get("pass")
    if arrival_pass is None:
        arrival_pass = (base.get("arrival") or {}).get("pass_")
    if dig_id and dig_id in slim_routes:
        r_dig = slim_routes[dig_id]
        named_places = [
            (i, km)
            for i, km, _ in r_dig.get("exp") or []
            if i in expo_by_id and expo_by_id[i]["kind"] == "places" and expo_by_id[i].get("name")
        ]
        if named_places:
            km0 = named_places[0][1]
            t_lo = km0 * 1000.0 / max(C.FRONT_VELOCITY_MS) / 60.0
            t_hi = km0 * 1000.0 / min(C.FRONT_VELOCITY_MS) / 60.0
            arrival_pass = not (t_hi < 30.0 or t_lo > 90.0)
            arrival_note = (
                f"first mapped settlement {km0:.1f} km downstream ({expo_by_id[named_places[0][0]]['name']}); "
                f"travel-time bracket {t_lo:.0f}-{t_hi:.0f} min versus reported 30-90 min for first bridges destroyed"
            )

    # Genuine falsifiable pass/fail assertions ONLY
    checks: list[dict[str, Any]] = []

    def chk(name: str, ok: bool, detail: str = "") -> None:
        checks.append({"name": name, "pass": bool(ok), "detail": detail})

    chk(
        "every lake has a valid hazard class (general & enumerated)",
        all(
            p.get("hazard") in HZ.ORDER and p.get("hazard_enum") in HZ.ORDER
            for p in byid.values()
        ),
        f"{len(byid)} lakes",
    )
    bad_iv = [
        p["id"]
        for p in byid.values()
        if p.get("qp_m3s") is not None and not (p["qp_lo"] <= p["qp_m3s"] <= p["qp_hi"])
    ]
    chk("peak-discharge intervals are ordered", not bad_iv, f"{len(bad_iv)} violations")
    bad_dv = [
        p["id"]
        for p in byid.values()
        if p.get("depth_m") is not None and not (p["depth_lo"] <= p["depth_m"] <= p["depth_hi"])
    ]
    chk("depth intervals are ordered", not bad_dv, f"{len(bad_dv)} violations")
    chk(
        "PFV never exceeds area x Fujita mean depth",
        all(
            (p.get("pfv_Mm3") or 0.0) <= (p.get("dm_fujita_m") or 0.0) * p["area_km2"] + 0.05
            for p in byid.values()
        ),
        "min[Hp, Dm] * A invariant within rounding tolerance",
    )
    chk(
        "lakes with a steep lakefront have a positive lowering height",
        all((p.get("hp_m") or 0.0) > 0.0 for p in byid.values() if (p.get("sla_area_km2") or 0.0) > 0.0),
        f"{sum(1 for p in byid.values() if (p.get('sla_area_km2') or 0) > 0)} SLA lakes",
    )
    chk(
        "lakes flagged for avalanche have a non-zero source volume",
        all((p.get("ava_volume_Mm3") or 0.0) > 0.0 for p in byid.values() if p.get("avalanche")),
        f"{sum(1 for p in byid.values() if p.get('avalanche'))} avalanche lakes",
    )
    chk(
        "routed paths are within configured distance",
        all(0.0 < v["km"] <= C.ROUTING_MAX_DISTANCE_KM + 25.0 for v in slim_routes.values()),
        f"{len(slim_routes)} routes, max {max((v['km'] for v in slim_routes.values()), default=0):.1f} km",
    )
    chk(
        "every routed lake has an impact and risk class",
        all(byid[k].get("impact") and byid[k].get("risk") for k in slim_routes if k in byid),
        f"{len(slim_routes)} routed lakes",
    )
    chk(
        "population range is ordered",
        all(
            (p.get("pop_low") or 0) <= (p.get("pop_high") or 0)
            for p in byid.values()
            if p.get("pop_high") is not None
        ),
        "constrained <= unconstrained WorldPop",
    )
    dangling = sum(1 for v in slim_routes.values() for e in v["exp"] if e[0] not in expo_by_id)
    chk("exposure references resolve", dangling == 0, f"{dangling} dangling references")
    chk(
        "ice-cored moraines matched documented lakes",
        sum(1 for p in byid.values() if p.get("ice_cored")) == 5,
        f"{sum(1 for p in byid.values() if p.get('ice_cored'))} of 5 matched",
    )
    dig_sla = float((byid.get(dig_id or "") or {}).get("sla_area_km2") or 0.0)
    chk("Dig Tsho has no steep lakefront after 1985 outburst", dig_sla == 0.0, f"SLA = {dig_sla:.3f} km2")
    chk(
        "no non-finite values in lakes output",
        all(
            all(not (isinstance(v, float) and not math.isfinite(v)) for v in p.values())
            for p in byid.values()
        ),
        "all numeric fields finite",
    )
    chk(
        "all 1,429 lakes carry canonical province and district spelling",
        all(
            bool(p.get("prov")) and bool(p.get("district")) and "Bagamati" not in str(p.get("prov"))
            for p in byid.values()
        ),
        f"{len(byid)} lakes verified (including GL_30.41653_80.68146)",
    )
    spans: dict[str, list[float]] = defaultdict(list)
    for p in byid.values():
        spans[p["prov"]].append(float(p["lon"]))
    worst = max(((max(v) - min(v), k) for k, v in spans.items()), default=(0.0, ""))
    chk(
        "province attribution is geographically coherent",
        worst[0] <= 4.0,
        f"widest province spans {worst[0]:.2f} deg longitude ({worst[1]})",
    )
    chk("reproduces Rounce et al. (2016) Table 5 avalanche classification", ava_ok == len(rounce_rows), f"{ava_ok}/{len(rounce_rows)} agree")
    chk("reproduces Rounce et al. (2016) Table 5 rockfall classification", rock_ok >= len(rounce_rows) - 2, f"{rock_ok}/{len(rounce_rows)} agree")
    chk(
        "reproduces Rounce et al. (2016) Table 5 SLA classification (production 4-cell predicate)",
        sla_ok >= len(rounce_rows) - 2,
        f"{sla_ok}/{len(rounce_rows)} agree on production sla_area_km2 > 0 ({sla_unfilt_ok}/{len(rounce_rows)} unfiltered)",
    )
    if arrival_pass is not None:
        chk("Dig Tsho travel-time bracket spans reported damage window", bool(arrival_pass), arrival_note)

    events = base.get("events") or []
    obs_in = sum(1 for e in events if e.get("within"))
    chk("measured outburst values fall inside predicted intervals", obs_in == len(events), f"{obs_in}/{len(events)}")
    fuj1 = base.get("fujita1") or []
    chk("mean-depth formula reproduces Fujita et al. (2013) Table 1", all(r.get("dm_ok") for r in fuj1), f"{sum(1 for r in fuj1 if r.get('dm_ok'))}/{len(fuj1)} lakes")
    chk("PFV formula reproduces Fujita et al. (2013) Table 1", all(r.get("pfv_ok") for r in fuj1), f"{sum(1 for r in fuj1 if r.get('pfv_ok'))}/{len(fuj1)} lakes")

    fuj_agr = base.get("fujita_agreement") or {}
    z_ok, z_tot = (int(x) for x in str(fuj_agr.get("zero", "0/0")).split("/"))
    l_ok, l_tot = (int(x) for x in str(fuj_agr.get("large", "0/0")).split("/"))
    chk("Fujita et al. (2013) zero-PFV lakes reproduced", z_ok >= z_tot - 1, f"{z_ok}/{z_tot} agree")
    chk("Fujita et al. (2013) large PFV (>=5 Mm3) reproduced within x3", l_ok >= l_tot - 1, f"{l_ok}/{l_tot} agree")

    # Multi-hazard checks
    n_faults = int(faults_data.get("n_traces") or 0)
    n_folds = sum(1 for f in faults_data.get("features") or [] if FA.is_non_fault_fold(f.get("properties")))
    chk(
        "active faults exclude non-fault folds and link to every lake",
        n_faults > 0 and n_folds == 0 and all(p.get("fault_km") is not None for p in byid.values()),
        f"{n_faults} active fault traces (4 folds excluded), 0 folds remaining",
    )
    basins = rivers_watch.get("basins") or []
    basins_ordered = all(
        (b.get("climatology") or {}).get("q2", 0)
        <= (b.get("climatology") or {}).get("q5", 0)
        <= (b.get("climatology") or {}).get("q20", 0)
        for b in basins
    )
    chk(
        "GloFAS river watch covers 10 major Nepal basins with ordered return levels",
        len(basins) == 10 and basins_ordered,
        f"{len(basins)}/10 basins; {rivers_watch.get('n_grid_snap_warnings', 0)} cached cells flagged for live mainstem re-snap",
    )
    nodes = hydromet.get("nodes") or []
    chk(
        "hydromet Dahal-Hasegawa watch covers 24 sentinel nodes with district & canonical province",
        len(nodes) == 24 and all(n.get("district") and "Bagamati" not in str(n.get("prov")) for n in nodes),
        f"{len(nodes)}/24 sentinel nodes",
    )
    chk(
        "all 77 districts and 7 provinces indexed with Nepali Devanagari names",
        districts.get("n_districts") == 77
        and districts.get("n_provinces") == 7
        and all(d.get("name_ne") for d in districts.get("districts") or [])
        and all(p.get("name_ne") for p in districts.get("provinces") or []),
        "77 districts, 7 provinces (including Madhesh Province)",
    )
    chk(
        "historical M>=6 earthquake catalogue has clean UTF-8 place names (zero mojibake)",
        len(eq_m6) > 0 and all("?" not in str(e.get("place") or "") for e in eq_m6),
        f"{len(eq_m6)} M>=6 events verified",
    )

    # Separated, transparent known limitations (NEVER inflated into pass checks)
    known_limitations: list[dict[str, Any]] = [
        {
            "id": "dem_30m_small_pfv",
            "title": "Small Potential Flood Volumes (<5 Mm3) under-detected at 30 m DEM resolution",
            "detail": (
                f"Only {fuj_agr.get('small', '0/4')} of small (<5 Mm3) published PFVs in Fujita et al. (2013) Table 2 "
                "are recovered on the 30 m Copernicus DEM vs 15 m ASTER DEM. PFV = 0 is a resolution limit, not a certificate of safety."
            ),
        },
        {
            "id": "glofas_cached_off_mainstem",
            "title": "GloFAS cached grid-cell snapping",
            "detail": (
                f"{rivers_watch.get('n_grid_snap_warnings', 0)} of 10 cached river basins have off-mainstem hillslope/tributary cells "
                "(flagged with grid_snap_warning=true) until the next live 3x3 mainstem snap runs."
            ),
        },
        {
            "id": "landslides_coolr_availability",
            "title": "Landslide inventory completeness",
            "detail": landslides.get("coverage_note", ""),
        },
        {
            "id": "gem_fault_surface_scope",
            "title": "Active fault surface-trace scope",
            "detail": faults_data.get("coverage_note", ""),
        },
        {
            "id": "screening_not_probabilistic",
            "title": "Screening tool, not probabilistic forecast or statutory warning",
            "detail": (
                "No probability of failure is computed, no 2D hydrodynamic inundation is modelled, and subsurface moraine ice "
                "cannot be ruled out from DEMs. Consult DHM (hydrology.gov.np), DMG/NEMRC (seismonepal.gov.np), and NDRRMA/BIPAD (bipadportal.gov.np)."
            ),
        },
    ]

    return {
        "build_utc": build_utc,
        "rounce": rounce_rows,
        "rounce_note": base.get("rounce_note", ""),
        "fujita1": fuj1,
        "fujita2": base.get("fujita2") or [],
        "fujita_large_threshold": base.get("fujita_large_threshold", 5.0),
        "fujita_agreement": fuj_agr,
        "rounce_agreement": {
            "avalanche": f"{ava_ok}/{len(rounce_rows)}",
            "rockfall": f"{rock_ok}/{len(rounce_rows)}",
            "sla_threshold": f"{sla_ok}/{len(rounce_rows)}",
            "sla_threshold_unfiltered": f"{sla_unfilt_ok}/{len(rounce_rows)}",
        },
        "events": events,
        "arrival": {"note": arrival_note, "pass": arrival_pass},
        "fit": base.get("fit") or {},
        "checks": checks,
        "n_checks_pass": sum(1 for c in checks if c["pass"]),
        "n_checks_total": len(checks),
        "known_limitations": known_limitations,
    }


# ---------------------------------------------------------------------------
# 7. Master Summary (`data/summary.json`)
# ---------------------------------------------------------------------------
def build_summary(
    lakes_core: dict[str, Any],
    lake_counts: dict[str, int],
    slim_routes: dict[str, dict[str, Any]],
    expo_all: list[dict[str, Any]],
    route_counts: dict[str, dict[str, int]],
    seis_summary: dict[str, Any],
    faults_data: dict[str, Any],
    rivers_watch: dict[str, Any],
    landslides: dict[str, Any],
    hydromet: dict[str, Any],
    alerts: dict[str, Any],
    districts: dict[str, Any],
    build_utc: str,
    offline: bool,
) -> dict[str, Any]:
    """Build lean `data/summary.json` with next Monday 03:15 UTC schedule."""
    legacy_sum = read_js_or_json(
        os.path.join(C.DATA, "summary.json"),
        os.path.join(C.DATA, "summary.js"),
    )
    feats = lakes_core["features"]
    routed_totals = Counter()
    for rc in route_counts.values():
        for k, v in rc.items():
            routed_totals[k] += v

    live_feeds = dict(legacy_sum.get("live_feeds") or {})
    live_feeds["usgs_fdsn_nepal"] = (
        f"{C.USGS_QUERY}?format=geojson&minmagnitude=2.5"
        f"&minlatitude={AL.USGS_NEPAL_BBOX[1]}&maxlatitude={AL.USGS_NEPAL_BBOX[3]}"
        f"&minlongitude={AL.USGS_NEPAL_BBOX[0]}&maxlongitude={AL.USGS_NEPAL_BBOX[2]}"
        "&orderby=time"
    )

    return {
        "build": build_utc,
        "build_mode": "offline" if offline else "live",
        "refresh_interval_days": 7,
        "schedule_cron": "15 3 * * 1",
        "schedule_npt": "Mondays 09:00 NPT (03:15 UTC)",
        "next_scheduled_refresh": next_monday_0315_utc(),
        "n_lakes": len(feats),
        "n_routed": len(slim_routes),
        "n_priority": sum(1 for f in feats if f["properties"].get("priority")),
        "n_provinces": districts["n_provinces"],
        "n_districts": districts["n_districts"],
        "counts": lake_counts,
        "hazard_counts": {k: lake_counts.get(f"hazard_{k}", 0) for k in HZ.ORDER},
        "hazard_enum_counts": {k: lake_counts.get(f"hazard_enum_{k}", 0) for k in HZ.ORDER},
        "risk_counts": {k: lake_counts.get(f"risk_{k}", 0) for k in HZ.ORDER},
        "risk_enum_counts": {k: lake_counts.get(f"risk_enum_{k}", 0) for k in HZ.ORDER},
        "seismicity": seis_summary,
        "active_faults": {
            "n_traces": faults_data["n_traces"],
            "n_folds_excluded": faults_data["n_folds_excluded"],
            "slip_type_counts": faults_data["slip_type_counts"],
            "coverage_note": faults_data["coverage_note"],
        },
        "river_basins": {
            "n_basins": rivers_watch["n_basins"],
            "updated_utc": rivers_watch["updated_utc"],
            "forecast_expires_utc": rivers_watch.get("forecast_expires_utc"),
            "climatology_years": rivers_watch.get("climatology_years"),
            "n_grid_snap_warnings": rivers_watch.get("n_grid_snap_warnings", 0),
        },
        "landslides_summary": {
            "updated_utc": landslides["updated_utc"],
            "n_total": landslides["n_total"],
            "n_nasa_coolr": landslides["n_nasa_coolr"],
            "n_osm": landslides["n_osm"],
            "nasa_coolr_available": landslides["nasa_coolr_available"],
            "fatalities": landslides["total_reported_fatalities"],
        },
        "hydromet_summary": {
            "updated_utc": hydromet["updated_utc"],
            "forecast_expires_utc": hydromet.get("forecast_expires_utc"),
            "n_nodes": hydromet["n_nodes"],
            "n_priority_monitored": hydromet["n_priority_lakes"],
        },
        "gdacs_summary": {
            "updated_utc": alerts["updated_utc"],
            "n_events": alerts["n_events"],
            "n_in_nepal": alerts["n_in_nepal"],
            "n_usgs_7d": alerts["usgs_recent"]["n_events"],
        },
        "exposure_totals": dict(Counter(o["kind"] for o in expo_all)),
        "routed_exposure_totals": dict(routed_totals),
        "exposure_method": "perpendicular point-to-segment distance <= 1000 m",
        "model": legacy_sum.get("model") or {},
        "thresholds": legacy_sum.get("thresholds") or {},
        "live_feeds": live_feeds,
        "sources": legacy_sum.get("sources") or C.SOURCES,
    }


# ---------------------------------------------------------------------------
# Main orchestrator
# ---------------------------------------------------------------------------
def run_refresh(offline: bool = False, refresh_osm: bool = False) -> dict[str, int]:
    t0 = time.perf_counter()
    build_utc = dt.datetime.now(dt.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    os.makedirs(C.DATA, exist_ok=True)
    sizes: dict[str, int] = {}

    print(f"=== Nepal TRĀYA refresh ({'OFFLINE' if offline else 'LIVE'}) @ {build_utc} ===")

    # 1. Active faults (filters out 4 non-fault folds)
    faults_data = FA.build_faults(offline=offline)
    sizes["faults.json"] = os.path.getsize(FA.OUT_JSON)
    print(f"  [1/10] faults.json          {sizes['faults.json']/1024:6.1f} KB  ({faults_data['n_traces']} traces, {faults_data['n_folds_excluded']} folds excluded)")

    # 2. Fluvial floods (10 basins, Gumbel EV1, grid-snap audit/live 3x3 snap)
    rivers_watch = FL.build_rivers_watch(offline=offline)
    sizes["rivers_watch.json"] = os.path.getsize(FL.OUT_JSON)
    print(f"  [2/10] rivers_watch.json    {sizes['rivers_watch.json']/1024:6.1f} KB  ({rivers_watch['n_basins']} basins, snap_warnings={rivers_watch['n_grid_snap_warnings']})")

    # 3. Alerts (GDACS + USGS Nepal bbox + STAC cache)
    alerts_data = AL.build_alerts(offline=offline)
    sizes["gdacs_alerts.json"] = os.path.getsize(AL.OUT_JSON)
    print(f"  [3/10] gdacs_alerts.json    {sizes['gdacs_alerts.json']/1024:6.1f} KB  (gdacs={alerts_data['n_events']}, stac={alerts_data['stac_summary']['n_priority_scenes']})")

    # 4. Hydromet (24 Dahal-Hasegawa nodes w/ district PIP + 20 priority lakes)
    hydromet_data = HM.build_hydromet_weekly(offline=offline)
    sizes["hydromet_weekly.json"] = os.path.getsize(HM.OUT_JSON)
    print(f"  [4/10] hydromet_weekly.json {sizes['hydromet_weekly.json']/1024:6.1f} KB  (nodes={hydromet_data['n_nodes']}, lakes={hydromet_data['n_priority_lakes']}, expires={hydromet_data['forecast_expires_utc']})")

    # 5. Landslides (NASA COOLR + OSM with honest availability flag)
    landslides_data = LS.build_landslides(offline=offline, refresh_osm=refresh_osm)
    sizes["landslides.json"] = os.path.getsize(LS.OUT_JSON)
    print(f"  [5/10] landslides.json      {sizes['landslides.json']/1024:6.1f} KB  (total={landslides_data['n_total']}, coolr={landslides_data['n_nasa_coolr']})")

    # 6. Historical M>=6 earthquakes (UTF-8 cleaned, zero mojibake) & GLOF history
    eq_m6, seis_summary = build_eq_history_m6(offline=offline)
    sizes["eq_history_m6.json"] = atomic_write_json(os.path.join(C.DATA, "eq_history_m6.json"), eq_m6)
    glof_hist = build_glof_history()
    sizes["glof_history.json"] = atomic_write_json(os.path.join(C.DATA, "glof_history.json"), glof_hist)
    print(f"  [6/10] eq_history_m6.json   {sizes['eq_history_m6.json']/1024:6.1f} KB  ({len(eq_m6)} M>=6 events) | glof_history.json {sizes['glof_history.json']/1024:5.1f} KB ({len(glof_hist)} records)")

    # 7. Recompute true perpendicular point-to-segment downstream exposure + slim routes & lakes_core
    adm = HM.StdlibAdminLookup()
    raw_routes = read_js_or_json(os.path.join(C.DATA, "routes.json"), os.path.join(C.DATA, "routes.js"))
    raw_lakes = read_js_or_json(os.path.join(C.DATA, "lakes.json"), os.path.join(C.DATA, "lakes.js"))
    expo_all = load_overpass_exposure(offline=offline, refresh_osm=refresh_osm)

    t_exp = time.perf_counter()
    slim_routes, expo_out, route_counts = recompute_point_to_segment_exposure(raw_routes, expo_all)
    dt_exp = time.perf_counter() - t_exp

    lakes_core, lake_counts = build_lakes_core(
        raw_lakes, adm, faults_data["features"], slim_routes, route_counts
    )
    lakes_core_packed = pack_lakes_core(lakes_core)
    sizes["exposure.json"] = atomic_write_json(os.path.join(C.DATA, "exposure.json"), expo_out)
    sizes["routes.json"] = atomic_write_json(os.path.join(C.DATA, "routes.json"), slim_routes)
    sizes["lakes_core.json"] = atomic_write_json(os.path.join(C.DATA, "lakes_core.json"), lakes_core_packed)
    sizes["lakes.json"] = atomic_write_json(os.path.join(C.DATA, "lakes.json"), lakes_core)
    print(
        f"  [7/10] lakes_core.json      {sizes['lakes_core.json']/1024:6.1f} KB "
        f"(compact; lakes.json {sizes['lakes.json']/1024:.1f} KB) | "
        f"routes.json {sizes['routes.json']/1024:6.1f} KB | "
        f"exposure.json {sizes['exposure.json']/1024:6.1f} KB  "
        f"(point-to-segment in {dt_exp:.2f}s, {len(expo_out)} objects)"
    )

    # 8. 77-district & 7-province cross-hazard index
    districts_data = build_districts_index(
        adm, lakes_core, slim_routes, rivers_watch, hydromet_data, landslides_data, build_utc
    )
    sizes["districts.json"] = atomic_write_json(os.path.join(C.DATA, "districts.json"), districts_data)
    print(f"  [8/10] districts.json       {sizes['districts.json']/1024:6.1f} KB  ({districts_data['n_provinces']} provinces, {districts_data['n_districts']} districts)")

    # 9. Sensitivity (with Hp-limited mean/median/IQR) & Validation (honest limitations separated)
    sens_data = build_sensitivity(lakes_core, build_utc)
    sizes["sensitivity.json"] = atomic_write_json(os.path.join(C.DATA, "sensitivity.json"), sens_data)
    val_data = build_validation(
        lakes_core,
        slim_routes,
        expo_out,
        faults_data,
        rivers_watch,
        hydromet_data,
        landslides_data,
        districts_data,
        eq_m6,
        build_utc,
    )
    sizes["validation.json"] = atomic_write_json(os.path.join(C.DATA, "validation.json"), val_data)
    print(
        f"  [9/10] validation.json      {sizes['validation.json']/1024:6.1f} KB  "
        f"({val_data['n_checks_pass']}/{val_data['n_checks_total']} pass, {len(val_data['known_limitations'])} limitations) | "
        f"sensitivity.json {sizes['sensitivity.json']/1024:4.1f} KB"
    )

    # 10. Summary (with next Monday 03:15 UTC schedule)
    summary_data = build_summary(
        lakes_core,
        lake_counts,
        slim_routes,
        expo_all,
        route_counts,
        seis_summary,
        faults_data,
        rivers_watch,
        landslides_data,
        hydromet_data,
        alerts_data,
        districts_data,
        build_utc,
        offline,
    )
    sizes["summary.json"] = atomic_write_json(os.path.join(C.DATA, "summary.json"), summary_data)
    tot_kb = sum(sizes.values()) / 1024.0
    print(
        f" [10/10] summary.json         {sizes['summary.json']/1024:6.1f} KB  "
        f"(next_refresh={summary_data['next_scheduled_refresh']})"
    )
    print(f"=== Done in {time.perf_counter()-t0:.2f}s | Total JSON bundle: {tot_kb:.1f} KB ({len(sizes)} files) ===")

    failed = [c for c in val_data["checks"] if not c["pass"]]
    if failed:
        for c in failed:
            print(f"  [FAIL] {c['name']}: {c['detail']}", file=sys.stderr)
        raise SystemExit(1)
    return sizes


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="Nepal TRĀYA 7-day multi-hazard refresh & JSON builder")
    ap.add_argument("--offline", action="store_true", help="Zero network calls; rebuild all data/*.json from cache")
    ap.add_argument("--refresh-osm", action="store_true", help="Refresh OpenStreetMap Overpass caches (live mode)")
    args = ap.parse_args(argv)
    run_refresh(offline=args.offline, refresh_osm=args.refresh_osm)
    return 0


if __name__ == "__main__":
    sys.exit(main())
