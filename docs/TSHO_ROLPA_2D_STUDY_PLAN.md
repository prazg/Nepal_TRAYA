# Tsho Rolpa 2D Hydrodynamic GLOF Pilot Study Plan (`TRAYA-011`)

**Document ID:** `TRAYA-011` | **Milestone:** `v2.2-science` (Wave C design) → `v3.0-pilot` (Wave D execution)  
**Target Glacial Lake:** **Tsho Rolpa** (`GL_27.86029_86.47725`) — Rolwaling Valley, Gaurishankar Rural Municipality, Dolakha District, Bagmati Province, Nepal (`27.8603° N, 86.4772° E`, `4,546 m a.s.l.`)  
**Parent Glacier:** Trakarding Glacier (`RGI2000-v7.0-G-15-08533`)  
**Downstream Corridor:** Rolwaling Khola → Tama Koshi → Sun Koshi Confluence at Khurkot (`102.6 km` core study domain; `120.5 km` TRĀYA routed screening limit)

> **Scientific Purpose & Non-Operational Boundary:**
> TRĀYA's national GLOF screening (`src/models_glof.py`, `src/routing.py`) uses empirical peak-discharge scaling and a 1 km horizontal river buffer — **not** 2D flood hydraulics. This protocol specifies a **fully reproducible, open-source 2D hydrodynamic case study** for Tsho Rolpa to: (1) produce physically based depth, velocity, and arrival-time envelopes along Rolwaling–Tama Koshi; (2) evaluate vulnerability at critical national infrastructure including **Upper Tamakoshi HPP (456 MW)** and **Singati Community Hospital**; and (3) quantify the false-positive/false-negative error bounds of TRĀYA's 1 km national screening buffer. All results remain research products until formally reviewed with **DHM** and **NDRRMA**.

---

## 1. TRĀYA 2.0 Screening Baseline & Motivation for 2D Upgrading

From TRĀYA's validated baseline (`data/lakes.json`, `data/routes.json`, `data/validation.json`), Tsho Rolpa ranks as Nepal's highest-priority proglacial lake (`priority: true`, `hazard: very high` under both general and enumerated Rounce readings):

| Baseline Metric (`GL_27.86029_86.47725`) | TRĀYA 2.0 Screening Value | Notes & Relevance to 2D Study |
| --- | --- | --- |
| **Lake Area & Trend** | `1.6638 km²` (`+4.1%`, `expanding`) | Ice-contact calving lake (`dist_glacier_m = 0`) |
| **Surface Elevation** | `4,546 m a.s.l.` (Copernicus DEM) | Local historic survey datum ~`4,577 m` post-2000 lowering |
| **Steep Lakefront Area (SLA)** | `0.3975 km²`, max angle `21.8°` | Strongly exceeds Fujita $10°$ threshold; ice-cored moraine documented (Yamada, 1998) |
| **Dynamic Triggers** | Avalanche (`38.5°`, `8.3 Mm³`), Rockfall (`20.3°`), Upstream GLOF (`true`) | All three dynamic susceptibility flags active |
| **Lowering Height $H_p$ / Mean Depth $D_m$** | $H_p = 66.6\text{ m}$ / $D_m = 62.5\text{ m}$ | $D_m$-limited PFV $= 103.93\text{ Mm}^3$ (`[76.91–130.95 Mm³]` $\pm 26\%$; vs. Fujita 2013 `89.6 Mm³`) |
| **Empirical Volume (Veh et al. half-ellipsoid)** | `135.72 Mm³` (depth `122 m`, 95% CI `46–335 m`) | Exceeds surveyed bathymetry (~`86–100 Mm³`), motivating direct sonar bathymetry integration |
| **Walder–O'Connor $Q_p$ (Pooled / Scenarios)** | Pooled `6,004 m³/s` (`95% CI: 130–146,888`); 10/30/50/100% = `929 / 7,167 / 11,737 / 12,347 m³/s` | Ratio `qp_over_mean_flow = 1,913`; massive 95% empirical span requires physical breach routing |
| **Seismic Context** | `19` $M \ge 5$ events within `50 km`; nearest $M \ge 6$ at `40.6 km` | Proximity to the 12 May 2015 $M_w 7.3$ Dolakha earthquake & active normal grabens (`42.0 km`) |
| **1 km Buffer Exposure (TRĀYA Screening)** | `29,322–40,620` people; `15` named settlements; `89` bridges; `3` health facilities; **`0` OSM hydropower** | **Critical OSM Blind Spot:** Upper Tamakoshi HPP (`456 MW`, Gonggar at `31.6 km`) & Khimti I HPP (`60 MW`, ~`77 km`) are missing from OSM `plant:source=hydro` tags — proving why 2D site-specific inventory auditing is essential |

---

## 2. Bathymetry & Historical Volume Evolution

Unlike unmapped Himalayan lakes where TRĀYA must rely on the empirical depth–area posterior, Tsho Rolpa has a multi-decade bathymetric survey record that MUST anchor the 2D study's stage–volume–area curve $V(z)$:

| Survey Epoch | Primary Reference | Area ($\text{km}^2$) | Max Depth ($\text{m}$) | Stored Volume ($\text{Mm}^3$) | Key Glaciological Notes |
| --- | --- | --- | --- | --- | --- |
| **1957–1959** | Survey of India / Yamada (1998) | `~0.23` | — | — | Initial coalescence of supraglacial ponds on Trakarding tongue |
| **1993–1994** | WECS / JICA / Damek; Yamada (1998) | `1.39` | `131–135` | `~76.6` | Deep asymmetric basin; steep ice-cored terminal moraine identified |
| **1999–2000** | DHM / Reynolds Geo-Sciences / Rana et al. (2000) | `~1.54` | `~132` (post-lowering) | `~85.9` | Post-3 m sluice lowering (~`4.5 Mm³` drained) |
| **2009–2019** | ICIMOD (2011); DHM / field sonar re-surveys; satellite shorelines | `1.54–1.65` | `~132–135` | `~86–100+` | Continued up-valley calving retreat of Trakarding Glacier; current TRĀYA polygon `1.6638 km²` |

### Bathymetric & Topographic DEM Assembly Protocol
1. **Lakebed Elevation Model:** Digitize and georeference published sonar depth contours / sounding tracks (Yamada, 1998; Rana et al., 2000; ICIMOD/DHM updates where accessible via `TRAYA-006` collaboration), extending the post-2000 up-valley calving expansion zone smoothly to the modern Trakarding ice cliff using a constrained bathymetric interpolation validated against total volume bounds (`86–105 Mm³`).
2. **Sub-Aerial Valley DEM Hierarchy (Multi-Resolution Testing):**
   - **Baseline Open DEM (Tier A):** **High Mountain Asia 8 m DEM** (Shean, 2017, NSIDC) mosaicked and void-filled with **Copernicus DEM GLO-30** (`30 m`, vertical datum EGM2008).
   - **Moraine & Critical Infrastructure Refinement (Tier B — Partner Data):** Where acquired under DHM/NDRRMA/ICIMOD academic partnership, substitute 1–2 m stereo Pléiades / UAV DSMs over the terminal moraine (`0–2 km`), Gonggar powerhouse/tailrace (`30–33 km`), and Singati Bazaar (`45–48 km`).
3. **Hydrological Conditioning:** Burn verified channel thalwegs beneath bridge decks and narrow overhanging rock walls (Rolwaling Gorge `14–28 km`) where satellite stereo DEMs create artificial "bridge dams" or cliff-shadow spikes that otherwise trap simulated floodwaters.

---

## 3. 1998–2000 Lowering Engineering History & End-Moraine Geotechnics

Any realistic breach scenario for Tsho Rolpa must explicitly represent the engineered terminal moraine geometry left by Nepal's landmark **Tsho Rolpa GLOF Risk Reduction Project (1998–2000)**:

- **Phase 0 — Trial Siphons & Early Warning (1995–1997):** Following the 1991 Chhubung (Ripimoshar) GLOF in the neighboring Rolwaling tributary, DHM and international partners installed experimental HDPE siphons and a meteor-burst / acoustic siren EWS extending down Rolwaling and Tama Koshi to Busti/Khimti. The legacy EWS subsequently suffered maintenance, power, and conflict-era degradation and is **not** assumed operational in this protocol.
- **Phase I — Engineered Open-Channel Lowering (1998–2000):** Implemented by **DHM / Government of Nepal** with funding from the **Netherlands (NEDA)** and **World Bank** (Reynolds, 1999; Rana et al., 2000). Engineers excavated a **~70 m long, 4.2 m wide gated open channel and gabion/concrete-lined spillway** through the southwestern end moraine, successfully lowering the lake level by **3.0 m** by June 2000 (draining $\sim 4.5\text{ Mm}^3$ and reducing hydrostatic pressure on the moraine crest).
- **Unexecuted Phase II:** Original geotechnical designs proposed a further **17 m lowering (20 m total)** to permanently neutralize outburst risk; Phase II was deferred due to high-altitude logistics, cost, and the hazard of exposing buried dead ice during deep excavation.
- **Residual Structural Vulnerabilities:**
  1. **Ice-Cored Moraine Subsidence:** Continued permafrost/dead-ice degradation inside the ~150 m tall terminal moraine complex (`SLA = 21.8°`) drives localized thermokarst settlement and piping pathways.
  2. **Spillway Flanking & Overtopping:** An impulse wave generated by a hanging-ice avalanche (`8.3 Mm³` source potential on surrounding steep headwalls) or Trakarding calving event could overtop the lined spillway walls, initiating rapid headcut erosion into unconsolidated glacial till.
  3. **Seismic Pre-Conditioning:** The 2015 $M_w 7.8$ Gorkha / $M_w 7.3$ Dolakha sequence (`40.6 km` from Tsho Rolpa) underscored the vulnerability of steep moraine slopes and surrounding rockwalls to strong ground motion.

---

## 4. Breach Hydrograph Boundary Conditions

Because moraine-breach mechanics carry order-of-magnitude parametric uncertainty, the protocol mandates a **4-scenario breach ensemble $\times$ 3 sediment-bulking factors** rather than a single deterministic run.

### 4.1 Upstream Breach Scenarios (`CP-01`, Outlet `0.0 km`)

| Scenario ID | Physical Failure Mechanism | Breach Depth $h_b$ ($\text{m}$) | Released Volume $V_0$ ($\text{Mm}^3$) | Target Clear-Water $Q_p$ ($\text{m}^3\text{ s}^{-1}$) | Breach Formation Time $t_f$ ($\text{hr}$) | TRĀYA Empirical Alignment |
| --- | --- | --- | --- | --- | --- | --- |
| **S1 — Spillway Overtopping / Partial Incision** | Hanging-ice avalanche wave overtops 2000 sluice & erodes upper till | `10–15` | `15–22` | `1,500–3,500` | `0.8–1.5` | `qp_10`–`qp_20` range |
| **S2 — Moderate Moraine Failure (Reference Case)** | Dead-ice piping / retrogressive headcut erosion across terminal moraine | `20–30` | `30–45` | `5,500–7,500` | `1.0–2.0` | TRĀYA pooled median (`6,004`) / `qp_30` (`7,167`) & Shrestha & Nakagawa (2014) |
| **S3 — Major End-Moraine Collapse** | Deep moraine incision triggered by combined seismic weakening + ice avalanche | `40–50` | `55–72` | `10,000–13,000` | `1.2–2.5` | `qp_50` (`11,737`) |
| **S4 — Extreme PFV Upper-Bound Stress Test** | Catastrophic drawdown approaching full Fujita $H_p = 66.6\text{ m}$ lowering envelope | `60–66` | `85–104` | `13,000–20,000` | `1.5–3.0` | `qp_100` (`12,347`) / PFV (`103.9 Mm³`) |

### 4.2 Hydrograph Parameterization, Sediment Bulking & Baseflow
- **Parametric Breach Inflow Generator:** Compute breach width, side slopes, and failure time $t_f$ using **Froehlich (2008 / 2016)** empirical embankment/moraine breach equations coupled with the lake's bathymetric stage–volume curve $V(z)$ and broad-crested weir outflow $Q(t) = C_d B(t) [z_{\text{lake}}(t) - z_{\text{breach}}(t)]^{3/2}$ — cross-checked against **BASEMENT** physically coupled 2D moraine erosion runs.
- **Sediment-Bulking Multipliers:** Himalayan GLOFs rapidly entrain valley-floor glacial till and boulders (e.g., 1985 Dig Tsho, 2016 Bhote Koshi, 2023 South Lhonak), inflating flow volume and stage. Each scenario S1–S4 is run at three bulking levels:
  - `B1.0` (clear water, $C_v = 0\%$, lower-bound reference)
  - `B1.3` (hyperconcentrated sediment-laden flood, $\sim 23\%$ solids by volume — primary planning envelope)
  - `B1.6` (debris-bulked surge in upper Rolwaling Gorge, $\sim 37\%$ solids by volume — upper-bound sensitivity)
- **Lateral Tributary Baseflow:** Initialize Rolwaling Khola and Tama Koshi mainstem (entering at Chetchet `28.8 km` from Lamabagar) under two seasonal regimes: **Pre-Monsoon Dry** (May, low Tama Koshi baseflow ~`40–80 m³/s`) and **Peak Monsoon** (July–August, Tama Koshi mean monsoon flow ~`300–500 m³/s`, referencing historical DHM Busti / Lamabagar hydrographs).

---

## 5. Open-Source 2D Hydrodynamic Solver Configuration

To ensure full open-science reproducibility without proprietary HEC-RAS/MIKE licensing lock-in, the protocol specifies a **dual-solver intercomparison** using two peer-reviewed open-access 2D shallow-water engines:

### 5.1 Primary Solver A — `LISFLOOD-FP v8.1` (GPL-3, University of Bristol)
- **Numerical Scheme:** **`fv1` (First-Order Finite-Volume Godunov / Roe-type shock-capturing 2D shallow-water solver)** — explicitly preferred over the simplified `acceleration` (local-inertial) solver in Rolwaling Gorge (`0–29 km`), where bed slopes reach $5\%\text{–}15\%$ and supercritical transcritical jumps ($\mathrm{Fr} > 1$) invalidate diffusive/local-inertial assumptions. GPU (`CUDA`) acceleration supported for full-ensemble runs.
- **Grid Architecture:**
  - **Domain 1 (High-Resolution Upper Gorge & HPP Reach, `0–50 km`, Tsho Rolpa → Singati):** `8 m` (HMA DEM native) / `10 m` structured raster (~`2.5–4.0 M` active valley cells after corridor masking).
  - **Domain 2 (Full Corridor Attenuation Reach, `0–105 km`, Tsho Rolpa → Khurkot):** `20 m` / `30 m` (Copernicus DEM GLO-30) to capture downstream wave attenuation through Manthali and BP Highway.
- **Numerical & Boundary Parameters (`.par` template):**
  - `fv1` solver enabled; adaptive timestep controlled by `cfl = 0.5` (tested at `0.3` for stability); drying depth threshold `depthoff = 0.001 m`.
  - Upstream boundary: `QVAR` time-series hydrograph (`.bdy`) injected across a 5-cell inflow line immediately below the terminal moraine outlet.
  - Lateral inflow: constant/hydrograph `QFIX` on Tama Koshi mainstem just upstream of the Chetchet confluence (`28.8 km`).
  - Downstream boundary: `FREE` (zero-gradient outflow) placed `3 km` downstream of Khurkot confluence on Sun Koshi to eliminate boundary backwater artefacts.
  - **Spatially Distributed Manning's $n$** (classified from Copernicus Land Cover + slope):
    - Steep boulder-bed gorge channel (`0–29 km`): $n = 0.065$ (sensitivity `0.050–0.085`)
    - Alluvial braided Tama Koshi channel (`29–103 km`): $n = 0.045$ (sensitivity `0.035–0.060`)
    - Valley terraces, farmland & forest floodplain: $n = 0.085\text{–}0.110$
    - Urban/bazaar footprints (Singati, Manthali, Khurkot): $n = 0.100$

### 5.2 Secondary / Cross-Validation Solver B — `BASEMENT v4` (ETH Zürich, Free Scientific Access)
- **Why Dual-Solver?** `BASEMENT v4` uses an **unstructured triangular finite-volume mesh** (`.2dm`) solving full 2D shallow-water equations (`BASEplane`) with optional **mobile-bed sediment transport (`BASEmorph` — Meyer-Peter & Müller / Smart & Jäggi steep-slope bedload)**, directly testing how boulder erosion/deposition alters peak stage at Gonggar and Singati!
- **Mesh Refinement Strategy:**
  - `3–5 m` edge length along Rolwaling/Tama Koshi channel thalweg, terminal moraine breach zone, Gonggar tailrace/NH28 bridges, and Singati Bridge/Hospital reach.
  - `15–25 m` on valley terraces and floodplains; `50 m` on steep valley sidewalls above maximum runup elevation.
- **Reproducible Packaging:** All pre-processing scripts (DEM conditioning, hydrograph generation, GeoJSON/COG post-processing) will live under `studies/tsho_rolpa_2d/` with pinned container definitions (`Dockerfile` / `Apptainer`) and deterministic SHA-256 input manifests. Only lightweight pre-computed GeoJSON flood envelopes and checkpoint hydrographs (`<500 KB`) will ever be exported to TRĀYA's static `data/` directory, preserving TRĀYA's zero-backend GitHub Pages architecture.

---

## 6. Rolwaling–Tama Koshi & Upper Tamakoshi HPP Checkpoints

Every simulation run extracts complete time-series of water surface elevation (WSE), maximum depth $h_{\max}$, maximum depth-averaged velocity $v_{\max}$, specific energy/stream power ($h \cdot v$), wave-front arrival time $t_{\text{arr}}$ ($h > 0.5\text{ m}$), and peak-stage time $t_{\text{peak}}$ at **10 mandatory checkpoints** anchored to TRĀYA's verified route distances (`data/routes.json`):

| ID | Checkpoint Name | Routed Distance (`km`) | Approx. Elevation (`m`) | Exposed Assets & Engineering / Emergency Significance |
| --- | --- | --- | --- | --- |
| **CP-01** | **Tsho Rolpa Terminal Moraine & Sluice Outlet** | `0.0` | `4,546` | Inflow hydrograph verification & moraine breach cross-section |
| **CP-02** | **Na Village** (Rolwaling Valley) | `6.3` | `~4,180` | First high-alpine settlement & trekking lodges; ultra-short lead time (`10–50 min` screening bracket) |
| **CP-03** | **Beding Village** (Rolwaling Valley) | `12.2` | `~3,700` | Principal Sherpa village, school & local health post; valley floor vs. terrace elevation separation check |
| **CP-04** | **Chhimu / Ramding Gorge** | `13.2–13.4` | `~3,450` | Steep narrow bedrock/boulder constriction; tests supercritical shock-capturing & debris jamming |
| **CP-05** | **Simi Gaun & Chetchet (Rolwaling–Tama Koshi Confluence)** | `28.6–28.8` | `~1,360` | Major tributary junction (`~3,180 m` vertical drop from lake!); hydraulic backwater into Tama Koshi & trailhead road access |
| **CP-06** | **Gonggar — Upper Tamakoshi HPP (456 MW) Powerhouse, Tailrace & NH28 Bridges** | `31.6` | `~1,270` | **Flagship National Energy Asset.** *Key geometric nuance:* Upper Tamakoshi's concrete dam/intake at **Lamabagar** lies `~8 km` *upstream* on Tama Koshi (above the Rolwaling confluence), whereas the **underground powerhouse access tunnel portal, tailrace outfall, switchyard, staff quarters, and NH28/F106 bridges at Gonggar** sit directly on the Tama Koshi floodway. Model evaluates tailrace back-flooding stage, portal sill clearance, and bridge scour velocity |
| **CP-07** | **Thadi / Jagat (NH28 Corridor)** | `32.9–34.2` | `~1,150` | Steep valley highway benches & multiple NH28 bridges (`34.7–40.6 km`) vulnerable to lateral undercut |
| **CP-08** | **Singati Bazaar, Singati Bridge & Singati Community Hospital** | `46.2–46.6` | `~950` | Major northern Dolakha market hub, **critical NH28 road-cut chokepoint**, and referral hospital (`46.6 km`, `road-cut hospital isolation` benchmark for `MC-5`) |
| **CP-09** | **Busti / Khimti (Khimti I 60 MW HPP Confluence & NH28)** | `75.0–77.2` | `~600` | Khimti I hydropower tailrace/switchyard reach, historic DHM Busti hydrological station, and 1998 EWS acoustic siren verification reach |
| **CP-10** | **Manthali & Khurkot (BP Highway NH03 / Sun Koshi Confluence)** | `91.4–102.6` | `~470` | Ramechhap district headquarters, Manthali Airport river terrace (`91.4 km`), Khurkot–Manthali & BP Highway bridges (`100.0–102.6 km`), and downstream attenuation boundary |

---

## 7. Validation Criteria & Acceptance Gates

Before any 2D inundation footprint or checkpoint envelope from this protocol is published on TRĀYA or shared for institutional planning, **all six validation criteria** must pass and be documented in a companion validation report:

1. **Numerical Mass Conservation:** Global domain mass-balance error
   $$\varepsilon_V = \frac{\left|V_{\text{in}} - (V_{\text{out}} + V_{\text{stored}})\right|}{V_{\text{in}}} < 1.0\%$$
   across every scenario S1–S4 in both `LISFLOOD-FP` and `BASEMENT`.
2. **Inter-Solver Consistency (`LISFLOOD-FP` vs. `BASEMENT`):** Clear-water peak discharge $Q_p(x)$ agrees within $\pm 15\%$ and front arrival time $t_{\text{arr}}(x)$ agrees within $\pm 20\%$ across `CP-05` through `CP-09`; any divergence in narrow gorges (`CP-04`) is diagnosed and reported explicitly.
3. **Literature & Regional Benchmark Consistency:** Simulated attenuation curves and reach-averaged front velocities are cross-checked against prior Tsho Rolpa studies (Rana et al., 2000; ICIMOD, 2011; Shrestha & Nakagawa, 2014; Sattar et al., 2021) and observed Himalayan GLOF surge speeds (1985 Dig Tsho `4–5 m/s`; 2016 Bhote Koshi; 2023 South Lhonak).
4. **DEM-Resolution & Roughness Sensitivity Audit:** Explicitly publish stage and inundation-width spreads across (a) `8 m` HMA DEM vs. `30 m` Copernicus DEM, (b) Manning's $n \pm 25\%$, and (c) bulking `B1.0` vs. `B1.3` vs. `B1.6` at every checkpoint `CP-02`–`CP-10`.
5. **Calibration of TRĀYA's 1 km National Screening Buffer:** Compute exact confusion metrics comparing TRĀYA's 1 km corridor (`data/routes.json`, `data/exposure.json`) against the 2D `S2 × B1.3` flood footprint:
   - **Buffer Over-Prediction Rate:** fraction of settlements/population inside the 1 km buffer sitting safely on elevated valley terraces above peak 2D flood stage.
   - **OSM Under-Detection Rate:** critical assets intersected by the 2D flood footprint that were absent from OSM tags (explicitly documenting Upper Tamakoshi HPP at `CP-06` and Khimti HPP at `CP-09`).
6. **External Peer & Statutory Technical Review:** Independent review of model setup, bathymetry assumptions, and Gonggar/Singati checkpoint interpretations by Nepalese hydrologists/glaciologists (DHM / ICIMOD / Tribhuvan University) prior to any Wave D (`v3.0-pilot`) visualization rollout.

---

## 8. Execution Phases & Resource Footprint

| Phase | Milestone | Deliverables | Compute / Data Requirement |
| --- | --- | --- | --- |
| **Phase 1 — Protocol & Governance** *(Complete)* | `v2.2-science` (`TRAYA-011`) | This reproducible study plan, checkpoint coordinates, and screening baseline audit | Zero external compute |
| **Phase 2 — Open DEM & Clear-Water Ensemble** | `v3.0-pilot` (`TRAYA-013`) | Conditioned 8 m HMA + 30 m Copernicus DEM, bathymetric stage–volume curve, `LISFLOOD-FP` S1–S4 × B1.0–B1.6 ensemble | Workstation / cloud GPU (~20–40 GPU-hours) |
| **Phase 3 — `BASEMENT` Mobile-Bed Cross-Check & Calibration** | `v3.0-pilot` (`TRAYA-013`) | Unstructured mesh `BASEMENT v4` verification at `CP-05`–`CP-09`, 1 km buffer error audit, open Zenodo data deposit | Multi-core CPU / HPC node + DHM/ICIMOD review |
| **Phase 4 — Static TRĀYA Pilot Layer** | `v3.0-pilot` (`TRAYA-013`) | Compact pre-computed GeoJSON envelopes (`data/pilots/tsho_rolpa_2d.json`) with strict non-operational caveats & bilingual `EN/NE` narrative | Static JSON (`<500 KB`), zero backend |

---

## Key Scientific References

- Fujita, K. et al. (2013). Potential flood volume of Himalayan glacial lakes. *Nat. Hazards Earth Syst. Sci.*, 13, 1827–1839.
- ICIMOD (2011). *Glacial Lakes and Glacial Lake Outburst Floods in Nepal*. International Centre for Integrated Mountain Development, Kathmandu.
- Rana, B., Shrestha, A. B., Reynolds, J. M., Aryal, R., Pokhrel, A. P., & Budhathoki, K. P. (2000). Hazard assessment of the Tsho Rolpa Glacier Lake and ongoing remediation measures. *Journal of Nepal Geological Society*, 22, 563–570.
- Reynolds, J. M. (1999). Glacial hazard assessment at Tsho Rolpa, Rolwaling, Central Nepal. *Q. J. Eng. Geol. Hydrogeol.*, 32(3), 209–214.
- Rounce, D. R. et al. (2016). A new remote hazard and risk assessment framework for glacial lakes in the Nepal Himalaya. *Hydrol. Earth Syst. Sci.*, 20, 3455–3475.
- Sattar, A. et al. (2021). Future glacial lake outburst flood (GLOF) hazard of the South Lhonak Lake, Sikkim Himalaya / comparative Himalayan 2D GLOF protocols. *Geomorphology*, 388, 107783.
- Shaw, J., Kesserwani, G., Neal, J., Bates, P., & Sharifian, M. K. (2021). LISFLOOD-FP 8.0: the new discontinuous Galerkin shallow-water solver for multi-core CPUs and GPUs. *Geosci. Model Dev.*, 14, 3577–3602.
- Shrestha, B. B., & Nakagawa, H. (2014). Assessment of potential outburst floods from the Tsho Rolpa glacial lake in Nepal. *Natural Hazards*, 71, 913–936.
- Veh, G., Korup, O., & Walz, A. (2020). Hazard from Himalayan glacier lake outburst floods. *PNAS*, 117(2), 907–912.
- Yamada, T. (1998). *Glacier Lake and Its Outburst Flood in the Nepal Himalaya*. Monograph No. 1, Data Center for Glacier Research, Japanese Society of Snow and Ice.
