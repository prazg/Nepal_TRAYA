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
import math
import os
import sys
import warnings

_HERE = os.path.dirname(os.path.abspath(__file__))
if _HERE not in sys.path:
    sys.path.insert(0, _HERE)

try:
    import numpy as np
except ImportError:
    np = None

import admin as AD
import build as BD
import config as C
import exposure as EX
import hazard as HZ
import hydromet as HM
import models_glof as MG
import refresh_weekly as RW
import routing as RT
import seismic as SZ
import sensitivity as SN
import terrain as TR
import validate as VL

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
# 7. Full-mode scientific tests (requires numpy, scipy, pyreadr, lit/*.rds)
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
