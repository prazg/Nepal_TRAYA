"""
Figures for paper/main.tex, generated from the pipeline outputs.

  fig_map.pdf          national distribution of screened lakes and the priority set
  fig_pfv_area.pdf     potential flood volume against lake area, showing where the
                       metric is limited by the lowering height and where by the
                       area-depth cap
  fig_validation.pdf   our potential flood volume against the published values,
                       and the peak-discharge model against its calibration data
"""
from __future__ import annotations
import json
import math
import os

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np

import config as C
import models_glof as MG

OUT = os.path.join(C.ROOT, "paper", "generated")
plt.rcParams.update({
    "font.size": 8, "axes.labelsize": 8, "axes.titlesize": 8.5,
    "legend.fontsize": 7, "xtick.labelsize": 7.5, "ytick.labelsize": 7.5,
    "axes.spines.top": False, "axes.spines.right": False,
    "figure.dpi": 200, "savefig.bbox": "tight", "pdf.fonttype": 42,
})
INK, ACC, WARN, BAD = "#1b2733", "#2f6f9f", "#d08c2a", "#b33a2e"


def rd(fn):
    t = open(os.path.join(C.DATA, fn)).read()
    return json.loads(t.split("=", 1)[1].rsplit(";", 1)[0])


def _province_outlines(ax):
    try:
        import admin as AD
        ix = AD.AdminIndex()
    except Exception:
        return
    for _, poly in ix.levels["4"]:
        geoms = getattr(poly, "geoms", [poly])
        for g in geoms:
            if g.geom_type != "Polygon":
                continue
            xs, ys = g.exterior.xy
            ax.plot(xs, ys, color="#c3ced9", lw=0.45, zorder=0)


def fig_map(P, routes):
    fig, ax = plt.subplots(figsize=(7.0, 3.1))
    _province_outlines(ax)
    lon = np.array([p["_lon"] for p in P])
    lat = np.array([p["_lat"] for p in P])
    pfv = np.array([p["pfv_Mm3"] or 0.0 for p in P])
    pri = np.array([bool(p.get("priority")) for p in P])

    for r in routes.values():
        path = np.array(r["path"])
        ax.plot(path[:, 0], path[:, 1], color="#9fb3c8", lw=0.25, alpha=0.5, zorder=1)
    ax.scatter(lon[~pri], lat[~pri], s=np.clip(pfv[~pri] * 2.5 + 1.2, 1.2, 26),
               c="#7aa6c2", alpha=0.55, lw=0, zorder=2, label="screened lake")
    ax.scatter(lon[pri], lat[pri], s=np.clip(pfv[pri] * 1.1 + 14, 14, 70),
               facecolor=BAD, edgecolor="white", lw=0.5, zorder=4,
               label=r"PFV $\geq 10\times10^6$ m$^3$")
    # rank by potential flood volume, keyed to the priority table
    ranked = sorted((p for p in P if p.get("priority")),
                    key=lambda q: -(q["pfv_Mm3"] or 0))
    for i, p in enumerate(ranked, 1):
        ax.annotate(str(i), (p["_lon"], p["_lat"]),
                    textcoords="offset points", xytext=(0, 0), fontsize=5.2,
                    color="white", zorder=6, ha="center", va="center",
                    fontweight="bold")
    ax.set_xlabel("longitude ($^\\circ$E)")
    ax.set_ylabel("latitude ($^\\circ$N)")
    ax.set_xlim(80.2, 88.5)
    ax.set_ylim(26.2, 30.8)
    ax.set_aspect(1 / math.cos(math.radians(28.5)))
    ax.legend(loc="lower left", frameon=False, handletextpad=0.4, borderpad=0.2)
    ax.grid(alpha=0.13, lw=0.4)
    fig.savefig(os.path.join(OUT, "fig_map.pdf"))
    plt.close(fig)


def fig_pfv_area(P):
    pos = [p for p in P if (p["pfv_Mm3"] or 0) > 0]
    a = np.array([p["area_km2"] for p in pos])
    v = np.array([p["pfv_Mm3"] for p in pos])
    hp = np.array([p["hp_m"] or 0.0 for p in pos])
    dm = np.array([p["dm_fujita_m"] or 0.0 for p in pos])
    dm_lim = hp >= dm

    fig, axes = plt.subplots(1, 2, figsize=(7.0, 2.7))
    ax = axes[0]
    ax.scatter(a[dm_lim], v[dm_lim], s=5, c=ACC, alpha=0.5, lw=0,
               label=f"limited by $D_m$ ({dm_lim.sum()})")
    ax.scatter(a[~dm_lim], v[~dm_lim], s=5, c=WARN, alpha=0.75, lw=0,
               label=f"limited by $H_p$ ({(~dm_lim).sum()})")
    xs = np.logspace(np.log10(a.min()), np.log10(a.max()), 50)
    ax.plot(xs, 55 * xs ** 1.25, color=INK, lw=1.0, ls="--",
            label=r"$D_m A = 55A^{1.25}$")
    ax.axhline(10, color=BAD, lw=0.8, ls=":")
    ax.text(a.min() * 1.15, 12.5, "screening threshold", color=BAD, fontsize=6.5)
    ax.set_xscale("log")
    ax.set_yscale("log")
    ax.set_xlabel("lake area (km$^2$)")
    ax.set_ylabel("potential flood volume ($10^6$ m$^3$)")
    ax.legend(loc="lower right", frameon=False, handletextpad=0.4)
    ax.grid(alpha=0.13, lw=0.4)

    ax = axes[1]
    allv = np.array([p["pfv_Mm3"] or 0.0 for p in P])
    alla = np.array([p["area_km2"] for p in P])
    zero = allv <= 0
    ax.scatter(alla[zero], np.full(zero.sum(), 1e-3), s=4, c="#b9c6d2", lw=0, alpha=0.6,
               label=f"no steep lakefront ({zero.sum()})")
    ax.scatter(alla[~zero], allv[~zero], s=4, c=ACC, lw=0, alpha=0.45,
               label=f"steep lakefront ({(~zero).sum()})")
    ax.set_xscale("log")
    ax.set_yscale("log")
    ax.set_ylim(5e-4, 300)
    ax.set_xlabel("lake area (km$^2$)")
    ax.set_ylabel("potential flood volume ($10^6$ m$^3$)")
    ax.legend(loc="upper left", frameon=False, handletextpad=0.4)
    ax.grid(alpha=0.13, lw=0.4)
    fig.tight_layout()
    fig.savefig(os.path.join(OUT, "fig_pfv_area.pdf"))
    plt.close(fig)


def fig_validation(V):
    fig, axes = plt.subplots(1, 2, figsize=(7.0, 2.8))

    ax = axes[0]
    pub = np.array([r["pfv_pub"] for r in V["fujita2"]])
    ours = np.array([r["pfv_ours"] for r in V["fujita2"]])
    floor = 0.02
    px, ox = np.maximum(pub, floor), np.maximum(ours, floor)
    both_zero = (pub == 0) & (ours < 0.1)
    ax.plot([floor, 200], [floor, 200], color=INK, lw=0.8)
    for f, ls in ((3, ":"), (1 / 3, ":")):
        ax.plot([floor, 200], [floor * f, 200 * f], color=INK, lw=0.6, ls=ls, alpha=0.6)
    ax.scatter(px[both_zero], ox[both_zero], s=22, facecolor="none", edgecolor="#7aa6c2",
               lw=0.9, label="both zero")
    ok = (~both_zero) & (pub > 0) & (ours > 0) & (ours / np.maximum(pub, 1e-9) >= 1 / 3) \
        & (ours / np.maximum(pub, 1e-9) <= 3)
    ax.scatter(px[ok], ox[ok], s=24, c=ACC, lw=0, label=r"within $\times3$")
    miss = ~(both_zero | ok)
    ax.scatter(px[miss], ox[miss], s=24, c=BAD, lw=0, marker="v",
               label="not recovered")
    ax.axvspan(floor, 5, color="#000000", alpha=0.04, lw=0)
    ax.text(0.055, 120, "published PFV\nbelow 5", fontsize=6.3, color="#5a6b7b")
    ax.set_xscale("log")
    ax.set_yscale("log")
    ax.set_xlim(floor, 200)
    ax.set_ylim(floor, 200)
    ax.set_xlabel("published PFV, ASTER ($10^6$ m$^3$)")
    ax.set_ylabel("our PFV, Copernicus ($10^6$ m$^3$)")
    ax.legend(loc="lower right", frameon=False, handletextpad=0.4)
    ax.grid(alpha=0.13, lw=0.4)

    ax = axes[1]
    x, y = MG.load_dambreak_data()
    fit = V["fit"]["qp_piecewise"]
    ax.scatter(x, y, s=13, c="#6b7f91", lw=0, alpha=0.85, label=f"{len(x)} natural dam breaks")
    xs = np.linspace(x.min() - 0.2, x.max() + 0.2, 300)
    mu = MG._piecewise(xs, fit["alpha"], fit["beta"], fit["chgpoint"])
    ax.plot(xs, mu, color=BAD, lw=1.3, label="piecewise fit")
    ax.fill_between(xs, mu - 1.96 * fit["sigma"], mu + 1.96 * fit["sigma"],
                    color=BAD, alpha=0.12, lw=0, label="95% predictive band")
    ax.axvline(fit["chgpoint"], color=INK, lw=0.7, ls="--")
    ax.text(fit["chgpoint"] + 0.06, y.min() + 0.15,
            f"change point\n$\\log_{{10}}\\eta = {fit['chgpoint']:.2f}$", fontsize=6.3, color=INK)
    ax.set_xlabel(r"$\log_{10}\eta$")
    ax.set_ylabel(r"$\log_{10} Q_p^{*}$")
    ax.legend(loc="upper left", frameon=False, handletextpad=0.4)
    ax.grid(alpha=0.13, lw=0.4)
    fig.tight_layout()
    fig.savefig(os.path.join(OUT, "fig_validation.pdf"))
    plt.close(fig)


def main():
    os.makedirs(OUT, exist_ok=True)
    feats = rd("lakes.js")["features"]
    P = []
    for f in feats:
        p = dict(f["properties"])
        ring = f["geometry"]["coordinates"][0]
        p["_lon"] = float(np.mean([c[0] for c in ring]))
        p["_lat"] = float(np.mean([c[1] for c in ring]))
        P.append(p)
    routes = rd("routes.js")
    V = rd("validation.js")
    fig_map(P, routes)
    fig_pfv_area(P)
    fig_validation(V)
    print("wrote fig_map.pdf, fig_pfv_area.pdf, fig_validation.pdf")


if __name__ == "__main__":
    main()
