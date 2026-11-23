# 🇳🇵 Nepal TRĀYA 2.0 (त्राय) — 7-Day Open-Data Multi-Hazard Risk Observatory & Screening Platform

**TRĀYA (त्राय)** derives from the Sanskrit verbal root *√trā* (*"to protect, shelter, or safeguard"*). **TRĀYA 2.0** is an open-access, **7-day open-data multi-hazard risk observatory and scientific screening platform** for Nepal — unifying peer-reviewed glacial lake outburst flood (GLOF) screening, basin-scale river discharge forecasts, Himalayan seismicity and active-fault context, a 5-type national landslide inventory, a privacy-hardened community landslide reporting & DEOC moderation sandbox, 1 km corridor exposure & road-cut hospital isolation screening, interpretable rule-based cascade graphs, all-weather Sentinel-1 SAR / Sentinel-2 optical Earth observation, a governed 6-language OASIS CAP v1.2 Exercise & SMS/IVR framework, and structurally separated read-only official Government of Nepal statutory context.

> **Important Safety Notice (Non-Operational Platform / गैर-सञ्चालनात्मक सूचना):**  
> **TRĀYA is an open-data research observatory and screening tool — NOT a deterministic forecast and NOT an operational early warning system (EWS).** Snapshot datasets refresh on a 7-day cycle (timestamped in Nepal Standard Time, `NPT / UTC+05:45`, alongside optional in-browser live API queries). Official Government of Nepal statutory records are displayed read-only in a dedicated lane and are never blended into modelled screening tiers. Community reporting (`public_live_endpoint_enabled: false`) and CAP v1.2 / SMS / IVR drafts (`status: Exercise`, `relay_enabled: false`) operate strictly in pre-MOU sandbox mode. Never rely on this site for life-safety decisions — always follow Nepal's official statutory agencies below.  
> **चेतावनी:** यो खुला तथ्याङ्कमा आधारित वैज्ञानिक जोखिम अवलोकन तथा स्क्रिनिङ पोर्टल हो — आधिकारिक पूर्वसूचना प्रणाली होइन। वास्तविक आपतकालीन अवस्थाका लागि तलका आधिकारिक सरकारी निकाय र हटलाइनमा सम्पर्क गर्नुहोस्।

## Nepal Emergency Hotlines & Official Statutory Agencies

| Service / Statutory Agency | Hotline | Official Portal |
| --- | --- | --- |
| **DHM Flood & Hydro-Met Warning** (जल तथा मौसम विज्ञान विभाग) | **`1155`** | [hydrology.gov.np](https://hydrology.gov.np/) |
| **NDRRMA / National Emergency Operation Centre (NEOC)** (राष्ट्रिय विपद् जोखिम न्यूनीकरण तथा व्यवस्थापन प्राधिकरण) | **`1149`** | [bipadportal.gov.np](https://bipadportal.gov.np/) |
| **DMG / National Earthquake Monitoring & Research Centre (NEMRC)** (राष्ट्रिय भूकम्प मापन तथा अनुसन्धान केन्द्र) | — | [seismonepal.gov.np](https://seismonepal.gov.np/) |
| **Department of Roads (DoR)** (सडक विभाग — Strategic Road Network) | — | [dor.gov.np](https://dor.gov.np/) |
| **Nepal Police** (नेपाल प्रहरी) | **`100`** | — |
| **Ambulance** (एम्बुलेन्स) | **`102`** | — |
| **Armed Police Force — Search & Rescue** (सशस्त्र प्रहरी बल) | **`1114`** | — |

## **Live Observatory: [https://prazg.github.io/Nepal_TRAYA/](https://prazg.github.io/Nepal_TRAYA/)**

### Governance, Science & Wave D Institutional Documentation

- **[`DATA_LICENSES.md`](DATA_LICENSES.md)** — Strict separation of MIT source code from every upstream open-data license (`ODbL 1.0`, `CC BY 4.0`, `CC BY-SA 4.0`, Copernicus Open Data, USGS/NASA Public Domain, ICIMOD RDS, HydroSHEDS) and Government of Nepal statutory non-redistribution governance.
- **[`docs/MODEL_CARDS.md`](docs/MODEL_CARDS.md)** — Transparent scientific model cards (intended use, non-operational warnings, inputs, physics/algorithms, validation, and uncertainty bounds) for all 6 screening models.
- **[`docs/INSTITUTIONAL_INTEGRATION_SPEC.md`](docs/INSTITUTIONAL_INTEGRATION_SPEC.md)** (`TRAYA-006`) — Agency interoperability specification for DHM, DMG/NEMRC, NDRRMA/BIPAD (documenting verified live BIPAD v1 API schemas), and DoR, including official-vs-modelled UI boundaries and Wave D MOU prerequisites.
- **[`docs/COMMUNITY_REPORTING_GOVERNANCE.md`](docs/COMMUNITY_REPORTING_GOVERNANCE.md)** (`TRAYA-008` / Issue `#5`) — Offline-first PWA / IndexedDB community landslide reporting architecture, deterministic Nepal PII redaction, mandatory EXIF stripping, authenticated DEOC moderation state machine, and anti-abuse controls.
- **[`docs/TSHO_ROLPA_2D_STUDY_PLAN.md`](docs/TSHO_ROLPA_2D_STUDY_PLAN.md)** (`TRAYA-011` / Issue `#8`) — Reproducible open-source 2D hydrodynamic GLOF case-study protocol (`LISFLOOD-FP` / `BASEMENT`) for Tsho Rolpa, Rolwaling–Tama Koshi, and Upper Tamakoshi HPP checkpoints.
- **[`docs/wave_d/AGENCY_MOU_TEMPLATE.md`](docs/wave_d/AGENCY_MOU_TEMPLATE.md)** — Draft multi-agency MOU template for NDRRMA, DHM, DMG/NEMRC, DoR, and pilot municipalities/DEOCs aligned with Nepal's DRRM Act 2074 & Individual Privacy Act 2075.
- **[`docs/wave_d/MULTILINGUAL_CAP_SMS_IVR_SOP.md`](docs/wave_d/MULTILINGUAL_CAP_SMS_IVR_SOP.md)** (`TRAYA-013` / Issue `#10`) — Standard Operating Procedure for OASIS CAP v1.2 profile, NTC/Ncell SMS & IVR relay architecture, 6-language native municipal validation (`en`/`ne`/`mai`/`bho`/`thr`/`taj`), officer sign-off, and anti-false-alarm guardrails.
- **[`docs/wave_d/DEOC_UAT_PROTOCOL.md`](docs/wave_d/DEOC_UAT_PROTOCOL.md)** — Structured multilingual UAT & field co-design rubric for Dolakha, Ramechhap, Madhesh, and Kailali/Bardiya DEOCs.
- **[`ROADMAP.md`](ROADMAP.md)** — TRĀYA 2.0 Waves A–D delivery plan mapping GitHub Issues `#1`–`#10` (`TRAYA-003`, `TRAYA-005`–`TRAYA-013`) across milestones `v2.0-foundation`, `v2.1-nepal-data`, `v2.2-science`, and `v3.0-pilot`.
- **[`SECURITY.md`](SECURITY.md)** — Coordinated vulnerability disclosure policy and browser/CI security controls.

---

## Key Platform Capabilities (TRĀYA 2.0 Architecture)

- **Official NDRRMA / BIPAD Data Separation (`src/integrations/bipad.py`, `TRAYA-005`):** Ingests read-only public Government of Nepal BIPAD Portal v1 alerts, verified landslide incidents (`hazard=17`, `expand=loss`), DHM rain/river relays, and NSC earthquakes into `data/bipad_official.json` — strictly preserving JSON `null` for missing counts (`None` is never coerced to `0`) and rendering statutory records separately from modelled watches. Direct DHM (`dhm.py`), DMG/NEMRC (`nemrc.py`), and DoR (`roads_authority.py`) institutional adapters carry explicit `requires_institutional_agreement: true` stubs pending formal MOUs (`TRAYA-006`).
- **6-State `ProvenanceEnvelope`, SHA-256 Manifest & Source Health (`src/integrations/provenance.py`, `TRAYA-003`):** Every feed emits a canonical `2.0.0` provenance envelope classifying its `data_class` (`live_observation`, `forecast`, `historical`, `static_assessment`, `cached`, `unavailable`), freshness `status` (`available`, `stale`, `unavailable`), SLA expiry, and Source Health roll-up (`healthy`, `degraded`, `stale`), backed by SHA-256 input/output checksums in `data/manifest.json`. Weekly snapshots are never disguised as green "live" sensors.
- **5-Type National Landslide Inventory & Flag-Only Duplicate Review Queue (`src/landslides.py`, `TRAYA-007`):** Conforms to [`schemas/landslide_event.v1.schema.json`](schemas/landslide_event.v1.schema.json), strictly partitioning records into `landslide_event`, `landslide_scar`, `susceptibility_zone`, `hazard_report`, and `coseismic_failure` with a strict `null`-not-`0` rule. Potential cross-source duplicates (`<= 1.5 km` & `<= 3 days` dated; `<= 0.35 km` undated cross-source) are flagged into `data/landslide_review_queue.json` (`auto_merged: false`) alongside QGIS-ready RFC 7946 `data/landslide_inventory.geojson`.
- **Community Landslide Reporting & Authenticated Moderation Queue Sandbox (`src/moderation.py`, `TRAYA-008` / Issue `#5`):** Conforms to [`schemas/community_report.v1.schema.json`](schemas/community_report.v1.schema.json) with deterministic Nepal PII redaction (`+977`/mobile/landline phones, emails, citizenship/license/NID numbers, `@handles`), mandatory `exif_stripped: true`, SHA-256 deduplication fingerprinting, strict unverified `null`-not-`0` casualties, flag-only duplicate screening against `data/landslides.json`, and an authenticated agency-officer state machine (`deoc_officer`, `ndrrma_verifier`, `dhm_verifier` + `agency_id`) promoting verified reports into `landslide_event.v1` records. Pre-MOU sandbox emits `data/moderation_queue.json` (`public_live_endpoint_enabled: false`) with synthetic Dolakha & Sindhupalchok UAT fixtures.
- **Governed 6-Language OASIS CAP v1.2 & SMS/IVR Exercise Relay (`src/cap_relay.py`, `TRAYA-013` / Issue `#10`):** Conforms to [`schemas/cap_v12_advisory.schema.json`](schemas/cap_v12_advisory.schema.json), generating standards-compliant `urn:oasis:names:tc:emergency:cap:1.2` **Exercise-only** advisories (`data/cap_drafts.json` and well-formed `data/cap_exercise_latest.xml`) across **English (`en`), Nepali (`ne`), Maithili (`mai`), Bhojpuri (`bho`), Tharu (`thr`), and Tamang (`taj`)**. Every scenario includes GSM-7 ASCII SMS drafts (`<= 160` chars for `en`), UCS-2 Devanagari SMS drafts (`<= 140` chars, `<= 2` segments), 25–35 s spoken IVR scripts referencing official Nepal hotlines (`1155 / 1149 / 1114 / 100 / 102`), transparent `linguistic_review_status`, and hard-locked `relay_governance.relay_enabled: false` until Wave D MOU activation.
- **1 km Corridor Exposure & Road-Cut Hospital Isolation (`src/exposure_isolation.py`, `TRAYA-009`):** Keeps Rounce et al. (2016) GLOF hazard classes untouched while separating cleaned 1 km perpendicular corridor exposure (human health facilities, vehicular vs. trail bridges, deduplicated hydropower MW) and functional road-cut hospital isolation across 3 bridge-cut mechanisms (`downstream_bridge_cut`, `cross_river_bridge_cut`, `upper_valley_single_egress_cut`) in `data/exposure_isolation.json`.
- **Interpretable Rule-Based Directed Cascade Graph (`src/cascades.py`, `TRAYA-010`):** Evaluates 3 auditable physical cascade chains (`rain_landslide_dam_road`, `quake_coseismic_isolation`, `glof_infra_isolation`) with explicit per-edge `evidence_type` (`observed` | `forecast` | `modelled_static`), `trigger_rule`, `uncertainty_note`, strict separation of undated OSM scars from live triggers, and bilingual `EN/नेपाली` plain-language summaries (`data/cascades.json`).
- **All-Weather Sentinel-1 SAR & Sentinel-2 L2A EO Discovery (`src/integrations/copernicus.py`):** Discovers cloud-penetrating C-band **Copernicus Sentinel-1 GRD** (`sentinel-1-grd`, IW VV/VH) repeat-pass scenes alongside 10 m **Sentinel-2 L2A** optical quicklooks via Element84 Earth Search STAC (`data/eo_sar.json`) to sustain priority glacial lake observation through June–September monsoon cloud cover.
- **Tsho Rolpa 2D Hydrodynamic Case Study (`docs/TSHO_ROLPA_2D_STUDY_PLAN.md`, `src/tsho_rolpa_pilot.py`, `TRAYA-011`):** Reproducible `LISFLOOD-FP` (`fv1`) & `BASEMENT v4` 2D study protocol and pre-simulation benchmark (`data/tsho_rolpa_pilot.json`) spanning bathymetry, 1998–2000 lowering history, 4×3 breach/sediment-bulking hydrographs, and 10 Rolwaling–Tama Koshi checkpoints including Upper Tamakoshi HPP (456 MW) and Singati Community Hospital.
- **77-District Bilingual `EN / नेपाली` Hardened Observatory:** Unified cross-hazard triage across all 77 Nepalese districts and 7 canonical provinces (*Koshi, Madhesh, Bagmati, Gandaki, Lumbini, Karnali, Sudurpashchim*), WCAG 2.1 AA high-contrast Dark/Light themes, CVD-safe map symbols, vendored **Leaflet 1.9.4**, zero external JS/font CDNs, strict `<meta http-equiv="Content-Security-Policy">` (zero inline `<script>`, `<style>`, or `on*=` attributes), and `<meta name="referrer" content="strict-origin-when-cross-origin">`.

---

## Multi-Hazard Scientific Architecture

*(Full assumptions, validation tables, and uncertainty bounds are documented in [`docs/MODEL_CARDS.md`](docs/MODEL_CARDS.md).)*

### 1. Glacial Lake Outburst Floods (1,429 Screened Glacial Lakes)

| Step | Scientific Question | Published Method & Open Dataset |
| --- | --- | --- |
| **Mass movement** | Can an ice avalanche or rockfall reach the lake? | Slope thresholds (45–60° glacierised; >30° non-glacierised) and volume-dependent reach angle ($\tan\alpha = 1.111 - 0.118\log_{10}V$) over a D8 route on a depression-filled **Copernicus DEM GLO-30** — Rounce et al. (2016), after Alean (1985), Bolch et al. (2011), Huggel et al. (2004) |
| **Dam stability** | Can the moraine self-destruct? | Steep lakefront area (SLA > 10° depression angle within 1 km of shoreline, $\ge 4$ contiguous cells) and permafrost-belt context ($\ge 4,800\text{ m}$; Gruber, 2012) — Fujita et al. (2013) |
| **Water & lowering** | How much water could drain? | Bayesian depth–area posterior on 24 Himalayan bathymetric surveys + half-ellipsoid basin across continuous Beta and 10%, 30%, 50%, 100% breach fractions — Veh et al. (2020); independently, Potential Flood Volume ($\mathrm{PFV} = \min[H_p, D_m] \cdot A$, $D_m = 55A^{0.25}$) — Fujita et al. (2013) |
| **Peak flood** | How large a peak discharge ($Q_p$)? | Dimensionless peak-discharge relation fitted piecewise ($t_{\nu=10}$ noise) to 63 natural dam breaks — Walder & O'Connor (1997), O'Connor & Beebee (2009), Veh et al. (2020) |
| **Downstream & isolation** | Who and what are in the path, and which hospitals face road-cut isolation? | 120 km routing on **HydroRIVERS v1.0**, exact perpendicular 1 km corridor exposure from **OpenStreetMap**, **WorldPop 2020** constrained/unconstrained population bracket, surge arrival bracket (2, 5, 10 m s⁻¹), and 3-mechanism road-cut hospital isolation screening (`src/exposure_isolation.py`) |
| **Classification** | How do hazard and exposure combine? | Side-by-side display of both readings (general & enumerated) of the Rounce et al. (2016) 4×4 hazard, impact, and risk framework (`977/1,429 = 68.4%` sensitivity transparently exposed) |

### 2. Fluvial Flood Watch — Copernicus EMS GloFAS (10 Major River Basins)

- **30-day reanalysis + 30-day ensemble discharge forecasts** (`median`, `p25–p75`, `max`) across Nepal's 10 DHM-referenced river outlets (**Mahakali, Karnali, Bheri, Babai, West Rapti, Kali Gandaki, Narayani, Bagmati, Saptakoshi, Kankai**) via the **Open-Meteo Flood API** (Harrigan et al., 2020; Alfieri et al., 2013), with 3×3 mainstem snapping and sanity bounds (`0/10` off-mainstem warnings).
- Graded against **Gumbel EV1 flood return levels** ($Q_{50}, Q_{90}, Q_{99}, Q_2, Q_5, Q_{20}$) fitted to **29 valid years (`1997–2025`)** of GloFAS-ERA5 annual maxima (`cache/glofas_climatology.json`), displayed strictly alongside — never merged with — official DHM river telemetry relayed via BIPAD.

### 3. Earthquakes & Active Himalayan Tectonics

- **GEM Global Active Faults Database** (Styron & Pagani, 2020; incorporating HimaTibetMap): 70 Quaternary active surface fault traces (4 non-fault folds excluded) and per-lake proximity (`fault_km`). *(Does not represent the buried 3D Main Himalayan Thrust décollement.)*
- **USGS Real-Time & Historical Seismicity:** Nepal-region FDSN live queries (paused automatically when tab is hidden), automatic **USGS ShakeMap MMI contours**, **USGS Ground-Failure** coseismic landslide & liquefaction alerts (Nowicki Jessee et al., 2018), sanitized historical $M \ge 6.0$ events (`data/eq_history_m6.json`), and read-only NSC/NEMRC records relayed via BIPAD (with explicit freshness audit).

### 4. Rainfall- & Earthquake-Triggered Landslides & Moderated Field Reporting

- **Nepal Himalaya Intensity–Duration Screening:** Rolling 24 h, 72 h, and 168 h **liquid rainfall** (`rain_sum`) across **24 physiographic sentinel nodes** evaluated against **Dahal & Hasegawa (2008)** ($I = 73.90\,D^{-0.79}\text{ mm h}^{-1}$; $E_c = 144.0 / 181.4 / 216.8\text{ mm}$) and **Guzzetti et al. (2008)** ($I = 2.20\,D^{-0.44}$), alongside 0–7 cm soil moisture.
- **5-Type National Landslide Inventory & Moderated Community Sandbox:** Combines NDRRMA BIPAD verified landslide incidents (`hazard=17`), NASA COOLR reports, OpenStreetMap mapped landslide scars, USGS coseismic failures, and static/community records under `schemas/landslide_event.v1.schema.json` with flag-only duplicate queuing (`data/landslide_review_queue.json`). Offline-captured community reports enter a separate PII-redacted, EXIF-stripped sandbox (`schemas/community_report.v1.schema.json`, `src/moderation.py`, `data/moderation_queue.json`) requiring authenticated agency verification prior to promotion.

### 5. Satellite Earth Observation, SAR & Cryosphere Thermal Regime

- **Copernicus Sentinel-1 SAR (`sentinel-1-grd`) & Sentinel-2 L2A (`sentinel-2-l2a`) STAC Discovery** (Element84 Earth Search): cloud-penetrating C-band IW VV/VH SAR metadata (`data/eo_sar.json`) paired with 10 m optical quicklooks, cloud percentages, and Copernicus Browser links for priority and ice-cored glacial lakes.
- **EOX Sentinel-2 Cloudless (10 m)** mosaic (CC BY 4.0) + offline *"No basemap"* fallback + **NASA EOSDIS GIBS** keyless WMTS overlays (GPM IMERG precipitation, MODIS Terra NDSI snow cover, VIIRS SNPP True Colour).
- **0 °C Freezing-Level Isotherm (`warm_rain_on_ice`):** Flags priority glacial lakes experiencing $\ge 10\text{ mm}$ 12-day liquid rain while the 0 °C isotherm rises $\ge 300\text{ m}$ above lake elevation.
- **UN OCHA / EC JRC GDACS:** Regional Hindu Kush Himalaya multi-hazard alerts.

---

## Automated 7-Day Refresh vs. Full GIS Rebuild

TRĀYA separates routine weekly data refreshes from heavy GIS/DEM modeling so CI runs rapidly, reliably, and without native geospatial build dependencies:

### Tier 1 — Automated 7-Day Weekly Refresh & Verification (Python 3.12 Stdlib ONLY)

Zero third-party `pip` packages are required. Both GitHub Actions workflows run natively on **Node 24** actions (`checkout@v7`, `setup-python@v7`, `cache@v6`, `configure-pages@v6`, `upload-pages-artifact@v5`, `deploy-pages@v5`):

- **`.github/workflows/weekly-refresh.yml`** runs every Monday at `03:15 UTC` (`09:00 NPT`) and on demand via `workflow_dispatch`:
  1. Executes `python src/refresh_weekly.py` (orchestrating pure-stdlib `src/integrations/*.py`, `src/seismic.py`, `src/faults.py`, `src/floods.py`, `src/landslides.py`, `src/hydromet.py`, `src/alerts.py`, `src/exposure_isolation.py`, `src/cascades.py`, `src/tsho_rolpa_pilot.py`, and rebuilding `data/*.json` + `data/manifest.json`).
  2. Executes `python src/test_pipeline.py --unit-only` (pure-stdlib unit tests).
  3. Executes `python src/verify_site.py` (enforces Node 24 workflows, byte-identical `index.html === src/template.html`, strict CSP & zero-inline HTML security, Nepal hotlines & statutory links, `.prazg-suite-bar`, 77 districts / 7 canonical provinces, zero blank lake provinces, zero `?` mojibake, and ES module static/XSS checks).
  4. Commits refreshed data/caches (`git pull --rebase --autostash`) and deploys to GitHub Pages.
- **`.github/workflows/pages.yml`** deploys pushes to `main` (`cancel-in-progress: false`) behind the mandatory `python src/verify_site.py` gate.

```bash
# Run locally with Python 3.12 stdlib only (no virtual environment or pip install needed):
python -B src/refresh_weekly.py               # 7-day open-data refresh & JSON payload rebuild
python -B src/refresh_weekly.py --offline     # zero-network deterministic rebuild from cache/
python -B src/refresh_weekly.py --refresh-osm # optional: also refresh Overpass OSM exposure/admin
python -B src/moderation.py                   # rebuild pre-MOU community moderation queue sandbox
python -B src/cap_relay.py                    # rebuild 6-language OASIS CAP v1.2 Exercise JSON & XML
python -B src/test_pipeline.py --unit-only    # pure-stdlib unit tests
python -B src/verify_site.py                  # full CI verification gate (<2s)
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
python validate.py                      # external & internal scientific validation suite (29 checks)

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

1. **Nothing here is a probability or operational alert.** No estimate is made of the likelihood of dam failure, slope failure, flood occurrence, cascade propagation, or earthquake occurrence in any period. CAP v1.2 drafts are strictly `<status>Exercise</status>` (`relay_enabled: false`) and community reporting is pre-MOU sandbox only (`public_live_endpoint_enabled: false`).
2. **Small potential flood volumes (<5 Mm³) are under-detected at 30 m resolution.** Only `0/4` small (<5 Mm³) published PFVs are recovered on Copernicus DEM GLO-30; $\mathrm{PFV} = 0$ is a 30 m DEM limit, not a safety certificate.
3. **Peak discharge carries a factor-of-two typical error** and a 95% predictive interval spanning 2–3 orders of magnitude. Always report the full interval.
4. **No 2D hydrodynamic inundation footprint is computed yet.** The 1 km corridor is an exposure screening buffer, not a flood extent (see [`docs/TSHO_ROLPA_2D_STUDY_PLAN.md`](docs/TSHO_ROLPA_2D_STUDY_PLAN.md) for the reproducible 2D pilot protocol).
5. **Buried ice in moraines** is documented for only 5 lakes from peer-reviewed literature; hazard classes for the remaining 1,424 lakes are lower bounds.
6. **Decision-tree sensitivity:** `977/1,429` lakes (`68.4%`) shift hazard class between the general and enumerated readings of Rounce et al. (2016) Sect. 4.2 — both are displayed side-by-side.
7. **Regional hydromet & flood grids:** GloFAS (~5 km) and Open-Meteo NWP (~9–11 km) smooth localized orographic cloudbursts and omit hydropower/barrage gate operations; official BIPAD river and earthquake endpoints can contain null or stale rows (surfaced via `ProvenanceEnvelope`).
8. **OpenStreetMap coverage is uneven & stops at the border:** Downstream asset counts and road-cut isolation metrics are strict **lower bounds** (e.g., Tsho Rolpa shows `n_hydropower = 0` in OSM despite Upper Tamakoshi 456 MW at Gonggar and Khimti I 60 MW downstream).
9. **Regional mother-tongue CAP templates require native municipal sign-off:** While `en` and `ne` carry `reviewed_baseline` status, `mai` (Maithili), `bho` (Bhojpuri), `thr` (Tharu), and `taj` (Tamang) are explicitly tagged `draft_pending_native_municipal_review` pending Wave D DEOC UAT panels (`docs/wave_d/DEOC_UAT_PROTOCOL.md`).

---

## Nepal Open-Science Observatory Suite

TRĀYA is part of an interconnected open-science observatory suite for Nepal by `@prazg` (linked persistently in `.prazg-suite-bar`):

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
index.html                                  static observatory shell (byte-identical to src/template.html)
assets/                                     modular ES modules (*.js) & accessible theme stylesheets (*.css)
vendor/leaflet/                             vendored Leaflet 1.9.4 (BSD-2-Clause; zero external CDN)
schemas/landslide_event.v1.schema.json      JSON Schema for 5-type national landslide inventory
schemas/community_report.v1.schema.json     JSON Schema for offline community landslide reports (TRAYA-008)
schemas/cap_v12_advisory.schema.json        JSON Schema for 6-language OASIS CAP v1.2 Exercise drafts (TRAYA-013)
data/*.json, data/*.geojson, data/*.xml     lazy-loaded payloads (summary, manifest, kpi_baseline, lakes,
                                            districts, routes, exposure, exposure_isolation, cascades,
                                            bipad_official, eo_sar, tsho_rolpa_pilot, landslides,
                                            landslide_review_queue, landslide_inventory.geojson,
                                            moderation_queue, cap_drafts, cap_exercise_latest.xml,
                                            rivers_watch, hydromet_weekly, eq_history_m6, glof_history,
                                            faults, gdacs_alerts, validation, model_fit)
cache/*.json                                cached upstream snapshots & Copernicus DEM terrain metrics
src/integrations/provenance.py              6-state ProvenanceEnvelope, SHA-256 manifest & Source Health (stdlib)
src/integrations/bipad.py                   NDRRMA BIPAD Portal API v1 read-only official client (stdlib)
src/integrations/copernicus.py              Sentinel-1 SAR GRD & Sentinel-2 L2A STAC discovery (stdlib)
src/integrations/{usgs,openmeteo,osm,icimod}.py  open-data provenance wrappers (stdlib)
src/integrations/{dhm,nemrc,roads_authority}.py  institutional adapter stubs (requires MOU; stdlib)
src/landslides.py                           5-type landslide inventory, null-not-0 & review queue (stdlib)
src/moderation.py                           community report PII redactor, validator & DEOC moderation queue (stdlib)
src/cap_relay.py                            6-language OASIS CAP v1.2 & SMS/IVR Exercise generator (stdlib)
src/exposure_isolation.py                   1 km corridor exposure & road-cut hospital isolation (stdlib)
src/cascades.py                             interpretable 3-chain directed cascade graph engine (stdlib)
src/tsho_rolpa_pilot.py                     Tsho Rolpa pre-simulation 2D benchmark builder (stdlib)
src/refresh_weekly.py                       pure-stdlib 7-day refresh & JSON builder orchestrator
src/floods.py, src/hydromet.py              GloFAS EV1 river watch & Dahal–Hasegawa hydromet (stdlib)
src/faults.py, src/seismic.py, src/alerts.py GEM faults, USGS seismicity & GDACS alerts (stdlib)
src/verify_site.py, src/test_pipeline.py    pure-stdlib CI verification gate & unit tests
src/terrain.py, src/models_glof.py, src/hazard.py, src/routing.py, src/exposure.py, src/build.py  Tier 2 GIS/GLOF stack
DATA_LICENSES.md                            MIT code vs. upstream dataset licenses & GoN governance
ROADMAP.md                                  TRĀYA 2.0 Waves A–D roadmap & GitHub Issues #1–#10
docs/MODEL_CARDS.md                         6 transparent scientific model cards
docs/INSTITUTIONAL_INTEGRATION_SPEC.md      DHM / DMG-NEMRC / NDRRMA-BIPAD / DoR spec (TRAYA-006)
docs/COMMUNITY_REPORTING_GOVERNANCE.md      community reporting PII/EXIF/IndexedDB/DEOC governance (TRAYA-008)
docs/TSHO_ROLPA_2D_STUDY_PLAN.md            reproducible Tsho Rolpa 2D GLOF study plan (TRAYA-011)
docs/wave_d/AGENCY_MOU_TEMPLATE.md          draft Wave D MOU for NDRRMA, DHM, DMG/NEMRC, DoR & DEOCs
docs/wave_d/MULTILINGUAL_CAP_SMS_IVR_SOP.md 6-language CAP v1.2, NTC/Ncell SMS/IVR & sign-off SOP (TRAYA-013)
docs/wave_d/DEOC_UAT_PROTOCOL.md            4-cohort multilingual DEOC UAT rubric & scoring protocol
SECURITY.md                                 coordinated vulnerability disclosure policy
.github/workflows/{pages,weekly-refresh}.yml Node 24-native CI/CD workflows
```

## Security, Licenses & Attribution

- **Security disclosures:** See [`SECURITY.md`](SECURITY.md) (report privately via GitHub Security Advisories or `prajwal.ghimire@crick.ac.uk`).
- **Code & Data Licensing:** Original source code in `src/`, `assets/`, and `docs/` is **MIT** ([`LICENSE`](LICENSE)); vendored Leaflet 1.9.4 is **BSD-2-Clause**. Upstream open and Government of Nepal statutory datasets retain their own licenses and governance rules — see the complete license and attribution table in **[`DATA_LICENSES.md`](DATA_LICENSES.md)**.

Built by **Prajwal Ghimire**  
Copyright © Prajwal Ghimire.  
Contact: `prajwal.1.ghimire@kcl.ac.uk` | Security: `prajwal.ghimire@crick.ac.uk`
