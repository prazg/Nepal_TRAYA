# Roadmap — Nepal TRĀYA 2.0 (Waves A–D)

This roadmap charts the evolution of **Nepal TRĀYA (त्राय)** from its hardened 7-day open-data screening baseline into **TRĀYA 2.0** (full provenance, official Nepal statutory data separation, 5-type landslide cataloguing, road-cut hospital isolation, interpretable multi-hazard cascades, and all-weather Sentinel-1 SAR EO) and forward toward **Wave D (`v3.0-pilot`)** institutional co-design and 2D hydrodynamic GLOF execution.

All implementation milestones obey TRĀYA's **non-negotiable engineering & safety invariants**:
- **Non-Operational Safety Boundary:** TRĀYA never impersonates an operational early warning system; official Nepal agencies (**DHM `1155`**, **NDRRMA/NEOC `1149`**, **DMG/NEMRC**) remain the sole statutory warning authorities.
- **Pure Python 3.12 Stdlib Weekly Pipeline:** Zero external `pip` dependencies in `src/integrations/*.py`, `src/landslides.py`, `src/exposure_isolation.py`, `src/cascades.py`, `src/refresh_weekly.py`, `src/verify_site.py`, and `--unit-only` tests.
- **Hardened Static Frontend:** Strict Content-Security-Policy (zero inline `<script>`, zero inline `<style>`, zero `on*=` attributes, zero external JS/font CDNs), byte-identical `index.html === src/template.html`, Node 24-native GitHub Actions workflows (`0` Node 20 actions), and `.prazg-suite-bar` suite integration.

---

## Delivery Architecture Across Waves A–D

```mermaid
flowchart LR
  WA["Wave A: v2.0-foundation\n#1 TRAYA-003 Provenance & Source Health"]
  WB["Wave B: v2.1-nepal-data\n#2 TRAYA-005 BIPAD · #3 TRAYA-006 Agency Spec\n#4 TRAYA-007 5-Type Landslides · #5 TRAYA-008 Governance"]
  WC["Wave C: v2.2-science\n#6 TRAYA-009 Exposure & Isolation · #7 TRAYA-010 Cascades\n#8 TRAYA-011 Tsho Rolpa 2D Plan · #9 TRAYA-012 Sentinel-1 SAR"]
  WD["Wave D: v3.0-pilot\n#10 TRAYA-013 Tsho Rolpa 2D Execution,\nAgency MOUs & CAP v1.2 Pilot"]

  WA --> WB --> WC --> WD
```

---

## Complete Issue & Milestone Mapping (`#1`–`#10`)

| GitHub Issue | Spec ID | Wave | Milestone | Deliverable & Primary Artifacts | Status |
| --- | --- | --- | --- | --- | --- |
| [#1](https://github.com/prazg/Nepal_TRAYA/issues/1) | `TRAYA-003` | **Wave A** | [`v2.0-foundation`](https://github.com/prazg/Nepal_TRAYA/milestones) | **6-State `ProvenanceEnvelope`, SHA-256 Build Manifest & Source Health Contract** (`src/integrations/provenance.py`, `src/integrations/{usgs,openmeteo,osm,icimod}.py`, `data/manifest.json`) | Implemented (TRĀYA 2.0) |
| [#2](https://github.com/prazg/Nepal_TRAYA/issues/2) | `TRAYA-005` | **Wave B** | [`v2.1-nepal-data`](https://github.com/prazg/Nepal_TRAYA/milestones) | **Official NDRRMA BIPAD Portal API v1 Client & Official-vs-Modelled Separation** (`src/integrations/bipad.py`, `cache/bipad_snapshot.json`, `data/bipad_official.json`) | Implemented (TRĀYA 2.0) |
| [#3](https://github.com/prazg/Nepal_TRAYA/issues/3) | `TRAYA-006` | **Wave B** | [`v2.1-nepal-data`](https://github.com/prazg/Nepal_TRAYA/milestones) | **Institutional Integration Specification & Agency Adapter Stubs — DHM, DMG/NEMRC, NDRRMA/BIPAD & DoR** ([`docs/INSTITUTIONAL_INTEGRATION_SPEC.md`](docs/INSTITUTIONAL_INTEGRATION_SPEC.md), `src/integrations/{dhm,nemrc,roads_authority}.py`) | Implemented (TRĀYA 2.0) |
| [#4](https://github.com/prazg/Nepal_TRAYA/issues/4) | `TRAYA-007` | **Wave B** | [`v2.1-nepal-data`](https://github.com/prazg/Nepal_TRAYA/milestones) | **5-Type National Landslide Inventory, `landslide_event.v1` Schema & Flag-Only Duplicate Review Queue** (`src/landslides.py`, `schemas/landslide_event.v1.schema.json`, `data/landslides.json`, `data/landslide_review_queue.json`, `data/landslide_inventory.geojson`) | Implemented (TRĀYA 2.0) |
| [#5](https://github.com/prazg/Nepal_TRAYA/issues/5) | `TRAYA-008` | **Wave B** | [`v2.1-nepal-data`](https://github.com/prazg/Nepal_TRAYA/milestones) | **Open-Science Governance, Dataset License Separation & 6-Model Scientific Model Cards** ([`DATA_LICENSES.md`](DATA_LICENSES.md), [`docs/MODEL_CARDS.md`](docs/MODEL_CARDS.md), [`ROADMAP.md`](ROADMAP.md), [`README.md`](README.md)) | Implemented (TRĀYA 2.0) |
| [#6](https://github.com/prazg/Nepal_TRAYA/issues/6) | `TRAYA-009` | **Wave C** | [`v2.2-science`](https://github.com/prazg/Nepal_TRAYA/milestones) | **1 km Corridor Exposure Breakdown & Road-Cut Hospital Isolation Screening** (`src/exposure_isolation.py`, `data/exposure_isolation.json`) | Implemented (TRĀYA 2.0) |
| [#7](https://github.com/prazg/Nepal_TRAYA/issues/7) | `TRAYA-010` | **Wave C** | [`v2.2-science`](https://github.com/prazg/Nepal_TRAYA/milestones) | **Interpretable Directed Multi-Hazard Cascade Graph Engine** (`src/cascades.py`, `data/cascades.json`) | Implemented (TRĀYA 2.0) |
| [#8](https://github.com/prazg/Nepal_TRAYA/issues/8) | `TRAYA-011` | **Wave C** | [`v2.2-science`](https://github.com/prazg/Nepal_TRAYA/milestones) | **Tsho Rolpa 2D Hydrodynamic GLOF Pilot Study Plan** ([`docs/TSHO_ROLPA_2D_STUDY_PLAN.md`](docs/TSHO_ROLPA_2D_STUDY_PLAN.md)) | Implemented (TRĀYA 2.0) |
| [#9](https://github.com/prazg/Nepal_TRAYA/issues/9) | `TRAYA-012` | **Wave C** | [`v2.2-science`](https://github.com/prazg/Nepal_TRAYA/milestones) | **All-Weather Copernicus Sentinel-1 SAR (`sentinel-1-grd`) & Sentinel-2 L2A Priority-Lake EO Discovery** (`src/integrations/copernicus.py`, `cache/eo_sar.json`, `data/eo_sar.json`) | Implemented (TRĀYA 2.0) |
| [#10](https://github.com/prazg/Nepal_TRAYA/issues/10) | `TRAYA-013` | **Wave D** | [`v3.0-pilot`](https://github.com/prazg/Nepal_TRAYA/milestones) | **Tsho Rolpa 2D Simulation Execution, Agency MOUs (DHM/DMG-NEMRC/NDRRMA/DoR), CAP v1.2 Interoperability & Municipal Co-Design Pilot** | Planned (Post-MOU / Compute) |

---

## Wave-by-Wave Scope & Milestone Exit Criteria

### Wave A — Foundation, Provenance & Source Health (`v2.0-foundation`)
Builds atop the completed v2 baseline (pure-stdlib 7-day refresh, Node 24 workflows, strict CSP, bilingual `EN/NE` UI, 77-district/7-province triage) to guarantee end-to-end data-lineage auditability:
- **[#1](https://github.com/prazg/Nepal_TRAYA/issues/1) (`TRAYA-003`):** Introduces canonical `ProvenanceEnvelope` (`schema_version = "2.0.0"`, `src/integrations/provenance.py`) classifying every feed into 6 `data_class` states (`live_observation`, `forecast`, `historical`, `static_assessment`, `cached`, `unavailable`), 3 freshness statuses (`available`, `stale`, `unavailable`), and 3 platform health roll-ups (`healthy`, `degraded`, `stale`). Generates deterministic SHA-256 build manifests (`data/manifest.json`) and wraps open-data feeds (`usgs.py`, `openmeteo.py`, `osm.py`, `icimod.py`).
- **Exit Criteria:** Every core dataset emits a validated `ProvenanceEnvelope`; `data/manifest.json` passes checksum & freshness checks in `src/verify_site.py`; Source Health UI surfaces exact staleness and fallback status transparently.

### Wave B — Official Nepal Data Separation, 5-Type Landslides & Governance (`v2.1-nepal-data`)
Bridges global open models with sovereign Government of Nepal statutory data while enforcing strict licensing, epistemic, and UI boundaries:
- **[#2](https://github.com/prazg/Nepal_TRAYA/issues/2) (`TRAYA-005`):** Live read-only ingestion from verified public BIPAD Portal v1 endpoints (`/alert/`, `/incident/?hazard=17&expand=loss`, `/river/`, `/rain/`, `/earthquake/`) into `data/bipad_official.json` with strict `null`-preservation and dedicated Official Statutory UI separation.
- **[#3](https://github.com/prazg/Nepal_TRAYA/issues/3) (`TRAYA-006`):** Formal technical specification ([`docs/INSTITUTIONAL_INTEGRATION_SPEC.md`](docs/INSTITUTIONAL_INTEGRATION_SPEC.md)) and standardized `requires_institutional_agreement: true` adapter stubs (`dhm.py`, `nemrc.py`, `roads_authority.py`) documenting verified 2026-11-23 BIPAD v1 schemas, SLA rules, and Wave D MOU gates.
- **[#4](https://github.com/prazg/Nepal_TRAYA/issues/4) (`TRAYA-007`):** Formal JSON Schema ([`schemas/landslide_event.v1.schema.json`](schemas/landslide_event.v1.schema.json)) partitioning records into 5 canonical `feature_type` classes (`landslide_event`, `landslide_scar`, `susceptibility_zone`, `hazard_report`, `coseismic_failure`), strict `null`-not-`0` casualty/date enforcement, flag-only duplicate detection (`<= 1.5 km` & `<= 3 days` dated; `<= 0.35 km` undated cross-source → `data/landslide_review_queue.json`, `auto_merged: false`), and QGIS-ready RFC 7946 `data/landslide_inventory.geojson`.
- **[#5](https://github.com/prazg/Nepal_TRAYA/issues/5) (`TRAYA-008`):** Comprehensive code-vs-data license governance ([`DATA_LICENSES.md`](DATA_LICENSES.md)) and transparent 6-model scientific audit cards ([`docs/MODEL_CARDS.md`](docs/MODEL_CARDS.md)).
- **Exit Criteria:** Zero silent merging of official statutory alerts with modelled watches; zero `None -> 0` casualty coercion; all 6 governance/model documents synchronized with code and passing CI gates.

### Wave C — Next-Generation Multi-Hazard Science & Monsoon EO (`v2.2-science`)
Upgrades TRĀYA from isolated single-hazard layers to connected corridor-impact, cascade-pathway, and all-weather satellite monitoring:
- **[#6](https://github.com/prazg/Nepal_TRAYA/issues/6) (`TRAYA-009`):** `src/exposure_isolation.py` emits `data/exposure_isolation.json` separating static GLOF susceptibility, cleaned 1 km corridor exposure (human health, vehicular vs. trail bridges, deduplicated hydropower MW), and 3 explicit road-cut hospital isolation mechanisms (`downstream_bridge_cut`, `cross_river_bridge_cut`, `upper_valley_single_egress_cut`) rolled up across 77 districts.
- **[#7](https://github.com/prazg/Nepal_TRAYA/issues/7) (`TRAYA-010`):** `src/cascades.py` evaluates 3 inspectable physical cascade chains (`rain_landslide_dam_road`, `quake_coseismic_isolation`, `glof_infra_isolation`) with per-edge `evidence_type`, explicit `trigger_rule`, `uncertainty_note`, strict isolation of undated OSM scars, and bilingual `EN/NE` summaries (`data/cascades.json`).
- **[#8](https://github.com/prazg/Nepal_TRAYA/issues/8) (`TRAYA-011`):** Reproducible 2D hydrodynamic GLOF study protocol for **Tsho Rolpa** ([`docs/TSHO_ROLPA_2D_STUDY_PLAN.md`](docs/TSHO_ROLPA_2D_STUDY_PLAN.md)) detailing bathymetry, 1998–2000 lowering history, 4×3 breach/bulking hydrograph ensemble, `LISFLOOD-FP v8.1` (`fv1`) + `BASEMENT v4` configurations, 10 Rolwaling–Tama Koshi / Upper Tamakoshi HPP checkpoints, and 6 quantitative validation gates.
- **[#9](https://github.com/prazg/Nepal_TRAYA/issues/9) (`TRAYA-012`):** `src/integrations/copernicus.py` integrates all-weather C-band **Sentinel-1 GRD** (`sentinel-1-grd`, IW VV/VH) alongside optical **Sentinel-2 L2A** via Element84 Earth Search STAC (`data/eo_sar.json`) to sustain priority glacial lake monitoring through June–September monsoon cloud cover.
- **Exit Criteria:** Pure-stdlib unit tests verify isolation mechanisms, cascade epistemic guardrails, and SAR STAC parsing; `python src/verify_site.py` passes with zero regressions.

### Wave D — Institutional Pilot, 2D Execution & Statutory Co-Design (`v3.0-pilot`)
Transitions selected research pilots into institutionally reviewed, field-calibrated decision-support tools — gated strictly behind formal Government of Nepal partnerships:
- **[#10](https://github.com/prazg/Nepal_TRAYA/issues/10) (`TRAYA-013`):**
  1. Execute Phases 2–4 of the **Tsho Rolpa 2D Hydrodynamic Study Plan** (`TRAYA-011`) on GPU/HPC infrastructure (`LISFLOOD-FP` + `BASEMENT`), deposit full open datasets on Zenodo, and publish compact static GeoJSON flood envelopes (`data/pilots/tsho_rolpa_2d.json`) after DHM/ICIMOD technical review.
  2. Activate formal MOUs under [`docs/INSTITUTIONAL_INTEGRATION_SPEC.md`](docs/INSTITUTIONAL_INTEGRATION_SPEC.md) to replace institutional stubs (`dhm.py`, `nemrc.py`, `roads_authority.py`) with authorized direct DHM 15-minute telemetry, DMG/NEMRC local $M_L$ seismic bulletins, and DoR highway blockage feeds.
  3. Align official alert rendering with ITU-T **CAP v1.2** and conduct bilingual `EN/NE` field co-design with Dolakha & Ramechhap District Emergency Operation Centres (DEOCs) and Gaurishankar Rural Municipality.
- **Hard Safety Gate:** Zero automated public alerting or EWS claims without signed statutory agency MOUs and legal mandate confirmation under Nepal's Disaster Risk Reduction and Management Act, 2074 (2017).

---

## Contributing & Governance

- Report bugs, scientific discrepancies, or institutional collaboration proposals via [GitHub Issues](https://github.com/prazg/Nepal_TRAYA/issues).
- Report security or CSP issues privately per [`SECURITY.md`](SECURITY.md).
- Review licensing and upstream attribution rules before reusing derived payloads in [`DATA_LICENSES.md`](DATA_LICENSES.md).
