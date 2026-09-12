"""
GLOF magnitude models: lake depth, lake volume, released flood volume, peak discharge.

This module reproduces the formulation of

    Veh, G., Korup, O., Walz, A. (2020) "Hazard from Himalayan glacier lake
    outburst floods", PNAS 117(2), 907-912, doi:10.1073/pnas.1914898117

using the authors' own published data (Zenodo 10.5281/zenodo.3523213, CC-BY-4.0)
and the structure of their published code (github.com/geveh/GLOFhazard, GPL-3).

Two departures from the original are deliberate and are reported as such:

 1. The depth-area regression uses the authors' published MCMC chain
    (mcmcChain.rds, 100,002 posterior draws of beta0, beta1, sigma) directly.
    This is the original posterior, not a refit.

 2. The dimensionless peak-discharge model is REFITTED here by maximum
    likelihood to the authors' own 63-point dataset (beebee-oconnor-2009-data.rds)
    using the same piecewise functional form and the same Student-t(nu=10)
    noise model. The original posterior sample (GLOF-dimless-posterior.rds) is a
    Stan object that cannot be read outside R, so the point estimate is ours while
    the data, model form and noise model are theirs. Parameter values and the fit
    diagnostic are written to data/model_fit.json for inspection.

Nothing here is calibrated to Nepal specifically, and none of it is a forecast.
The outputs are screening-level magnitudes for a hypothetical complete or partial
breach, not statements about whether a breach will occur.
"""
from __future__ import annotations
import json
import math
import os

import numpy as np
import pyreadr
import zlib
from scipy import optimize, stats

import config as C

_HERE = os.path.dirname(os.path.abspath(__file__))
LIT = C.LIT


# ---------------------------------------------------------------------------
# 1. Lake depth from lake area  (Veh et al. 2020 posterior)
# ---------------------------------------------------------------------------
def load_depth_posterior() -> np.ndarray:
    """Return an (n, 3) array of posterior draws [beta0, beta1, sigma].

    Model (log10 space):  log10(depth_m) ~ Normal(beta0 + beta1*log10(area_m2), sigma)
    """
    path = os.path.join(LIT, "mcmcChain.rds")
    df = list(pyreadr.read_r(path).values())[0]
    return df[["beta0", "beta1", "sigma"]].to_numpy()


def depth_samples(area_m2: float, post: np.ndarray, n: int, rng) -> np.ndarray:
    """Posterior-predictive draws of maximum lake depth (m) for one lake area."""
    idx = rng.integers(0, post.shape[0], n)
    b0, b1, sig = post[idx, 0], post[idx, 1], post[idx, 2]
    mu = b0 + b1 * math.log10(area_m2)
    return 10.0 ** rng.normal(mu, sig)


# ---------------------------------------------------------------------------
# 2. Lake and flood volume  (half-ellipsoid bathymetry, Veh et al. 2020)
# ---------------------------------------------------------------------------
def total_volume(area_m2: float, depth_m: np.ndarray) -> np.ndarray:
    """Half-ellipsoid volume: V = (4/3) pi r^2 c / 2 = (2/3) A d, with r = sqrt(A/pi)."""
    return (2.0 / 3.0) * area_m2 * depth_m


def released_volume(area_m2: float, depth_m: np.ndarray, breach_depth_m: np.ndarray) -> np.ndarray:
    """Flood volume V0 released when the dam is breached to `breach_depth_m` below
    the lake surface.

    The water remaining afterwards is the cap of the half-ellipsoid:
        V_remaining = pi r^2 ( 2h/3 - c + c^3 / (3 h^2) )
    with h the total depth and c the breach depth (Veh et al. 2020 code).
    V0 = V_total - V_remaining.
    """
    r2 = area_m2 / math.pi
    h = depth_m
    c = breach_depth_m
    v_remaining = math.pi * r2 * ((2.0 * h / 3.0) - c + (c ** 3) / (3.0 * h ** 2))
    return total_volume(area_m2, depth_m) - v_remaining


# ---------------------------------------------------------------------------
# 3. Peak discharge  (Walder & O'Connor 1997 dimensionless formulation)
# ---------------------------------------------------------------------------
def load_dambreak_data() -> tuple[np.ndarray, np.ndarray]:
    """Return (log10 eta, log10 Qp*) for the 63 natural dam breaks used by Veh et al."""
    path = os.path.join(LIT, "beebee-oconnor-2009-data.rds")
    df = list(pyreadr.read_r(path).values())[0]
    return df["eta"].to_numpy(float), df["Qp_star"].to_numpy(float)


def _piecewise(x, alpha, beta, chg):
    """Linear below the change point, constant above (Veh et al. Stan model)."""
    return alpha + beta * x - beta * (x - chg) * (x >= chg)


def fit_piecewise(nu: int = C.STUDENT_T_NU) -> dict:
    """Maximum-likelihood fit of the piecewise model with Student-t(nu) noise.

    Returns a dict of parameters in the ORIGINAL (unstandardised) log10 space,
    plus fit diagnostics.
    """
    x, y = load_dambreak_data()

    def nll(p):
        alpha, beta, chg, log_sigma = p
        sigma = math.exp(log_sigma)
        mu = _piecewise(x, alpha, beta, chg)
        return -np.sum(stats.t.logpdf((y - mu) / sigma, df=nu) - log_sigma)

    best = None
    for chg0 in np.linspace(x.min() + 0.5, x.max() - 0.5, 25):
        p0 = [np.median(y), 0.5, chg0, math.log(np.std(y))]
        r = optimize.minimize(nll, p0, method="Nelder-Mead",
                              options=dict(maxiter=20000, xatol=1e-8, fatol=1e-8))
        if best is None or r.fun < best.fun:
            best = r
    alpha, beta, chg, log_sigma = best.x
    mu = _piecewise(x, alpha, beta, chg)
    resid = y - mu
    ss_tot = np.sum((y - y.mean()) ** 2)
    return dict(alpha=float(alpha), beta=float(beta), chgpoint=float(chg),
                sigma=float(math.exp(log_sigma)), nu=nu, n=int(len(x)),
                pseudo_r2=float(1.0 - np.sum(resid ** 2) / ss_tot),
                rmse_log10=float(np.sqrt(np.mean(resid ** 2))),
                eta_range=[float(x.min()), float(x.max())],
                note="refit by maximum likelihood to the 63-point dataset of "
                     "O'Connor & Beebee (2009) compiled by Veh et al. (2020); "
                     "functional form and Student-t(nu=10) noise as published")


def breach_rate_lognormal() -> tuple[float, float, float]:
    """MLE lognormal fit to the 19 published natural-dam breach rates, and the cap."""
    k = np.asarray(C.PUBLISHED_BREACH_RATES, float)
    lk = np.log(k)
    return float(lk.mean()), float(lk.std(ddof=0)), float(k.max() * C.BREACH_RATE_MAX_FACTOR)


def peak_discharge(v0_m3: np.ndarray, breach_depth_m: np.ndarray,
                   k_ms: np.ndarray, fit: dict, rng,
                   include_noise: bool = True) -> np.ndarray:
    """Peak discharge Qp (m3/s) from released volume, breach depth and breach rate.

    Dimensionless variables (Walder & O'Connor 1997):
        Qp*    = Qp / (g^0.5 h^2.5)
        V0*    = V0 / h^3
        k*     = k / (g^0.5 h^0.5)
        eta    = V0* k*
    """
    h = np.asarray(breach_depth_m, float)
    v0 = np.asarray(v0_m3, float)
    k = np.asarray(k_ms, float)
    with np.errstate(divide="ignore", invalid="ignore"):
        eta = (v0 / h ** 3) * k / (C.G ** 0.5 * h ** 0.5)
        x = np.log10(eta)
        mu = _piecewise(x, fit["alpha"], fit["beta"], fit["chgpoint"])
        if include_noise:
            mu = mu + fit["sigma"] * rng.standard_t(fit["nu"], size=np.shape(mu))
        qp = 10.0 ** mu * C.G ** 0.5 * h ** 2.5
    return qp


# ---------------------------------------------------------------------------
# 4. Per-lake Monte Carlo
# ---------------------------------------------------------------------------
def lake_magnitudes(area_m2: float, post: np.ndarray, fit: dict,
                    n_depth: int = 200, n_k: int = 100, seed: int = 0) -> dict:
    """Monte Carlo estimate of depth, volume, released volume and Qp for one lake.

    Following Veh et al. (2020), every breach depth between a small fraction and
    the full lake depth is treated as possible, and the resulting peak discharges
    are pooled. The pooled distribution is the headline output; the individual
    breach-fraction scenarios are also reported for transparency.

    Note on model behaviour: because the dimensionless response Qp* saturates
    above a change point in eta, a partial breach can yield a peak discharge
    comparable to a full breach. That is a property of the published model, not
    an artefact of this implementation, and it means the breach fraction is not
    the dominant control on Qp for Himalayan lakes of this size; lake depth and
    breach rate are.
    """
    rng = np.random.default_rng(seed)
    d = depth_samples(area_m2, post, n_depth, rng)
    d = d[d > 1.0]                                    # discard non-physical draws
    if d.size == 0:
        return {}
    vt = total_volume(area_m2, d)

    meanlog, sdlog, kmax = breach_rate_lognormal()
    k = rng.lognormal(meanlog, sdlog, n_k)
    k = k[k < kmax]

    out = dict(depth_m=_q(d), volume_m3=_q(vt), scenarios={})
    pooled_qp, pooled_v0 = [], []
    for frac in C.BREACH_FRACTIONS:
        bd = d * frac                                  # breach depth below lake surface
        v0 = np.clip(released_volume(area_m2, d, bd), 1.0, None)
        V0 = np.repeat(v0, k.size)
        H = np.repeat(bd, k.size)
        K = np.tile(k, v0.size)
        qp = peak_discharge(V0, H, K, fit, rng)
        qp = qp[np.isfinite(qp) & (qp > 0)]
        out["scenarios"][f"{int(frac * 100)}pct"] = dict(
            flood_volume_m3=_q(v0), peak_discharge_m3s=_q(qp))
        pooled_qp.append(qp)
        pooled_v0.append(v0)
    out["pooled"] = dict(flood_volume_m3=_q(np.concatenate(pooled_v0)),
                         peak_discharge_m3s=_q(np.concatenate(pooled_qp)))
    return out


def stable_seed(key: str) -> int:
    """Process-independent seed, so the pipeline output is byte-deterministic
    (Python's built-in hash() is randomised per process)."""
    return zlib.crc32(key.encode()) & 0x7FFFFFFF


def _q(a: np.ndarray) -> dict:
    a = np.asarray(a, float)
    a = a[np.isfinite(a)]
    if a.size == 0:
        return dict(p50=None, p2_5=None, p97_5=None)
    return dict(p50=float(np.percentile(a, 50)),
                p2_5=float(np.percentile(a, 2.5)),
                p97_5=float(np.percentile(a, 97.5)))


if __name__ == "__main__":
    fit = fit_piecewise()
    print("piecewise fit:", json.dumps(fit, indent=2))
    post = load_depth_posterior()
    print("depth posterior draws:", post.shape,
          "beta0=%.3f beta1=%.3f sigma=%.3f" % tuple(post.mean(0)))
