## 🇳🇵 Nepal TRĀYA — Nepal Multi-Hazard Early Warning & Screening System

**TRĀYA (त्राय)** derives from the Sanskrit verbal root *√trā*, meaning *"to protect, save, or deliver."* It is an open-access, integrated platform for multi-hazard screening, satellite Earth observation, hydrometeorological situational awareness, and risk communication across Nepal — **automatically refreshed every 7 days**.

## Detect. Warn. Protect.

A screening and situational-awareness assessment of **glacial lake outburst floods (GLOFs)**, **fluvial floods**, **earthquakes & active faults**, and **rainfall- & earthquake-triggered landslides** across Nepal, built entirely from peer-reviewed methods, open-access datasets, and keyless satellite feeds.

> **Important:** **This is a screening, prioritisation, and situational-awareness tool — not a deterministic forecast and not an operational warning service.** Consult Nepal's Department of Hydrology and Meteorology ([DHM](https://hydrology.gov.np/)) and National Disaster Risk Reduction and Management Authority ([NDRRMA / BIPAD](https://bipadportal.gov.np/)) for official operational alerts, and read the **Methods & Citations** tab before citing any figure.

## **Live Observatory: https://prazg.github.io/Nepal_TRAYA/**

---

## Multi-Hazard Architecture

### 1. Glacial Lake Outburst Floods (1,429 Screened Glacial Lakes)

For every mapped glacial lake in the Nepal Cryosphere Inventory:

| Step | Scientific Question | Published Method & Open Dataset |
|---|---|---|
| **Mass movement** | Can an ice avalanche or rockfall reach the lake? | Slope thresholds (45–60° glacierised; >30° non-glacierised) and volume-dependent reach angle ($\tan\alpha = 1.111 - 0.118\log_{10}V$) over a D8 route on a depression-filled **Copernicus DEM GLO-30** — Rounce et al. (2016), after Alean (1985), Bolch et al. (2011), Huggel et al. (2004) |
| **Dam stability** | Can the moraine self-destruct? | Steep lakefront area (SLA > 10° depression angle within 1 km of shoreline) and permafrost-belt context ($\ge$4,800 m; Gruber, 2012) — Fujita et al. (2013) |
| **Water & lowering** | How much water could drain? | Bayesian depth–area posterior on 24 Himalayan bathymetric surveys + half-ellipsoid basin across 10%, 30%, 50%, and 100% breach fractions — Veh et al. (2020); independently, Potential Flood Volume ($\mathrm{PFV} = \min[H_p, D_m] \cdot A$) — Fujita et al. (2013) |
| **Peak flood** | How large a peak discharge ($Q_p$)? | Dimensionless peak-discharge relation fitted piecewise ($t_{\nu=10}$ noise) to 63 natural dam breaks — Walder & O'Connor (1997), O'Connor & Beebee (2009), Veh et al. (2020) |
| **Downstream** | Who and what are in the path, and when? | 120 km downstream routing on **HydroRIVERS v1.0**, exposure within 1 km from **OpenStreetMap**, population bracket from **WorldPop 2020** (constrained & unconstrained), surge arrival bracket (2, 5, 10 m s⁻¹) |
| **Classification** | How do hazard and exposure combine? | Both readings (general & enumerated) of the Rounce et al. (2016) 4×4 hazard, impact, and risk framework |

### 2. Fluvial Flood Watch — Copernicus EMS GloFAS (10 Major River Basins)
- **30-day reanalysis + 30-day ensemble discharge forecasts** (median, interquartile p25–p75, ensemble max) across Nepal's 10 major river outlets (**Mahakali, Karnali, Bheri, Babai, West Rapti, Kali Gandaki, Narayani, Bagmati, Saptakoshi, Kankai**) via the open-access **Open-Meteo Flood API** (Harrigan et al., 2020; Alfieri et al., 2013).
- Graded against **35-year Gumbel EV1 flood return levels** ($Q_{90}, Q_2, Q_5, Q_{20}$) computed from 1991–2025 GloFAS-ERA5 daily reanalysis, plus on-demand GloFAS queries for any glacial lake's receiving river reach.

### 3. Earthquakes & Active Himalayan Tectonics
- **GEM Global Active Faults Database** (Styron & Pagani, 2020; incorporating HimaTibetMap): active traces and kinematics for the Main Frontal Thrust (MFT), Main Boundary Thrust (MBT), Main Central Thrust (MCT), and Tibetan grabens, with per-lake active-fault proximity (`fault_km`).
- **USGS Real-Time & Historical Seismicity**: live GeoJSON feeds (past 24 h / 7 d / 30 d), automatic **USGS ShakeMap MMI contours**, operational **USGS Ground-Failure coseismic landslide & liquefaction alerts** (Nowicki Jessee et al., 2018; Zhu et al., 2017), and catalogued $M \ge 4.0$ seismicity since 1913.

### 4. Rainfall- & Earthquake-Triggered Landslides
- **Nepal Himalaya Intensity–Duration Screening**: rolling 24 h, 72 h, and 168 h precipitation across **24 Nepalese physiographic sentinel nodes** (High Himalaya, Middle Mountains/Mahabharat, Siwalik/Churia) evaluated against **Dahal & Hasegawa (2008)** ($I = 73.90\,D^{-0.79}\text{ mm h}^{-1}$) and **Guzzetti et al. (2008)** ($I = 2.20\,D^{-0.44}$), alongside 0–7 cm topsoil moisture.
- **Documented Landslide Inventories**: **NASA Global Landslide Catalog / COOLR** (Kirschbaum et al., 2010; 2015) and **OpenStreetMap** mapped landslide scars.

### 5. Satellite Earth Observation & Cryosphere Thermal Regime
- **Copernicus Sentinel-2 L2A STAC Discovery** (Element84 Earth Search on AWS Open Data): weekly cloud-screened optical quicklook thumbnails, scene IDs, cloud cover percentages, and direct Copernicus Browser links for priority and ice-cored lakes — plus live in-browser STAC queries for **any of the 1,429 lakes**.
- **EOX Sentinel-2 Cloudless (10 m)** global optical mosaic basemap (CC-BY-4.0).
- **NASA EOSDIS GIBS Live Overlays**: keyless WMTS layers for **GPM IMERG Precipitation Rate**, **MODIS Terra NDSI Snow Cover**, and **VIIRS SNPP True Colour** with interactive date stepping and opacity control.
- **0 °C Freezing-Level Isotherm**: tracks atmospheric freezing-level altitude (`freezinglevel_height`) relative to glacial lake elevation to flag warm rain-on-snow / hanging-ice melt episodes.
- **UN OCHA / EC JRC GDACS**: regional multi-hazard alerts across the Hindu Kush Himalaya.

---

## Automated 7-Day Refresh Cycle

A GitHub Actions workflow ([`.github/workflows/weekly-refresh.yml`](.github/workflows/weekly-refresh.yml)) runs automatically **every 7 days** (Mondays at `03:15 UTC` / `09:00 NPT`, and on demand via `workflow_dispatch`):

1. Refreshes the **USGS FDSN earthquake catalogue**, **Copernicus GloFAS 10-basin river forecasts**, **NASA COOLR & OSM landslide records**, **Open-Meteo 24-zone rainfall/soil-moisture/0 °C freezing-level feeds**, **Sentinel-2 L2A STAC scene metadata**, and **GDACS regional alerts** (while refreshing OpenStreetMap exposure monthly with graceful cache fallback).
2. Runs **16 unit tests** (`src/test_pipeline.py`), rebuilds all deterministic `data/*.js` bundles (`src/build.py`), and enforces **28 external & internal validation checks** (`src/validate.py`).
3. Commits updated products and deploys directly to **GitHub Pages** only if every test and consistency check passes.
4. Between weekly builds, users can click **↻ Refresh live** in the UI header to pull real-time USGS, GloFAS, Open-Meteo, and Sentinel-2 STAC updates directly in the browser.

---

## Headline Results & Validation

- **16 glacial lakes** exceed the $10\times 10^6\text{ m}^3$ Potential Flood Volume threshold proposed by Fujita et al. (2013) for detailed investigation (led by **Tsho Rolpa** at ~104 Mm³).
- **697 glacial lakes** have a routed flood path with mapped downstream exposure.
- **28 of 28** validation and multi-hazard consistency checks pass (`src/validate.py`), with zero parameter tuning:
  - **Rounce et al. (2016) Table 5** (8 lakes): avalanche 8/8, rockfall 7/8, steep-lakefront threshold 7/8.
  - **Fujita et al. (2013) Table 1 & Table 2**: exact formula reproduction (5/5) and 9/9 zero-PFV agreement + 5/6 large-PFV agreement within $\times 3$.
  - **Measured events**: Imja Tsho surveyed depth/volume (Somos-Valenzuela et al., 2014) and 1985 Dig Tsho peak discharge & bridge-damage arrival window (Vuichard & Zimmermann, 1987; Cenderelli & Wohl, 2001) fall inside predicted intervals.

---

## Known Limitations (Read Before Using Any Number)

1. **Nothing here is a probability.** No estimate is made of the likelihood of dam failure, slope failure, or earthquake occurrence in any period.
2. **Small potential flood volumes (<5 Mm³) are under-detected at 30 m resolution.** $\mathrm{PFV} = 0$ is a statement about the 30 m DEM, not a statement that a lake is safe.
3. **Peak discharge carries a factor-of-two typical error** and a 95% interval spanning ~2 orders of magnitude. Always use the interval.
4. **No 2D hydrodynamic inundation footprint is computed.** The 1 km corridor is an exposure search radius, not a flood extent.
5. **Buried ice in moraines** is flagged only where documented in peer-reviewed literature; hazard classes elsewhere are lower bounds.
6. **Decision-tree sensitivity:** 68% of lakes shift hazard class between the general and literal-enumerated readings of Rounce et al. (2016) Sect. 4.2 — both readings are provided in the UI so users can inspect the difference directly.
7. **Regional hydromet & flood grids:** GloFAS (~5 km grid) and Dahal & Hasegawa (2008) represent regional hydrological/meteorological regimes, not site-specific geotechnical or flash-flood models.
8. **OpenStreetMap coverage is uneven** and **routed exposure stops at the Nepalese border**, so downstream counts are lower bounds.

---

## Running the Pipeline Locally

```bash
pip install -r requirements.txt
cd src

# Routine 7-day refresh & full multi-hazard build (~100 MB core inputs; uses committed cache/terrain.json)
python refresh_weekly.py

# Or step by step:
python fetch_inputs.py --core          # lakes, glaciers, HydroRIVERS, WorldPop, calibration chains
python seismic.py --refresh            # USGS earthquake catalogue
python exposure.py                     # OpenStreetMap exposure
python faults.py                       # GEM Global Active Faults
python floods.py --refresh             # Copernicus GloFAS 10-basin river flood watch
python landslides.py --refresh         # NASA COOLR/GLC + OSM landslides & I-D thresholds
python alerts.py --refresh             # UN/EC GDACS regional multi-hazard alerts
python hydromet.py --refresh           # Open-Meteo 24-zone watch, 0 °C isotherm & Sentinel-2 STAC
python test_pipeline.py                # 16 unit tests
python build.py                        # assemble data/*.js and index.html
python validate.py                     # 28 validation & consistency checks

# Optional: regenerate cache/terrain.json from raw Copernicus DEM tiles (~1.4 GB)
python fetch_inputs.py --dem
python build_terrain.py --workers 4
```

## Repository Layout

```
index.html                          generated from src/template.html by src/build.py
requirements.txt                    Python scientific dependencies
data/*.js                           LAKES, ROUTES, EXPOSURE, EQ_HISTORY, GLOF_HISTORY,
                                    FAULTS, RIVERS_WATCH, LANDSLIDES, HYDROMET_WEEKLY,
                                    GDACS_ALERTS, VALIDATION, SENSITIVITY, SUMMARY
vendor/leaflet/                     Leaflet 1.9.4 (vendored, zero external JS CDN needed)
src/config.py                       every threshold, basin, node & endpoint with citation
src/terrain.py                      Copernicus DEM slope, D8 routing, reach angle, SLA, PFV
src/models_glof.py                  Bayesian depth, volume & piecewise dam-break discharge
src/routing.py                      HydroRIVERS v1.0 downstream & upstream network traversal
src/exposure.py, src/admin.py       OpenStreetMap exposure & point-in-polygon admin lookup
src/seismic.py, src/faults.py       USGS seismicity & GEM Global Active Faults
src/floods.py                       Copernicus GloFAS reanalysis return levels & forecasts
src/landslides.py                   Dahal & Hasegawa (2008) thresholds & NASA/OSM inventory
src/hydromet.py                     Open-Meteo cryosphere/rain watch & Sentinel-2 STAC EO
src/alerts.py                       GDACS regional multi-hazard alert feed
src/refresh_weekly.py               end-to-end 7-day refresh orchestrator
src/build.py, src/validate.py       deterministic assembly & 28-check validation suite
.github/workflows/weekly-refresh.yml  scheduled 7-day refresh, validation & Pages deploy
```

## Licences & Attribution

Code in `src/` is MIT. Derived data products in `data/` attribute their open upstream providers:
Copernicus DEM GLO-30 (© DLR/ESA), RGI 7.0 & Nepal Cryosphere Inventory (CC-BY-4.0), HydroRIVERS v1.0 (HydroSHEDS), OpenStreetMap (© OSM contributors, ODbL 1.0), WorldPop 2020 (CC-BY-4.0), USGS Earthquake Hazards Program (public domain), GEM Global Active Faults (CC-BY-SA-4.0), Copernicus EMS GloFAS & Open-Meteo (CC-BY-4.0), NASA COOLR / EOSDIS GIBS (NASA Open Data), Copernicus Sentinel-2 L2A & EOX Sentinel-2 cloudless (CC-BY-4.0), UN/EC GDACS, ICIMOD HMAGLOFDB v4.0, and Veh, Korup & Walz (2020) supplementary data (CC-BY-4.0, Zenodo 3523213).

Built by Prajwal Ghimire
CopyRight @Prajwal Ghimire.
For Permission to use: prajwal.1.ghimire@kcl.ac.uk
