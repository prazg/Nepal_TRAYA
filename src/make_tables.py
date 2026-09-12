"""
Generate the LaTeX tables and numeric macros used by paper/main.tex directly
from the pipeline outputs, so that no number in the manuscript is typed by hand
and none can drift from the data.

Writes into paper/generated/:
  macros.tex                every headline number as a \newcommand
  tab_rounce.tex            reproduction of Rounce et al. (2016) Table 5
  tab_fujita1.tex           reproduction of Fujita et al. (2013) Table 1
  tab_fujita2.tex           per-lake PFV against Fujita et al. (2013) Table 2
  tab_observations.tex      measured depths, volumes and discharges
  tab_priority.tex          the lakes above the 10 Mm3 screening threshold
  tab_sensitivity.tex       sensitivity of the results to implementation choices
  tab_checks.tex            the internal consistency checks
"""
from __future__ import annotations
import json
import os

import numpy as np

import config as C

OUT = os.path.join(C.ROOT, "paper", "generated")


def rd(fn):
    t = open(os.path.join(C.DATA, fn)).read()
    return json.loads(t.split("=", 1)[1].rsplit(";", 1)[0])


def esc(s):
    return (str(s).replace("&", "\\&").replace("%", "\\%").replace("_", "\\_")
            .replace("#", "\\#"))


def num(v, nd=0, dash="--"):
    if v is None or (isinstance(v, float) and not np.isfinite(v)):
        return dash
    return f"{v:,.{nd}f}"


def table(caption, label, header, rows, spec, note=None, small=True, fit=True):
    s = ["\\begin{table}[htbp]", "\\centering"]
    if small:
        s.append("\\footnotesize")
    s += [f"\\caption{{{caption}}}", f"\\label{{{label}}}"]
    if fit:
        s.append("\\resizebox{\\ifdim\\width>\\linewidth\\linewidth\\else\\width\\fi}{!}{%")
    s += [f"\\begin{{tabular}}{{{spec}}}", "\\hline",
          " & ".join(header) + " \\\\", "\\hline"]
    s += [" & ".join(r) + " \\\\" for r in rows]
    s += ["\\hline", "\\end{tabular}"]
    if fit:
        s.append("}")
    if note:
        s.append(f"\\\\[2pt]\\begin{{minipage}}{{\\linewidth}}\\footnotesize {note}\\end{{minipage}}")
    s.append("\\end{table}")
    return "\n".join(s) + "\n"


def main():
    os.makedirs(OUT, exist_ok=True)
    L = rd("lakes.js")["features"]
    P = [f["properties"] for f in L]
    S = rd("summary.js")
    R = rd("routes.js")
    V = rd("validation.js")
    sens = rd("sensitivity.js") if os.path.exists(os.path.join(C.DATA, "sensitivity.js")) else None

    pfv = np.array([p["pfv_Mm3"] or 0.0 for p in P])
    qp = np.array([p["qp_m3s"] or 0.0 for p in P])
    area = np.array([p["area_km2"] for p in P])
    pri = [p for p in P if p.get("priority")]

    # ---------------- macros ------------------------------------------------
    pos = [p for p in P if (p["pfv_Mm3"] or 0) > 0]
    dm_lim = sum(1 for p in pos if (p["hp_m"] or 0) >= (p["dm_fujita_m"] or 0))
    la, lv = np.log10([p["area_km2"] for p in pos]), np.log10([p["pfv_Mm3"] for p in pos])
    slope = float(np.polyfit(la, lv, 1)[0])
    r2 = float(np.corrcoef(la, lv)[0, 1] ** 2)
    west = [p for p in pri if p["prov"].startswith(("Karnali", "Sudurpash"))]

    m = {
        "NLakes": f"{len(P):,}",
        "NRouted": f"{len(R):,}",
        "TotalArea": f"{area.sum():.0f}",
        "MedianArea": f"{np.median(area):.3f}",
        "NPriority": str(len(pri)),
        "NPriorityWest": str(len(west)),
        "NPriorityNamed": str(sum(1 for p in pri if p["name"])),
        "NPFVPositive": f"{len(pos):,}",
        "PctDmLimited": f"{100*dm_lim/len(pos):.0f}",
        "PFVAreaSlope": f"{slope:.2f}",
        "PFVAreaRsq": f"{r2:.2f}",
        "NVeryHigh": f"{S['hazard_counts']['very high']:,}",
        "PctVeryHigh": f"{100*S['hazard_counts']['very high']/len(P):.0f}",
        "NAvalanche": f"{sum(1 for p in P if p['avalanche']):,}",
        "NRockfall": f"{sum(1 for p in P if p['rockfall']):,}",
        "NSLA": f"{sum(1 for p in P if (p['sla_area_km2'] or 0) > 0):,}",
        "NUpstream": f"{sum(1 for p in P if p['upstream_glof']):,}",
        "MaxPFV": f"{pfv.max():.0f}",
        "MedianQp": f"{np.median(qp[qp>0]):.0f}",
        "MaxQp": f"{qp.max():,.0f}",
        "PopPriority": f"{sum(p['pop_high'] or 0 for p in pri):,.0f}",
        "PopPriorityWest": f"{sum(p['pop_high'] or 0 for p in west):,.0f}",
        "NProvReassigned": f"{S['province_reassigned']:,}",
        "NChecks": str(len(V["checks"])),
        "NChecksPass": str(sum(c["pass"] for c in V["checks"])),
        "RounceAva": esc(V["rounce_agreement"]["avalanche"]),
        "RounceRock": esc(V["rounce_agreement"]["rockfall"]),
        "RounceSLA": esc(V["rounce_agreement"]["sla_threshold"]),
        "FujitaZero": esc(V["fujita_agreement"]["zero"]),
        "FujitaLarge": esc(V["fujita_agreement"]["large"]),
        "FujitaSmall": esc(V["fujita_agreement"]["small"]),
        "FujitaBand": f"{V['fujita_large_threshold']:.0f}",
        "DepthBetaZero": f"{V['fit']['depth_beta0']:.3f}",
        "DepthBetaOne": f"{V['fit']['depth_beta1']:.3f}",
        "DepthSigma": f"{V['fit']['depth_sigma']:.3f}",
        "QpRsq": f"{V['fit']['qp_piecewise']['pseudo_r2']:.2f}",
        "QpRmse": f"{V['fit']['qp_piecewise']['rmse_log10']:.2f}",
        "QpFactor": f"{10**V['fit']['qp_piecewise']['rmse_log10']:.1f}",
        "QpChg": f"{V['fit']['qp_piecewise']['chgpoint']:.2f}",
        "QpAlpha": f"{V['fit']['qp_piecewise']['alpha']:.3f}",
        "QpBeta": f"{V['fit']['qp_piecewise']['beta']:.3f}",
        "NDamBreaks": str(V["fit"]["qp_piecewise"]["n"]),
        "NBreachRates": str(len(C.PUBLISHED_BREACH_RATES)),
        "NEq": f"{S['seismicity']['n_events']:,}",
        "EqFirst": str(S["seismicity"]["first_year"]),
        "EqMSix": str(S["seismicity"]["n_m6plus"]),
        "EqMSeven": str(S["seismicity"]["n_m7plus"]),
        "NPlaces": f"{S['exposure_totals']['places']:,}",
        "NBridges": f"{S['exposure_totals']['bridges']:,}",
        "NHydro": f"{S['exposure_totals']['hydropower']:,}",
        "NHealth": f"{S['exposure_totals']['health']:,}",
        "BuildDate": esc(S["build"][:10]),
    }
    if sens:
        m["SensSample"] = str(sens["sample_size"])
        m["NHazardDiffer"] = f"{sens['hazard_reading']['n_lakes_differing']:,}"
        m["PctHazardDiffer"] = f"{100*sens['hazard_reading']['n_lakes_differing']/sens['hazard_reading']['n_lakes']:.0f}"
        ref = next(r for r in sens["variants"] if r["variant"] == sens["reference"])
        for r in sens["variants"]:
            if "8 deg" in r["variant"]:
                m["SensEightPriority"] = str(r["n_priority"])
            if "12 deg" in r["variant"]:
                m["SensTwelvePriority"] = str(r["n_priority"])
            if "15 deg" in r["variant"]:
                m["SensFifteenPriority"] = str(r["n_priority"])
            if "100 m" in r["variant"]:
                m["SensBufferPriority"] = str(r["n_priority"])
                m["SensBufferFlips"] = str(r["priority_set_changed"])
            if "6 km" in r["variant"]:
                m["SensSixAva"] = str(r["n_avalanche"])
            if "10 km" in r["variant"]:
                m["SensTenAva"] = str(r["n_avalanche"])
        m["SensRefPriority"] = str(ref["n_priority"])
        m["SensRefAva"] = str(ref["n_avalanche"])

    with open(os.path.join(OUT, "macros.tex"), "w") as fh:
        fh.write("% generated by src/make_tables.py -- do not edit\n")
        for k, v in m.items():
            fh.write(f"\\newcommand{{\\{k}}}{{{v}}}\n")

    # ---------------- tables ------------------------------------------------
    rows = [[esc(r["lake"]),
             "yes" if r["ava"] else "no", "yes" if r["ava_pub"] else "no",
             "yes" if r["rock"] else "no", "yes" if r["rock_pub"] else "no",
             num(r["sla"], 1), num(r["sla_pub"], 1),
             "$\\bullet$" if r["sla_agree"] else "$\\times$"]
            for r in V["rounce"]]
    open(os.path.join(OUT, "tab_rounce.tex"), "w").write(table(
        "Reproduction of the hazard classification of \\citet{rounce2016} Table~5 for the "
        "eight lakes they assessed. No parameter was adjusted to improve agreement.",
        "tab:rounce",
        ["Lake", "Ava.\\ ours", "Ava.\\ pub.", "Rock.\\ ours", "Rock.\\ pub.",
         "SLA$^\\circ$ ours", "SLA$^\\circ$ pub.", "$\\geq 10^\\circ$ agrees"],
        rows, "lcccccccc",
        note="Published values were computed on the ASTER GDEM and ours on the Copernicus DEM "
             "GLO-30, so the absolute SLA angles are not expected to coincide; the comparison "
             "that matters is the classification each threshold produces. Our SLA figure is the "
             "steepest depression angle within 1\\,km, theirs a single representative value."))

    rows = [[esc(r["lake"]), num(r["area"], 2), num(r["hp"]),
             num(r["dm_pub"]), num(r["dm_ours"], 1),
             num(r["pfv_pub"], 1), num(r["pfv_ours"], 1),
             num(r["fv_obs"], 1), ("$\\times$" + num(r["pfv_over_fv"], 2)) if r["pfv_over_fv"] else "--"]
            for r in V["fujita1"]]
    open(os.path.join(OUT, "tab_fujita1.tex"), "w").write(table(
        "Reproduction of \\citet{fujita2013} Table~1. Five lakes assessed on pre-outburst "
        "Hexagon KH-9 topography, with the flood volume observed when each later burst.",
        "tab:fujita1",
        ["Lake", "$A$ (km$^2$)", "$H_p$ (m)", "$D_m$ pub.", "$D_m$ ours",
         "PFV pub.", "PFV ours", "Observed $FV$", "PFV/$FV$"],
        rows, "lcccccccc",
        note="Volumes in $10^6$\\,m$^3$. $D_m$ and PFV are recomputed here from the published "
             "$A$ and $H_p$ using $D_m = 55A^{0.25}$ and $\\mathrm{PFV} = \\min[H_p, D_m]\\,A$."))

    rows = [[esc(r["lake"]), num(r["pfv_pub"], 1), num(r["pfv_ours"], 2),
             ("$\\times$" + num(r["ratio"], 2)) if r["ratio"] is not None else "--",
             num(r["sla_km2"], 3), num(r["hp"], 1),
             "both zero" if r["both_zero"] else ("within $\\times 3$" if r["within3"] else "\\textbf{no}")]
            for r in V["fujita2"]]
    open(os.path.join(OUT, "tab_fujita2.tex"), "w").write(table(
        "Potential flood volume for every Nepalese lake in \\citet{fujita2013} Table~2, "
        "recomputed from the Copernicus DEM GLO-30 against their ASTER-derived published values.",
        "tab:fujita2",
        ["Lake", "PFV pub.", "PFV ours", "Ratio", "SLA ours (km$^2$)", "$H_p$ ours (m)", "Agreement"],
        rows, "lcccccc",
        note="Volumes in $10^6$\\,m$^3$. Agreement is exact for lakes with no steep lakefront and "
             "good above about 5$\\times 10^6$\\,m$^3$; smaller published values are not recovered "
             "at 30\\,m resolution."))

    KIND = {"depth": "maximum depth (m)",
            "volume": "volume ($10^6$\\,m$^3$)",
            "qp": "peak discharge (m$^3$\\,s$^{-1}$)"}
    def obsfmt(s):
        return (esc(s).replace("+/-", "$\\pm$").replace(" m3/s", "")
                .replace(" Mm3", "").replace(" m ", " "))
    rows = [[esc(e.get("lake", "")), KIND.get(e.get("kind"), esc(e.get("kind", ""))),
             obsfmt(e["observed"]), num(e["p50"], 1),
             f"{num(e['lo'],1)}--{num(e['hi'],1)}",
             "$\\bullet$" if e["within"] else "$\\times$"]
            for e in V["events"]]
    open(os.path.join(OUT, "tab_observations.tex"), "w").write(table(
        "Model estimates against measured or reconstructed values. Units are given "
        "in the quantity column and apply to the observed value, the median and the "
        "interval alike.",
        "tab:obs",
        ["Lake", "Quantity", "Observed", "Median", "95\\% interval", "Contains"],
        rows, "lllccc",
        note="Sources: Imja Tsho depth and volume from the 2012 sonar survey of "
             "\\citet{somos2014}; Dig Tsho peak discharge from \\citet{vuichard1987} and the "
             "reconstruction of \\citet{cenderelli2001}. The inventory polygon for Imja Tsho is a "
             "later and larger extent than the lake that was surveyed."))

    rows = []
    for rank, p in enumerate(sorted(pri, key=lambda x: -(x["pfv_Mm3"] or 0)), 1):
        rows.append([str(rank), esc(p["name"] or "unnamed"), esc(p["district"]),
                     num(p["area_km2"], 3), num(p["pfv_Mm3"], 1),
                     num(p["qp_m3s"]), num(p["route_km"], 0),
                     num(p["pop_high"]), num(p["n_hydropower"]),
                     esc(p["hazard"]), esc(p["risk"] or "--")])
    open(os.path.join(OUT, "tab_priority.tex"), "w").write(table(
        "The \\NPriority\\ lakes whose potential flood volume exceeds the "
        "$10 \\times 10^6$\\,m$^3$ screening threshold of \\citet{fujita2013}.",
        "tab:priority",
        ["\\#", "Lake", "District", "$A$ (km$^2$)", "PFV", "$Q_p$ (m$^3$\\,s$^{-1}$)",
         "Path (km)", "People", "Hydro.", "Hazard", "Risk"],
        rows, "rllcccccclc",
        note="PFV in $10^6$\\,m$^3$; $Q_p$ is the pooled median with a 95\\% interval spanning "
             "roughly two orders of magnitude (Sect.~\\ref{sec:limits}). People counts those "
             "within 1\\,km of the routed channel in the WorldPop 2020 unconstrained grid; the "
             "constrained grid gives a lower figure. Unnamed lakes carry no name in any previous "
             "Nepalese inventory. The numbers key to Fig.~\\ref{fig:map}."))

    if sens:
        rows = [[esc(r["variant"]), str(r["n_with_sla"]), str(r["n_priority"]),
                 num(r["total_pfv_Mm3"], 0),
                 num(r["median_ratio_to_reference"], 2),
                 str(r["n_avalanche"]), str(r["n_rockfall"]),
                 str(r["priority_set_changed"])]
                for r in sens["variants"]]
        open(os.path.join(OUT, "tab_sensitivity.tex"), "w").write(table(
            "Sensitivity of the terrain products to the implementation choices this work had to "
            "make, over the \\SensSample\\ lakes of at least "
            f"{sens['sample_min_area_km2']}\\,km$^2$.",
            "tab:sensitivity",
            ["Variant", "SLA $>0$", "Priority", "$\\sum$PFV", "Median ratio",
             "Avalanche", "Rockfall", "Priority flips"],
            rows, "lccccccc",
            note="$\\sum$PFV in $10^6$\\,m$^3$. Median ratio is the per-lake potential flood "
                 "volume relative to the reference configuration, over lakes with a non-zero "
                 "value in both. Priority flips counts lakes crossing the "
                 "$10\\times10^6$\\,m$^3$ threshold relative to the reference."))

    rows = [[esc(c["name"]), "pass" if c["pass"] else "\\textbf{FAIL}", esc(c["detail"])[:110]]
            for c in V["checks"]]
    open(os.path.join(OUT, "tab_checks.tex"), "w").write(table(
        "Internal consistency and validation checks executed by \\texttt{src/validate.py}. "
        "The build fails if any does not pass.",
        "tab:checks", ["Check", "Result", "Detail"], rows,
        "p{0.33\\linewidth}lp{0.45\\linewidth}", note=None, fit=False))

    print(f"wrote {len(os.listdir(OUT))} files to paper/generated/")
    print(f"  macros: {len(m)} values")


if __name__ == "__main__":
    main()
