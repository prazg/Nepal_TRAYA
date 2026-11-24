"""
Unit tests for the Nepal TRAYA geohazard pipeline.

Supports two execution modes:
  * ``python src/test_pipeline.py --unit-only``: runs purely with Python 3.12
    stdlib (no numpy, scipy, geopandas, rasterio, shapely, or lit/*.rds needed).
  * ``python src/test_pipeline.py``: runs all stdlib unit tests PLUS full
    scientific stack tests (NumPy terrain parity, Veh et al. 2020 RDS depth
    posterior, piecewise dam-break scaling, continuous breach-fraction sampling).

Exit status is non-zero if any test fails.
"""
from __future__ import annotations
import argparse
from datetime import datetime, timezone
import json
import math
import os
import sys
import tempfile
import warnings
import xml.etree.ElementTree as ET

_HERE = os.path.dirname(os.path.abspath(__file__))
if _HERE not in sys.path:
    sys.path.insert(0, _HERE)

try:
    import numpy as np
except ImportError:
    np = None

import admin as AD
import build as BD
import cap_relay as CAP
import cascades as CAS
import config as C
import exposure as EX
import exposure_isolation as EI
import hazard as HZ
import hydromet as HM
import landslides as LS
import models_glof as MG
import moderation as MOD
import refresh_weekly as RW
import routing as RT
import seismic as SZ
import sensitivity as SN
import terrain as TR
import tsho_rolpa_2d_sim as TR2D
import validate as VL
from integrations import (
    bipad as BIPAD,
    copernicus as COP,
    dhm as DHM,
    nemrc as NEMRC,
    provenance as PROV,
    roads_authority as DOR,
)

FAILS: list[str] = []


def check(name: str, ok: bool, detail: str = "") -> None:
    print(f"  [{'PASS' if ok else 'FAIL'}] {name}" + (f" -- {detail}" if detail else ""))
    if not ok:
        FAILS.append(name)


# ---------------------------------------------------------------------------
# 1. Classification matrices & hazard flowchart (pure stdlib)
# ---------------------------------------------------------------------------
def test_risk_matrix():
    """The full 4x4 matrix as written out in Rounce et al. (2016) Sect. 4.2,
    which follows the ranking scheme of Worni et al. (2013)."""
    L, M, H, V = "low", "moderate", "high", "very high"
    expected = {
        (L, L): L, (L, M): L, (L, H): M, (L, V): M,
        (M, L): L, (M, M): M, (M, H): M, (M, V): H,
        (H, L): M, (H, M): M, (H, H): H, (H, V): H,
        (V, L): M, (V, M): H, (V, H): H, (V, V): V,
    }
    bad = [(h, i, HZ.risk(h, i), e) for (h, i), e in expected.items()
           if HZ.risk(h, i) != e]
    check("risk matrix matches the published scheme in all 16 cells", not bad,
          f"{len(bad)} mismatches" + (f": {bad}" if bad else ""))


def test_hazard_flowchart():
    """Rounce et al. (2016) Fig. 4 including (dyn='low', sdf='high') == 'high'."""
    cases = [
        # avalanche, rockfall, upstream, sla_steep, ice_cored, expected
        (False, False, False, False, None, "low"),
        (False, True,  False, False, None, "moderate"),
        (False, False, True,  False, None, "moderate"),
        (False, False, False, True,  None, "moderate"),
        (False, False, False, False, True, "moderate"),
        (False, False, False, True,  True, "high"),      # dyn='low', sdf='high' -> 'high'
        (True,  False, False, False, None, "high"),
        (True,  False, False, True,  None, "very high"),
        (False, True,  False, True,  None, "very high"),
        (True,  False, False, False, True, "very high"),
        (False, True,  False, False, True, "very high"),
    ]
    bad = [(c, HZ.overall_hazard(*c[:5])) for c in cases
           if HZ.overall_hazard(*c[:5]) != c[5]]
    check("hazard flow chart, general reading (incl. dyn='low', sdf='high' -> 'high')",
          not bad, f"{len(bad)} mismatches" + (f": {bad}" if bad else ""))

    # Exhaustive check across all 32 boolean combinations: general >= enumerated
    inv_violations = []
    for ava in (False, True):
        for rock in (False, True):
            for ups in (False, True):
                for sla in (False, True):
                    for ice in (False, True):
                        g = HZ.overall_hazard(ava, rock, ups, sla, ice)
                        e = HZ.overall_hazard_enumerated(ava, rock, ups, sla, ice)
                        if HZ.ORDER[g] < HZ.ORDER[e]:
                            inv_violations.append(((ava, rock, ups, sla, ice), g, e))
    check("general hazard reading is never less conservative than enumerated reading (32/32)",
          not inv_violations, str(inv_violations))

    alt = [
        (False, False, False, False, None, "low"),
        (False, True,  False, False, None, "moderate"),
        (False, False, False, False, True, "moderate"),
        (False, False, False, True,  True, "high"),
        (True,  False, False, False, None, "high"),
        (False, True,  False, False, True, "high"),
        (False, True,  False, True,  None, "moderate"),
        (True,  False, False, False, True, "very high"),
    ]
    bad2 = [(c, HZ.overall_hazard_enumerated(*c[:5])) for c in alt
            if HZ.overall_hazard_enumerated(*c[:5]) != c[5]]
    check("hazard flow chart, enumerated reading", not bad2,
          f"{len(bad2)} mismatches" + (f": {bad2}" if bad2 else ""))


def test_impact_classes():
    cases = [((0, 0, 0, 0), "low"), ((0, 0, 3, 0), "moderate"),
             ((5, 0, 2, 0), "high"), ((0, 1, 0, 0), "high"),
             ((5, 1, 2, 1), "very high"), ((0, 0, 0, 1), "high")]
    bad = [(a, HZ.downstream_impact(*a)) for a, e in cases
           if HZ.downstream_impact(*a) != e]
    check("downstream impact classes follow Table 4", not bad, str(bad))


# ---------------------------------------------------------------------------
# 2. GLOF volume, Fujita formulas, and unbiased breach rates (pure stdlib)
# ---------------------------------------------------------------------------
def test_volume_algebra():
    """The ellipsoid-cap formula must be exact at both ends: no breach releases
    nothing, a full-depth breach releases the whole lake."""
    a = 1.0e6
    depths = [50.0, 120.0]
    v_total = [MG.total_volume(a, d) for d in depths]
    v0_none = [MG.released_volume(a, d, 0.0) for d in depths]
    v0_full = [MG.released_volume(a, d, d) for d in depths]
    check("no breach releases no water",
          all(abs(v) < 1e-6 for v in v0_none),
          f"max {max(abs(v) for v in v0_none):.3e} m3")
    check("a full-depth breach releases the whole lake",
          all(math.isclose(vf, vt, rel_tol=1e-9) for vf, vt in zip(v0_full, v_total)),
          f"max rel err {max(abs(vf/vt - 1.0) for vf, vt in zip(v0_full, v_total)):.2e}")
    check("half-ellipsoid volume equals (2/3) A d",
          all(math.isclose(vt, (2.0 / 3.0) * a * d, rel_tol=1e-12)
              for vt, d in zip(v_total, depths)))
    fracs = [i / 20.0 for i in range(21)]
    vols = [MG.released_volume(a, 100.0, f * 100.0) for f in fracs]
    mono = all(vols[i] <= vols[i + 1] + 1e-9 for i in range(len(vols) - 1))
    check("released volume increases monotonically with breach depth", mono)


def test_fujita_formulas():
    """Fujita et al. (2013) Table 1: Dm = 55 A^0.25 and PFV = min[Hp, Dm] A."""
    table = [("Nagma", 0.66, 60, 50, 32.8), ("Dig", 0.34, 21, 42, 7.1),
             ("Lugge", 1.14, 13, 57, 14.9), ("Sabai/Tam", 0.38, 52, 43, 16.3),
             ("Unnamed", 0.46, 16, 45, 7.2)]
    dm_err = max(abs(TR.mean_depth_fujita(a) - dm) for _, a, _, dm, _ in table)
    pfv_err = max(abs(TR.pfv_fujita(a, hp) / 1e6 - pfv) for _, a, hp, _, pfv in table)
    check("Dm reproduces Fujita et al. (2013) Table 1", dm_err <= 0.6,
          f"max error {dm_err:.2f} m")
    check("PFV reproduces Fujita et al. (2013) Table 1", pfv_err <= 0.3,
          f"max error {pfv_err:.2f} Mm3")


def test_breach_rates():
    meanlog, sdlog, kmax = MG.breach_rate_lognormal()
    rates = list(C.PUBLISHED_BREACH_RATES)
    lk = [math.log(v) for v in rates]
    mu_exp = sum(lk) / len(lk)
    sd_ddof1 = math.sqrt(sum((v - mu_exp) ** 2 for v in lk) / (len(lk) - 1))
    sd_ddof0 = math.sqrt(sum((v - mu_exp) ** 2 for v in lk) / len(lk))
    check("all 19 published breach rates are present", len(rates) == 19)
    check("breach-rate lognormal uses unbiased sample sd (ddof=1, n=19)",
          math.isclose(meanlog, mu_exp, rel_tol=1e-12)
          and math.isclose(sdlog, sd_ddof1, rel_tol=1e-12)
          and sdlog > sd_ddof0
          and math.isclose(kmax, max(rates) * 2.0, rel_tol=1e-12),
          f"sdlog={sdlog:.5f} (ddof=1) vs {sd_ddof0:.5f} (ddof=0)")


# ---------------------------------------------------------------------------
# 3. Terrain: Horn (1981) slope, Barnes Priority-Flood+eps, coupled D8 (stdlib)
# ---------------------------------------------------------------------------
def test_horn_slope_and_cells():
    """Verify true 3x3 Horn (1981) weighted finite difference and transform spacing."""
    dxm, dym = 27.0, 31.0
    n = 12
    for true_deg in (10.0, 30.0, 45.0, 60.0):
        g = math.tan(math.radians(true_deg))
        z = [[c * dxm * g for c in range(n)] for _ in range(n)]
        s = TR.slope_deg(z, dxm, dym)
        interior = [s[r][c] for r in range(2, n - 2) for c in range(2, n - 2)]
        mean_s = sum(interior) / len(interior)
        if abs(mean_s - true_deg) > 1e-6:
            check(f"Horn slope of a {true_deg} deg plane", False, f"got {mean_s:.6f}")
            return
    check("Horn (1981) slope is exact on anisotropic constant-gradient planes", True,
          "tested at 10, 30, 45 and 60 degrees with dx=27m, dy=31m")

    # Distinguish true Horn 3x3 [1,2,1] weights from plain central difference [0,1,0]:
    # Only the NE corner is raised by +10 m; central difference gives 0 deg, Horn gives 60.504 deg.
    patch = [
        [0.0, 0.0, 10.0],
        [0.0, 0.0,  0.0],
        [0.0, 0.0,  0.0],
    ]
    s_center = TR.slope_deg(patch, 1.0, 1.0)[1][1]
    expected_horn = math.degrees(math.atan(math.hypot(10.0 / 8.0, -10.0 / 8.0)))
    check("slope_deg uses true 3x3 Horn weights (not plain 1D central difference)",
          math.isclose(s_center, expected_horn, rel_tol=1e-9),
          f"centre={s_center:.4f} deg vs expected {expected_horn:.4f} deg")

    class _MockTransform:
        a = 1.0 / 1800.0    # 2-arcsec E-W
        e = -1.0 / 3600.0   # 1-arcsec N-S

    dx2, dy2 = TR.cell_metres_from_transform(_MockTransform(), 28.0)
    dx1, dy1 = TR.cell_metres(28.0, 1.0 / 3600.0)
    check("cell_metres_from_transform reads actual affine (a, e) spacing",
          math.isclose(dx2, 2.0 * dx1, rel_tol=1e-12)
          and math.isclose(dy2, dy1, rel_tol=1e-12)
          and 26 < dx1 < 29 and 30 < dy1 < 32,
          f"1-arcsec=({dx1:.1f}m, {dy1:.1f}m), transform=({dx2:.1f}m, {dy2:.1f}m)")


def test_coupled_flat_fill_and_d8_connectivity():
    """Coupled Barnes Priority-Flood+eps + D8 routing at 5,000 m Himalayan elevation.

    Creates a sloped valley draining south into a lake with a deep closed glacier
    pit mid-slope. Previously, flat depression filling left zero-gradient flats
    where D8 terminated (recv = -1), severing the upper glacier headwall from the
    lake. Priority-Flood+eps in float64 must route every upslope cell continuously
    through the filled pit into the lake.
    """
    rows, cols = 25, 15
    # Valley trough sloping down toward row 24 (5000 m at bottom -> 5240 m at top)
    # with gentle lateral banks so water stays in the valley channel.
    dem = []
    for r in range(rows):
        row = []
        for c in range(cols):
            bank = abs(c - 7) * 4.0
            elev = 5000.0 + (rows - 1 - r) * 10.0 + bank
            row.append(elev)
        dem.append(row)

    # Lake at bottom of valley (rows 22..24, cols 5..9)
    lake = [[(r >= 22 and 5 <= c <= 9) for c in range(cols)] for r in range(rows)]
    z_lake = 5000.0
    for r in range(rows):
        for c in range(cols):
            if lake[r][c]:
                dem[r][c] = z_lake

    # Carve a deep closed supraglacial pit (rows 10..15, cols 5..9) 40 m below its rim!
    for r in range(10, 16):
        for c in range(5, 10):
            dem[r][c] -= 40.0

    filled = TR.fill_depressions(dem, sink_mask=lake)

    # Verify fill never lowers terrain
    never_lowered = all(
        filled[r][c] >= dem[r][c] - 1e-12
        for r in range(rows) for c in range(cols)
    )
    check("Priority-Flood+eps never lowers terrain", never_lowered)

    # Verify float64 preserves strict 1e-5 m epsilon gradient inside the pit at 5000+ m
    pit_grad_ok = filled[12][7] > filled[14][7] > filled[15][7]
    check("float64 Priority-Flood+eps preserves monotonic gradient through 5,000 m pit",
          pit_grad_ok,
          f"z[12,7]={filled[12][7]:.6f} > z[14,7]={filled[14][7]:.6f} > z[15,7]={filled[15][7]:.6f}")

    drains, plen = TR.d8_route_to_lake(filled, lake, 30.0, 30.0)

    # Every centreline cell from the upper headwall (rows 1..9) through the pit
    # (rows 10..15) down to the lake (row 22) must drain continuously to the lake!
    headwall_drains = all(drains[r][7] for r in range(1, 10))
    pit_drains = all(drains[r][7] for r in range(10, 16))
    check("coupled flat-fill + D8 routes upper headwall through closed pit into lake",
          headwall_drains and pit_drains,
          f"headwall_connected={sum(drains[r][7] for r in range(1, 10))}/9, "
          f"pit_connected={sum(drains[r][7] for r in range(10, 16))}/6")

    # Path length must increase monotonically moving upslope along the centreline
    plens = [plen[r][7] for r in range(21, 0, -1)]
    mono_len = all(math.isfinite(v) for v in plens) and all(
        plens[i + 1] > plens[i] for i in range(len(plens) - 1)
    )
    check("routed path length increases monotonically through filled pit to headwall",
          mono_len, f"range {min(plens):.0f}--{max(plens):.0f} m")

    # Standalone pit on flat 100 m surface (compatibility check)
    flat = [[100.0 for _ in range(20)] for _ in range(20)]
    for r in range(8, 12):
        for c in range(8, 12):
            flat[r][c] = 80.0
    ff = TR.fill_depressions(flat)
    check("standalone depression fill removes closed pit within 1e-3 m",
          math.isclose(ff[9][9], 100.0, abs_tol=1e-3) and ff[9][9] > 100.0,
          f"pit raised from 80.0 to {ff[9][9]:.6f}")


def test_avalanche_reach_bounds():
    """Verify Huggel (2004) threshold & bounded representative slab parameters."""
    a_small = TR.avalanche_reach_threshold_deg(1.0e5)
    a_large = TR.avalanche_reach_threshold_deg(1.0e7)
    check("Huggel reach angle decreases with volume and floors at 17 deg",
          a_small > a_large and math.isclose(a_large, C.REACH_ANGLE_AVALANCHE, rel_tol=1e-9),
          f"1e5 m3 -> {a_small:.1f} deg, 1e7 m3 -> {a_large:.1f} deg")
    check("bounded avalanche slab thickness and 10/30/50 m scenarios configured",
          C.AVALANCHE_REPRESENTATIVE_DEPTH_M == 15.0
          and C.AVALANCHE_DEPTHS_M == (10.0, 30.0, 50.0)
          and C.AVALANCHE_SLAB_AREA_CAP_M2 > 0,
          f"rep={C.AVALANCHE_REPRESENTATIVE_DEPTH_M}m, scenarios={C.AVALANCHE_DEPTHS_M}")


# ---------------------------------------------------------------------------
# 4. Routing, point-to-segment distance, UTM zones, cascade detection (stdlib)
# ---------------------------------------------------------------------------
def test_point_to_segment_distance():
    """An exposure object 333 m off the midpoint of a 10 km segment (5 km from
    both vertices) must be captured with exact perpendicular distance and
    projected along-channel chainage."""
    # Straight east-west river segment (~9.85 km long) with only 2 vertices
    river_coords = [(86.000, 27.800), (86.100, 27.800)]
    # 0.003 deg north of midpoint ~ 332.5 m perpendicular, ~4.93 km from either vertex
    expo = [
        dict(kind="hydropower", name="Upper Tamakoshi HPP (synthetic)",
             lon=86.050, lat=27.803),
        dict(kind="places", name="Far Hilltop Village",
             lon=86.050, lat=27.815),   # ~1.66 km away -> outside 1 km corridor
    ]
    hits = BD.nearest_exposure_on_coords(river_coords, expo, corridor_m=1000.0)
    dx_m, dy_m = TR.cell_metres(27.800, 1.0)
    exp_chain_km = 0.050 * dx_m / 1000.0
    exp_offset_m = 0.003 * dy_m
    ok = (
        len(hits) == 1
        and hits[0][0] == 0
        and math.isclose(hits[0][1], exp_chain_km, rel_tol=1e-4)
        and math.isclose(hits[0][2], exp_offset_m, rel_tol=1e-4)
    )
    check("point-to-segment distance captures mid-segment HPP missed by vertex matching",
          ok,
          f"hits={hits}, expected chainage={exp_chain_km:.3f} km, offset={exp_offset_m:.1f} m")


def test_same_reach_upstream_glof():
    """Twin-lake cascades on the same HydroRIVERS reach (e.g. Aug 2024 Thame
    Upper/Lower Ngole Cho) must flag upstream_glof on the lower lake."""
    lake_reach = {
        "upper_ngole": 1001,
        "lower_ngole": 1001,
        "downstream_lake": 1002,
        "isolated_lake": 2001,
    }
    lake_elev = {
        "upper_ngole": 4789.1,
        "lower_ngole": 4749.0,
        "downstream_lake": 4653.2,
        "isolated_lake": 4900.0,
    }
    up_map = {1001: [], 1002: [(1001, 2.5)], 2001: []}
    res = BD.detect_upstream_glof(lake_reach, lake_elev, lambda r: up_map.get(r, []))
    ok = (
        res["upper_ngole"] is False
        and res["lower_ngole"] is True
        and res["downstream_lake"] is True
        and res["isolated_lake"] is False
    )
    check("same-reach upstream_glof detects twin-lake cascades", ok, str(res))


def test_utm_zone_selection():
    check("UTM zone selects EPSG:32644 west of 84 E and EPSG:32645 east of 84 E",
          BD.utm_epsg_for_lon(80.5) == 32644
          and BD.utm_epsg_for_lon(83.99) == 32644
          and BD.utm_epsg_for_lon(84.0) == 32645
          and BD.utm_epsg_for_lon(86.92) == 32645)


def test_glof_history_fallback():
    """Missing HMAGLOFDB_v4.csv falls back to raw/glof.geojson with warning;
    missing both raises FileNotFoundError."""
    raw_geojson = os.path.join(C.RAW, "glof.geojson")
    missing_csv = os.path.join(C.RAW, "__nonexistent_HMAGLOFDB_v4.csv")
    if os.path.exists(raw_geojson):
        with warnings.catch_warnings(record=True) as caught:
            warnings.simplefilter("always")
            recs, meta = BD.load_glof_history(csv_path=missing_csv,
                                              fallback_geojson=raw_geojson)
        ok = (len(recs) > 0 and meta["fallback_used"] is True
              and meta["source"] == "glof.geojson" and len(caught) >= 1)
        check("missing HMAGLOFDB_v4.csv falls back to raw/glof.geojson with warning",
              ok, f"{len(recs)} records from {meta['source']}")
    raised = False
    try:
        BD.load_glof_history(csv_path=missing_csv,
                             fallback_geojson=os.path.join(C.RAW, "__nonexistent_glof.geojson"))
    except FileNotFoundError:
        raised = True
    check("missing both GLOF sources raises FileNotFoundError instead of silent []", raised)


# ---------------------------------------------------------------------------
# 5. Seismic haversine antipodal clamping & exact UTC year (stdlib)
# ---------------------------------------------------------------------------
def test_haversine_antipodal_and_utc_year():
    d_anti1 = SZ.haversine_km(0.0, 0.0, 180.0, 0.0)
    d_anti2 = SZ.haversine_km(85.324, 27.717, -94.676, -27.717)
    d_zero = SZ.haversine_km(86.925, 27.899, 86.925, 27.899)
    half_circ = math.pi * 6371.0088
    check("haversine_km clamps domain safely on antipodal points",
          math.isclose(d_anti1, half_circ, rel_tol=1e-9)
          and math.isclose(d_anti2, half_circ, rel_tol=1e-9)
          and d_zero == 0.0,
          f"antipodal={d_anti2:.2f} km, half_circ={half_circ:.2f} km")

    # Exact UTC calendar year across Jan 1 boundary & pre-1970 (1934 Bihar-Nepal eq)
    ms_1934 = (datetime(1934, 1, 15, 8, 43, 25, tzinfo=timezone.utc)
               - datetime(1970, 1, 1, tzinfo=timezone.utc)).total_seconds() * 1000.0
    ms_2024_end = datetime(2024, 12, 31, 23, 59, 59, tzinfo=timezone.utc).timestamp() * 1000.0
    ms_2025_start = datetime(2025, 1, 1, 0, 0, 0, tzinfo=timezone.utc).timestamp() * 1000.0
    yrs = (SZ.utc_year_from_ms(ms_1934),
           SZ.utc_year_from_ms(ms_2024_end),
           SZ.utc_year_from_ms(ms_2025_start))
    check("seismic UTC calendar year is exact across pre-1970 and year boundaries",
          yrs == (1934, 2024, 2025), f"got {yrs}")


# ---------------------------------------------------------------------------
# 6. Admin normalization, inner rings, validation & sensitivity helpers (stdlib)
# ---------------------------------------------------------------------------
def test_admin_normalization_and_holes():
    norm_ok = (
        AD.normalize_province_name("Bagamati Province") == "Bagmati Province"
        and AD.normalize_province_name("  Bagamati  ") == "Bagmati Province"
        and AD.normalize_province_name("Province No. 1") == "Koshi Province"
        and AD.normalize_province_name("Bagmati Province") == "Bagmati Province"
    )
    check("admin normalizes Bagamati Province -> Bagmati Province", norm_ok)

    # Pure-stdlib polygon with inner hole ring: centre (5, 5) is inside hole -> excluded
    donut = AD._PureGeoPolygon({
        "type": "Polygon",
        "coordinates": [
            [[0, 0], [10, 0], [10, 10], [0, 10], [0, 0]],
            [[3, 3], [7, 3], [7, 7], [3, 7], [3, 3]],
        ],
    })
    check("admin polygon preserves inner rings (holes excluded)",
          donut.contains_xy(1.0, 1.0) and not donut.contains_xy(5.0, 5.0))

    if os.path.exists(AD.PRIMARY_CACHE):
        ix = AD.AdminIndex()
        provs = sorted(n for n, _ in ix.levels["4"])
        ktm_p = ix.province(85.324, 27.717)
        imja_p = ix.province(86.923, 27.899)
        thul_p = ix.province(84.485, 28.488)
        ok = (
            len(provs) == 7
            and len(ix.levels["6"]) == 77
            and "Bagmati Province" in provs
            and "Bagamati Province" not in provs
            and ktm_p == "Bagmati Province"
            and imja_p == "Koshi Province"
            and thul_p == "Gandaki Province"
        )
        check("AdminIndex loads cache/nepal_admin.json with 7 canonical provinces and 77 districts",
              ok, f"Kathmandu={ktm_p}, Imja={imja_p}, Thulagi={thul_p}")


def test_validate_and_sensitivity_helpers():
    poly = {"type": "Polygon", "coordinates": [[[85.0, 27.0], [85.1, 27.0], [85.1, 27.1], [85.0, 27.0]]]}
    mpoly = {
        "type": "MultiPolygon",
        "coordinates": [
            [[[85.0, 27.0], [85.1, 27.0], [85.0, 27.1], [85.0, 27.0]]],
            [[[86.0, 27.8], [86.1, 27.8], [86.1, 27.9], [86.0, 27.9], [86.0, 27.8]]],
        ],
    }
    r1 = VL._exterior_ring(poly)
    r2 = VL._exterior_ring(mpoly)
    check("validate._exterior_ring handles Polygon and MultiPolygon safely",
          len(r1) == 4 and len(r2) == 5 and r2[0][0] == 86.0)

    ok_good, _ = VL.check_canonical_provinces(["Bagmati Province", "Koshi Province"])
    ok_bad, _ = VL.check_canonical_provinces(["Bagamati Province", "Koshi Province"])
    check("canonical province check accepts Bagmati Province and rejects Bagamati Province",
          ok_good and not ok_bad)

    # Physical GloFAS sanity check must reject mis-snapped off-mainstem discharges
    good_rivers = {
        "basins": [
            {"id": bid, "climatology": {
                "q50": lo50 * 2.0, "q90": lo2 * 0.6, "q99": lo2 * 0.95,
                "q2": lo2 * 1.5, "q5": lo2 * 2.2, "q20": lo2 * 3.0,
            }}
            for bid, (lo50, lo2) in C.GLOFAS_BASIN_SANITY_BOUNDS.items()
        ]
    }
    bad_rivers = {
        "basins": [
            (
                {"id": "karnali", "climatology": {
                    "q50": 0.5, "q90": 6.7, "q99": 16.1,
                    "q2": 17.8, "q5": 34.4, "q20": 56.0,
                }}
                if b["id"] == "karnali" else b
            )
            for b in good_rivers["basins"]
        ]
    }
    g_ok, _, _ = VL.check_glofas_sanity(good_rivers)
    b_ok, _, b_issues = VL.check_glofas_sanity(bad_rivers)
    check("GloFAS sanity bounds accept mainstem flows and flag off-mainstem Karnali snap",
          g_ok and not b_ok and any("karnali" in s for s in b_issues),
          b_issues[0] if b_issues else "")

    # Sensitivity Hp-limited ratio statistics must reveal shifts even when >50% are Dm-capped
    ref = {
        "dm1": dict(sla_km2=0.2, hp_m=80.0, dm_m=40.0, hp_limited=False, pfv_Mm3=20.0, avalanche=False, rockfall=False),
        "dm2": dict(sla_km2=0.2, hp_m=90.0, dm_m=40.0, hp_limited=False, pfv_Mm3=20.0, avalanche=False, rockfall=False),
        "dm3": dict(sla_km2=0.2, hp_m=70.0, dm_m=40.0, hp_limited=False, pfv_Mm3=20.0, avalanche=False, rockfall=False),
        "hp1": dict(sla_km2=0.1, hp_m=10.0, dm_m=40.0, hp_limited=True,  pfv_Mm3=5.0,  avalanche=False, rockfall=False),
        "hp2": dict(sla_km2=0.1, hp_m=20.0, dm_m=40.0, hp_limited=True,  pfv_Mm3=10.0, avalanche=False, rockfall=False),
    }
    var = {
        "dm1": dict(ref["dm1"]),
        "dm2": dict(ref["dm2"]),
        "dm3": dict(ref["dm3"]),
        "hp1": dict(ref["hp1"], hp_m=15.0, pfv_Mm3=7.5),
        "hp2": dict(ref["hp2"], hp_m=30.0, pfv_Mm3=15.0),
    }
    rows = SN.summarise({"ref": ref, "var": var}, "ref")
    vr = [r for r in rows if r["variant"] == "var"][0]
    check("sensitivity reports mean & IQR on Hp-limited lakes (unmasked from Dm-cap 1.0)",
          vr["median_ratio_to_reference"] == 1.0
          and vr["n_hp_limited"] == 2
          and math.isclose(vr["hp_limited_mean_ratio"], 1.5, rel_tol=1e-6)
          and vr["hp_limited_iqr_ratio"] == [1.5, 1.5],
          f"all_med={vr['median_ratio_to_reference']}, hp_mean={vr['hp_limited_mean_ratio']}, hp_iqr={vr['hp_limited_iqr_ratio']}")


def test_capacity_parser():
    cases = [("12.5 MW", 12.5), ("456 kW", 0.456), ("1 GW", 1000.0),
             ("2500000", 2.5), (None, None), ("not a number", None)]
    bad = [(v, EX._mw(v), e) for v, e in cases
           if (EX._mw(v) is None) != (e is None)
           or (e is not None and not math.isclose(EX._mw(v), e, rel_tol=1e-9))]
    check("hydropower capacity parser handles documented tag forms", not bad, str(bad))


def test_stable_seed():
    a = MG.stable_seed("GL_27.86029_86.47725")
    check("seeds are stable across processes and non-negative",
          a == MG.stable_seed("GL_27.86029_86.47725") and 0 <= a < 2 ** 31, str(a))


def test_travel_times():
    tt = RT.travel_times_min(6.0)
    check("travel_times_min brackets 2, 5, 10 m/s correctly",
          tt == {"v2": 50.0, "v5": 20.0, "v10": 10.0}, str(tt))


def test_lakes_core_compact_roundtrip():
    """Verify pack_lakes_core / unpack_lakes_core round-trips losslessly."""
    sample = {
        "type": "FeatureCollection",
        "features": [
            {
                "type": "Feature",
                "geometry": {
                    "type": "Polygon",
                    "coordinates": [[[86.4781, 27.8589], [86.4805, 27.8589], [86.4805, 27.8612], [86.4781, 27.8589]]],
                },
                "properties": {
                    "id": "GL_27.86029_86.47725",
                    "lon": 86.4781,
                    "lat": 27.8589,
                    "area_km2": 1.5421,
                    "z": 4546,
                    "typ": "moraine-dammed lake",
                    "prov": "Bagmati Province",
                    "district": "Dolakha",
                    "priority": True,
                    "avalanche": True,
                    "rockfall": False,
                    "hazard": "very high",
                    "hazard_enum": "very high",
                    "name": "Tsho Rolpa",
                    "ice_cored": True,
                    "route_km": 120.0,
                },
            },
            {
                "type": "Feature",
                "geometry": {
                    "type": "Polygon",
                    "coordinates": [[[81.6791, 30.1111], [81.6801, 30.1111], [81.6801, 30.1121], [81.6791, 30.1111]]],
                },
                "properties": {
                    "id": "GL_30.1111_81.67915",
                    "lon": 81.6791,
                    "lat": 30.1111,
                    "area_km2": 0.0266,
                    "z": 4254,
                    "typ": "unconnected glacial lake",
                    "prov": "Karnali Province",
                    "district": "Humla",
                    "priority": False,
                    "avalanche": False,
                    "rockfall": True,
                    "hazard": "moderate",
                    "hazard_enum": "moderate",
                },
            },
        ],
    }
    packed = RW.pack_lakes_core(sample)
    unpacked = RW.unpack_lakes_core(packed)
    ok = (
        packed["format"] == RW.LAKES_COMPACT_FORMAT
        and unpacked == sample
    )
    check("lakes_core compact pack/unpack round-trips losslessly", ok,
          f"format={packed['format']}, n={packed['n_lakes']}")


def test_hydromet_hourly_and_rain_basis():
    """Verify hydromet extracts hourly freezing level / soil moisture and honest rain_basis."""
    adm = HM.StdlibAdminLookup()
    spec = HM.SENTINEL_NODES[0]
    days = [f"2026-11-{d:02d}" for d in range(12, 24)]
    item_rain = {
        "elevation": 1800.0,
        "daily": {
            "time": days,
            "precipitation_sum": [10.0] * 12,
            "rain_sum": [8.0] * 12,
            "snowfall_sum": [2.0] * 12,
            "temperature_2m_max": [15.0] * 12,
        },
        "hourly": {
            "freezinglevel_height": [4200.0] * (12 * 24),
            "soil_moisture_0_to_7cm": [0.345] * (12 * 24),
        },
    }
    n1 = HM._build_live_node(spec, item_rain, adm)
    item_fallback = {
        "elevation": 1800.0,
        "daily": {
            "time": days,
            "precipitation_sum": [10.0] * 12,
            "snowfall_sum": [3.0] * 12,
            "temperature_2m_max": [12.0] * 12,
        },
        "hourly": {
            "freezinglevel_height": [3900.0] * (12 * 24),
            "soil_moisture_0_to_7cm": [0.250] * (12 * 24),
        },
    }
    n2 = HM._build_live_node(spec, item_fallback, adm)
    ok = (
        n1["rain_basis"] == "daily_rain_sum"
        and n1["freezing_level_m"] == 4200.0
        and n1["soil_moisture_m3m3"] == 0.345
        and n2["rain_basis"] == "live_precip_minus_swe"
        and math.isclose(n2["rain_past_7d_mm"], 49.0, rel_tol=1e-6)
        and n2["freezing_level_m"] == 3900.0
        and n2["soil_moisture_m3m3"] == 0.250
    )
    check("hydromet extracts hourly freezing/soil fields and sets honest rain_basis", ok,
          f"rain={n1['rain_basis']}/{n1['freezing_level_m']}m/{n1['soil_moisture_m3m3']}, fb={n2['rain_basis']}/{n2['rain_past_7d_mm']}mm")


# ---------------------------------------------------------------------------
# 7. TRĀYA 2.0 pure-stdlib unit tests (Provenance, BIPAD, Landslides,
#    Road-Cut Hospital Isolation, Multi-Hazard Cascades & Sentinel-1 SAR)
# ---------------------------------------------------------------------------
def test_provenance_envelope_and_manifest():
    """Verify 6-state ProvenanceEnvelope validation, SLA evaluation, manifest
    health roll-up with institutional stubs, KPI baseline & Markdown summary."""
    build_iso = "2026-11-23T12:00:00Z"
    created = []
    for dc in PROV.VALID_DATA_CLASSES:
        env = PROV.make_envelope(
            source="UnitTest Source",
            dataset=f"ds_{dc}",
            data_class=dc,
            retrieved_at_utc=build_iso,
            status="unavailable" if dc == "unavailable" else "available",
            license_ref="CC-BY-4.0",
            sla_hours=168,
            record_count=0 if dc == "unavailable" else 5,
        )
        created.append(env)
    check(
        "ProvenanceEnvelope accepts all 6 canonical data_class states",
        len(created) == 6 and {e["data_class"] for e in created} == set(PROV.VALID_DATA_CLASSES),
        str(PROV.VALID_DATA_CLASSES),
    )

    rejected_dc = False
    try:
        PROV.make_envelope("S", "D", "bogus_class", build_iso, license_ref="MIT")
    except ValueError:
        rejected_dc = True
    rejected_st = False
    try:
        PROV.make_envelope("S", "D", "cached", build_iso, status="broken", license_ref="MIT")
    except ValueError:
        rejected_st = True
    check(
        "ProvenanceEnvelope rejects invalid data_class and status values",
        rejected_dc and rejected_st,
        f"rejected_dc={rejected_dc}, rejected_st={rejected_st}",
    )

    # SLA evaluation: fresh vs expired forecast vs aged-past-SLA vs unavailable
    ev_fresh = PROV.evaluate_envelope_sla(
        {"status": "available", "data_class": "forecast", "retrieved_at_utc": "2026-11-23T06:00:00Z",
         "valid_until_utc": "2026-11-26T00:00:00Z", "sla_hours": 168},
        ref_utc=build_iso,
    )
    ev_expired = PROV.evaluate_envelope_sla(
        {"status": "available", "data_class": "forecast", "retrieved_at_utc": "2026-11-20T06:00:00Z",
         "valid_until_utc": "2026-11-22T23:59:59Z", "sla_hours": 168},
        ref_utc=build_iso,
    )
    ev_aged = PROV.evaluate_envelope_sla(
        {"status": "available", "data_class": "cached", "retrieved_at_utc": "2026-11-10T00:00:00Z",
         "sla_hours": 168},
        ref_utc=build_iso,
    )
    ev_unavail = PROV.evaluate_envelope_sla(
        {"status": "unavailable", "data_class": "unavailable", "retrieved_at_utc": build_iso,
         "sla_hours": 168},
        ref_utc=build_iso,
    )
    check(
        "evaluate_envelope_sla distinguishes fresh, expired forecast, stale SLA & unavailable",
        ev_fresh["within_sla"] is True
        and ev_fresh["effective_status"] == "available"
        and ev_expired["within_sla"] is False
        and ev_expired["effective_status"] == "stale"
        and ev_expired["expired"] is True
        and ev_aged["within_sla"] is False
        and ev_aged["effective_status"] == "stale"
        and ev_unavail["effective_status"] == "unavailable",
        f"fresh={ev_fresh['effective_status']}, exp={ev_expired['effective_status']}, aged={ev_aged['effective_status']}",
    )

    # Manifest health ignores institutional stubs (DHM, NEMRC, DoR) when operational feeds are healthy
    op_env = PROV.make_envelope(
        source="Open-Meteo",
        dataset="openmeteo_test",
        data_class="forecast",
        retrieved_at_utc=build_iso,
        valid_until_utc="2026-11-27T23:59:59Z",
        status="available",
        fallback_used=False,
        license_ref="CC-BY-4.0",
        sla_hours=168,
        record_count=24,
    )
    envelopes = [
        op_env,
        DHM.get_provenance(build_iso),
        NEMRC.get_provenance(build_iso),
        DOR.get_provenance(build_iso),
    ]
    with tempfile.TemporaryDirectory() as tmpd:
        mf = PROV.build_manifest(tmpd, envelopes, build_iso, git_sha="deadbeef", write=False)
        kpi = PROV.build_kpi_baseline(tmpd, mf, {"n_provinces": 7, "n_districts": 77}, None, None, None, write=False)
        md = PROV.format_step_summary_markdown(mf, kpi)
    check(
        "build_manifest keeps overall_health='healthy' with 3 institutional stubs & formats step summary",
        mf["overall_health"] == "healthy"
        and mf["source_counts"]["operational"] == 1
        and mf["source_counts"]["institutional_stubs"] == 3
        and kpi["feed_freshness_pct"] == 100.0
        and kpi["provenance_completeness_pct"] == 100.0
        and "## Nepal TRĀYA 2.0" in md
        and "openmeteo_test" in md,
        f"health={mf['overall_health']}, stubs={mf['source_counts']['institutional_stubs']}, freshness={kpi['feed_freshness_pct']}%",
    )


def test_bipad_record_normalization():
    """Verify BIPAD v1 parser preserves verified 0 vs null (NEVER coerces None -> 0),
    filters empty river stations, and degrades gracefully offline without cache."""
    verified_zero_raw = {
        "id": 96552,
        "title": "Landslide at Pachaljharana Rural Municipality-3",
        "titleNe": "कर्णाली, कालिकोट, पचालझरना-३ मा पहिरो",
        "incidentOn": "2026-11-19T00:00:00+05:45",
        "reportedOn": "2026-11-20T10:33:04+05:45",
        "point": {"type": "Point", "coordinates": [81.74506, 29.21559]},
        "hazard": 17,
        "verified": True,
        "approved": True,
        "loss": {
            "id": 491281,
            "peopleDeathCount": 0,
            "peopleInjuredCount": 0,
            "peopleMissingCount": None,
            "familyAffectedCount": 0,
            "estimatedLoss": None,
        },
        "source": "other",
    }
    null_loss_raw = {
        "id": 96999,
        "title": "Unverified slope slip report",
        "incidentOn": "2026-11-20T06:00:00+05:45",
        "point": {"type": "Point", "coordinates": [86.16, 27.74]},
        "hazard": 17,
        "verified": False,
        "loss": None,
    }
    p_ver = BIPAD.parse_landslide_incident(verified_zero_raw)
    p_null = BIPAD.parse_landslide_incident(null_loss_raw)
    ok_bipad = (
        p_ver["peopleDeathCount"] == 0
        and p_ver["peopleInjuredCount"] == 0
        and p_ver["peopleMissingCount"] is None
        and p_ver["estimatedLoss"] is None
        and p_ver["verified"] is True
        and p_ver["date"] == "2026-11-19"
        and p_null["loss"] is None
        and p_null["peopleDeathCount"] is None
        and p_null["peopleInjuredCount"] is None
        and p_null["estimatedLoss"] is None
    )
    check(
        "BIPAD incident normalization preserves verified 0 and strict None (never None -> 0)",
        ok_bipad,
        f"ver=(death={p_ver['peopleDeathCount']}, missing={p_ver['peopleMissingCount']}), null=(death={p_null['peopleDeathCount']})",
    )

    # Cross-check with landslides.parse_bipad_incident: verified=True keeps 0; verified=False maps 0 -> None
    ls_ver = LS.parse_bipad_incident(verified_zero_raw)
    ls_unver_zero = LS.parse_bipad_incident({
        **verified_zero_raw,
        "id": 96553,
        "verified": False,
    })
    check(
        "landslides.parse_bipad_incident allows 0 only when verified=True and enforces null when verified=False",
        ls_ver is not None
        and ls_ver["feature_type"] == "landslide_event"
        and ls_ver["fatalities"] == 0
        and ls_ver["injuries"] == 0
        and ls_ver["households_affected"] == 0
        and ls_unver_zero is not None
        and ls_unver_zero["feature_type"] == "hazard_report"
        and ls_unver_zero["fatalities"] is None
        and ls_unver_zero["injuries"] is None
        and ls_unver_zero["households_affected"] is None
        and not LS.validate_landslide_record(ls_ver)
        and not LS.validate_landslide_record(ls_unver_zero),
        f"ver_ft={ls_ver['feature_type']}/fat={ls_ver['fatalities']}, unver_ft={ls_unver_zero['feature_type']}/fat={ls_unver_zero['fatalities']}",
    )

    # Verify landslides.py live BIPAD endpoint requests expand=loss and shares cache/bipad_snapshot.json
    check(
        "landslides.py requests BIPAD expand=loss and aligns CACHE_BIPAD with bipad_snapshot.json",
        "expand=loss" in LS.BIPAD_LANDSLIDE_URL
        and os.path.normpath(LS.CACHE_BIPAD) == os.path.normpath(BIPAD.CACHE_BIPAD),
        f"url={LS.BIPAD_LANDSLIDE_URL}, cache={os.path.basename(LS.CACHE_BIPAD)}",
    )

    # Verify build_landslides exact-ID dedup keeps verified 0 casualty detail over unexpanded int-FK loss
    unexp_raw = dict(verified_zero_raw, loss=491281)
    ls_unexp = LS.parse_bipad_incident(unexp_raw)
    with tempfile.TemporaryDirectory() as tmpd:
        res_dedup = LS.build_landslides(
            offline=True,
            out_path=os.path.join(tmpd, "landslides.json"),
            review_queue_path=os.path.join(tmpd, "rq.json"),
            geojson_path=os.path.join(tmpd, "ls.geojson"),
            extra_records=[ls_unexp, ls_ver],
        )
    rec_96552 = next((e for e in res_dedup["events"] if e["id"] == "bipad_96552"), None)
    check(
        "build_landslides preserves expanded verified-zero casualty fields over unexpanded FK duplicate",
        ls_unexp is not None
        and ls_unexp["fatalities"] is None
        and rec_96552 is not None
        and rec_96552["fatalities"] == 0
        and rec_96552["injuries"] == 0
        and rec_96552["households_affected"] == 0,
        f"rec_96552={(rec_96552 or {}).get('fatalities')}/{(rec_96552 or {}).get('injuries')}/{(rec_96552 or {}).get('households_affected')}",
    )

    # River station filtering (null waterLevel + null waterLevelOn dropped) & rain intervals
    empty_riv = BIPAD.parse_river({"id": 1, "title": "Empty", "waterLevel": None, "waterLevelOn": None})
    valid_riv = BIPAD.parse_river({
        "id": 2, "title": "Lohare Khola", "basin": "Karnali",
        "waterLevel": 2.478, "warningLevel": 4.0, "dangerLevel": None,
        "waterLevelOn": "2026-11-22T08:50:00+05:45", "status": "BELOW WARNING LEVEL",
        "point": {"type": "Point", "coordinates": [81.5842, 28.7845]},
    })
    rain_rec = BIPAD.parse_rain({
        "id": 3, "title": "Dumkauli", "measuredOn": "2026-11-23T06:00:00+05:45",
        "point": {"type": "Point", "coordinates": [84.2285, 27.6807]},
        "averages": [
            {"interval": 1, "value": 2.5, "status": {"warning": False, "danger": False}},
            {"interval": 24, "value": 42.0, "status": {"warning": False, "danger": False}},
        ],
    })
    with tempfile.TemporaryDirectory() as tmpd:
        missing_snap = BIPAD.fetch_bipad_snapshot(
            offline=True, cache_path=os.path.join(tmpd, "missing_bipad.json")
        )
    check(
        "BIPAD filters null river telemetry, parses rain intervals & degrades cleanly offline",
        empty_riv is None
        and valid_riv is not None
        and valid_riv["waterLevel"] == 2.478
        and valid_riv["dangerLevel"] is None
        and rain_rec["rain_1h_mm"] == 2.5
        and rain_rec["rain_24h_mm"] == 42.0
        and rain_rec["rain_6h_mm"] is None
        and missing_snap["provenance"]["data_class"] == "unavailable"
        and missing_snap["provenance"]["status"] == "unavailable",
        f"riv_ok={valid_riv is not None}, rain24={rain_rec['rain_24h_mm']}, offline={missing_snap['provenance']['data_class']}",
    )


def test_landslides_5type_and_duplicate_matcher():
    """Verify strict 5-type landslide partitioning, null-not-0 schema validation,
    and flag-only duplicate-candidate matching (never auto-merged)."""
    raw_five = [
        # 1. landslide_event (dated verified BIPAD)
        {
            "id": "bipad_1001", "provider_id": "bipad_ndrrma", "source": "BIPAD Portal (NDRRMA)",
            "title": "Sindhupalchok highway landslide", "event_date_utc": "2026-08-12T04:00:00Z",
            "lon": 85.8800, "lat": 27.8000, "district": "Sindhupalchok", "province": "Bagmati Province",
            "trigger": "heavy rainfall", "fatalities": 0, "injuries": 2, "verified": True,
            "evidence_url": "https://bipadportal.gov.np/api/v1/incident/1001/",
        },
        # 2. landslide_scar (undated OSM — must force null date & null casualties even if 0 passed!)
        {
            "id": "osm_n5001", "provider_id": "osm_overpass", "source": "OpenStreetMap",
            "title": "Mapped scar near Araniko Highway", "event_date_utc": "2020-01-01",
            "lon": 85.8810, "lat": 27.8005, "district": "Sindhupalchok", "province": "Bagmati Province",
            "fatalities": 0, "injuries": 0, "verified": True,
            "evidence_url": "https://www.openstreetmap.org/node/5001",
        },
        # 3. susceptibility_zone
        {
            "id": "static_2001", "provider_id": "traya_static", "source": "TRĀYA Susceptibility Screening",
            "title": "Steep colluvial corridor", "event_date_utc": None,
            "lon": 86.1600, "lat": 27.7400, "district": "Dolakha", "province": "Bagmati Province",
            "trigger": "terrain susceptibility", "fatalities": None, "verified": False,
        },
        # 4. hazard_report (unverified community report — 0 must coerce to None)
        {
            "id": "comm_3001", "provider_id": "community_field", "source": "Community Report",
            "title": "Unverified slope crack report", "event_date_utc": "2026-08-13",
            "lon": 84.4200, "lat": 28.2200, "district": "Lamjung", "province": "Gandaki Province",
            "trigger": "rainfall", "fatalities": 0, "verified": False,
        },
        # 5. coseismic_failure (earthquake-triggered)
        {
            "id": "usgs_4001", "provider_id": "usgs_ground_failure", "source": "USGS Ground Failure",
            "title": "Coseismic rockslide cluster", "event_date_utc": "2026-08-15T10:00:00Z",
            "lon": 82.1200, "lat": 28.9500, "district": "Jajarkot", "province": "Karnali Province",
            "trigger": "earthquake shaking", "fatalities": 3, "verified": False,
        },
    ]
    normed = [LS.normalize_record(r) for r in raw_five]
    types_got = [r["feature_type"] for r in normed if r is not None]
    val_errs = [LS.validate_landslide_record(r) for r in normed if r is not None]
    scar = normed[1]
    report = normed[3]
    check(
        "5-type landslide partitioning enforces schema & null-not-0 invariants",
        types_got == [
            "landslide_event",
            "landslide_scar",
            "susceptibility_zone",
            "hazard_report",
            "coseismic_failure",
        ]
        and all(len(e) == 0 for e in val_errs)
        and scar["event_date_utc"] is None
        and scar["date_precision"] == "unknown"
        and scar["fatalities"] is None
        and scar["verified"] is False
        and report["fatalities"] is None,
        f"types={types_got}",
    )

    # Confirm validator rejects illegal unverified fatalities=0
    bad_rec = dict(report, fatalities=0)
    bad_errs = LS.validate_landslide_record(bad_rec)
    check(
        "validate_landslide_record rejects unverified record with fatalities=0",
        any("null-not-0" in e for e in bad_errs),
        str(bad_errs),
    )

    # Duplicate-candidate matcher tests
    coolr_near = LS.normalize_record({
        "id": "coolr_9001", "provider_id": "nasa_coolr", "source": "NASA COOLR",
        "title": "Sindhupalchok Araniko highway landslide", "event_date_utc": "2026-08-13T08:00:00Z",
        "lon": 85.8830, "lat": 27.8020, "district": "Sindhupalchok", "province": "Bagmati Province",
        "trigger": "rainfall", "fatalities": 1, "verified": False,
    })
    coolr_old = LS.normalize_record({
        "id": "coolr_9002", "provider_id": "nasa_coolr", "source": "NASA COOLR",
        "title": "Old historical slide same slope", "event_date_utc": "2026-07-01T00:00:00Z",
        "lon": 85.8805, "lat": 27.8002, "district": "Sindhupalchok", "province": "Bagmati Province",
        "trigger": "rainfall", "verified": False,
    })
    osm_twin = LS.normalize_record({
        "id": "osm_n5002", "provider_id": "osm_overpass", "source": "OpenStreetMap",
        "title": "Adjacent OSM scar", "event_date_utc": None,
        "lon": 85.8812, "lat": 27.8006, "district": "Sindhupalchok", "province": "Bagmati Province",
    })
    cands = LS.find_duplicate_candidates(
        [normed[0], scar, coolr_near, coolr_old, osm_twin],
        max_km=1.5,
        max_days=3,
        undated_cross_source_max_km=0.35,
    )
    pair_reasons = {(c["record_a_id"], c["record_b_id"]): c["reason"] for c in cands}
    ok_dups = (
        pair_reasons.get(("bipad_1001", "coolr_9001")) == "dated_cross_source_spatiotemporal_proximity"
        and pair_reasons.get(("bipad_1001", "osm_n5001")) == "undated_cross_source_spatial_proximity"
        and ("bipad_1001", "coolr_9002") not in pair_reasons
        and ("osm_n5001", "osm_n5002") not in pair_reasons
        and all(c["review_status"] == "pending_review" and c["auto_merged"] is False for c in cands)
    )
    check(
        "duplicate-candidate matcher flags dated & undated cross-source pairs without auto-merging",
        ok_dups,
        f"{len(cands)} candidates: {sorted(pair_reasons.items())}",
    )


def test_road_cut_hospital_isolation():
    """Verify road-cut hospital isolation detects downstream_bridge_cut and
    cross_river_bridge_cut, filters veterinary clinics & bridge=no, deduplicates
    hydropower MW within 250 m, and preserves published GLOF hazard classes."""
    with tempfile.TemporaryDirectory() as tmpd:
        ov_dir = os.path.join(tmpd, "overpass")
        os.makedirs(ov_dir, exist_ok=True)
        lakes_fc = {
            "type": "FeatureCollection",
            "features": [
                {
                    "type": "Feature",
                    "geometry": {"type": "Point", "coordinates": [86.10, 27.80]},
                    "properties": {
                        "id": "GL_SYNTH_1",
                        "name": "Synthetic Alpine Lake",
                        "district": "Dolakha",
                        "prov": "Bagmati Province",
                        "hazard": "very high",
                        "hazard_enum": "high",
                        "impact": "high",
                        "risk": "very high",
                        "priority": True,
                        "pfv_Mm3": 25.0,
                        "ice_cored": True,
                    },
                }
            ],
        }
        routes = {
            "GL_SYNTH_1": {
                "km": 15.0,
                "path": [[86.10, 27.80], [86.25, 27.80]],
                "exp": [],
            }
        }
        districts_doc = {
            "districts": [
                {"name": "Dolakha", "name_ne": "दोलखा", "prov": "Bagmati Province", "prov_ne": "बागमती प्रदेश"}
            ]
        }
        places_ov = {
            "elements": [
                # Upstream of bridge & hospital -> downstream_bridge_cut
                {"type": "node", "id": 1, "lon": 86.12, "lat": 27.801, "tags": {"name": "Upper Village", "place": "village"}},
                # South bank across river from hospital at north bank -> cross_river_bridge_cut
                {"type": "node", "id": 2, "lon": 86.19, "lat": 27.798, "tags": {"name": "South Bank Hamlet", "place": "hamlet"}},
            ]
        }
        health_ov = {
            "elements": [
                # Real human hospital on north bank downstream of bridge
                {"type": "node", "id": 10, "lon": 86.19, "lat": 27.801, "tags": {"name": "Valley District Hospital", "amenity": "hospital"}},
                # Veterinary facility right next to Upper Village — MUST be excluded!
                {"type": "node", "id": 11, "lon": 86.1201, "lat": 27.801, "tags": {"name": "Animal Veterinary Hospital", "amenity": "hospital"}},
            ]
        }
        bridges_ov = {
            "elements": [
                {"type": "node", "id": 20, "lon": 86.15, "lat": 27.800, "tags": {"name": "Main Valley Bridge", "highway": "primary", "bridge": "yes"}},
                # Explicitly tagged bridge=no — MUST be excluded!
                {"type": "node", "id": 21, "lon": 86.16, "lat": 27.800, "tags": {"name": "Not A Bridge", "highway": "primary", "bridge": "no"}},
            ]
        }
        hydro_ov = {
            "elements": [
                # Plant + generator 100 m apart -> must count 100.0 MW once, not 200.0 MW
                {"type": "node", "id": 30, "lon": 86.1700, "lat": 27.800, "tags": {"name": "Valley HPP", "power": "plant", "plant:output:electricity": "100 MW"}},
                {"type": "node", "id": 31, "lon": 86.1708, "lat": 27.800, "tags": {"name": "Valley HPP Unit", "power": "generator", "generator:output:electricity": "100 MW"}},
            ]
        }

        def _wj(p, obj):
            with open(p, "w", encoding="utf-8") as fh:
                json.dump(obj, fh)

        lakes_p = os.path.join(tmpd, "lakes_core.json")
        routes_p = os.path.join(tmpd, "routes.json")
        expo_p = os.path.join(tmpd, "exposure.json")
        dist_p = os.path.join(tmpd, "districts.json")
        out_p = os.path.join(tmpd, "exposure_isolation.json")
        _wj(lakes_p, lakes_fc)
        _wj(routes_p, routes)
        _wj(expo_p, [])
        _wj(dist_p, districts_doc)
        _wj(os.path.join(ov_dir, "places.json"), places_ov)
        _wj(os.path.join(ov_dir, "health.json"), health_ov)
        _wj(os.path.join(ov_dir, "bridges.json"), bridges_ov)
        _wj(os.path.join(ov_dir, "hydropower.json"), hydro_ov)

        res = EI.build_exposure_isolation(
            lakes_path=lakes_p,
            routes_path=routes_p,
            exposure_path=expo_p,
            districts_path=dist_p,
            overpass_dir=ov_dir,
            out_path=out_p,
        )

    lk = res["lakes"]["GL_SYNTH_1"]
    corr = lk["corridor_exposure_screening"]
    iso = lk["road_cut_hospital_isolation"]
    mechs = {ex["name"]: ex["mechanism"] for ex in iso["isolated_settlement_examples"]}
    ok = (
        lk["hazard_susceptibility_static"]["hazard"] == "very high"
        and res["uncertainty_and_coverage_limits"]["published_hazard_classes_modified"] is False
        and corr["hospitals"] == 1
        and corr["health_facilities"] == 1
        and corr["bridges"] == 1
        and corr["vehicular_bridges"] == 1
        and math.isclose(corr["hydropower_mw_tagged"], 100.0, rel_tol=1e-6)
        and iso["upstream_settlements_potentially_isolated"] == 2
        and mechs.get("Upper Village") == "downstream_bridge_cut"
        and mechs.get("South Bank Hamlet") == "cross_river_bridge_cut"
    )
    check(
        "road-cut hospital isolation identifies bridge/cross-river cuts, filters non-human health & deduplicates MW",
        ok,
        f"isolated={iso['upstream_settlements_potentially_isolated']}, mechs={mechs}, mw={corr['hydropower_mw_tagged']}",
    )


def test_cascade_graph_evaluation():
    """Verify rule-based cascade graph evaluation across baseline (undated scar
    exclusion), rainfall+landslide+river Chain 1, seismic Chain 2, and thermal Chain 3."""
    now = datetime(2026, 11, 23, 12, 0, 0, tzinfo=timezone.utc)
    lakes_fc = {
        "type": "FeatureCollection",
        "features": [
            {
                "type": "Feature",
                "geometry": {"type": "Point", "coordinates": [86.4772, 27.8603]},
                "properties": {
                    "id": "GL_27.86029_86.47725",
                    "name": "Tsho Rolpa",
                    "lon": 86.4772,
                    "lat": 27.8603,
                    "district": "Dolakha",
                    "prov": "Bagmati Province",
                    "hazard": "very high",
                    "priority": True,
                    "ice_cored": True,
                },
            }
        ],
    }
    expo_iso = {
        "lakes": {
            "GL_27.86029_86.47725": {
                "lake_id": "GL_27.86029_86.47725",
                "traversed_districts": ["Dolakha", "Ramechhap"],
                "hazard_susceptibility_static": {
                    "hazard": "very high",
                    "priority": True,
                    "ice_cored": True,
                },
                "road_cut_hospital_isolation": {"corridor_disruption_risk": "high"},
            }
        },
        "districts": [
            {
                "name": "Dolakha",
                "prov": "Bagmati Province",
                "unique_bridges_at_crossings": 89,
                "hydropower_mw_exposed": 456.0,
                "unique_settlements_potentially_isolated": 13,
                "district_isolation_risk": "high",
                "top_corridor_lake_ids": ["GL_27.86029_86.47725"],
            }
        ],
    }
    quiet_rivers = {"basins": [{"id": "koshi", "name": "Koshi", "district": "Dolakha", "status_now": "normal", "status_14d": "normal"}]}
    quiet_hm = {
        "nodes": [{"id": "n1", "district": "Dolakha", "dh_obs": {"max_ratio": 0.1}, "dh_combined": {"max_ratio": 0.2}}],
        "priority_lakes": [{"id": "GL_27.86029_86.47725", "district": "Dolakha", "warm_rain_on_ice": False}],
    }
    scars_only = {
        "counts_by_type": {"landslide_scar": 50},
        "events": [
            {"id": f"osm_n{i}", "feature_type": "landslide_scar", "event_date_utc": None, "district": "Dolakha"}
            for i in range(50)
        ],
    }

    # 1. Baseline quiet: undated OSM scars must NOT trigger Chain 1
    g_base = CAS.evaluate_cascades(quiet_rivers, quiet_hm, scars_only, lakes_fc, expo_iso, now_utc=now)
    c3_scn = next((s for s in g_base["active_scenarios"] if s["chain_id"] == "glof_infra_isolation"), None)
    check(
        "cascade graph excludes undated OSM scars and labels standing GLOF as static_susceptibility_watch",
        g_base["chains"]["rain_landslide_dam_road"]["dynamic_active"] is False
        and g_base["chains"]["quake_coseismic_isolation"]["dynamic_active"] is False
        and g_base["chains"]["glof_infra_isolation"]["dynamic_active"] is False
        and c3_scn is not None
        and c3_scn["status"] == "static_susceptibility_watch"
        and all(e["evidence_type"] in {"observed", "forecast", "modelled_static"} for e in g_base["edges"]),
        f"active_dynamic_scenarios={g_base['summary']['n_active_dynamic_scenarios']}, highest={g_base['summary']['highest_severity']}",
    )

    # 2. Chain 1 active: DH exceedance + recent dated landslide + elevated river -> critical
    hot_rivers = {"basins": [{"id": "koshi", "name": "Koshi", "district": "Dolakha", "status_now": "q5_warning", "status_14d": "q5_warning"}]}
    hot_hm = {
        "nodes": [{"id": "n1", "district": "Dolakha", "dh_obs": {"max_ratio": 1.3}, "dh_combined": {"max_ratio": 1.5}}],
        "priority_lakes": [{"id": "GL_27.86029_86.47725", "district": "Dolakha", "warm_rain_on_ice": True}],
    }
    dated_ls = {
        "counts_by_type": {"landslide_event": 1, "landslide_scar": 50},
        "events": [
            {"id": "bipad_777", "feature_type": "landslide_event", "event_date_utc": "2026-11-21T06:00:00Z", "district": "Dolakha"}
        ],
    }
    recent_eq = [
        {"id": "usgs_eq1", "source": "USGS FDSN", "mag": 5.8, "lon": 86.40, "lat": 27.80, "place": "Dolakha", "time_utc": "2026-11-22T02:00:00Z"}
    ]
    g_hot = CAS.evaluate_cascades(
        hot_rivers, hot_hm, dated_ls, lakes_fc, expo_iso, live_usgs=recent_eq, now_utc=now
    )
    edges_by_id = {e["rule_id"]: e for e in g_hot["edges"]}
    check(
        "cascade graph activates all 3 dynamic chains with rule evidence & bilingual summaries",
        g_hot["chains"]["rain_landslide_dam_road"]["dynamic_active"] is True
        and g_hot["chains"]["rain_landslide_dam_road"]["severity"] == "critical"
        and g_hot["chains"]["quake_coseismic_isolation"]["dynamic_active"] is True
        and g_hot["chains"]["glof_infra_isolation"]["dynamic_active"] is True
        and all(edges_by_id[rid]["active"] is True for rid in ("RLDR-01", "RLDR-02", "RLDR-03", "QCI-01", "QCI-02", "GII-02"))
        and all(ch.get("summary_en") and ch.get("summary_ne") for ch in g_hot["chains"].values()),
        f"active_edges={g_hot['summary']['n_active_edges']}/{g_hot['summary']['n_edges']}, dynamic_scenarios={g_hot['summary']['n_active_dynamic_scenarios']}",
    )

    # 3. BIPAD `dhm_rivers` WARNING/DANGER gauges activate RLDR-01; BELOW WARNING LEVEL does not
    bipad_river_warn = {
        "provenance": {"retrieved_at_utc": "2026-11-23T11:30:00Z"},
        "alerts": [],
        "landslide_incidents": [],
        "dhm_rivers": [
            {"id": 1, "title": "Normal Gauge", "basin": "Koshi", "status": "BELOW WARNING LEVEL"},
            {"id": 2, "title": "Tama Koshi Gauge", "basin": "Koshi", "status": "WARNING LEVEL"},
        ],
    }
    watch_hm = {
        "nodes": [{"id": "n1", "district": "Dolakha", "dh_obs": {"max_ratio": 0.65}, "dh_combined": {"max_ratio": 0.70}}],
        "priority_lakes": [{"id": "GL_27.86029_86.47725", "district": "Dolakha", "warm_rain_on_ice": False}],
    }
    g_bipad_rv = CAS.evaluate_cascades(
        quiet_rivers, watch_hm, scars_only, lakes_fc, expo_iso, bipad=bipad_river_warn, now_utc=now
    )
    rv_edges = {e["rule_id"]: e for e in g_bipad_rv["edges"]}
    rv_nodes = {n["id"]: n for n in g_bipad_rv["nodes"]}
    check(
        "cascade graph wires BIPAD dhm_rivers WARNING/DANGER gauges into river_warnings and RLDR-01",
        rv_nodes["c1_debris_dam_valley_flood"]["metrics"]["n_bipad_river_warnings"] == 1
        and rv_edges["RLDR-01"]["active"] is True
        and "Tama Koshi Gauge" in rv_edges["RLDR-01"]["supporting_evidence"].get("bipad_river_warnings", []),
        f"warnings={rv_nodes['c1_debris_dam_valley_flood']['metrics']['n_bipad_river_warnings']}, RLDR-01={rv_edges['RLDR-01']['active']}",
    )

    # 4. Distant M>=4.5 earthquake (>100 km from high-hazard lakes/steep corridors) must NOT emit
    #    a contradictory active_dynamic SCN-QUAKE-COSEISMIC-ISOLATION with active_rule_ids=[]
    distant_eq = [
        {"id": "usgs_far", "source": "USGS FDSN", "mag": 5.2, "lon": 80.50, "lat": 26.50, "place": "Far southwest", "time_utc": "2026-11-22T02:00:00Z"}
    ]
    g_far_eq = CAS.evaluate_cascades(
        quiet_rivers, quiet_hm, scars_only, lakes_fc, expo_iso, live_usgs=distant_eq, now_utc=now
    )
    far_c2_scn = next((s for s in g_far_eq["active_scenarios"] if s["chain_id"] == "quake_coseismic_isolation"), None)
    far_c2_ch = g_far_eq["chains"]["quake_coseismic_isolation"]
    check(
        "distant M>=4.5 quake (>100 km) does not emit active_dynamic scenario with empty active_rule_ids",
        far_c2_scn is None
        and far_c2_ch["dynamic_active"] is False
        and far_c2_ch["severity"] == "baseline"
        and "No active seismic-coseismic isolation cascade" in far_c2_ch["summary_en"],
        f"scenario={far_c2_scn is not None}, sev={far_c2_ch['severity']}",
    )

    # 5. build_cascades() reads bipad_official.json provenance.retrieved_at_utc
    with tempfile.TemporaryDirectory() as tmpd:
        with open(os.path.join(tmpd, "bipad_official.json"), "w", encoding="utf-8") as fh:
            json.dump(bipad_river_warn, fh)
        built = CAS.build_cascades(offline=True, out_path=os.path.join(tmpd, "cascades.json"), data_dir=tmpd)
        bipad_src = next((s for s in built["provenance"]["sources"] if s.get("provider_id") == "bipad_ndrrma"), {})
        check(
            "build_cascades populates bipad_ndrrma updated_utc from provenance.retrieved_at_utc",
            bipad_src.get("updated_utc") == "2026-11-23T11:30:00Z",
            f"updated_utc={bipad_src.get('updated_utc')!r}",
        )


def test_ui_contrast_severity_and_csp_alignment():
    """Verify WCAG 2.1 AA light-theme --ok contrast, cascade severity UI mapping,
    and STAC_THUMB_HOSTS <-> CSP img-src alignment."""
    import re

    root = C.ROOT
    with open(os.path.join(root, "assets", "style.css"), encoding="utf-8") as fh:
        css = fh.read()
    with open(os.path.join(root, "assets", "app.js"), encoding="utf-8") as fh:
        app_js = fh.read()
    with open(os.path.join(root, "index.html"), encoding="utf-8") as fh:
        index_html = fh.read()
    with open(os.path.join(root, "src", "template.html"), encoding="utf-8") as fh:
        tmpl_html = fh.read()

    # 1. Light-theme --ok contrast over --ok-bg on --panel (#ffffff) and --panel2 (#f4f7fb)
    m_light = re.search(r'html\[data-theme="light"\]\s*\{([^}]+)\}', css)
    light_block = m_light.group(1) if m_light else ""
    m_ok = re.search(r"--ok\s*:\s*#([0-9a-fA-F]{6})", light_block)
    m_ok_bg = re.search(r"--ok-bg\s*:\s*rgba\(\s*(\d+)\s*,\s*(\d+)\s*,\s*(\d+)\s*,\s*([0-9.]+)\s*\)", light_block)
    ok_contrast_pass = False
    c_panel = c_panel2 = 0.0
    if m_ok and m_ok_bg:
        hx = m_ok.group(1)
        fg = tuple(int(hx[i:i + 2], 16) for i in (0, 2, 4))
        bg_c = (int(m_ok_bg.group(1)), int(m_ok_bg.group(2)), int(m_ok_bg.group(3)))
        alpha = float(m_ok_bg.group(4))

        def _lin(ch: float) -> float:
            v = ch / 255.0
            return v / 12.92 if v <= 0.04045 else ((v + 0.055) / 1.055) ** 2.4

        def _cr(rgb1: tuple[float, float, float], rgb2: tuple[float, float, float]) -> float:
            l1 = 0.2126 * _lin(rgb1[0]) + 0.7152 * _lin(rgb1[1]) + 0.0722 * _lin(rgb1[2])
            l2 = 0.2126 * _lin(rgb2[0]) + 0.7152 * _lin(rgb2[1]) + 0.0722 * _lin(rgb2[2])
            return (max(l1, l2) + 0.05) / (min(l1, l2) + 0.05)

        def _blend(base: tuple[int, int, int]) -> tuple[float, float, float]:
            return (
                bg_c[0] * alpha + base[0] * (1.0 - alpha),
                bg_c[1] * alpha + base[1] * (1.0 - alpha),
                bg_c[2] * alpha + base[2] * (1.0 - alpha),
            )

        c_panel = _cr(fg, _blend((255, 255, 255)))
        c_panel2 = _cr(fg, _blend((244, 247, 251)))
        ok_contrast_pass = c_panel >= 4.5 and c_panel2 >= 4.5
    check(
        "light-theme --ok over --ok-bg meets WCAG 2.1 AA >= 4.5:1 on --panel and --panel2",
        ok_contrast_pass,
        f"panel={c_panel:.2f}:1, panel2={c_panel2:.2f}:1",
    )

    # 2. Cascade UI severity mapping covers all cascades.py levels without legacy 'alert' check
    ok_sev_ui = (
        "severity === 'alert'" not in app_js
        and "badgeCascadeSeverity" in app_js
        and "cascadeCardSeverityClass" in app_js
        and "s === 'critical'" in app_js
        and "s === 'high'" in app_js
        and "s === 'moderate' || s === 'watch'" in app_js
    )
    check(
        "tabCascades maps critical/high/moderate/watch/baseline without legacy severity==='alert'",
        ok_sev_ui,
        "explicit cascade severity helpers verified in assets/app.js",
    )

    # 3. STAC_THUMB_HOSTS entries are all covered by CSP img-src in index.html & src/template.html
    m_hosts = re.search(r"const\s+STAC_THUMB_HOSTS\s*=\s*\[([^\]]+)\]", app_js)
    thumb_hosts = re.findall(r"['\"]([^'\"]+)['\"]", m_hosts.group(1)) if m_hosts else []
    m_csp = re.search(r"img-src\s+([^;\"]+)", index_html)
    img_src_tokens = m_csp.group(1).split() if m_csp else []

    def _host_allowed(host: str) -> bool:
        for tok in img_src_tokens:
            if tok == f"https://{host}":
                return True
            if tok.startswith("https://*."):
                suffix = tok[len("https://*"):]  # e.g. ".amazonaws.com"
                if host.endswith(suffix):
                    return True
        return False

    unaligned = [h for h in thumb_hosts if not _host_allowed(h)]
    check(
        "STAC_THUMB_HOSTS aligns with CSP img-src in byte-identical index.html and src/template.html",
        bool(thumb_hosts) and not unaligned and index_html == tmpl_html,
        f"hosts={thumb_hosts}, unaligned={unaligned}",
    )

    # 4. Light-theme active .prazg-suite-bar link (>= 4.5:1 AA) and .sym-* glyphs (>= 4.5:1 / SC 1.4.11)
    def _lin_srgb(ch: float) -> float:
        v = ch / 255.0
        return v / 12.92 if v <= 0.04045 else ((v + 0.055) / 1.055) ** 2.4

    def _hex_rgb(hx: str) -> tuple[int, int, int]:
        h = hx.lstrip("#")
        return (int(h[0:2], 16), int(h[2:4], 16), int(h[4:6], 16))

    def _contrast(rgb1: tuple[float, float, float], rgb2: tuple[float, float, float]) -> float:
        l1 = 0.2126 * _lin_srgb(rgb1[0]) + 0.7152 * _lin_srgb(rgb1[1]) + 0.0722 * _lin_srgb(rgb1[2])
        l2 = 0.2126 * _lin_srgb(rgb2[0]) + 0.7152 * _lin_srgb(rgb2[1]) + 0.0722 * _lin_srgb(rgb2[2])
        return (max(l1, l2) + 0.05) / (min(l1, l2) + 0.05)

    m_acc = re.search(r"--accent\s*:\s*(#[0-9a-fA-F]{6})", light_block)
    m_suite_rule = re.search(
        r'html\[data-theme="light"\]\s+\.prazg-suite-bar\s+a\[aria-current="page"\][^{]*\{([^}]+)\}',
        css,
    )
    suite_cr = 0.0
    if m_acc and m_suite_rule:
        sblock = m_suite_rule.group(1)
        bg_tok = re.search(r"background\s*:\s*([^;]+);", sblock)
        fg_tok = re.search(r"(?<![-\w])color\s*:\s*([^;]+);", sblock)
        if bg_tok and fg_tok:
            bg_val = bg_tok.group(1).strip()
            fg_val = fg_tok.group(1).strip()
            bg_hex = m_acc.group(1) if bg_val == "var(--accent)" else bg_val
            fg_hex = m_acc.group(1) if fg_val == "var(--accent)" else fg_val
            if re.fullmatch(r"#[0-9a-fA-F]{6}", bg_hex) and re.fullmatch(r"#[0-9a-fA-F]{6}", fg_hex):
                suite_cr = _contrast(_hex_rgb(fg_hex), _hex_rgb(bg_hex))

    base_syms = re.findall(r"^\.(sym-[a-z0-9]+)\s*\{\s*color\s*:\s*(#[0-9a-fA-F]{6})\s*;", css, re.M)
    light_syms = dict(
        re.findall(
            r'^html\[data-theme="light"\]\s+\.(sym-[a-z0-9]+)\s*\{\s*color\s*:\s*(#[0-9a-fA-F]{6})\s*;',
            css,
            re.M,
        )
    )
    min_sym_cr = 99.0
    missing_light_syms: list[str] = []
    for sname, _ in base_syms:
        if sname not in light_syms:
            missing_light_syms.append(sname)
        else:
            min_sym_cr = min(min_sym_cr, _contrast(_hex_rgb(light_syms[sname]), (255, 255, 255)))
    check(
        "light-theme active .prazg-suite-bar link & all .sym-* glyphs meet WCAG 2.1 AA (>= 4.5:1)",
        suite_cr >= 4.5 and bool(base_syms) and not missing_light_syms and min_sym_cr >= 4.5,
        f"suite_active={suite_cr:.2f}:1, syms={len(light_syms)}/{len(base_syms)}, min_sym={min_sym_cr:.2f}:1",
    )

    # 5. Basemap tileerror fallback guards baselayerchange, uses cross-provider chain & parameterized i18n
    with open(os.path.join(root, "assets", "i18n.js"), encoding="utf-8") as fh:
        i18n_js = fh.read()
    m_chain = re.search(r"const\s+BASEMAP_FALLBACK_CHAIN\s*=\s*\[([^\]]+)\]", app_js)
    chain_items = re.findall(r"['\"]([^'\"]+)['\"]", m_chain.group(1)) if m_chain else []
    fallback_notices = re.findall(r"basemapFallbackNotice\s*:\s*'([^']+)'", i18n_js)
    has_basemap_guard = (
        "let isAutoFallbackSwitching = false;" in app_js
        and "if (isAutoFallbackSwitching) return;" in app_js
        and "isAutoFallbackSwitching = true;" in app_js
        and "isAutoFallbackSwitching = false;" in app_js
        and "CARTO Voyager" in chain_items
        and "OpenStreetMap" in chain_items
        and "Esri World Topo" not in chain_items
        and "t('basemapFallbackNotice', { basemap: fallbackName })" in app_js
        and len(fallback_notices) == 6
        and all("{basemap}" in msg and "OpenStreetMap" not in msg for msg in fallback_notices)
    )
    check(
        "basemap tileerror fallback guards baselayerchange, crosses providers & formats all 6 i18n notices",
        has_basemap_guard,
        f"chain={chain_items}, i18n_notices={len(fallback_notices)}",
    )

    # 6. SECURITY.md documents strict-origin-when-cross-origin (zero stale no-referrer)
    with open(os.path.join(root, "SECURITY.md"), encoding="utf-8") as fh:
        sec_md = fh.read()
    sec_ref_ok = (
        '<meta name="referrer" content="strict-origin-when-cross-origin">' in sec_md
        and "no-referrer" not in sec_md.lower()
    )
    check(
        "SECURITY.md documents strict-origin-when-cross-origin with zero stale no-referrer",
        sec_ref_ok,
        "aligned with index.html and src/template.html",
    )


def test_copernicus_sentinel1_sar_parsing():
    """Verify Sentinel-1 GRD all-weather SAR STAC item parsing preserves polarizations & HTTPS URLs."""
    s1_item = {
        "id": "S1D_IW_GRDH_1SDV_20261123T001050",
        "properties": {
            "datetime": "2026-11-23T00:10:50.001609Z",
            "sat:orbit_state": "descending",
            "sar:instrument_mode": "IW",
            "sar:polarizations": ["VV", "VH"],
            "platform": "sentinel-1d",
        },
        "assets": {
            "thumbnail": {"href": "https://example.org/thumb.png"},
        },
    }
    parsed = COP.parse_sentinel1_item(s1_item, lon=86.4772, lat=27.8603)
    check(
        "Copernicus Sentinel-1 GRD parser extracts IW VV/VH SAR metadata & HTTPS browser URL",
        parsed["collection"] == "sentinel-1-grd"
        and parsed["platform"] == "sentinel-1d"
        and parsed["orbit_state"] == "descending"
        and parsed["instrument_mode"] == "IW"
        and parsed["polarizations"] == ["VV", "VH"]
        and parsed["all_weather_capability"] is True
        and str(parsed.get("copernicus_browser_url") or "").startswith("https://"),
        f"platform={parsed['platform']}, mode={parsed['instrument_mode']}, pols={parsed['polarizations']}",
    )


def test_bates_2d_shallow_water_solver():
    """Verify 2D Bates (2010) inertial shallow-water solver:
    1. Flat-water stillness (Lake-at-Rest C-property over uneven submerged bed);
    2. Exact mass conservation (< 1% error) on both closed and open-outflow valleys;
    3. Downhill floodwave propagation with strictly positive monotonic arrival times."""
    # 1. Lake-at-Rest stillness over non-flat submerged bathymetry
    n = 9
    eta0 = 100.0
    z_lake = [[110.0 for _ in range(n)] for _ in range(n)]
    h_lake = [[0.0 for _ in range(n)] for _ in range(n)]
    for r in range(1, n - 1):
        for c in range(1, n - 1):
            bed = 96.0 + (2.5 if (r == 4 and c == 4) else (1.2 if (r == 3 and c == 4) else 0.0))
            z_lake[r][c] = bed
            h_lake[r][c] = eta0 - bed

    still = TR2D.run_2d_solver_on_grid(
        z_lake,
        dx=50.0,
        dy=50.0,
        h_init_grid=h_lake,
        manning_n=0.05,
        duration_s=120.0,
    )
    max_v_still = max(v for row in still["v_max"] for v in row)
    max_dh_still = max(
        abs(still["h_final"][r][c] - h_lake[r][c])
        for r in range(n) for c in range(n)
    )
    check(
        "2D Bates solver preserves exact Lake-at-Rest flat-water stillness over uneven bed",
        max_v_still == 0.0
        and max_dh_still < 1e-12
        and still["mass_balance_error_pct"] < 1e-9,
        f"max_v={max_v_still:.3e} m/s, max_dh={max_dh_still:.3e} m, mb_err={still['mass_balance_error_pct']:.3e}%",
    )

    # 2. Sloped 2D valley channel with asymmetric gamma breach pulse (open outflow + closed check)
    rows, cols = 16, 7
    mid_c = cols // 2
    z_val = [
        [1000.0 - r * 5.0 + abs(c - mid_c) * 15.0 for c in range(cols)]
        for r in range(rows)
    ]
    tp_s, qp_eff, shape_m = TR2D.build_gamma_hydrograph_params(
        vol_m3=5.0e5, q_peak_m3s=350.0, duration_s=400.0
    )

    def _pulse(t_s: float) -> float:
        return TR2D.eval_gamma_hydrograph(t_s, tp_s, qp_eff, shape_m)

    sim_open = TR2D.run_2d_solver_on_grid(
        z_val,
        dx=50.0,
        dy=50.0,
        manning_n=0.055,
        inflow_cells=[(0, mid_c)],
        inflow_fn=_pulse,
        outflow_cells=[(rows - 1, c) for c in range(cols)],
        duration_s=400.0,
    )
    sim_closed = TR2D.run_2d_solver_on_grid(
        z_val,
        dx=50.0,
        dy=50.0,
        manning_n=0.055,
        inflow_cells=[(0, mid_c)],
        inflow_fn=_pulse,
        outflow_cells=[],
        duration_s=200.0,
    )
    min_h_open = min(h for row in sim_open["h_final"] for h in row)
    min_h_closed = min(h for row in sim_closed["h_final"] for h in row)
    check(
        "2D Bates solver conserves global mass (< 1% error) with non-negative depths",
        sim_open["volume_in_m3"] > 0.0
        and sim_open["volume_out_m3"] > 0.0
        and sim_open["mass_balance_error_pct"] < 1.0
        and sim_closed["mass_balance_error_pct"] < 1.0
        and sim_closed["volume_out_m3"] == 0.0
        and min_h_open >= 0.0
        and min_h_closed >= 0.0,
        f"open_err={sim_open['mass_balance_error_pct']:.5f}% (out={sim_open['volume_out_m3']:.0f} m3), "
        f"closed_err={sim_closed['mass_balance_error_pct']:.5f}%",
    )

    # 3. Downhill floodwave propagation & strictly increasing positive arrival times
    probe_rows = (2, 6, 10, 14)
    arr_times = [sim_open["t_arrival_s"][r][mid_c] for r in probe_rows]
    peak_depths = [sim_open["h_max"][r][mid_c] for r in probe_rows]
    max_vel = max(v for row in sim_open["v_max"] for v in row)
    strictly_increasing = all(t > 0.0 for t in arr_times) and all(
        arr_times[i] < arr_times[i + 1] for i in range(len(arr_times) - 1)
    )
    all_wet = all(d >= TR2D.WET_THRESHOLD_M for d in peak_depths)
    check(
        "2D Bates solver propagates wave downhill with strictly positive monotonic arrival times",
        strictly_increasing and all_wet and 0.0 < max_vel <= TR2D.MAX_VELOCITY_MS,
        f"t_arr(r={probe_rows})={[round(t, 1) for t in arr_times]}s, "
        f"h_max={[round(d, 2) for d in peak_depths]}m, max_v={max_vel:.2f} m/s",
    )


def test_community_moderation_engine():
    """Verify src/moderation.py PII redaction, EXIF-required rejection, unverified
    null-not-0 casualty lock, flag-only duplicate detection & authenticated role promotion."""
    # 1. Deterministic Nepal PII redaction + hotline/coord preservation + idempotence
    raw_pii = (
        "Slope slip at 27.8603, 86.4772 near Singati. Contact +977-9841234567 or 9801234567 "
        "or 01-4211234 or ९८४१२३४५६७, email field.observer@example.org, citizenship 27-01-74-01234, "
        "license 01-06-00123456, NID 123-456-789-0, handle @dolakha_scout. "
        "Official hotlines: 100, 102, 1114, 1149, 1155."
    )
    redacted, tags = MOD.redact_pii(raw_pii)
    redacted_again, tags_again = MOD.redact_pii(redacted)
    leaked_literals = [
        tok for tok in (
            "9841234567", "9801234567", "01-4211234", "९८४१२३४५६७",
            "field.observer@example.org", "27-01-74-01234", "01-06-00123456",
            "123-456-789-0", "@dolakha_scout",
        )
        if tok in redacted
    ]
    preserved_safe = all(
        tok in redacted for tok in ("27.8603", "86.4772", "100", "102", "1114", "1149", "1155")
    )
    check(
        "moderation.redact_pii strips Nepal phones/emails/IDs/handles, keeps hotlines & is idempotent",
        set(tags) == {"email", "phone", "id", "handle"}
        and not leaked_literals
        and preserved_safe
        and "[REDACTED_PHONE]" in redacted
        and "[REDACTED_EMAIL]" in redacted
        and "[REDACTED_ID]" in redacted
        and "[REDACTED_HANDLE]" in redacted
        and redacted_again == redacted
        and tags_again == [],
        f"tags={tags}, leaked={leaked_literals}",
    )

    # 2. EXIF-required, PII-leak & unverified zero-casualty validation rejections
    base_report = {
        "report_id": "cr_unit_dolakha_001",
        "feature_type": "hazard_report",
        "moderation_status": "pending_agency_review",
        "captured_at_utc": "2026-11-23T08:00:00Z",
        "event_date_utc": "2026-11-23T06:00:00Z",
        "time_precision": "exact_hour",
        "location_source": "gps",
        "lon": 86.1652,
        "lat": 27.7164,
        "district": "Dolakha",
        "province": "Bagmati Province",
        "trigger": "rainfall",
        "road_blocked": True,
        "fatalities": None,
        "injuries": None,
        "description_redacted": redacted,
        "photo_attached": True,
        "exif_stripped": True,
        "dedup_fingerprint": MOD.compute_dedup_fingerprint(86.1652, 27.7164, "2026-11-23T06:00:00Z", "rainfall"),
        "pii_redaction_applied": True,
    }
    errs_valid = MOD.validate_community_report(base_report)
    errs_no_exif = MOD.validate_community_report({**base_report, "exif_stripped": False})
    errs_zero_fat = MOD.validate_community_report({**base_report, "fatalities": 0})
    errs_zero_inj = MOD.validate_community_report({**base_report, "injuries": 0})
    errs_pii_leak = MOD.validate_community_report({**base_report, "description_redacted": "Call 9841234567"})
    check(
        "moderation.validate_community_report enforces EXIF stripping, PII scrubbing & unverified null-not-0",
        errs_valid == []
        and any("exif_stripped" in e for e in errs_no_exif)
        and any("null-not-0" in e for e in errs_zero_fat)
        and any("null-not-0" in e for e in errs_zero_inj)
        and any("unredacted PII" in e for e in errs_pii_leak),
        f"valid={len(errs_valid)}, no_exif={len(errs_no_exif)}, zero_fat={len(errs_zero_fat)}, pii_leak={len(errs_pii_leak)}",
    )

    # 3. Flag-only duplicate detection against landslide inventory
    inv_events = [
        {
            "id": "bipad_near_dated", "source": "BIPAD Portal", "provider_id": "bipad_ndrrma",
            "feature_type": "landslide_event", "title": "Singati slope failure",
            "lon": 86.1670, "lat": 27.7175, "event_date_utc": "2026-11-22T12:00:00Z",
        },
        {
            "id": "osm_near_scar", "source": "OpenStreetMap", "provider_id": "osm_overpass",
            "feature_type": "landslide_scar", "title": "Mapped valley scar",
            "lon": 86.1655, "lat": 27.7166, "event_date_utc": None,
        },
        {
            "id": "bipad_far_or_old", "source": "BIPAD Portal", "provider_id": "bipad_ndrrma",
            "feature_type": "landslide_event", "title": "Old distant event",
            "lon": 85.3240, "lat": 27.7172, "event_date_utc": "2026-10-01T00:00:00Z",
        },
    ]
    dups = MOD.check_duplicate_against_inventory(base_report, inv_events, max_km=1.5, max_days=3)
    dup_by_id = {d["inventory_event_id"]: d for d in dups}
    check(
        "moderation.check_duplicate_against_inventory flags dated & undated matches with auto_merged=False",
        dup_by_id.get("bipad_near_dated", {}).get("reason") == "dated_spatiotemporal_proximity"
        and dup_by_id.get("osm_near_scar", {}).get("reason") == "undated_spatial_proximity"
        and "bipad_far_or_old" not in dup_by_id
        and all(d["auto_merged"] is False and d["review_status"] == "pending_review" for d in dups),
        f"flagged={list(dup_by_id.keys())}",
    )

    # 4. Authenticated role enforcement & verified promotion to landslide_event.v1
    blocked_role = False
    try:
        MOD.transition_moderation_state(base_report, "verified_promoted", "public_user", "PUBLIC-1", "attempt")
    except PermissionError:
        blocked_role = True
    blocked_agency = False
    try:
        MOD.transition_moderation_state(base_report, "verified_promoted", "deoc_officer", "   ", "missing id")
    except PermissionError:
        blocked_agency = True

    promoted_rep = MOD.transition_moderation_state(
        base_report,
        "verified_promoted",
        "deoc_officer",
        "DEOC-DOLAKHA-01",
        "Verified on site by Dolakha DEOC duty officer.",
    )
    promoted_ls = promoted_rep.get("promoted_landslide_record") or {}
    ls_errs = LS.validate_landslide_record(promoted_ls) if promoted_ls else ["missing promoted record"]

    blocked_terminal = False
    try:
        MOD.transition_moderation_state(
            promoted_rep, "rejected_duplicate", "ndrrma_verifier", "NDRRMA-01", "re-transition"
        )
    except ValueError:
        blocked_terminal = True

    with tempfile.TemporaryDirectory() as tmpd:
        mq = MOD.build_moderation_queue(tmpd, write=True)
    check(
        "moderation.transition_moderation_state blocks unauthorized callers & promotes valid landslide_event.v1",
        blocked_role
        and blocked_agency
        and blocked_terminal
        and promoted_rep["moderation_status"] == "verified_promoted"
        and len(promoted_rep["moderation_history"]) == 1
        and promoted_ls.get("verified") is True
        and promoted_ls.get("feature_type") == "landslide_event"
        and not ls_errs
        and mq["public_live_endpoint_enabled"] is False,
        f"blocked=(role={blocked_role}, agency={blocked_agency}, terminal={blocked_terminal}), "
        f"promoted_type={promoted_ls.get('feature_type')}, sandbox_live={mq['public_live_endpoint_enabled']}",
    )


def test_cap_v12_multilingual_relay():
    """Verify src/cap_relay.py generates valid OASIS CAP v1.2 Exercise XML,
    hard-locks status=Exercise & relay_enabled=False, and covers all 6 languages + SMS/IVR."""
    with tempfile.TemporaryDirectory() as tmpd:
        ddir = os.path.join(tmpd, "data")
        os.makedirs(ddir, exist_ok=True)
        with open(os.path.join(ddir, "cascades.json"), "w", encoding="utf-8") as fh:
            json.dump({
                "generated_utc": "2026-11-23T12:00:00Z",
                "active_scenarios": [
                    {
                        "scenario_id": "SCN-GLOF-INFRA-ISOLATION",
                        "chain_id": "glof_infra_isolation",
                        "severity": "high",
                        "status": "active_dynamic",
                        "evidence_types": ["observed", "modelled_static"],
                        "affected_districts": ["Dolakha", "Ramechhap"],
                        "affected_provinces": ["Bagmati Province"],
                        "summary_en": "Synthetic GLOF corridor exercise scenario for Dolakha and Ramechhap.",
                    }
                ],
            }, fh)
        with open(os.path.join(ddir, "rivers_watch.json"), "w", encoding="utf-8") as fh:
            json.dump({
                "basins": [
                    {
                        "id": "koshi", "name": "Saptakoshi", "district": "Sunsari",
                        "prov": "Koshi Province", "dhm_ref": "Chatara",
                        "status_now": "q5_warning", "status_14d": "q5_warning",
                        "current_m3s": 4200.0, "peak_14d_median_m3s": 5100.0,
                    }
                ]
            }, fh)
        with open(os.path.join(ddir, "bipad_official.json"), "w", encoding="utf-8") as fh:
            json.dump({
                "alerts": [
                    {
                        "id": 9001, "public": True, "hazard": 11,
                        "title": "Flood alert in Dhanusha and Kailali",
                        "description": "Synthetic exercise mirror.",
                        "startedOn": "2026-11-23T06:00:00+05:45",
                    }
                ]
            }, fh)

        payload = CAP.build_cap_drafts(tmpd, write=True)
        xml_path = os.path.join(ddir, "cap_exercise_latest.xml")
        xml_text = open(xml_path, encoding="utf-8").read()

    # 1. Governance locks & rejection of Actual / relay_enabled=True
    adv0 = payload["advisories"][0]
    xml_blocks_actual = False
    try:
        CAP.advisory_to_cap_xml({**adv0, "status": "Actual"})
    except ValueError:
        xml_blocks_actual = True
    errs_actual = CAP.validate_cap_advisory({**adv0, "status": "Actual"})
    errs_relay_on = CAP.validate_cap_advisory({
        **adv0,
        "relay_governance": {**adv0["relay_governance"], "relay_enabled": True},
    })
    gov = payload["relay_governance"]
    check(
        "cap_relay hard-locks <status>Exercise</status> & relay_enabled=False (blocks Actual)",
        gov["relay_enabled"] is False
        and gov["requires_signed_mou"] is True
        and gov["statutory_warning"] is False
        and gov["cap_status"] == "Exercise"
        and payload["summary"]["all_cap_status_exercise"] is True
        and len(payload["advisories"]) == 3
        and xml_blocks_actual
        and bool(errs_actual)
        and bool(errs_relay_on),
        f"advisories={len(payload['advisories'])}, relay_enabled={gov['relay_enabled']}, blocks_actual={xml_blocks_actual}",
    )

    # 2. Valid OASIS CAP v1.2 XML structure
    xml_errs = CAP.validate_cap_xml(xml_text)
    root_el = ET.fromstring(xml_text)
    ns = {"cap": CAP.CAP_XMLNS}
    xml_langs = [el.findtext("cap:language", default="", namespaces=ns) for el in root_el.findall("cap:info", ns)]
    check(
        "cap_relay emits well-formed OASIS CAP v1.2 XML with Exercise status & 6 <info> blocks",
        not xml_errs
        and root_el.tag == f"{{{CAP.CAP_XMLNS}}}alert"
        and root_el.findtext("cap:status", namespaces=ns) == "Exercise"
        and xml_langs == ["en", "ne", "mai", "bho", "thr", "taj"],
        f"status={root_el.findtext('cap:status', namespaces=ns)}, langs={xml_langs}",
    )

    # 3. All 6 language info blocks + SMS budgets + IVR voice scripts + 5 hotlines
    expected_langs = ["en", "ne", "mai", "bho", "thr", "taj"]
    block_issues: list[str] = []
    for adv in payload["advisories"]:
        if [i["language"] for i in adv["info"]] != expected_langs:
            block_issues.append(f"{adv['identifier']}: language list mismatch")
        for info in adv["info"]:
            lc = info["language"]
            sms = info["sms_draft"]
            ivr = info["ivr_voice_script"]
            budget = 160 if lc == "en" else 140
            if not sms["within_budget"] or len(sms["text"]) > budget:
                block_issues.append(f"{lc}: SMS len {len(sms['text'])} > {budget}")
            if lc == "en" and (sms["encoding"] != "GSM-7" or not sms["text"].isascii()):
                block_issues.append("en: SMS must be ASCII GSM-7")
            if lc != "en" and sms["encoding"] != "UCS-2":
                block_issues.append(f"{lc}: SMS must be UCS-2")
            if not (20.0 <= float(ivr["estimated_duration_sec"]) <= 40.0) or not ivr["repeat_key_instruction"]:
                block_issues.append(f"{lc}: invalid IVR script ({ivr['estimated_duration_sec']}s)")
            for hl in CAP.REQUIRED_HOTLINES:
                if hl not in info["instruction"]:
                    block_issues.append(f"{lc}: missing hotline {hl}")
    check(
        "cap_relay validates all 6 languages (en/ne/mai/bho/thr/taj), SMS budgets, IVR scripts & 5 hotlines",
        not block_issues,
        f"{payload['summary']['n_info_blocks']} info blocks verified across 6 languages"
        if not block_issues
        else "; ".join(block_issues[:5]),
    )


# ---------------------------------------------------------------------------
# 8. Full-mode scientific tests (requires numpy, scipy, pyreadr, lit/*.rds)
# ---------------------------------------------------------------------------
def test_peak_discharge_scaling():
    """Qp* is dimensionless, so scaling breach depth h must move Qp by g^0.5 h^2.5
    at fixed eta, and unsaturated eta < eta_c follows h^(2.5 - 3.5*beta)."""
    fit = MG.fit_piecewise()
    rng = np.random.default_rng(0)
    h = np.array([20.0, 40.0])
    k = np.array([3e-3, 3e-3])
    v0 = np.array([1e7, 1e7 * (40 / 20) ** 3.5])
    qp = MG.peak_discharge(v0, h, k, fit, rng, include_noise=False)
    check("dimensionless Qp* scaling holds at fixed eta",
          math.isclose(float(qp[1] / qp[0]), (40 / 20) ** 2.5, rel_tol=1e-6),
          f"ratio {qp[1]/qp[0]:.4f} against {(40/20)**2.5:.4f}")
    q_small = MG.peak_discharge(np.array([1e5]), np.array([10.0]), np.array([1e-3]),
                                fit, rng, include_noise=False)[0]
    q_big = MG.peak_discharge(np.array([1e9]), np.array([10.0]), np.array([1e-3]),
                              fit, rng, include_noise=False)[0]
    check("a larger flood volume never gives a smaller peak", bool(q_big >= q_small),
          f"{q_small:.1f} then {q_big:.1f} m3/s")


def test_depth_regression_and_continuous_sampling():
    """Verify published depth posterior and continuous breach-fraction sampling."""
    post = MG.load_depth_posterior()
    fit = MG.fit_piecewise()
    b0, b1, _sig = post.mean(0)
    check("depth posterior has expected shape", post.shape[1] == 3 and post.shape[0] > 1e4,
          f"{post.shape[0]} draws")
    check("depth-area slope is positive and sub-linear", 0.3 < b1 < 0.8,
          f"beta1 = {b1:.3f}")
    d = 10 ** (b0 + b1 * math.log10(1.0e6))
    check("a 1 km2 lake predicts a plausible maximum depth", 60 < d < 160,
          f"{d:.0f} m, against 116 m measured at Imja Tsho in 2012")
    mag = MG.lake_magnitudes(1.0e6, post, fit, n_depth=80, n_k=40, seed=42)
    check("lake_magnitudes exposes continuous pooled + fixed 10/30/50/100% scenarios",
          set(mag["scenarios"].keys()) == {"10pct", "30pct", "50pct", "100pct"}
          and "pooled" in mag and "pooled_discrete" in mag
          and mag["continuous_sampling"]["distribution"] == "scaled_beta"
          and mag["pooled"]["peak_discharge_m3s"]["p50"] > 0)


def test_numpy_terrain_parity():
    """NumPy and pure-Python terrain kernels produce matching slopes and routing."""
    z_list = [[5000.0 + (15 - r) * 8.0 + abs(c - 7) * 3.0 for c in range(15)] for r in range(15)]
    for r in range(5, 9):
        for c in range(5, 10):
            z_list[r][c] -= 25.0
    lake_list = [[(r >= 13 and 5 <= c <= 9) for c in range(15)] for r in range(15)]
    z_np = np.asarray(z_list, dtype="float64")
    lake_np = np.asarray(lake_list, dtype=bool)
    f_py = TR.fill_depressions(z_list, sink_mask=lake_list)
    f_np = TR.fill_depressions(z_np, sink_mask=lake_np)
    d_py, p_py = TR.d8_route_to_lake(f_py, lake_list, 30.0, 30.0)
    d_np, p_np = TR.d8_route_to_lake(f_np, lake_np, 30.0, 30.0)
    s_py = TR.slope_deg(z_list, 27.0, 31.0)
    s_np = TR.slope_deg(z_np, 27.0, 31.0)
    check("NumPy and pure-Python terrain kernels are numerically identical",
          np.allclose(f_np, np.asarray(f_py), atol=1e-12)
          and np.array_equal(d_np, np.asarray(d_py))
          and np.allclose(np.where(np.isfinite(p_np), p_np, -1.0),
                          np.where(np.isfinite(np.asarray(p_py)), np.asarray(p_py), -1.0),
                          atol=1e-9)
          and np.allclose(s_np, np.asarray(s_py), atol=1e-12))


def test_multi_agency_seismic_fusion_and_cache():
    """Verify EMSC positive-depth normalization, USGS+EMSC cross-agency dedup, and alerts offline cache retention."""
    import alerts as AL

    emsc_raw = {
        "type": "Feature",
        "id": "20261124_0000019",
        "geometry": {"type": "Point", "coordinates": [88.0209, 27.9065, -25.2]},
        "properties": {
            "source_id": "2094176",
            "time": "2026-11-24T01:32:44.63Z",
            "flynn_region": "SIKKIM, INDIA",
            "lat": 27.9065,
            "lon": 88.0209,
            "depth": 25.2,
            "auth": "EMSC",
            "mag": 5.3,
        },
    }
    emsc_neg_only = {
        "type": "Feature",
        "id": "20261123_0000099",
        "geometry": {"type": "Point", "coordinates": [81.05, 29.45, -14.5]},
        "properties": {
            "source_id": "2094100",
            "time": "2026-11-23T12:00:00Z",
            "flynn_region": "NEPAL-INDIA BORDER REG.",
            "auth": "NDI",
            "mag": 3.1,
        },
    }
    n1 = AL.normalize_emsc_feature(emsc_raw)
    n2 = AL.normalize_emsc_feature(emsc_neg_only)
    check(
        "alerts.normalize_emsc_feature converts negative z to positive depth_km & builds EMSC link",
        n1 is not None and n2 is not None
        and n1["depth_km"] == 25.2 and n2["depth_km"] == 14.5
        and n1["url"].startswith("https://www.emsc-csem.org/")
        and n2["place"] == "Nepal-India Border Region"
        and n2["agency"] == "NDI",
        f"n1_depth={n1 and n1['depth_km']}, n2_depth={n2 and n2['depth_km']}, n2_place={n2 and n2['place']}",
    )

    usgs_dup = {
        "id": "us7000sikkim",
        "time": n1["time"] + 18000,  # 18 s offset
        "mag": 5.3,
        "place": "67 km WNW of Mangan, India",
        "depth_km": 10.0,
        "lon": 88.05,
        "lat": 27.89,
        "url": "https://earthquake.usgs.gov/earthquakes/eventpage/us7000sikkim",
        "source": "USGS",
        "sources": ["USGS"],
        "agency": "US",
        "in_nepal": False,
    }
    merged = AL.merge_seismic_events([usgs_dup], [n1, n2])
    check(
        "alerts.merge_seismic_events deduplicates USGS+EMSC within 90s/65km & retains regional EMSC",
        len(merged) == 2
        and merged[0]["id"] == "us7000sikkim"
        and merged[0]["sources"] == ["USGS", "EMSC"]
        and merged[1]["id"].startswith("emsc_")
        and merged[1]["sources"] == ["EMSC"],
        f"merged_ids={[m['id'] for m in merged]}, srcs={[m['sources'] for m in merged]}",
    )

    # Verify build_alerts(offline=True) preserves usgs_recent.events from cache instead of wiping to []
    with tempfile.TemporaryDirectory() as tmpd:
        fake_cache = os.path.join(tmpd, "cache_gdacs.json")
        fake_out = os.path.join(tmpd, "out_gdacs.json")
        with open(fake_cache, "w", encoding="utf-8") as fh:
            json.dump({
                "updated_utc": "2026-11-24T02:00:00Z",
                "events": [],
                "usgs_recent": {"updated_utc": "2026-11-24T02:00:00Z", "events": merged},
            }, fh)
        orig_cache = AL.CACHE_GDACS
        try:
            AL.CACHE_GDACS = fake_cache
            res = AL.build_alerts(offline=True, out_path=fake_out)
        finally:
            AL.CACHE_GDACS = orig_cache
    check(
        "alerts.build_alerts(offline=True) retains cached usgs_recent.events (no wipe to [])",
        res["usgs_recent"]["n_events"] == 2
        and res["usgs_recent"]["updated_utc"] == "2026-11-24T02:00:00Z",
        f"n_events={res['usgs_recent']['n_events']}, updated={res['usgs_recent']['updated_utc']}",
    )


# ---------------------------------------------------------------------------
def main(argv=None) -> int:
    ap = argparse.ArgumentParser(
        description="Run Nepal TRAYA pipeline unit tests."
    )
    ap.add_argument(
        "--unit-only", action="store_true",
        help="Run stdlib-only unit tests (no numpy/scipy/pyreadr or lit/*.rds required).",
    )
    args = ap.parse_args(argv)

    unit_tests = (
        test_risk_matrix,
        test_hazard_flowchart,
        test_impact_classes,
        test_volume_algebra,
        test_fujita_formulas,
        test_breach_rates,
        test_horn_slope_and_cells,
        test_coupled_flat_fill_and_d8_connectivity,
        test_avalanche_reach_bounds,
        test_point_to_segment_distance,
        test_same_reach_upstream_glof,
        test_utm_zone_selection,
        test_glof_history_fallback,
        test_haversine_antipodal_and_utc_year,
        test_admin_normalization_and_holes,
        test_validate_and_sensitivity_helpers,
        test_capacity_parser,
        test_stable_seed,
        test_travel_times,
        test_lakes_core_compact_roundtrip,
        test_hydromet_hourly_and_rain_basis,
        test_provenance_envelope_and_manifest,
        test_bipad_record_normalization,
        test_landslides_5type_and_duplicate_matcher,
        test_road_cut_hospital_isolation,
        test_cascade_graph_evaluation,
        test_ui_contrast_severity_and_csp_alignment,
        test_copernicus_sentinel1_sar_parsing,
        test_bates_2d_shallow_water_solver,
        test_community_moderation_engine,
        test_cap_v12_multilingual_relay,
        test_multi_agency_seismic_fusion_and_cache,
    )

    print(f"unit tests ({'stdlib --unit-only' if args.unit_only else 'full mode'})")
    for fn in unit_tests:
        fn()

    if not args.unit_only:
        if np is None:
            check("full scientific stack available (pass --unit-only for stdlib-only mode)",
                  False, "numpy is not installed")
        else:
            for fn in (test_peak_discharge_scaling,
                       test_depth_regression_and_continuous_sampling,
                       test_numpy_terrain_parity):
                fn()

    print(f"\n{'all tests pass' if not FAILS else str(len(FAILS)) + ' FAILED: ' + ', '.join(FAILS)}")
    return 1 if FAILS else 0


if __name__ == "__main__":
    sys.exit(main())
