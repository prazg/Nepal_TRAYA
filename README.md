# 🇳🇵 Nepal TRĀYA (त्राय) — 7-Day Open-Data Multi-Hazard Risk Observatory & Screening Platform

**TRĀYA (त्राय)** derives from the Sanskrit verbal root *√trā* (*"to protect, shelter, or safeguard"*). It is an open-access, **7-day open-data multi-hazard risk observatory and scientific screening platform** for Nepal — integrating peer-reviewed glacial lake outburst flood (GLOF) screening, basin-scale river discharge reanalysis/forecasts, Himalayan seismicity and active-fault context, rainfall-threshold landslide screening, and keyless satellite Earth observation.

> **Important Safety Notice (Non-Operational Platform / गैर-सञ्चालनात्मक सूचना):**  
> **TRĀYA is an open-data research observatory and screening tool — NOT a deterministic forecast and NOT an operational early warning system (EWS).** Snapshot datasets refresh on a 7-day cycle (timestamped in Nepal Standard Time, `NPT / UTC+05:45`, alongside optional in-browser live API queries). Never rely on this site for life-safety decisions. Always follow Nepal's official statutory agencies below.  
> **चेतावनी:** यो खुला तथ्याङ्कमा आधारित वैज्ञानिक जोखिम अवलोकन तथा स्क्रिनिङ पोर्टल हो — आधिकारिक पूर्वसूचना प्रणाली होइन। वास्तविक आपतकालीन अवस्थाका लागि तलका आधिकारिक सरकारी निकाय र हटलाइनमा सम्पर्क गर्नुहोस्।

## Nepal Emergency Hotlines & Official Statutory Agencies

| Service / Statutory Agency | Hotline | Official Portal |
| --- | --- | --- |
| **DHM Flood & Hydro-Met Warning** (जल तथा मौसम विज्ञान विभाग) | **`1155`** | [hydrology.gov.np](https://hydrology.gov.np/) |
| **NDRRMA / National Emergency Operation Centre (NEOC)** (राष्ट्रिय विपद् जोखिम न्यूनीकरण तथा व्यवस्थापन प्राधिकरण) | **`1149`** | [bipadportal.gov.np](https://bipadportal.gov.np/) |
| **DMG / National Earthquake Monitoring & Research Centre (NEMRC)** (राष्ट्रिय भूकम्प मापन तथा अनुसन्धान केन्द्र) | — | [seismonepal.gov.np](https://seismonepal.gov.np/) |
| **Nepal Police** (नेपाल प्रहरी) | **`100`** | — |
| **Ambulance** (एम्बुलेन्स) | **`102`** | — |
| **Armed Police Force — Search & Rescue** (सशस्त्र प्रहरी बल) | **`1114`** | — |

## **Live Observatory: [https://prazg.github.io/Nepal_TRAYA/](https://prazg.github.io/Nepal_TRAYA/)**

---

## Key Platform Capabilities (v2 Architecture)

- **77-District & 7-Province Unified Triage (`data/districts.json`):** Search and inspect cross-hazard context across all **77 Nepalese districts** and **7 canonical provinces** (*Koshi, Madhesh, Bagmati, Gandaki, Lumbini, Karnali, Sudurpashchim*), including high-mountain, mid-hill, and Terai districts where no glacial lakes exist.
- **Bilingual `EN / नेपाली` Interface & WCAG 2.1 AA Accessibility:** Interactive English and Nepali (`नेपाली`) language switcher, persistent bilingual non-operational disclaimer, one-tap Nepal emergency hotlines (`100 / 102 / 1114 / 1149 / 1155`), high-contrast Dark & Light themes, color-vision-deficiency (CVD) safe map shapes/symbols, keyboard focus management, and mobile-first map layout.
- **Honest Freshness & Live Client-Side Re-Grading:** Every feed displays its exact Nepal Standard Time (`NPT / UTC+05:45`) timestamp and staleness state (weekly snapshots are never disguised as green "live" sensors). Clicking **Refresh live** fetches fresh USGS, Copernicus GloFAS, Open-Meteo rainfall/freezing-level, and Sentinel-2 L2A STAC observations in the browser and recalculates return-period flood tiers and Dahal–Hasegawa rainfall ratios dynamically.
- **Lazy JSON Payloads & Zero-CDN Hardened Frontend:** Static ES modules (`assets/*.js`, `assets/*.css`), vendored **Leaflet 1.9.4** (`vendor/leaflet/`), zero external JavaScript or Google Fonts CDNs, strict `<meta http-equiv="Content-Security-Policy">` (zero inline `<script>`, `<style>`, or `on*=` handlers), `<meta name="referrer" content="no-referrer">`, and lazy-loaded `data/*.json` payloads so the initial map paints rapidly on mobile connections.

---

## Multi-Hazard Scientific Architecture

### 1. Glacial Lake Outburst Floods (1,429 Screened Glacial Lakes)

For every mapped glacial lake in the Nepal Cryosphere Inventory (with all 1,429 lakes attributed to canonical Nepalese provinces):

| Step | Scientific Question | Published Method & Open Dataset |
| --- | --- | --- |
| **Mass movement** | Can an ice avalanche or rockfall reach the lake? | Slope thresholds (45–60° glacierised; >30° non-glacierised) and volume-dependent reach angle ($\tan\alpha = 1.111 - 0.118\log_{10}V$) over a D8 route on a depression-filled **Copernicus DEM GLO-30** — Rounce et al. (2016), after Alean (1985), Bolch et al. (2011), Huggel et al. (2004) |
| **Dam stability** | Can the moraine self-destruct? | Steep lakefront area (SLA > 10° depression angle within 1 km of shoreline) and permafrost-belt context ($\ge$4,800 m; Gruber, 2012) — Fujita et al. (2013) |
| **Water & lowering** | How much water could drain? | Bayesian depth–area posterior on 24 Himalayan bathymetric surveys + half-ellipsoid basin across 10%, 30%, 50%, and 100% breach fractions — Veh et al. (2020); independently, Potential Flood Volume ($\mathrm{PFV} = \min[H_p, D_m] \cdot A$) — Fujita et al. (2013) |
| **Peak flood** | How large a peak discharge ($Q_p$)? | Dimensionless peak-discharge relation fitted piecewise ($t_{\nu=10}$ noise) to 63 natural dam breaks — Walder & O'Connor (1997), O'Connor & Beebee (2009), Veh et al. (2020) |
| **Downstream** | Who and what are in the path, and when? | 120 km downstream routing on **HydroRIVERS v1.0**, corridor exposure within 1 km from **OpenStreetMap**, population bracket from **WorldPop 2020** (constrained & unconstrained), surge arrival bracket (2, 5, 10 m s⁻¹) |
| **Classification** | How do hazard and exposure combine? | Side-by-side display of both readings (general & enumerated) of the Rounce et al. (2016) 4×4 hazard, impact, and risk framework |

### 2. Fluvial Flood Watch — Copernicus EMS GloFAS (10 Major River Basins)

- **30-day reanalysis + 30-day ensemble discharge forecasts** (median, interquartile p25–p75, ensemble max) across Nepal's 10 major river outlets (**Mahakali, Karnali, Bheri, Babai, West Rapti, Kali Gandaki, Narayani, Bagmati, Saptakoshi, Kankai**) via the open-access **Open-Meteo Flood API** (Harrigan et al., 2020; Alfieri et al., 2013).
- Graded against **Gumbel EV1 flood return levels** ($Q_{50}, Q_{90}, Q_{99}, Q_2, Q_5, Q_{20}$) fitted to the available **GloFAS-ERA5 daily reanalysis** annual-maxima record. The exact reanalysis record length (`years`, e.g., the 21-year baseline record in `cache/glofas_climatology.json`) and snapped ~0.05° (~5 km) GloFAS grid cell coordinates (`grid_lat`, `grid_lon`) are disclosed transparently per basin in `data/rivers_watch.json` and the UI.

### 3. Earthquakes & Active Himalayan Tectonics

- **GEM Global Active Faults Database** (Styron & Pagani, 2020; incorporating HimaTibetMap): regional active fault surface traces and kinematics with per-lake fault proximity (`fault_km`). *(Note: 2D surface traces are regional context and do not represent full 3D Main Himalayan Thrust décollement geometry.)*
- **USGS Real-Time & Historical Seismicity:** Nepal-bounding-box FDSN live queries (paused automatically when the browser tab is hidden), automatic **USGS ShakeMap MMI contours**, **USGS Ground-Failure** coseismic landslide & liquefaction alerts (Nowicki Jessee et al., 2018; Zhu et al., 2017), and sanitized historical $M \ge 6.0$ seismicity (`data/eq_history_m6.json`, plus full $M \ge 4.0$ archive in `cache/usgs_catalogue.json`).

### 4. Rainfall- & Earthquake-Triggered Landslides

- **Nepal Himalaya Intensity–Duration Screening:** Rolling 24 h, 72 h, and 168 h precipitation across **24 Nepalese physiographic sentinel nodes** (High Himalaya, Middle Mountains/Mahabharat, Siwalik/Churia) evaluated against **Dahal & Hasegawa (2008)** ($I = 73.90\,D^{-0.79}\text{ mm h}^{-1}$) and **Guzzetti et al. (2008)** ($I = 2.20\,D^{-0.44}$), alongside 0–7 cm topsoil moisture.
- **Documented Landslide Inventories:** **OpenStreetMap** mapped landslide scars and **NASA Global Landslide Catalog / COOLR** records (Kirschbaum et al., 2010; 2015), with exact per-source record counts surfaced dynamically in `data/landslides.json` and `data/summary.json`.

### 5. Satellite Earth Observation & Cryosphere Thermal Regime

- **Copernicus Sentinel-2 L2A STAC Discovery** (Element84 Earth Search on AWS Open Data): cloud-screened optical quicklooks, scene IDs, cloud cover percentages, and direct Copernicus Browser links for priority and ice-cored lakes — plus on-demand in-browser STAC queries for any of the 1,429 lakes.
- **EOX Sentinel-2 Cloudless (10 m)** global optical mosaic basemap (CC-BY-4.0) plus offline *"No basemap"* fallback.
- **NASA EOSDIS GIBS Live Overlays:** Keyless WMTS layers for **GPM IMERG Precipitation Rate**, **MODIS Terra NDSI Snow Cover**, and **VIIRS SNPP True Colour**.
- **0 °C Freezing-Level Isotherm:** Tracks atmospheric freezing-level altitude (`freezinglevel_height`) relative to glacial lake elevation to flag warm rain-on-snow / hanging-ice melt episodes.
- **UN OCHA / EC JRC GDACS:** Regional multi-hazard disaster alerts across the Hindu Kush Himalaya.

---

## Automated 7-Day Refresh vs. Full GIS Rebuild

TRĀYA separates routine weekly data refreshes from heavy GIS/DEM modeling so CI runs rapidly, reliably, and without heavyweight native geospatial builds:

### Tier 1 — Automated 7-Day Weekly Refresh & Verification (Python 3.12 Stdlib ONLY)

Zero third-party `pip` packages are required. Both GitHub Actions workflows run natively on **Node 24** actions (`checkout@v7`, `setup-python@v7`, `cache@v6`, `configure-pages@v6`, `upload-pages-artifact@v5`, `deploy-pages@v5`):

- **`.github/workflows/weekly-refresh.yml`** runs every Monday at `03:15 UTC` (`09:00 NPT`) and on demand via `workflow_dispatch` (with optional `refresh_osm` toggle):
  1. Executes `python src/refresh_weekly.py` (orchestrating pure-stdlib `src/seismic.py`, `src/faults.py`, `src/floods.py`, `src/landslides.py`, `src/hydromet.py`, `src/alerts.py`, and rebuilding lazy `data/*.json` payloads).
  2. Executes `python src/test_pipeline.py --unit-only` (pure-stdlib unit tests).
  3. Executes `python src/verify_site.py` (enforces Node 24 workflows, byte-identical `index.html` ↔ `src/template.html`, CSP & zero-inline HTML security, Nepal hotlines & statutory links, `.prazg-suite-bar`, 77 districts / 7 canonical provinces, zero blank lake provinces, zero `?` mojibake, and ES module balance/import/XSS checks).
  4. Commits refreshed data/caches (`git pull --rebase --autostash` before push) and deploys `index.html`, `assets/`, `data/`, `vendor/`, and `.nojekyll` to GitHub Pages.
- **`.github/workflows/pages.yml`** deploys pushes to `main` (with `cancel-in-progress: false` so pushes never interrupt a scheduled refresh) and runs `python src/verify_site.py` as a mandatory pre-deploy gate.

```bash
# Run locally with Python 3.12 stdlib only (no virtual environment or pip install needed):
python src/refresh_weekly.py            # 7-day open-data refresh & JSON payload rebuild
python src/refresh_weekly.py --refresh-osm  # optional: also refresh Overpass OSM exposure/admin
python src/test_pipeline.py --unit-only # pure-stdlib unit tests
python src/verify_site.py               # full CI verification gate (<2s)
```

### Tier 2 — Full GIS / Copernicus DEM / GLOF Modeling Rebuild (`requirements.txt`)

Required only when recomputing 30 m Copernicus DEM terrain metrics, HydroRIVERS routing, WorldPop exposure, or Bayesian GLOF posteriors from scratch:

```bash
python -m venv .venv
source .venv/bin/activate               # or .venv\Scripts\activate on Windows
pip install -r requirements.txt

cd src
python fetch_inputs.py --core           # lakes, glaciers, HydroRIVERS, WorldPop, calibration data
python build.py                         # full GIS + multi-hazard assembly
python test_pipeline.py                 # full unit test suite (including numpy/terrain tests)
python validate.py                      # external & internal scientific validation suite

# Optional: rebuild cache/terrain.json from raw Copernicus DEM GLO-30 tiles (~1.4 GB)
python fetch_inputs.py --dem
python build_terrain.py --workers 4
```

### Tier 3 — Manuscript Figures & LaTeX Tables (`requirements-paper.txt`)

```bash
pip install -r requirements-paper.txt
cd src
python make_tables.py                   # paper/generated/tab_*.tex & macros.tex
python make_figures.py                  # paper/generated/fig_*.pdf
```

---

## Known Limitations (Read Before Using Any Number)

1. **Nothing here is a probability or operational alert.** No estimate is made of the likelihood of dam failure, slope failure, flood occurrence, or earthquake occurrence in any period.
2. **Small potential flood volumes (<5 Mm³) are under-detected at 30 m resolution.** $\mathrm{PFV} = 0$ is a statement about the 30 m DEM, not a statement that a lake is safe.
3. **Peak discharge carries a factor-of-two typical error** and a 95% interval spanning ~2 orders of magnitude. Always report the interval.
4. **No 2D hydrodynamic inundation footprint is computed.** The 1 km river corridor is an exposure screening buffer, not a flood extent.
5. **Buried ice in moraines** is flagged only where documented in peer-reviewed literature; hazard classes elsewhere are lower bounds.
6. **Decision-tree sensitivity:** 68% of lakes shift hazard class between the general and literal-enumerated readings of Rounce et al. (2016) Sect. 4.2 — both readings are exposed in the UI for direct inspection.
7. **Regional hydromet & flood grids:** GloFAS (~0.05° / ~5 km grid) and Dahal & Hasegawa (2008) represent regional hydrological/meteorological regimes, not site-specific geotechnical or flash-flood models. Return-period precision depends on the reanalysis sample length (`years`) reported per basin.
8. **OpenStreetMap coverage is uneven** and **routed exposure stops at the Nepalese border**, so downstream asset counts are lower bounds.

---

## Nepal Open-Science Observatory Suite

TRĀYA is part of an interconnected open-science observatory suite for Nepal by `@prazg`:

| Observatory / Portal | Scope | Live URL |
| --- | --- | --- |
| **Nepal Open-Science Observatory Hub** | Portal index for open-access Nepal earth-science & heritage tools | [prazg.github.io](https://prazg.github.io/) |
| **Nepal TRĀYA (त्राय)** *(this repo)* | 7-day open-data multi-hazard risk observatory & screening platform | [prazg.github.io/Nepal_TRAYA](https://prazg.github.io/Nepal_TRAYA/) |
| **Nepal Quake Watch** | Real-time & historical Himalayan seismicity explorer | [prazg.github.io/Nepal_Quake_Watch](https://prazg.github.io/Nepal_Quake_Watch/) |
| **Nepal Cryosphere Inventory** | 1,429 glacial lakes & 4,679 RGI 7.0 glacier outlines across Nepal | [prazg.github.io/Nepal_Cryosphere_Inventory](https://prazg.github.io/Nepal_Cryosphere_Inventory/) |
| **GLOF Dashboard** | Himalayan glacial lake outburst flood analytics & visualisations | [prazg.github.io/GLOF_dashboard](https://prazg.github.io/GLOF_dashboard/) |
| **Nepal Heritage Catalogue** | Open geospatial catalogue of Nepal's cultural & architectural heritage | [prazg.github.io/Nepal_Heritage_Catalogue](https://prazg.github.io/Nepal_Heritage_Catalogue/) |

---

## Repository Layout

```text
index.html                              static observatory shell (byte-identical to src/template.html)
assets/                                 modular ES modules (*.js) & accessible theme stylesheets (*.css)
vendor/leaflet/                         vendored Leaflet 1.9.4 (zero external JS/CSS CDN needed)
data/*.json                             lazy-loaded JSON payloads (summary, lakes, districts, routes,
                                        exposure, eq_history_m6, glof_history, faults, rivers_watch,
                                        landslides, hydromet_weekly, gdacs_alerts, validation, model_fit)
cache/*.json                            cached upstream snapshots & Copernicus DEM terrain metrics
src/config.py                           centralised scientific thresholds, stations & citations
src/refresh_weekly.py                   pure-stdlib 7-day refresh & JSON builder orchestrator
src/floods.py                           Copernicus GloFAS mainstem forecasts & EV1 climatology (stdlib)
src/hydromet.py                         Open-Meteo 24-node rainfall, 0 °C isotherm & Sentinel-2 STAC (stdlib)
src/landslides.py                       Dahal & Hasegawa (2008) screening & OSM/NASA COOLR records (stdlib)
src/faults.py, src/seismic.py           GEM Active Faults & USGS FDSN seismicity catalogue (stdlib)
src/alerts.py                           UN/EC GDACS regional multi-hazard alerts (stdlib)
src/verify_site.py                      pure-stdlib CI & local pre-deploy verification gate
src/test_pipeline.py                    unit tests (--unit-only runs in pure stdlib)
src/terrain.py, src/build_terrain.py    Copernicus DEM GLO-30 slope, D8 routing, reach angle, SLA, PFV
src/models_glof.py, src/hazard.py       Bayesian depth/volume, dam-break Qp & Rounce (2016) classification
src/routing.py, src/exposure.py         HydroRIVERS v1.0 network routing & OSM/WorldPop exposure
src/admin.py, src/build.py              77-district / 7-province admin index & full GIS assembly
src/validate.py, src/sensitivity.py     published benchmark reproduction & sensitivity analysis
src/make_figures.py, src/make_tables.py manuscript PDF figures & LaTeX table generators
requirements.txt                        full GIS/DEM rebuild dependencies
requirements-paper.txt                  manuscript figure/table dependencies (-r requirements.txt + matplotlib)
SECURITY.md                             vulnerability disclosure policy
.github/workflows/pages.yml             Node 24 Pages deploy with pre-deploy verify_site.py gate
.github/workflows/weekly-refresh.yml    Node 24 scheduled 7-day stdlib refresh, verification & deploy
```

## Security, Licences & Attribution

- **Security disclosures:** See [`SECURITY.md`](SECURITY.md) (report privately via GitHub Security Advisories or `prajwal.ghimire@crick.ac.uk`).
- **Licence:** Code in `src/` and `assets/` is MIT (see [`LICENSE`](LICENSE)). Derived data products in `data/` attribute their open upstream providers:
  Copernicus DEM GLO-30 (© DLR/ESA), RGI 7.0 & Nepal Cryosphere Inventory (CC-BY-4.0), HydroRIVERS v1.0 (HydroSHEDS), OpenStreetMap (© OSM contributors, ODbL 1.0), WorldPop 2020 (CC-BY-4.0), USGS Earthquake Hazards Program (public domain), GEM Global Active Faults (CC-BY-SA-4.0), Copernicus EMS GloFAS & Open-Meteo (CC-BY-4.0), NASA COOLR / EOSDIS GIBS (NASA Open Data), Copernicus Sentinel-2 L2A & EOX Sentinel-2 cloudless (CC-BY-4.0), UN/EC GDACS, ICIMOD HMAGLOFDB v4.0, and Veh, Korup & Walz (2020) supplementary data (CC-BY-4.0, Zenodo 3523213).

Built by **Prajwal Ghimire**  
Copyright © Prajwal Ghimire.  
Contact: `prajwal.1.ghimire@kcl.ac.uk` | Security: `prajwal.ghimire@crick.ac.uk`
