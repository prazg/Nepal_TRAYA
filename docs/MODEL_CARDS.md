# Scientific Model Cards — Nepal TRĀYA 2.0

These model cards document the scientific design, inputs, governing physics/algorithms, validation benchmarks, known limitations, and uncertainty bounds of all six analytical screening models in **Nepal TRĀYA 2.0**. They follow a geophysical adaptation of *Model Cards for Model Reporting* (Mitchell et al., 2019) so researchers, planners, and reviewers can audit every assumption before citing any number.

> **Platform-Wide Non-Operational Safety Warning (गैर-सञ्चालनात्मक चेतावनी):**
> **None of the six models below is an operational early warning system (EWS), a probabilistic failure forecast, or a site-specific engineering design study.** Outputs are screening-level indicators refreshed on a 7-day cycle (with optional in-browser live queries). For life-safety decisions in Nepal, rely exclusively on statutory authorities: **DHM Flood Hotline `1155`** ([hydrology.gov.np](https://hydrology.gov.np/)), **NDRRMA / NEOC `1149`** ([bipadportal.gov.np](https://bipadportal.gov.np/)), **DMG / NEMRC** ([seismonepal.gov.np](https://seismonepal.gov.np/)), **Police `100`**, **Ambulance `102`**, and **APF Search & Rescue `1114`**.

---

## Summary of Models

| ID | Model Name | Implementation Module(s) | Primary Output(s) | Cadence | Operational Status |
| --- | --- | --- | --- | --- | --- |
| **MC-1** | GLOF Susceptibility, PFV & Walder–O'Connor $Q_p$ | `src/terrain.py`, `src/models_glof.py`, `src/hazard.py`, `src/validate.py`, `src/sensitivity.py` | `data/lakes.json`, `data/model_fit.json`, `data/validation.json`, `data/sensitivity.json` | Static GIS baseline (Tier 2 rebuild) | Screening only — NOT breach probability |
| **MC-2** | GloFAS Gumbel EV1 River Flood Watch | `src/floods.py`, `assets/app.js` (live re-grading) | `data/rivers_watch.json`, `cache/glofas_climatology.json` | 7-day CI + on-demand live browser refresh | Basin screening — NOT DHM gauge stage |
| **MC-3** | Dahal–Hasegawa Rainfall-Landslide Screening | `src/hydromet.py`, `assets/app.js` (live re-grading) | `data/hydromet_weekly.json` | 7-day CI + on-demand live browser refresh | Regional I-D screening — NOT slope stability |
| **MC-4** | 5-Type National Landslide Inventory & Duplicate Matcher | `src/landslides.py`, `src/integrations/bipad.py`, `schemas/landslide_event.v1.schema.json` | `data/landslides.json`, `data/landslide_review_queue.json`, `data/landslide_inventory.geojson` | 7-day CI + BIPAD/COOLR sync | Situational catalogue — strict lower bound |
| **MC-5** | 1 km Corridor Exposure & Road-Cut Hospital Isolation | `src/routing.py`, `src/exposure.py`, `src/exposure_isolation.py` | `data/routes.json`, `data/exposure.json`, `data/exposure_isolation.json` | Static routing + weekly/OSM refresh | Screening buffer — NOT 2D flood extent or live DoR status |
| **MC-6** | Interpretable Directed Cascade Graph | `src/cascades.py` | `data/cascades.json` + district triage overlays | 7-day CI + live provenance propagation | Rule-based coupling indicator — NOT joint probability |

---

## MC-1: GLOF Susceptibility, PFV & Walder–O'Connor $Q_p$

### Intended Use
- National-scale first-order screening and comparative triage across all **1,429 mapped glacial lakes** in Nepal to identify candidate lakes warranting high-resolution bathymetric surveys, field geotechnical inspection, and 2D hydrodynamic modelling (such as the Tsho Rolpa protocol in [`docs/TSHO_ROLPA_2D_STUDY_PLAN.md`](TSHO_ROLPA_2D_STUDY_PLAN.md)).
- Transparent audit of methodological sensitivity between published Himalayan GLOF screening frameworks (Fujita et al., 2013; Rounce et al., 2016; Veh et al., 2020).

### Out-of-Scope / Non-Operational Warning
- **Does NOT compute probability of dam failure** in any time window.
- **Does NOT simulate 2D dam-breach hydraulics, debris bulking, or inundation depth.**
- **$\mathrm{PFV} = 0$ is NOT a certificate of safety:** small flood volumes ($<5\text{ Mm}^3$) are systematically under-detected on a 30 m DEM, and unmapped buried ice cores in moraines make hazard classes **lower bounds** for 1,424 of 1,429 lakes.

### Inputs
- **Lake & Glacier Geometries:** 1,429 glacial lake polygons (`Nepal Cryosphere Inventory`) and 4,679 glacier outlines (`RGI 7.0`).
- **Topography:** Copernicus DEM GLO-30 (`30 m`, $1° \times 1°$ COG tiles).
- **Published Calibration Data (CC BY 4.0, Zenodo `3523213`):**
  - Veh et al. (2020) depth-area MCMC posterior (`mcmcChain.rds`, `100,002` draws from 24 Himalayan bathymetric surveys).
  - O'Connor & Beebee (2009) compilation of `63` natural dam-break events (`beebee-oconnor-2009-data.rds`) and `19` published breach rates $k \in [3.7\times10^{-4},\; 1.1\times10^{-1}]\text{ m s}^{-1}$.
- **Literature Ice-Core Registry:** 5 lakes with peer-reviewed evidence of ice-cored moraines (`Imja Tsho`, `Lower Barun Tsho`, `Thulagi Tsho`, `Tsho Rolpa`, `Chamlang South Tsho`; Rounce et al., 2016 Table 5).

### Physics / Algorithm
1. **Mass-Movement Susceptibility (Rounce et al., 2016):**
   - Local slope computed via $3 \times 3$ Horn (1981) finite differences with latitude-corrected WGS84 cell spacing.
   - Depressions filled in `float64` using Barnes et al. (2014) Priority-Flood+$\varepsilon$ so single-flow-direction (D8) routes terminate cleanly in the lake sink without flat-cell stalls.
   - Source thresholds: glacierised ice/snow avalanche $45° < \text{slope} < 60°$ (Alean, 1985; Osti et al., 2011; Shea et al., 2015); non-glacierised rockfall $\text{slope} > 30°$ (Bolch et al., 2011).
   - Runout reach angle (Fahrböschung) evaluated along routed D8 path length: rockfall $\ge 20°$; avalanche volume-dependent threshold $\tan\alpha = 1.111 - 0.118\log_{10}V$ for $V < 6.67\times10^6\text{ m}^3$ and fixed $17°$ above (Huggel et al., 2004). Coherent slab detachment area is capped at $5.0\times10^5\text{ m}^2$ ($0.5\text{ km}^2$) with representative thickness $15\text{ m}$, plus explicit $10 / 30 / 50\text{ m}$ scenario outputs.
2. **Moraine Self-Destruction & Potential Flood Volume (Fujita et al., 2013):**
   - Steep Lakefront Area (SLA): depression angle $>10°$ from lake surface within $1,000\text{ m}$ requiring a contiguous patch of $\ge 4$ DEM cells to suppress pixel noise.
   - Potential lowering height $H_p$ solved by bisection (capped at $300\text{ m}$ and flagged via `hp_capped`).
   - Empirical mean depth $D_m = 55\,A^{0.25}$ ($A$ in $\text{km}^2$, $D_m$ in $\text{m}$) and $\mathrm{PFV} = \min[H_p, D_m]\cdot A$. Priority triage threshold: $\mathrm{PFV} \ge 10\text{ Mm}^3$ (`16` priority lakes in Nepal).
3. **Bayesian Volume & Walder–O'Connor Peak Discharge (Veh et al., 2020):**
   - Posterior predictive depth draws: $\log_{10}(d) \sim \mathcal{N}(\beta_0 + \beta_1\log_{10}A,\; \sigma)$ (posterior means $\bar\beta_0 = -1.209$, $\bar\beta_1 = 0.531$, $\bar\sigma = 0.225$).
   - Half-ellipsoid lake volume $V = \frac{2}{3}Ad$ and released volume $V_0(h, c) = V - \pi r^2\left(\frac{2h}{3} - c + \frac{c^3}{3h^2}\right)$ for breach depth $c \le h$.
   - Dimensionless parameter $\eta = V_0^* k^* = \frac{V_0}{c^3}\cdot\frac{k}{\sqrt{gc}}$ mapped to $Q_p^* = Q_p / (g^{0.5}c^{2.5})$ via piecewise Student-$t_{\nu=10}$ maximum-likelihood fit to the 63-event dataset ($\alpha = 0.324$, $\beta = 0.942$, change-point $\log_{10}\eta_c = -0.557$, $\sigma = 0.287$, pseudo-$R^2 = 0.669$, $\mathrm{RMSE}_{\log_{10}} = 0.326$).
   - Breach rate $k$ drawn from unbiased lognormal fit to the 19 published rates ($\mu_{\ln} = -5.553$, $\sigma_{\ln} = 1.506$, capped at $k_{\max} = 0.22\text{ m s}^{-1}$).
   - Headline `pooled` distribution samples continuous breach fractions from scaled $\mathrm{Beta}(1,1)$ on $[0.05, 1.0]$ alongside fixed $10\%, 30\%, 50\%, 100\%$ scenarios. In the breach-rate-limited unsaturated regime ($\eta < \eta_c$), $Q_p \propto V_0^{0.942}k^{0.942}c^{-0.797}$, causing genuine algebraic non-monotonicity where a partial breach can exceed a 100% breach $Q_p$.
4. **Dual Hazard & Risk Classification (Rounce et al., 2016):**
   - Both readings of Rounce et al. (2016) Sect. 4.2 are computed and displayed side-by-side: **general rule** (`980` very high / `40` high / `363` moderate / `46` low) and **literal enumerated rule** (`3` very high / `198` high / `1,182` moderate / `46` low).

### Validation & Known Limitations
- **Automated Verification (`data/validation.json`, `29/29` checks passing):**
  - Rounce et al. (2016) Table 5 benchmarks (8 major lakes): avalanche `8/8`, rockfall `7/8`, production 4-cell SLA `6/8` (`7/8` unfiltered).
  - Fujita et al. (2013) Table 1: mean-depth $D_m$ `5/5`, PFV `5/5`.
  - Fujita et al. (2013) Table 2 (19 lakes): zero-PFV `9/9`, large PFV ($\ge 5\text{ Mm}^3$) `5/6` within $3\times$, small PFV ($<5\text{ Mm}^3$) **`0/4`** (confirming the 30 m Copernicus DEM resolution floor vs. 15 m ASTER).
  - Observed outburst/bathymetry brackets: `4/4` within 95% intervals (Imja 2012 depth $116.3\text{ m}$ vs. p50 $133.1\text{ m}$; Imja volume $61.7\text{ Mm}^3$ vs. half-ellipsoid p50 $154.2\text{ Mm}^3$, noting over-prediction of half-ellipsoid geometry; Dig Tsho 1985 $Q_p$ $1,600$ & $2,350\text{ m}^3\text{ s}^{-1}$ vs. p50 $970.4\text{ m}^3\text{ s}^{-1}$ $[16.2\text{–}25,753]$).
- **Sensitivity (`data/sensitivity.json`, 322 lakes $\ge 0.05\text{ km}^2$):**
  - Varying SLA angle from $8°$ to $15°$ swings aggregate PFV from $+20.2\%$ ($1,164.7\text{ Mm}^3$, 22 priority lakes) to $-25.9\%$ ($717.9\text{ Mm}^3$, 14 priority lakes); `179/229` ($78.2\%$) SLA lakes are $D_m$-limited.
  - **`977/1,429` lakes (`68.4%`)** shift hazard class between the general and enumerated Rounce readings.
- **Key Limitations:** Subsurface moraine ice is unassessed for 1,424 lakes; half-ellipsoid geometry can overestimate shallow irregular lakes by $\sim 1.5\text{–}2.5\times$; static DEM cannot detect recent moraine subsidence or ongoing glacier-calving lake expansion.

### Uncertainty Bounds
- **PFV:** $\pm 26\%$ reported baseline uncertainty (Fujita et al., 2013) plus DEM-resolution floor below $5\text{ Mm}^3$.
- **Maximum depth $d$:** 95% posterior predictive interval spans $\sim 2.5\text{–}3\times$ around median.
- **Peak discharge $Q_p$:** Typical factor-of-2 residual error ($\mathrm{RMSE}_{\log_{10}} = 0.326$) and 95% predictive interval spanning **2–3 orders of magnitude** (e.g., Tsho Rolpa median $6,004\text{ m}^3\text{ s}^{-1}$, 95% CI $130\text{–}146,888\text{ m}^3\text{ s}^{-1}$). Always report the full interval, never the median alone.

---

## MC-2: GloFAS Gumbel EV1 River Flood Watch

### Intended Use
- Basin-scale hydrological situational awareness and 30-day ensemble discharge trend screening across Nepal's **10 major trans-Himalayan and mid-hill river outlets** (*Mahakali, Karnali, Bheri, Babai, West Rapti, Kali Gandaki, Narayani, Bagmati, Saptakoshi, Kankai*).

### Out-of-Scope / Non-Operational Warning
- **NOT a replacement for DHM real-time river gauge telemetry** (`hydrology.gov.np`, hotline `1155`).
- **Cannot detect** localized cloudburst flash floods, debris flows, landslide-dam outburst floods (LDOFs), tributary dam releases, or barrage gate operations (e.g., Koshi Barrage, Kali Gandaki A, Sharada Barrage).

### Inputs
- **Copernicus EMS GloFAS v4** via Open-Meteo Flood API (`flood-api.open-meteo.com/v1/flood`, ~0.05° / ~5 km grid):
  - **Reanalysis climatology:** 29 complete calendar years (`1997–2025`, requiring $\ge 250$ valid daily values per year) stored in `cache/glofas_climatology.json`.
  - **Rolling window:** 30-day historical reanalysis + 30-day ensemble discharge forecasts (`river_discharge`, `median`, `mean`, `p25`, `p75`, `max`).
- **Reference Outlet Stations:** 10 DHM-referenced coordinates (`DHM-170` Mahakali through `DHM-795` Kankai) with physical sanity lower bounds (`GLOFAS_BASIN_SANITY_BOUNDS` in `src/config.py`).

### Physics / Algorithm
1. **3×3 Mainstem Grid-Cell Snapping:** On a ~5 km grid, raw gauge coordinates frequently fall on adjacent hillslope cells (underestimating discharge by $10\times\text{–}3,000\times$). Live refreshes probe the $3 \times 3$ neighborhood ($\pm 0.05°$) and select the cell maximizing $0.5\,\bar{Q} + 0.5\,Q_{\max}$, disclosing exact `grid_lat` / `grid_lon` and flagging violations of `expected_min_q50_m3s` via `grid_snap_warning` (`0/10` warnings currently).
2. **Pure-Stdlib Gumbel EV1 Return Levels:** Fitted by method of moments to the $N = 29$ annual maxima daily discharges:
   $$\alpha = \frac{s\sqrt{6}}{\pi}, \qquad \mu = \bar{x} - \gamma\alpha \quad (\gamma = 0.5772156649)$$
   $$Q_T = \mu - \alpha \ln\!\left(-\ln\!\left(1 - \frac{1}{T}\right)\right), \qquad T \in \{2, 5, 20\}\text{ yr}$$
   Monotonic hierarchy $Q_{50} \le Q_{90} \le Q_2 \le Q_5 \le Q_{20}$ is enforced alongside empirical daily percentiles ($Q_{50}, Q_{90}, Q_{99}$).
3. **Deterministic 5-Tier Grading:** Forecast/observed discharge $Q$ maps to `normal` ($< Q_{90}$), `elevated` ($\ge Q_{90}$), `q2_watch` ($\ge Q_2$), `q5_warning` ($\ge Q_5$), or `q20_severe` ($\ge Q_{20}$). In-browser **Refresh live** recomputes tiers dynamically against the stored EV1 climatology.

### Validation & Known Limitations
- All 10 basins pass monotonic return-level checks and mainstem physical bounds (`validation.json` check 26/29; `0` off-mainstem warnings across 29-year 1997–2025 baselines, e.g., Saptakoshi $Q_{50} = 826.9$, $Q_2 = 8,099.5$, $Q_{20} = 12,349.5\text{ m}^3\text{ s}^{-1}$).
- **Limitations:** Daily mean discharge underestimates instantaneous sub-daily flood peaks in steep Himalayan catchments; Gumbel EV1 fixes the tail shape parameter ($\xi = 0$) and assumes climate stationarity; GloFAS models naturalized flow without real-time Nepalese hydropower or irrigation gate schedules; rating-curve water stage (metres) is not predicted.

### Uncertainty Bounds
- Ensemble spread (`p25–p75` interquartile range and `max` member) is exposed per forecast day across the 30-day horizon; forecast skill degrades substantially beyond lead days 7–10.
- Under Gumbel EV1 with $N = 29$ annual maxima, asymptotic sampling standard error on $Q_2$ is roughly $\pm 8\text{–}12\%$ and on $Q_{20}$ roughly $\pm 20\text{–}35\%$, excluding hydrological model structural bias.

---

## MC-3: Dahal–Hasegawa Rainfall-Landslide Screening

### Intended Use
- National hydrometeorological screening of regional rainfall-induced landslide potential across **24 physiographic sentinel nodes** (High Himalaya, Trans-Himalaya, Middle Mountains/Mahabharat, Siwalik/Churia) and cryosphere warm-rain episodes across **20 priority / ice-cored glacial lakes**.

### Out-of-Scope / Non-Operational Warning
- **NOT a site-specific slope-stability model, geotechnical factor-of-safety calculation, or local landslide warning.**
- Cannot predict individual cut-slope collapses, rockfalls, or localized convective cloudbursts below NWP grid resolution.

### Inputs
- **Open-Meteo Weather & Cryosphere API:** Hourly/daily liquid rainfall (`rain_sum` — explicitly excluding high-alpine `snowfall`), 0–7 cm volumetric topsoil moisture, and atmospheric 0 °C freezing-level altitude (`freezinglevel_height`) over rolling historical + forecast windows.
- **Sentinel Geometry:** 24 physiographic sentinel coordinates with elevations (`190 m` Butwal to `3,850 m` Khumbu) and canonical district/province attribution (`StdlibAdminLookup` against `cache/nepal_admin.json`).

### Physics / Algorithm
1. **Dahal & Hasegawa (2008) Nepal Himalaya I-D Curve:**
   $$I(D) = 73.90\,D^{-0.79}\;\mathrm{mm\,h^{-1}} \implies E_c(D) = I(D)\cdot D = 73.90\,D^{0.21}\;\mathrm{mm}$$
   Evaluated strictly on rolling **liquid rain** sums at $D \in \{24, 72, 168\}\text{ h}$:
   - $E_c(24\text{ h}) = 144.0\text{ mm}$, $E_c(72\text{ h}) = 181.4\text{ mm}$, $E_c(168\text{ h}) = 216.8\text{ mm}$.
   - Global lower-bound reference of Guzzetti et al. (2008) ($I = 2.20\,D^{-0.44}$: $13.0 / 24.1 / 38.8\text{ mm}$) is reported alongside for cross-comparison.
   - Maximum exceedance ratio $R = \max(P_{24}/144.0,\; P_{72}/181.4,\; P_{168}/216.8)$ maps deterministically to `low` ($R < 0.4$), `elevated` ($0.4 \le R < 0.7$), `watch` ($0.7 \le R < 1.0$), or `exceeded` ($R \ge 1.0$).
2. **Cryosphere Warm-Rain-on-Ice Rule (20 Priority Lakes):**
   - Freezing margin $\Delta z_0 = z_{0°\mathrm{C},\max} - z_{\text{lake}}$.
   - Flag `warm_rain_on_ice = true` iff 12-day cumulative liquid rain $\ge 10.0\text{ mm}$ **AND** $\Delta z_0 \ge 300.0\text{ m}$ (indicating liquid rain falling well above lake level onto glacierised/permafrost slopes).

### Validation & Known Limitations
- Automated verification confirms all 24 sentinel nodes carry valid canonical provinces, districts, and exact Dahal–Hasegawa thresholds (`validation.json` check 27/29).
- **Limitations:** Dahal & Hasegawa (2008) was fitted empirically to 193 Nepal landslide events (1951–2006) as a regional lower envelope — it ignores local bedrock dip, soil depth, seismic pre-weakening (e.g., 2015 Gorkha and 2023 Jajarkot epicentral zones), and rural road-cut excavations that routinely fail well below $R = 1.0$. Conversely, gentle terrain can exceed $R = 1.0$ without landslides. Global NWP rainfall grids (~9–11 km) systematically smooth extreme orographic cloudburst peaks by $2\text{–}4\times$ relative to DHM valley gauges (such as the September 2024 Roshi/Kavre extreme event).

### Uncertainty Bounds
- Ratios $R$ are deterministic point evaluations over deterministic NWP forecasts (no ensemble rainfall spread yet); forecast uncertainty grows sharply beyond 48–72 h in convective monsoon regimes.
- Empirical I-D screening carries substantial false-positive and false-negative rates at the single-slope scale and should always be read together with official DHM rain gauges (`/api/v1/rain/` via BIPAD) and geological susceptibility maps.

---

## MC-4: 5-Type National Landslide Inventory & Duplicate Matcher

### Intended Use
- Consolidated, source-transparent situational cataloguing of landslides across Nepal (`src/landslides.py`, `TRAYA-007`), conforming to [`schemas/landslide_event.v1.schema.json`](../schemas/landslide_event.v1.schema.json). Strictly partitions dated events from undated geomorphic scars, enforces `null`-not-`0` casualty/date semantics, and surfaces potential cross-source duplicates for human review **without silently auto-merging uncertain pairs**.

### Out-of-Scope / Non-Operational Warning
- **NOT a complete national landslide census and NOT a real-time road-blockage dispatch system.**
- Zero recorded landslides in a ward or district reflects observation/reporting absence, **not** slope safety.

### Inputs (5 Canonical `feature_type` Classes & 6 Providers)
TRĀYA 2.0 partitions every normalized record (`landslide_event.v1`) into one of **5 canonical `feature_type` values** across **6 `provider_id` sources** (`bipad_ndrrma`, `nasa_coolr`, `osm_overpass`, `usgs_ground_failure`, `traya_static`, `community_field`):

| Canonical `feature_type` | Epistemic Definition | Primary Provider(s) | Temporal / Casualty Rules |
| --- | --- | --- | --- |
| `landslide_event` | Dated confirmed/reported landslide event | `bipad_ndrrma` (`/api/v1/incident/?hazard=17`, `verified=true`), `nasa_coolr` | Requires non-null ISO-8601 `event_date_utc` (`day`/`month`/`year` precision); `0` fatalities permitted **only** when `verified=true` |
| `landslide_scar` | Undated mapped geomorphic landslide scar | `osm_overpass` (`hazard=landslide`, `geological=landslide`, `natural=landslide`; 663 baseline scars) | Strictly enforces `event_date_utc: null`, `date_precision: "unknown"`, `verified: false`, and `fatalities/injuries/households_affected: null` |
| `susceptibility_zone` | Static terrain / slope susceptibility point or zone | `traya_static` | Static baseline (`data_class: "static_assessment"`); never counted as an observed event |
| `hazard_report` | Unverified community or preliminary field observation | `bipad_ndrrma` (`verified=false`), `community_field` | `verified: false`; enforces `null`-not-`0` for unknown casualties |
| `coseismic_failure` | Earthquake-triggered slope failure | `usgs_ground_failure` (Nowicki Jessee et al., 2018), seismic-tagged `bipad_ndrrma` / `nasa_coolr` | Tagged via coseismic trigger / earthquake source linkage |

### Physics / Algorithm (Strict `null`-not-`0` & Flag-Only Duplicate Matcher)
1. **Schema Validation & Strict `null`-not-`0` Rule:** Every record is validated against `schemas/landslide_event.v1.schema.json` (WGS84 Nepal bounds `lon ∈ [79.5, 88.8]`, `lat ∈ [26.0, 31.0]`, canonical 77-district & 7-province lookup via `StdlibAdminLookup`, strict `https://` `evidence_url`). Unknown dates, fatalities, injuries, and affected households MUST remain JSON `null` — `0` is strictly reserved for `verified=true` official records (e.g., BIPAD `loss.peopleDeathCount == 0`).
2. **Flag-Only Spatio-Temporal Duplicate Candidate Detector (`find_duplicate_candidates`):**
   - Uses a deterministic spatial grid index over Haversine distance (`SZ.haversine_km`) and computes normalized title similarity (`difflib.SequenceMatcher`):
     - **Dated pairs (both `event_date_utc` present):** flagged when Haversine distance $\le 1.5\text{ km}$ **AND** $|\Delta t| \le 3\text{ days}$ (`dated_cross_source_spatiotemporal_proximity` or `dated_same_source_spatiotemporal_proximity`).
     - **Undated pairs (at least one missing date):** flagged **only across distinct `provider_id`s** when Haversine distance $\le 0.35\text{ km}$ (`undated_cross_source_spatial_proximity`).
   - Every candidate pair is written to **`data/landslide_review_queue.json`** with `distance_km`, `days_apart`, `title_similarity`, `reason`, `review_status: "pending_review"`, and **`auto_merged: false`** — preventing silent erasure of distinct same-day ward events.
3. **Three Atomic Outputs:** Emits `data/landslides.json` (backward-compatible enriched inventory), `data/landslide_review_queue.json` (human-audit duplicate queue), and `data/landslide_inventory.geojson` (RFC 7946 `FeatureCollection` for QGIS/GIS interoperability).

### Validation & Known Limitations
- Pure-stdlib schema validation (`validate_record`) and unit tests enforce the 5-type partition, strict `null`-not-`0` invariants, `https://` evidence links, and zero auto-merging in `find_duplicate_candidates`.
- **Limitations:** Severe observation bias toward highways, market towns, and media-covered districts; remote high-Himalayan slope failures are heavily under-reported. BIPAD ward centroids can place multiple distinct same-day incidents at identical coordinates (precisely why `auto_merged: false` review queuing is mandatory). NASA COOLR's ArcGIS FeatureServer experiences intermittent outages (transparently surfaced via `nasa_coolr_available: false` and `ProvenanceEnvelope`).

### Uncertainty Bounds
- **Spatial precision:** $\sim 10\text{–}50\text{ m}$ (`landslide_scar`) vs. $\sim 1\text{–}5\text{ km}$ (`bipad_ndrrma` ward centroids, `nasa_coolr` media geocodes).
- **Temporal precision:** Explicit `date_precision` enum (`day`, `month`, `year`, `unknown`); $\pm 1\text{–}3\text{ days}$ reporting lag on dated incidents.
- **Count completeness:** All national and district counts are strict **lower bounds**.

---

## MC-5: 1 km Corridor Exposure & Road-Cut Hospital Isolation

### Intended Use
- Screening-level estimation of downstream settlements, human health facilities, hydropower plants (with deduplicated tagged MW), and bridges along routed GLOF/river corridors (`src/exposure.py`, `src/routing.py`), paired with **functional road-cut hospital isolation screening** (`src/exposure_isolation.py`, `TRAYA-009`, `data/exposure_isolation.json`) identifying mountain valleys where bridge washouts cut off emergency hospital access.

### Out-of-Scope / Non-Operational Warning
- **The 1 km river corridor is an exposure screening buffer — NOT a 2D hydrodynamic flood inundation map.**
- **Road-cut isolation flags are topological OpenStreetMap corridor screenings — NOT real-time Department of Roads (`dor.gov.np`) highway closure status.**

### Inputs
- **HydroRIVERS v1.0:** Downstream flowpaths for `697` routed glacial lakes (capped at `120 km` downstream distance).
- **OpenStreetMap Overpass Caches (`cache/overpass/*.json`):** Cleaned human-health facilities (filtering out veterinary/animal/livestock tags), real bridges (excluding `bridge=no`, partitioning `VEHICULAR_HIGHWAYS` vs. `PEDESTRIAN_HIGHWAYS`), populated places, hydropower plants/generators, and border control posts.
- **WorldPop Nepal 2020 (100 m):** Both UN-adjusted constrained (`pop_low`) and unconstrained (`pop_high`) population grids.

### Physics / Algorithm
`src/exposure_isolation.py` leaves published Rounce et al. (2016) GLOF hazard classes untouched and explicitly separates **4 conceptual dimensions** in `data/exposure_isolation.json` (`exposure_isolation.v1`):
1. **`hazard_susceptibility_static`:** Published GLOF hazard class & PFV carried through unaltered.
2. **`corridor_exposure_screening`:** Exact perpendicular point-to-segment distance $d_\perp \le 1,000\text{ m}$ via a fast pure-stdlib `SpatialGrid` (`0.05°` cells). Deduplicates hydropower capacity (`_deduplicated_hydro_mw`) by skipping OSM `generator` nodes within `250 m` of a tagged `plant` to prevent double-counting MW. Surge arrival bracketed at $v \in \{2, 5, 10\}\text{ m s}^{-1}$ (anchored to 1985 Dig Tsho observed $4\text{–}5\text{ m s}^{-1}$, Vuichard & Zimmermann, 1987).
3. **`road_cut_hospital_isolation`:** For every corridor settlement, computes distances to the nearest health facility (`amenity=hospital|clinic`) and nearest hospital (`amenity=hospital`) and tests **3 transparent bridge-cut isolation mechanisms** when corridor bridges are present (`n_bridges > 0`):
   - `downstream_bridge_cut`: nearest health facility lies downstream along the corridor ($\le 5\text{ km}$ perpendicular offset, $>0.2\text{ km}$ downstream) with at least one corridor bridge between settlement and facility.
   - `cross_river_bridge_cut`: straight access segment from settlement to nearest health facility intersects the routed river channel polyline.
   - `upper_valley_single_egress_cut`: settlement lies upstream of any corridor health facility, has at least one bridge at or below it, and nearest health facility is $>2.0\text{ km}$ away.
   Corridors are classified into 3 transparent disruption tiers (`high`, `moderate`, `low`) via `_classify_corridor_disruption_risk` using isolated settlement count, total/vehicular bridge counts, and median/max hospital distance, with deduplicated per-district roll-ups across all 77 districts.
4. **`uncertainty_and_coverage_limits`:** Explicit OSM completeness bounds, screening-corridor caveat, and non-hydrodynamic disclaimers embedded in every payload.

### Validation & Known Limitations
- Automated checks confirm `0` dangling exposure references, monotonic `pop_low <= pop_high`, deduplicated per-district bridge/settlement accounting, and Dig Tsho's first settlement arrival bracket (`12–58 min` at $7.0\text{ km}$ vs. `30–90 min` reported bridge destruction).
- **Critical Known Limitations:**
  - **Vertical relief blindness:** In deep V-shaped Himalayan gorges, villages $<500\text{ m}$ horizontally from the river may sit $100\text{–}300\text{ m}$ above any plausible flood stage; conversely, on low-gradient Terai megafans (Koshi, Karnali, Narayani), floods spread far beyond $1\text{ km}$.
  - **Severe OSM under-tagging:** OSM counts are **strict lower bounds**. For example, Tsho Rolpa's corridor reports `n_hydropower = 0` in `data/lakes.json` even though Nepal's largest operating hydropower plant (**Upper Tamakoshi 456 MW**, Gonggar powerhouse/tailrace at `31.6 km`) and **Khimti I (60 MW)** lie along its routed Tama Koshi path — because underground or untagged facilities omit `plant:source=hydro`.
  - **International border truncation:** Exposure routing stops at the Nepalese border; downstream Indian and upstream Tibetan assets are excluded.
  - **Mobility nuance:** Corridor geometry cannot capture temporary Bailey bridges, functional pedestrian suspension bridges (*jholunge pul*) above flood stage, seasonal dry-riverbed tracks, or emergency helicopter landing zones.

### Uncertainty Bounds
- **Population exposure:** Bracketed by constrained vs. unconstrained WorldPop (typically $\pm 20\text{–}40\%$; e.g., Tsho Rolpa `29,322–40,620`).
- **Travel time:** $5\times$ bracket between $2\text{ m s}^{-1}$ and $10\text{ m s}^{-1}$ wave fronts.
- **Asset counts & isolation tiers:** Lower bounds subject to OSM mapping completeness; must be cross-checked against official DoR, Ministry of Health, and DoED (Department of Electricity Development) registries for planning use.

---

## MC-6: Interpretable Directed Cascade Graph

### Intended Use
- Auditable, rule-based synthesis of **compound and cascading multi-hazard pathways** across Nepal's 77 districts and major river basins (`src/cascades.py`, `data/cascades.json`), surfacing *why* co-occurring seismic, cryospheric, meteorological, fluvial, and infrastructure stressors interact without resorting to opaque black-box machine learning.

### Out-of-Scope / Non-Operational Warning
- **Does NOT compute conditional failure probabilities $P(\text{target} \mid \text{source})$ or multi-hazard return periods.**
- **NOT an automated disaster trigger or civil-protection dispatch engine.**

### Inputs
- Normalized hazard indicators and **6-class `ProvenanceEnvelope` metadata** (`live_observation`, `forecast`, `historical`, `static_assessment`, `cached`, `unavailable`; freshness `status` $\in \{\text{available}, \text{stale}, \text{unavailable}\}$; `src/integrations/provenance.py`) from MC-1 through MC-5, USGS/BIPAD seismicity, GEM active faults, and Copernicus Sentinel-1/2 EO freshness (`data/eo_sar.json`).

### Physics / Algorithm
1. **3 Transparent Physical Cascade Chains (`data/cascades.json`, `schema_version = "cascades.v1"`, `TRAYA-010`):**
   - **`rain_landslide_dam_road`:** Heavy rainfall / Dahal–Hasegawa exceedance (`DH_OBS_WATCH_RATIO = 0.50`, `DH_OBS_EXCEED_RATIO = 1.00`, `DH_COMBINED_WATCH_RATIO = 0.75`) + recent dated landslides (`<= 14 days`) $\to$ debris-flow blockage / elevated mainstem river tier (`elevated`, `q2_watch`, `q5_warning`, `q20_severe`) $\to$ road & bridge isolation.
   - **`quake_coseismic_isolation`:** Recent $M \ge 4.5$ earthquake (USGS FDSN or BIPAD NSC within `<= 30 days` and `<= 100.0 km` radius) near steep/high-hazard basins or glacial lakes $\to$ coseismic slope failure / moraine destabilization $\to$ valley corridor access cut.
   - **`glof_infra_isolation`:** High / Very High static GLOF susceptibility (plus dynamic `warm_rain_on_ice` or seismic proximity) $\to$ bridge & hydropower corridor impact $\to$ hospital access disruption.
2. **Per-Edge Epistemic Metadata & Auditable Firing Rules:** Every edge declares `evidence_type` (`"observed"` | `"forecast"` | `"modelled_static"`), explicit `trigger_rule`, `active` boolean, `confidence`, `uncertainty_note`, and bilingual (`EN / नेपाली`) plain-language narrative summaries.
3. **Strict Epistemic Guardrails:**
   - **Undated OSM `landslide_scar` records NEVER trigger live rainfall-landslide chains** (only dated `landslide_event` / `coseismic_failure` / `hazard_report` records within 14 days can activate live chains).
   - **Static vs. Dynamic Separation:** Standing static GLOF susceptibility is labeled `static_susceptibility_watch` and strictly separated from dynamically triggered active hazards (`active_dynamic`).
   - **Ordinal Severity Ranks (No Synthetic Probabilities):** Scenarios roll up into explicit ordinal tiers (`baseline`, `watch`, `moderate`, `high`, `critical`) with full rule trace and propagated `ProvenanceEnvelope` status.

### Validation & Known Limitations
- **Historical Archetype & Unit Verification:** Rule topology is verified in pure-stdlib unit tests against canonical Nepali compound-hazard cases: (i) **2015 Gorkha $M7.8$ / Dolakha $M7.3$** (`quake_coseismic_isolation`); (ii) **2014 Jure rockslide** & **2024 Roshi/Bagmati monsoon** (`rain_landslide_dam_road`); and (iii) **1985 Dig Tsho / 2021 Melamchi / Tsho Rolpa** (`glof_infra_isolation`), confirming undated OSM scars never fire live triggers.
- **Limitations:** Discrete rule thresholds cannot capture physical flood attenuation, debris bulking, breach timing lags, or sub-grid unmonitored headwater failures. Boundary sensitivity near discrete cut-offs (e.g., $M4.4$ vs. $M4.5$, or Dahal–Hasegawa ratio $0.49$ vs. $0.50$) can flip edge activation, so raw continuous upstream observations are always surfaced beside each edge.

### Uncertainty Bounds
- Outputs are **ordinal qualitative tiers (`baseline`–`critical`) with explicit `evidence_type`, `trigger_rule`, `confidence`, and `uncertainty_note` per edge** — zero calibrated joint probabilities. Confidence is bounded strictly by the weakest upstream model card (MC-1 through MC-5) and `ProvenanceEnvelope` freshness.

---

## Cross-References

- Upstream dataset licenses and attribution rules: [`../DATA_LICENSES.md`](../DATA_LICENSES.md)
- Institutional API schemas, official-vs-modelled separation & MOU prerequisites: [`INSTITUTIONAL_INTEGRATION_SPEC.md`](INSTITUTIONAL_INTEGRATION_SPEC.md)
- Reproducible 2D hydrodynamic pilot protocol (addressing MC-1 & MC-5 1D/buffer limits): [`TSHO_ROLPA_2D_STUDY_PLAN.md`](TSHO_ROLPA_2D_STUDY_PLAN.md)
- TRĀYA 2.0 Waves A–D delivery plan: [`../ROADMAP.md`](../ROADMAP.md)
