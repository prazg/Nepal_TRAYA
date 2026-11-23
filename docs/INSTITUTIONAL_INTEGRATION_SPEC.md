# Institutional Integration Specification — Nepal TRĀYA 2.0 (`TRAYA-006`)

**Document ID:** `TRAYA-006` | **Milestone:** `v2.1-nepal-data` (Wave B) → `v3.0-pilot` (Wave D)  
**Scope:** Formal technical interoperability, attribution governance, agency outreach blueprint, and MOU prerequisites for connecting **Nepal TRĀYA 2.0** with Nepal's four core statutory geohazard and infrastructure agencies:
1. **Department of Hydrology and Meteorology (DHM)** — `hydrology.gov.np` (Flood Hotline `1155`)
2. **Department of Mines and Geology / National Earthquake Monitoring & Research Centre (DMG / NEMRC)** — `seismonepal.gov.np`
3. **National Disaster Risk Reduction and Management Authority (NDRRMA) / BIPAD Portal** — `bipadportal.gov.np` (NEOC Hotline `1149`)
4. **Department of Roads (DoR)** — `dor.gov.np` (Strategic Road Network & Highway Disruption Monitoring)

> **Constitutional & Statutory Principle:**
> Under Nepal's *Disaster Risk Reduction and Management Act, 2074 (2017)*, official flood, meteorological, seismic, and civil-protection warnings are the sole legal mandate of statutory Government of Nepal agencies. **Nepal TRĀYA is an independent open-science risk observatory** designed to *amplify and contextualize* statutory information with transparent open-data screening — never to impersonate, override, or compete with official warnings.

---

## 1. Agency Overview & Interoperability Roadmap

| Statutory Agency | Legal Mandate | Primary Portal / Hotline | Current TRĀYA 2.0 Integration (Wave B) | Target Wave D (`v3.0-pilot`) Integration (Post-MOU) |
| --- | --- | --- | --- | --- |
| **NDRRMA / BIPAD Portal** | National disaster information management, NEOC coordination, verified incident/loss registry, unified alert aggregation | [bipadportal.gov.np](https://bipadportal.gov.np/) / **`1149`** | **Read-only public REST v1 ingestion** (`alert`, `incident`, `hazard`, `rain`, `river`, `earthquake`) verified live on **2026-11-23**, strictly isolated into an Official Statutory lane | Formal data-sharing MOU, CAP v1.2 alert feed alignment, verified bilateral ward-level loss reconciliation |
| **DHM** | Hydrological & meteorological monitoring, river danger/warning levels, flood forecasting, GLOF field monitoring | [hydrology.gov.np](https://hydrology.gov.np/) / **`1155`** | DHM station metadata & river/rain alerts surfaced read-only via BIPAD v1 + DHM outlet cross-references (`DHM-170` to `DHM-795`) alongside GloFAS screening | Direct authenticated/authorized read-only JSON telemetry & rating-curve stage feed; joint Tsho Rolpa 2D GLOF technical review (`TRAYA-011`) |
| **DMG / NEMRC (NSC)** | National seismic network operation, local magnitude ($M_L$) epicentral solutions, national earthquake bulletins | [seismonepal.gov.np](https://seismonepal.gov.np/) | Direct statutory deep links + historical NSC rows mirrored in BIPAD `/api/v1/earthquake/` *(freshness lag explicitly disclosed)* alongside live USGS FDSN | Direct authorized JSON/QuakeML feed from NEMRC to close the >15-month BIPAD earthquake sync gap and provide local $M_L \ge 4.0$ Nepal bulletins |
| **Department of Roads (DoR)** | Strategic Road Network (SRN) engineering, bridge status, monsoon highway blockage & restoration | [dor.gov.np](https://dor.gov.np/) | Reference SRN highway tags (`NH03`, `NH23`, `NH28`, BP Highway) inside OSM topological road-cut hospital isolation screening (`src/exposure_isolation.py`) | Standardized read-only highway/bridge closure JSON feed (one-lane, blocked, washed-out, Bailey bridge) to replace purely topological isolation flags |

---

## 2. Live Public BIPAD v1 API Audit (Verified 2026-11-23)

Live unauthenticated read-only probes executed on **2026-11-23** against `https://bipadportal.gov.np/api/v1/` confirmed active Django REST Framework (DRF) JSON endpoints. All TRĀYA 2.0 integration parsers (`src/integrations/bipad.py`) MUST implement the exact field names and defensive workarounds documented below.

### 2.1 Discovery Root & Pagination Quirks

- **Root Endpoint:** `GET https://bipadportal.gov.np/api/v1/` (`HTTP 200`) advertises **25 registered resources**:
  `hazard`, `alert`, `document`, `document-category`, `incident`, `citizen-report`, `incident-feedback`, `event`, `country`, `province`, `district`, `municipality`, `ward`, `municipality-contact`, `contact-training`, `resource`, `organization`, `project`, `loss`, `loss-people`, `loss-family`, `loss-infrastructure`, `loss-agriculture`, `loss-livestock`, `infrastructure-type`.
- **Additional Live Telemetry Endpoints (Verified `HTTP 200`, unlisted in root index):**
  - `GET /api/v1/river/`
  - `GET /api/v1/rain/`
  - `GET /api/v1/earthquake/`
- **Critical Pagination Quirk (`INT64_MAX` Sentinel):** Every list endpoint returns:
  ```json
  { "count": 9223372036854775807, "next": "...", "previous": null, "results": [...] }
  ```
  BIPAD uses `9223372036854775807` (`2^63 - 1`) as a fast-pagination sentinel rather than running `SELECT COUNT(*)`. **Parsers MUST NEVER display `count` to users**; always count `len(results)` within an explicit bounded query (`limit`, `ordering`, and date range).

### 2.2 Verified Resource Schemas & Live Observations

#### A. Hazard Taxonomy — `GET /api/v1/hazard/` (`HTTP 200`, 47 entries)
- **Exact Fields (9):** `id`, `title`, `titleEn`, `titleNe`, `order`, `description`, `icon`, `color`, `type`.
- **Key Verified Geohazard IDs for TRĀYA Filtering:**

| `hazard.id` | `titleEn` | `titleNe` | TRĀYA Layer Mapping |
| --- | --- | --- | --- |
| `17` | `Landslide` | `पहिरो` | 5-Type Landslide Inventory (`bipad_official`) |
| `11` | `Flood` | `बाढी` | Official Flood Alerts & Incidents |
| `28` | `Inundation` | `डुबान` | Terai / Plain Official Inundation Incidents |
| `14` | `Heavy Rainfall` | `भारीवर्षा` | Official Hydromet / Rainfall Incidents |
| `8` | `Earthquake` | `भूकम्प` | Official Seismic Incidents |
| `26` | `Glacial lake outburst` | `हिमताल विस्फोटन` | Official GLOF Incidents |
| `3` | `Avalanche` | `हिमपहिरो` | High-Mountain Cryosphere Incidents |
| `5` | `Bridge Collapse` | `पुल भत्कीनु` | Road-Cut / Bridge Chokepoint Cross-Check |
| `29` | `Soil Erosion` | `भू-स्खलन` | Slope / Riverbank Erosion Context |

#### B. Official Statutory Alerts — `GET /api/v1/alert/?limit=N&ordering=-started_on` (`HTTP 200`)
- **Exact Fields (23):** `id`, `title`, `wards`, `affectedDemography` (`maleCount`, `femaleCount`, `householdCount`), `point` (GeoJSON Point `[lon, lat]`), `createdOn`, `titleNe`, `source` (e.g. `"dhm"`), `description`, `verified`, `public`, `startedOn`, `expireOn`, `polygon`, `referenceType`, `referenceData`, `referenceId`, `region`, `regionId`, `createdBy`, `updatedBy`, `hazard`, `event`.
- **Verified Live Sample (2026-11-23):**
  - `id`: `46481` | `title`: `"Flood warning at Chandrapur-4, Rautahat"` | `titleNe`: `"चन्द्रपुर-४, रौतहटमा बाढी"`
  - `source`: `"dhm"` | `verified`: `true` | `public`: `true` | `startedOn`: `"2026-11-21T12:10:00+05:45"`
  - `description`: `"Basin:Bagmati\nElevation:120\nWarning level:122.0\nWater level:122.381"`
  - **Parser Note:** Always filter `public == true`, retain `verified` explicitly, respect `expireOn` (flagging expired alerts cleanly), and parse `description` as plain escaped text (never `innerHTML`).

#### C. Verified Disaster Incidents & Structured Losses — `GET /api/v1/incident/?hazard=17&limit=N&ordering=-incident_on` (`HTTP 200`)
- **Exact Fields (28):** `id`, `title`, `wards`, `point`, `createdOn`, `modifiedOn`, `titleNe`, `description`, `cause`, `verified`, `verificationMessage`, `approved`, `polygon`, `incidentOn`, `reportedOn`, `streetAddress`, `detail`, `needFollowup`, `region`, `regionId`, `dataSourceId`, `dataSource`, `source`, `event`, `hazard`, `loss`, `createdBy`, `updatedBy`.
- **Nested `loss` Object (39 verified keys):** `id`, `peopleDeathCount` (+ `Male/Female/Other/Unknown/Disabled` breakdowns), `peopleMissingCount` (+ breakdowns), `peopleInjuredCount` (+ breakdowns), `peopleAffectedCount`, `familyAffectedCount`, `familyRelocatedCount`, `familyEvacuatedCount`, `livestockDestroyedCount`, `infrastructureDestroyedCount`, `infrastructureDestroyedHouseCount`, `infrastructureAffectedHouseCount`, `infrastructureDestroyedRoadCount`, `infrastructureAffectedRoadCount`, `infrastructureDestroyedBridgeCount`, `infrastructureAffectedBridgeCount`, `infrastructureDestroyedElectricityCount`, `infrastructureAffectedElectricityCount`, `infrastructureEconomicLoss`, `agricultureEconomicLoss`, `createdOn`, `modifiedOn`, `description`, `estimatedLoss`.
- **Verified Live Landslide Samples (`hazard=17` on 2026-11-23):**
  - `id=96552`: `"Landslide at Pachaljharana Rural Municipality-3"` (`2026-11-19`, Kalikot, `verified: true`)
  - `id=96478`: `"Landslide at Resunga Municipality-14"` (`2026-11-15`, Gulmi, `verified: true`)
  - `id=96447`: `"Landslide at Dharche Rural Municipality-5"` (`2026-11-14`, Gorkha, `verified: true`)

#### D. DHM Rainfall Telemetry via BIPAD — `GET /api/v1/rain/?limit=N` (`HTTP 200`)
- **Exact Fields (20):** `id`, `createdOn`, `modifiedOn`, `title`, `basin`, `measuredOn`, `point`, `elevation`, `image`, `averages`, `status`, `description` (DHM station code, e.g. `"0706"`), `stationSeriesId`, `isHourly`, `isDaily`, `ward`, `municipality`, `district`, `province`, `station`.
- **Nested `averages` Array:** 5 rolling intervals (`interval` $\in \{1, 3, 6, 12, 24\}$ hours), each with `{"value": <mm>, "status": {"danger": bool, "warning": bool}, "interval": <h>}`.
- **Verified Live Freshness (2026-11-23):** Fresh sub-hourly telemetry confirmed (`measuredOn: "2026-11-24T00:00:18.601625+05:45"` NPT for *Yangjakot*, *West Rapti at Kusum Rainfall*, and *Udayapur Gadhi*).
- **Security Rule:** `image` contains cleartext HTTP (`http://daq.hydrology.gov.np/images/...`). **MUST BE DISCARDED** at ingestion time to preserve TRĀYA's strict HTTPS Content-Security-Policy and avoid mixed-content or third-party hotlinking.

#### E. DHM River Water-Level Telemetry via BIPAD — `GET /api/v1/river/?limit=N` (`HTTP 200`)
- **Exact Fields (23):** `id`, `createdOn`, `modifiedOn`, `title`, `basin`, `point`, `waterLevel`, `image`, `dangerLevel`, `warningLevel`, `waterLevelOn`, `status` (e.g., `"BELOW WARNING LEVEL"`), `elevation`, `steady`, `description`, `stationSeriesId`, `dataSource`, `dataSourceId`, `ward`, `municipality`, `district`, `province`, `station`.
- **Verified Data-Quality Findings (2026-11-23):**
  1. Default/latest rows include numerous offline stations with `waterLevel: null` and `waterLevelOn: null` (e.g., *Bagmati River at Bhorleni*, *Indrawati at Melamchi*, *Likhu Khola at Sangutar*) alongside stale historic entries (`waterLevelOn: "2024-09-19T08:50:00+05:45"`, *Lohare Khola at Tallo Dungeshwor*).
  2. Ingestion parsers MUST filter out null readings, check `waterLevelOn` age against the freshness SLA, and emit `ProvenanceEnvelope.status = "degraded"` or `"stale"` whenever active gauges are missing or outdated.
  3. Discard `http://daq.hydrology.gov.np/images/...` URLs (same CSP rule as `/rain/`).

#### F. National Earthquake Records via BIPAD — `GET /api/v1/earthquake/?limit=N` (`HTTP 200`)
- **Exact Fields (12):** `id`, `createdOn`, `modifiedOn`, `description` (e.g., `"NSC"`), `point`, `magnitude`, `address`, `eventOn`, `ward`, `municipality`, `district`, `province`.
- **Verified Freshness Gap (2026-11-23):** The newest earthquake returned by BIPAD `/api/v1/earthquake/` was `id=1272` (`2025-08-22T23:15:00+05:45`, $M4.4$ Sankhuwasabha) — **15 months stale**. This confirms that TRĀYA MUST:
  1. Flag BIPAD earthquake records transparently as `stale` via `ProvenanceEnvelope` when `eventOn` lags real time;
  2. Retain live USGS FDSN (`earthquake.usgs.gov`) for real-time global monitoring while pursuing a direct MOU feed with **DMG/NEMRC** (`seismonepal.gov.np`).

---

## 3. Target Normalized JSON Schemas & 6-State `ProvenanceEnvelope`

Every institutional and open-data feed normalized into `data/*.json` in TRĀYA 2.0 wraps its payload in a uniform **`ProvenanceEnvelope` (`schema_version = "2.0.0"`, `src/integrations/provenance.py`)**, accompanied by a deterministic SHA-256 build manifest (`data/manifest.json`) and explicit institutional adapter stubs (`src/integrations/dhm.py`, `src/integrations/nemrc.py`, `src/integrations/roads_authority.py`).

### 3.1 `ProvenanceEnvelope` Contract (6 Canonical `data_class` States + Freshness & Health Roll-Up)

| Canonical `data_class` (6 States) | Meaning & Usage in TRĀYA 2.0 | UI & Source Health Treatment |
| --- | --- | --- |
| `live_observation` | Fresh upstream observational telemetry within SLA (e.g., live USGS FDSN seismicity, fresh BIPAD/DHM rain gauges) | Positive/fresh observation badge with exact `NPT` timestamp |
| `forecast` | Modelled future horizon (e.g., 30-day GloFAS ensemble discharge, 5-day Open-Meteo rainfall/freezing level) with explicit `valid_until_utc` | Forecast badge with expiry countdown; shifts to `stale` once `valid_until_utc < now` |
| `historical` | Archival event record (e.g., ICIMOD HMAGLOFDB v4.0, USGS $M \ge 4.0$ archive since 1900) | Archival baseline badge |
| `static_assessment` | Static geospatial/geophysical modelling baseline (e.g., Copernicus DEM GLO-30 terrain, 1,429-lake GLOF PFV, GEM active faults, OSM infrastructure) | Static baseline badge with build/inventory date |
| `cached` | Fallback snapshot served from `cache/*.json` (`fallback_used: true`) during `--offline` rebuilds or upstream timeout | Informational snapshot/cached badge — **never disguised as green "live"** |
| `unavailable` | Upstream unreachable, empty with no usable cache, or direct agency stub requiring an executed MOU (`requires_institutional_agreement: true`: `dhm.py`, `nemrc.py`, `roads_authority.py`) | Explicit unavailable / MOU-required badge; dependent cascade edges downgraded |

Freshness & Source Health roll-ups evaluate every envelope against `sla_hours` and `valid_until_utc`:
- **Per-Feed Freshness `status` (3 values):** `available`, `stale`, `unavailable`.
- **Platform Source Health Roll-Up (3 states):** `healthy`, `degraded`, `stale` (note: institutional stubs carrying `requires_institutional_agreement: true` are surfaced transparently without falsely marking open-data feeds broken).

```json
{
  "provenance": {
    "schema_version": "2.0.0",
    "source": "Government of Nepal NDRRMA / BIPAD Portal",
    "dataset": "bipad_official_multi_hazard_snapshot",
    "data_class": "live_observation",
    "status": "available",
    "retrieved_at_utc": "2026-11-23T18:49:15Z",
    "observation_time_utc": "2026-11-23T18:15:18Z",
    "valid_until_utc": null,
    "fallback_used": false,
    "license_ref": "Government of Nepal NDRRMA / BIPAD Portal public API (https://bipadportal.gov.np/)",
    "sla_hours": 168,
    "record_count": 42,
    "notes": "Official Government of Nepal NDRRMA/BIPAD records — kept structurally separate from modelled forecasts."
  }
}
```

### 3.2 Implemented Institutional Adapter Stubs (`requires_institutional_agreement: true`)

| Adapter Module | Target Agency | `status` / `data_class` | `bipad_relay_available` | Expected Direct Datasets Post-MOU |
| --- | --- | --- | --- | --- |
| `src/integrations/bipad.py` | NDRRMA / BIPAD Portal | Active read-only (`available` / `cached`) | Primary relay (`cache/bipad_snapshot.json` → `data/bipad_official.json`) | Live alerts, `hazard=17` landslide incidents (`expand=loss`), DHM river/rain relays, NSC earthquakes |
| `src/integrations/dhm.py` | DHM (`hydrology.gov.np`) | `unavailable` (stub) | `True` (via `/alert/`, `/river/`, `/rain/`) | 15-min telemetric river stage/discharge, hourly AWS rain/temp, rating curves, CAP v1.2 bulletins, Surkhet/Palpa/Udayapur Doppler radar |
| `src/integrations/nemrc.py` | DMG / NEMRC (`seismonepal.gov.np`) | `unavailable` (stub) | `True` (via `/earthquake/`; USGS FDSN in `usgs.py`) | Low-latency $M_L < 4.0$ microseismicity, strong-motion PGA/PGV accelerographs, local focal mechanisms, CAP/QuakeML feeds |
| `src/integrations/roads_authority.py` | Department of Roads (`dor.gov.np`) | `unavailable` (stub) | `False` (OSM bridges in `osm.py`) | SSRN monsoon blockage & one-way status feed, bridge scour/clearance ratings, diversion corridors, estimated reopening timestamps |

### 3.3 Target Agency Payload Schemas

#### Target 1 — NDRRMA / BIPAD Normalized Snapshot (`data/bipad_official.json`)
```json
{
  "provenance": { "...": "ProvenanceEnvelope (authority_class: official_statutory)" },
  "alerts": [
    {
      "bipad_id": 46481,
      "source_agency": "dhm",
      "hazard_id": 11,
      "title_en": "Flood warning at Chandrapur-4, Rautahat",
      "title_ne": "चन्द्रपुर-४, रौतहटमा बाढी",
      "started_npt": "2026-11-21T12:10:00+05:45",
      "expire_npt": null,
      "verified": true,
      "lon": 85.3711,
      "lat": 27.1134,
      "summary_text": "Basin:Bagmati | Elevation:120 | Warning level:122.0 | Water level:122.381",
      "official_url": "https://bipadportal.gov.np/"
    }
  ],
  "incidents_recent": [ "..." ],
  "rain_stations": [ "..." ],
  "river_stations": [ "..." ]
}
```

#### Target 2 — Direct DHM Hydro-Met Telemetry Feed (Post-MOU Wave D: `dhm_telemetry.json`)
- **Requested Fields from DHM:** `station_id` (canonical `DHM-*`), `station_name_en`, `station_name_ne`, `basin`, `district`, `lon`, `lat`, `elevation_m`, `observed_npt` (ISO-8601 `+05:45`), `water_level_m`, `warning_level_m`, `danger_level_m`, `trend` (`rising`/`steady`/`falling`), `rain_1h_mm`, `rain_3h_mm`, `rain_6h_mm`, `rain_24h_mm`, `official_status` (`BELOW_WARNING` / `WARNING` / `DANGER`), `bulletin_url` (`https://hydrology.gov.np/...`).
- **Format Preference:** Signed HTTPS JSON or CAP v1.2 XML feed with CORS or server-side pull token, `Cache-Control` headers, and zero cleartext `http://` media dependencies.

#### Target 3 — Direct DMG / NEMRC Seismic Bulletin Feed (Post-MOU Wave D: `nemrc_seismic.json`)
- **Requested Fields from DMG/NEMRC:** `event_id` (canonical NEMRC ID), `origin_npt` (`+05:45`), `origin_utc`, `magnitude_ml`, `magnitude_type` (`ML` / `Mw`), `epicenter_en`, `epicenter_ne`, `district`, `lon`, `lat`, `depth_km`, `review_status` (`automatic` / `reviewed`), `bulletin_url` (`https://seismonepal.gov.np/...`).
- **Format Preference:** Standard **FDSN Event Web Service (GeoJSON / QuakeML)** or lightweight HTTPS JSON feed matching `seismonepal.gov.np` earthquake tables.

#### Target 4 — Department of Roads (DoR) Highway Disruption Feed (Post-MOU Wave D: `dor_road_closures.json`)
- **Requested Fields from DoR:** `incident_id`, `highway_code` (e.g., `NH03`, `NH23`, `NH28`, `NH13`), `highway_name_en`, `highway_name_ne`, `location_chainage_km`, `district`, `lon`, `lat`, `status` (`blocked` / `one_way` / `resumed` / `bridge_washed_out`), `cause` (`landslide` / `flood` / `bridge_collapse` / `snowfall`), `reported_npt`, `expected_clearance_npt`, `detour_available`, `official_url`.

---

## 4. Attribution Boundaries & Official-vs-Modelled UI Separation Contract

To eliminate any risk of confusing open-science screening outputs with statutory Government of Nepal warnings, TRĀYA 2.0 enforces a **hard architectural and visual separation contract** verified by automated checks (`src/verify_site.py`):

1. **Two Distinct Data & UI Lanes:**
   - **Lane 1 — Official Statutory Agency Feed (Read-Only):** Labeled *"Official Statutory Notice / आधिकारिक सरकारी सूचना"* with the originating agency's exact name (`NDRRMA / BIPAD`, `DHM`, `DMG / NEMRC`, `DoR`), `verified` status, exact `NPT` timestamp, and direct clickable link to the official portal.
   - **Lane 2 — Open-Data Modelled Screening:** Labeled *"Modelled Screening / खुला तथ्याङ्क स्क्रिनिङ"* (GloFAS EV1, Dahal–Hasegawa I-D, GLOF PFV/$Q_p$, OSM road-cut isolation, Rule-Based Cascade Graph).
2. **Prohibition on Blending or Re-Labeling:**
   - Never merge a GloFAS `q5_warning` with a DHM `DANGER LEVEL` into a single combined "Flood Alert" badge.
   - Never overwrite official BIPAD fatality/loss counts with crowd-sourced or modelled estimates.
   - Never paraphrase or escalate official agency status strings; display verbatim status codes alongside bilingual `EN/NE` explanations.
3. **Strict CSP & XSS Hygiene:**
   - All strings parsed from external agency JSON (`title`, `titleNe`, `description`, `address`) MUST be rendered via `textContent` or strict HTML escaping (`esc()`).
   - Only validated `https://` official portal links are clickable; cleartext `http://` media URLs (such as `http://daq.hydrology.gov.np/images/...`) are never injected into the DOM or `img-src`.
4. **Persistent Emergency Escalation:**
   - Every view retains one-tap statutory emergency hotlines (`tel:1155`, `tel:1149`, `tel:100`, `tel:102`, `tel:1114`) and clickable statutory links (`hydrology.gov.np`, `bipadportal.gov.np`, `seismonepal.gov.np`).

---

## 5. SLA Expectations & Polite-Polling Stewardship

| Operational Dimension | Wave B (Current Read-Only Public API) | Wave D (Post-MOU Authorized Integration) |
| --- | --- | --- |
| **Polling Origin** | GitHub Actions scheduled runner (`weekly-refresh.yml`, once every 7 days) — **zero** high-frequency browser fan-out hitting `bipadportal.gov.np` | Negotiated server-side relay/cache with agency-approved polling interval (e.g., 15–60 min during monsoon) |
| **Request Volume Cap** | $\le 10$ paginated GET requests per weekly CI build (`limit=50–200`, strict timeouts $\le 20\text{ s}$, exponential backoff, max 2 retries) | Per signed MOU rate-limit budget; `If-Modified-Since` / `ETag` conditional requests |
| **Identification** | Explicit descriptive header: `User-Agent: Nepal-TRAYA/2.1 (+https://prazg.github.io/Nepal_TRAYA/)` | Dedicated agency API key / registered institutional contact |
| **Availability Expectation** | **Best-effort, zero SLA demanded from agency.** If an agency API times out or returns 5xx, TRĀYA cleanly degrades via `ProvenanceEnvelope` without retrying aggressively | Mutually documented uptime expectations, maintenance windows, and technical incident contact escalation |
| **Client-Side CORS Rule** | Static GitHub Pages never assumes GoN endpoints emit `Access-Control-Allow-Origin: *`; browser loads pre-staged `data/bipad_official.json` snapshot cleanly | Authorized CORS or vetted static-JSON mirror CDN approved in writing by the agency |

---

## 6. MOU Prerequisites for Wave D (`v3.0-pilot`) Operational Alerting

TRĀYA **will not** enable automated public push alerting (SMS, CAP broadcast, WhatsApp/Viber alerts, or municipal siren integration) until **all six MOU prerequisites** below are formally executed:

1. **Statutory Mandate & Ownership Agreement:** Written MOU with **NDRRMA** and relevant technical department (**DHM** for hydro-met/GLOF, **DMG/NEMRC** for seismic, **DoR** for highways) confirming that statutory agencies retain exclusive authority to issue, modify, and cancel public warnings.
2. **Common Alerting Protocol (CAP v1.2) Compliance:** Adoption of ITU-T X.1303 / WMO **CAP v1.2** XML/JSON alert envelopes aligned with Nepal's National Alerting Protocol, including standardized urgency/severity/certainty codes and Nepali/English bilingual templates reviewed by NDRRMA.
3. **Liability, Non-Warranty & Attribution Clauses:** Clear legal framework establishing TRĀYA's role as a technical decision-support and visualization research collaborator rather than a liable statutory warning issuer, alongside explicit rules for attribution and public data reuse (`DATA_LICENSES.md`).
4. **Scientific Verification & Field Calibration Gate:** Independent technical review by DHM / ICIMOD / Tribhuvan University hydrologists and engineers of pilot models (specifically the Tsho Rolpa 2D hydrodynamic study in [`TSHO_ROLPA_2D_STUDY_PLAN.md`](TSHO_ROLPA_2D_STUDY_PLAN.md) and basin-specific rating-curve mappings).
5. **Security, Privacy & Operational Continuity Audit:** Verification that zero personally identifiable citizen data (`citizen-report` reporter contacts, phone numbers, private ward contact rosters) are ingested or exposed publicly; formal incident-response contact path aligned with [`../SECURITY.md`](../SECURITY.md).
6. **Municipal Co-Design & Accessibility Sign-Off:** Bilingual `EN/NE` usability testing with at least two District Emergency Operation Centres (DEOCs, e.g., Dolakha and Ramechhap) and local rural municipalities (e.g., Gaurishankar RM) confirming low-bandwidth mobile readability and zero alert-fatigue ambiguity.

---

## 7. Agency Outreach Contact Summary (Draft Engagement Pack)

For formal institutional outreach under `TRAYA-006`, technical briefings and MOU proposals are prepared with:
- **Repository & Live Demo:** `https://github.com/prazg/Nepal_TRAYA` | `https://prazg.github.io/Nepal_TRAYA/`
- **Maintainer Contact:** Prajwal Ghimire (`prajwal.1.ghimire@kcl.ac.uk` | Security: `prajwal.ghimire@crick.ac.uk`)
- **Companion Technical Annexes:** [`MODEL_CARDS.md`](MODEL_CARDS.md) (scientific transparency), [`TSHO_ROLPA_2D_STUDY_PLAN.md`](TSHO_ROLPA_2D_STUDY_PLAN.md) (flagship 2D pilot proposal), and [`../DATA_LICENSES.md`](../DATA_LICENSES.md) (licensing & GoN governance boundaries).
