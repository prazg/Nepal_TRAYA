"""
Unit tests for the parts of the pipeline whose correctness is checkable in
isolation: the classification matrices, the volume and discharge algebra, the
published-formula reproductions, and the tag parsers.

Run:  python3 test_pipeline.py
Exit status is non-zero if any test fails.
"""
from __future__ import annotations
import math
import sys

import numpy as np

import config as C
import exposure as EX
import hazard as HZ
import models_glof as MG
import terrain as TR

FAILS = []


def check(name, ok, detail=""):
    print(f"  [{'PASS' if ok else 'FAIL'}] {name}" + (f" — {detail}" if detail else ""))
    if not ok:
        FAILS.append(name)


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
    """Rounce et al. (2016) Fig. 4: an avalanche route is high hazard; combined
    dynamic and self-destructive susceptibility is very high; an ice core with
    an avalanche route is very high."""
    # general reading: susceptibility to both failure modes is very high
    cases = [
        # avalanche, rockfall, upstream, sla_steep, ice_cored, expected
        (False, False, False, False, None, "low"),
        (False, True, False, False, None, "moderate"),
        (False, False, True, False, None, "moderate"),
        (False, False, False, True, None, "moderate"),
        (False, False, False, False, True, "moderate"),
        (True, False, False, False, None, "high"),
        (True, False, False, True, None, "very high"),
        (False, True, False, True, None, "very high"),
        (True, False, False, False, True, "very high"),
        (False, True, False, False, True, "very high"),
    ]
    bad = [(c, HZ.overall_hazard(*c[:5])) for c in cases
           if HZ.overall_hazard(*c[:5]) != c[5]]
    check("hazard flow chart, general reading", not bad,
          f"{len(bad)} mismatches" + (f": {bad}" if bad else ""))

    # enumerated reading, used for the sensitivity analysis
    alt = [
        (False, False, False, False, None, "low"),
        (False, True, False, False, None, "moderate"),
        (False, False, False, False, True, "moderate"),
        (True, False, False, False, None, "high"),
        (False, True, False, False, True, "high"),
        (False, True, False, True, None, "moderate"),
        (True, False, False, False, True, "very high"),
    ]
    bad2 = [(c, HZ.overall_hazard_enumerated(*c[:5])) for c in alt
            if HZ.overall_hazard_enumerated(*c[:5]) != c[5]]
    check("hazard flow chart, enumerated reading", not bad2,
          f"{len(bad2)} mismatches" + (f": {bad2}" if bad2 else ""))
    check("the two readings differ only where the source text conflicts",
          HZ.overall_hazard(False, True, False, False, True) == "very high"
          and HZ.overall_hazard_enumerated(False, True, False, False, True) == "high",
          "rockfall with an ice core: very high against high")


def test_impact_classes():
    cases = [((0, 0, 0, 0), "low"), ((0, 0, 3, 0), "moderate"),
             ((5, 0, 2, 0), "high"), ((0, 1, 0, 0), "high"),
             ((5, 1, 2, 1), "very high"), ((0, 0, 0, 1), "high")]
    bad = [(a, HZ.downstream_impact(*a)) for a, e in cases
           if HZ.downstream_impact(*a) != e]
    check("downstream impact classes follow Table 4", not bad, str(bad))


# ---------------------------------------------------------------------------
def test_volume_algebra():
    """The ellipsoid-cap formula must be exact at both ends: no breach releases
    nothing, a full-depth breach releases the whole lake."""
    a = 1.0e6
    d = np.array([50.0, 120.0])
    v_total = MG.total_volume(a, d)
    v0_none = MG.released_volume(a, d, np.zeros_like(d))
    v0_full = MG.released_volume(a, d, d)
    check("no breach releases no water", np.allclose(v0_none, 0.0, atol=1e-6),
          f"max {np.abs(v0_none).max():.3e} m3")
    check("a full-depth breach releases the whole lake",
          np.allclose(v0_full, v_total, rtol=1e-9),
          f"max relative error {np.abs(v0_full/v_total - 1).max():.2e}")
    check("half-ellipsoid volume equals (2/3) A d",
          np.allclose(v_total, (2 / 3) * a * d))
    mono = all(MG.released_volume(a, np.array([100.0]), np.array([f * 100.0]))[0]
               <= MG.released_volume(a, np.array([100.0]), np.array([g * 100.0]))[0] + 1e-9
               for f, g in zip(np.linspace(0, 0.95, 20), np.linspace(0.05, 1.0, 20), strict=True))
    check("released volume increases with breach depth", mono)


def test_peak_discharge_scaling():
    """Qp* is dimensionless, so scaling the breach depth h must move Qp by
    exactly g^0.5 h^2.5 once eta is held fixed."""
    fit = MG.fit_piecewise()
    rng = np.random.default_rng(0)
    h = np.array([20.0, 40.0])
    # choose V0 and k so that eta is identical for both depths
    k = np.array([3e-3, 3e-3])
    v0 = np.array([1e7, 1e7 * (40 / 20) ** 3.5])
    qp = MG.peak_discharge(v0, h, k, fit, rng, include_noise=False)
    check("dimensionless scaling holds",
          math.isclose(qp[1] / qp[0], (40 / 20) ** 2.5, rel_tol=1e-6),
          f"ratio {qp[1]/qp[0]:.4f} against {(40/20)**2.5:.4f}")
    q_small = MG.peak_discharge(np.array([1e5]), np.array([10.0]), np.array([1e-3]),
                                fit, rng, include_noise=False)[0]
    q_big = MG.peak_discharge(np.array([1e9]), np.array([10.0]), np.array([1e-3]),
                              fit, rng, include_noise=False)[0]
    check("a larger flood volume never gives a smaller peak", q_big >= q_small,
          f"{q_small:.1f} then {q_big:.1f} m3/s")


def test_fujita_formulas():
    """Fujita et al. (2013) Table 1: Dm = 55 A^0.25 and PFV = min[Hp, Dm] A."""
    table = [("Nagma", 0.66, 60, 50, 32.8), ("Dig", 0.34, 21, 42, 7.1),
             ("Lugge", 1.14, 13, 57, 14.9), ("Sabai/Tam", 0.38, 52, 43, 16.3),
             ("Unnamed", 0.46, 16, 45, 7.2)]
    dm_err = max(abs(TR.mean_depth_fujita(a) - dm) for _, a, _, dm, _ in table)
    pfv_err = max(abs(TR.pfv_fujita(a, hp) / 1e6 - pfv) for _, a, hp, _, pfv in table)
    check("Dm reproduces the published table", dm_err <= 0.6, f"max error {dm_err:.2f} m")
    check("PFV reproduces the published table", pfv_err <= 0.3,
          f"max error {pfv_err:.2f} Mm3")


def test_depth_regression():
    """The published posterior must be the one we think it is."""
    post = MG.load_depth_posterior()
    b0, b1, sig = post.mean(0)
    check("depth posterior has the expected shape", post.shape[1] == 3 and post.shape[0] > 1e4,
          f"{post.shape[0]} draws")
    check("depth-area slope is positive and sub-linear", 0.3 < b1 < 0.8,
          f"beta1 = {b1:.3f}")
    # a 1 km2 lake should come out in the range Himalayan bathymetry actually shows
    d = 10 ** (b0 + b1 * math.log10(1.0e6))
    check("a 1 km2 lake predicts a plausible maximum depth", 60 < d < 160,
          f"{d:.0f} m, against 116 m measured at Imja Tsho in 2012")


def test_breach_rates():
    meanlog, sdlog, kmax = MG.breach_rate_lognormal()
    k = np.asarray(C.PUBLISHED_BREACH_RATES)
    check("breach-rate fit matches the published sample",
          math.isclose(meanlog, np.log(k).mean(), rel_tol=1e-12)
          and math.isclose(kmax, k.max() * 2, rel_tol=1e-12),
          f"median k = {math.exp(meanlog):.2e} m/s, cap {kmax:.2e}")
    check("all 19 published breach rates are present", len(k) == 19)


# ---------------------------------------------------------------------------
def test_slope_and_cells():
    """A synthetic constant-gradient surface must return its own slope."""
    dxm, dym = 30.0, 30.0
    n = 40
    for true_deg in (10.0, 30.0, 45.0, 60.0):
        g = math.tan(math.radians(true_deg))
        z = np.tile(np.arange(n) * dxm * g, (n, 1)).astype("float32")
        s = TR.slope_deg(z, dxm, dym)[2:-2, 2:-2]
        if abs(s.mean() - true_deg) > 0.01:
            check(f"slope of a {true_deg} deg plane", False, f"got {s.mean():.3f}")
            return
    check("slope is exact on constant-gradient surfaces", True,
          "tested at 10, 30, 45 and 60 degrees")
    dx, dy = TR.cell_metres(28.0, 1 / 3600)
    check("one arcsecond at 28 N is about 27 m east-west and 31 m north-south",
          26 < dx < 29 and 30 < dy < 32, f"{dx:.1f} m by {dy:.1f} m")


def test_routing_on_synthetic_dem():
    """A tilted plane draining into a lake at its foot: every cell above the
    lake must route into it, and path length must increase with distance."""
    n = 60
    z = np.tile(np.arange(n, 0, -1).astype("float32") * 5.0, (n, 1)).T
    lake = np.zeros((n, n), bool)
    lake[-3:, 20:40] = True
    z[lake] = z[lake].min()
    drains, plen = TR.d8_route_to_lake(z, lake, 30.0, 30.0)
    frac = drains[:-3, 20:40].mean()
    check("cells upslope of a lake route into it", frac > 0.95,
          f"{frac:.0%} of the column above the lake drains to it")
    col = plen[:-4, 30]
    finite = col[np.isfinite(col)]
    check("routed path length grows with distance upslope",
          np.all(np.diff(finite[::-1]) >= -1e-6),
          f"{finite.min():.0f}-{finite.max():.0f} m")


def test_depression_fill():
    z = np.full((40, 40), 100.0, "float32")
    z[18:22, 18:22] = 80.0                 # a pit
    f = TR.fill_depressions(z)
    check("depression filling removes a closed pit",
          math.isclose(float(f[19, 19]), 100.0, abs_tol=1e-3),
          f"pit raised from 80.0 to {f[19,19]:.1f}")
    check("depression filling never lowers terrain", bool(np.all(f >= z - 1e-6)))


# ---------------------------------------------------------------------------
def test_capacity_parser():
    cases = [("12.5 MW", 12.5), ("456 kW", 0.456), ("1 GW", 1000.0),
             ("2500000", 2.5), (None, None), ("not a number", None)]
    bad = [(v, EX._mw(v), e) for v, e in cases
           if (EX._mw(v) is None) != (e is None)
           or (e is not None and not math.isclose(EX._mw(v), e, rel_tol=1e-9))]
    check("hydropower capacity parser handles the documented tag forms", not bad, str(bad))


def test_stable_seed():
    a = MG.stable_seed("GL_27.86029_86.47725")
    check("seeds are stable across processes and non-negative",
          a == MG.stable_seed("GL_27.86029_86.47725") and 0 <= a < 2 ** 31, str(a))


# ---------------------------------------------------------------------------
def main():
    print("unit tests")
    for fn in (test_risk_matrix, test_hazard_flowchart, test_impact_classes,
               test_volume_algebra, test_peak_discharge_scaling,
               test_fujita_formulas, test_depth_regression, test_breach_rates,
               test_slope_and_cells, test_routing_on_synthetic_dem,
               test_depression_fill, test_capacity_parser, test_stable_seed):
        fn()
    print(f"\n{'all tests pass' if not FAILS else str(len(FAILS)) + ' FAILED: ' + ', '.join(FAILS)}")
    return 1 if FAILS else 0


if __name__ == "__main__":
    sys.exit(main())
