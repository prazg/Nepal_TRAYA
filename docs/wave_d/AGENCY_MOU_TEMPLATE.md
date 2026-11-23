# Draft Memorandum of Understanding (MOU) Template — Nepal TRĀYA Wave D Institutional Pilot (`v3.0-pilot`)

> **DOCUMENT STATUS: DRAFT TEMPLATE FOR INSTITUTIONAL REVIEW — NOT AN EXECUTED LEGAL AGREEMENT**  
> This template provides a structured institutional framework for formal cooperation between statutory agencies of the **Government of Nepal**, **Pilot Local Governments / District Emergency Operation Centres (DEOCs)**, and the **Nepal TRĀYA Open-Science Technical Collaborator Team**. All bracketed fields (`[...]`) must be reviewed, adapted, and approved by each signatory's legal counsel prior to execution.

---

## MEMORANDUM OF UNDERSTANDING

**ON TECHNICAL COLLABORATION FOR OPEN-DATA MULTI-HAZARD DECISION SUPPORT, INTEROPERABLE DATA EXCHANGE, MODERATED COMMUNITY HAZARD REPORTING, AND GOVERNED MULTILINGUAL CAP v1.2 ADVISORY EXERCISES**

This Memorandum of Understanding ("**MOU**") is entered into on this `[Day]` day of `[Month]`, `[Year]` (`[BS Date: YYYY-MM-DD]`), at Kathmandu, Nepal, by and among:

1. **National Disaster Risk Reduction and Management Authority (NDRRMA)**, Ministry of Home Affairs, Government of Nepal, Singha Durbar, Kathmandu, operating the **BIPAD Portal** (`bipadportal.gov.np`) and **National Emergency Operation Centre (NEOC — Hotline 1149)** ("**NDRRMA**");
2. **Department of Hydrology and Meteorology (DHM)**, Ministry of Energy, Water Resources and Irrigation, Government of Nepal, Babarmahal, Kathmandu (`hydrology.gov.np` — Flood Helpline **1155**) ("**DHM**");
3. **Department of Mines and Geology (DMG) — National Earthquake Monitoring & Research Centre (NEMRC)**, Ministry of Industry, Commerce and Supplies, Lainchaur, Kathmandu (`seismonepal.gov.np`) ("**DMG/NEMRC**");
4. **Department of Roads (DoR)**, Ministry of Physical Infrastructure and Transport, Chakupat, Lalitpur (`dor.gov.np`) ("**DoR**");
5. **Pilot Local Governments & District Emergency Operation Centres (DEOCs)**, namely `[Dolakha DEOC / Gaurishankar Rural Municipality]`, `[Ramechhap DEOC / Manthali Municipality]`, `[Madhesh Province Pilot DEOC(s) — e.g., Dhanusha / Rautahat]`, and `[Kailali & Bardiya DEOCs]` ("**Pilot Municipalities / DEOCs**"); and
6. **Nepal TRĀYA Open-Science Technical Collaborator Team** (represented by `[Principal Investigator / Host Academic or Research Institution]`, maintaining `https://github.com/prazg/Nepal_TRAYA`) ("**TRĀYA Collaborator**").

*(Each individually a "**Party**" and collectively the "**Parties**". Any bilateral subset of the above agencies may execute this template as a two-party MOU by striking inapplicable agency schedules.)*

---

## RECITALS

**WHEREAS**, Nepal faces compounding mountain and lowland geohazards including glacial lake outburst floods (GLOFs), monsoon riverine floods, rainfall- and earthquake-triggered landslides, active Himalayan seismicity, and highway-bridge isolation cutting off emergency hospital access;

**WHEREAS**, under the **Disaster Risk Reduction and Management Act, 2074 (2017)** and the **Local Government Operation Act, 2074 (2017)**, NDRRMA, DHM, DMG/NEMRC, DoR, Provincial EOCs, DEOCs, and Local Governments exercise distinct statutory mandates for hazard monitoring, disaster risk information management, and public early warning;

**WHEREAS**, **Nepal TRĀYA 2.0** is an open-access, non-operational multi-hazard risk observatory and scientific screening platform unifying transparent open geospatial models, 5-type landslide cataloguing, road-cut hospital isolation screening, interpretable cascade graphs, Sentinel-1 SAR / Sentinel-2 optical Earth observation, and standards-compliant OASIS CAP v1.2 / 6-language exercise templates;

**NOW, THEREFORE**, the Parties agree to collaborate in good faith under the following terms:

---

## ARTICLE 1 — PURPOSE, SCOPE & NON-OPERATIONAL BOUNDARY

1.1 **Collaborative Purpose.** This MOU establishes the technical, scientific, privacy, and governance gates for transitioning selected TRĀYA Wave D pilot modules from pre-MOU open-data sandboxes into institutionally reviewed decision-support workflows:
   - *(a)* Authorized read-only statutory data exchange (`TRAYA-006`: DHM river/rain telemetry, DMG/NEMRC seismic bulletins, DoR Strategic Road Network blockages, and NDRRMA BIPAD reconciliation);
   - *(b)* Controlled pilot activation of offline-first community landslide reporting with authenticated DEOC/NDRRMA/DHM moderation (`TRAYA-008`);
   - *(c)* Joint scientific review and open-data validation of the **Tsho Rolpa 2D Hydrodynamic GLOF Pilot** (`TRAYA-011`) and event-calibrated landslide holdout validation (`TRAYA-012`); and
   - *(d)* Governed testing and optional agency-controlled activation of **OASIS CAP v1.2** and 6-language (`en`, `ne`, `mai`, `bho`, `thr`, `taj`) SMS/IVR advisories (`TRAYA-013`).

1.2 **Strict Non-Operational Framing.** Unless explicitly authorized in a signed Operational Addendum under Article 4, TRĀYA operates exclusively as a **scientific screening and situational-awareness decision-support platform** — NOT an independent operational Early Warning System (EWS). Every public interface shall display prominent bilingual non-operational safety notices and official Nepal emergency hotlines (`1155`, `1149`, `1114`, `100`, `102`).

---

## ARTICLE 2 — STATUTORY WARNING AUTHORITY & OFFICIAL-VS-MODELLED SEPARATION

2.1 **Exclusive Statutory Mandate.** Nothing in this MOU transfers, delegates, or dilutes the exclusive statutory authority of **DHM**, **DMG/NEMRC**, **NDRRMA/NEOC**, **DoR**, or statutory District/Local Disaster Management Committees to issue, modify, escalate, or cancel official public warnings in Nepal.

2.2 **Hard UI & Data Separation Contract.** TRĀYA Collaborator shall maintain a verifiable technical separation (enforced via automated CI gates in `src/verify_site.py`) between:
   - **Lane 1 — Official Statutory Agency Records (Read-Only):** Displayed verbatim with originating agency attribution, exact Nepal Standard Time (`NPT / UTC+05:45`) timestamps, `verified` flags, and HTTPS deep links to official agency portals.
   - **Lane 2 — Open-Data Modelled Screening:** Clearly labeled as non-statutory screening (GloFAS, Dahal–Hasegawa, GLOF PFV/$Q_p$, OSM road-cut isolation, cascade screening).
   - **Prohibition on Blending:** Modelled screening tiers shall NEVER be merged into or relabeled as official DHM danger levels, NEMRC seismic solutions, DoR closure statuses, or BIPAD loss totals.

---

## ARTICLE 3 — DATA SHARING, API INTEROPERABILITY & POLITE-POLLING SLAS

3.1 **Authorized Agency Feeds.** Subject to Annex A, participating statutory agencies agree to provide read-only technical access (API credentials, authenticated HTTPS JSON/CAP/QuakeML endpoints, or approved mirrors) in accordance with [`docs/INSTITUTIONAL_INTEGRATION_SPEC.md`](../INSTITUTIONAL_INTEGRATION_SPEC.md):
   - **DHM:** Telemetric 15-minute river water level (`warning`/`danger` thresholds), hourly AWS rainfall, basin rating-curve context, and official CAP v1.2 bulletins (`src/integrations/dhm.py`).
   - **DMG/NEMRC:** Low-latency reviewed/automatic local magnitude ($M_L$) Nepal seismic bulletins via JSON or FDSN/QuakeML (`src/integrations/nemrc.py`).
   - **DoR:** Standardized Strategic Road Network (SRN) highway blockage, one-way, bridge washout, and clearance feed (`src/integrations/roads_authority.py`).
   - **NDRRMA/BIPAD:** Authorized read-only BIPAD v1 polling quota and bilateral ward-level landslide verification workflow (`src/integrations/bipad.py`).

3.2 **Polite-Polling Stewardship & Security Hygiene.** TRĀYA Collaborator shall:
   - Perform all agency polling from scheduled server-side relays/caches rather than unthrottled client browser fan-out;
   - Respect agreed rate limits, conditional `ETag` / `If-Modified-Since` headers, strict timeouts (`<= 20 s`), and registered `User-Agent` / API key identification;
   - Strip all cleartext `http://` media URLs (e.g., legacy gauge snapshots) to maintain TRĀYA's strict HTTPS Content-Security-Policy (`script-src 'self'`, zero inline scripts/styles);
   - Never coerce missing agency counts (`null`) to `0`.

---

## ARTICLE 4 — CAP v1.2 & MULTILINGUAL SMS/IVR RELAY ACTIVATION GATE

4.1 **Default Hard Lock (`Exercise` Only).** By default, TRĀYA's CAP v1.2 engine (`src/cap_relay.py`, [`schemas/cap_v12_advisory.schema.json`](../../schemas/cap_v12_advisory.schema.json)) is hard-locked to `status = "Exercise"`, `relay_enabled = false`, and `statutory_warning = false`.

4.2 **Prerequisites for `Actual` Relay Activation.** Transitioning any advisory pipeline from `Exercise` to live public `Actual` CAP broadcast or NTC/Ncell SMS/IVR dispatch requires **all five** written gates:
   1. Written operational authorization signed by **NDRRMA** and the relevant technical hazard authority (**DHM** for hydro-met/GLOF; **DMG/NEMRC** for seismic);
   2. Completion of native-speaker & municipal DRR review promoting target languages (`mai`, `bho`, `thr`, `taj`) from `draft_pending_native_municipal_review` to `reviewed_native_approved` per [`MULTILINGUAL_CAP_SMS_IVR_SOP.md`](MULTILINGUAL_CAP_SMS_IVR_SOP.md);
   3. Successful completion of pilot **DEOC UAT** meeting all exit criteria in [`DEOC_UAT_PROTOCOL.md`](DEOC_UAT_PROTOCOL.md);
   4. Verified telecom gateway integration (NTC/Ncell SMPP or Cell Broadcast & IVR) operating strictly under agency sender IDs (`DHM-1155` / `NDRRMA-1149`) with two-person officer sign-off for `Severe`/`Extreme` advisories; and
   5. Documented `Cancel` / `Update` false-alarm retraction drill verified end-to-end.

---

## ARTICLE 5 — COMMUNITY LANDSLIDE REPORTING & PRIVACY GOVERNANCE

5.1 **Compliance with Individual Privacy Act, 2075 (2018).** Any pilot deployment of offline-first community landslide reporting (`TRAYA-008`, [`docs/COMMUNITY_REPORTING_GOVERNANCE.md`](../COMMUNITY_REPORTING_GOVERNANCE.md)) shall enforce:
   - Mandatory client-side EXIF/GPS photo metadata stripping (`exif_stripped: true`);
   - Deterministic PII redaction (`src/moderation.py::redact_pii`) stripping Nepal mobile/landline numbers, emails, citizenship/license/NID numbers, and `@handles`;
   - Zero public storage or display of citizen names, phone numbers, IMEIs, or raw IP addresses;
   - Strict `null`-not-`0` casualty encoding on unverified reports.

5.2 **Authenticated Agency Moderation.** Pilot Municipalities / DEOCs, NDRRMA, and DHM shall designate credentialed verifiers (`deoc_officer`, `ndrrma_verifier`, `dhm_verifier`) with unique `agency_id` identifiers. Only authenticated verifiers may promote a `hazard_report` into a `landslide_event.v1` record or reject duplicates (`flag_only_never_auto_merge`).

---

## ARTICLE 6 — SCIENTIFIC VALIDATION & JOINT PILOT REVIEW

6.1 **Tsho Rolpa 2D Hydrodynamic Pilot (`TRAYA-011`).** DHM, NDRRMA, Dolakha/Ramechhap DEOCs, and academic partners may jointly review bathymetric inputs, `LISFLOOD-FP` / `BASEMENT` breach hydrographs, and checkpoint depth-velocity envelopes along Rolwaling–Tama Koshi prior to publishing static pilot envelopes (`data/pilots/tsho_rolpa_2d.json`).

6.2 **Holdout Validation (`TRAYA-012`).** Historical BIPAD/COOLR landslide incidents and DHM rainfall observations shared under this MOU may be used to perform transparent spatiotemporal holdout calibration of Dahal–Hasegawa rainfall thresholds, with full uncertainty bounds published openly.

---

## ARTICLE 7 — INTELLECTUAL PROPERTY, DATA LICENSING & NON-REDISTRIBUTION

7.1 **Code vs. Sovereign Data Separation.** Consistent with [`DATA_LICENSES.md`](../../DATA_LICENSES.md):
   - Original TRĀYA software code, JSON schemas, and documentation remain open-source under the **MIT License**;
   - Government of Nepal statutory data remain the sovereign public property of the originating agency. Nothing herein grants TRĀYA Collaborator or third parties a blanket open-source license to commercially resell or bulk-repackage raw agency databases;
   - Upstream open datasets (`ODbL 1.0`, `CC BY 4.0`, `CC BY-SA 4.0`, Copernicus Sentinel Open Data, HydroSHEDS non-commercial terms) retain their respective licenses.

---

## ARTICLE 8 — CYBERSECURITY, CONTINUITY & INCIDENT RESPONSE

8.1 **Security Baseline.** All web interfaces and relays shall maintain strict HTTPS TLS, Content-Security-Policy enforcement, XSS-safe DOM rendering, zero external untrusted script CDNs, and responsible vulnerability disclosure per [`SECURITY.md`](../../SECURITY.md).

8.2 **24-Hour Incident Notification.** Any Party detecting unauthorized API access, PII leakage, compromised moderator credentials, or erroneous CAP/SMS generation shall notify all designated technical nodal officers within **24 hours** (and immediately for active alerting faults).

---

## ARTICLE 9 — LIABILITY, NON-WARRANTY & NO FINANCIAL OBLIGATION

9.1 **Non-Binding Technical Cooperation & Non-Warranty.** All open-science models, screening metrics, and draft tools are provided *"as-is"* for technical collaboration and research decision support without warranty of uninterrupted availability or predictive accuracy. Neither TRĀYA Collaborator nor any statutory agency assumes legal liability to another Party for consequential damages arising from reliance on open-data screening models.

9.2 **No Unfunded Financial Commitment.** Execution of this MOU creates no automatic financial obligation for any Party. Specific compute, telecom SMS/IVR airtime, field UAT logistics, or hosting costs shall be funded under separate written project budgets or donor grants mutually approved by the relevant Parties.

---

## ARTICLE 10 — TERM, AMENDMENT, EMERGENCY KILL-SWITCH & TERMINATION

10.1 **Term.** This MOU shall take effect on the date of final signature and remain valid for **three (3) years**, renewable by mutual written consent.

10.2 **Immediate Emergency Kill-Switch.** Any signatory statutory agency (`NDRRMA`, `DHM`, `DMG/NEMRC`, `DoR`, or Pilot DEOC) may unilaterally and immediately suspend its data feed, community reporting queue (`public_live_endpoint_enabled = false`), or CAP/SMS/IVR relay (`relay_enabled = false`) upon written or verified emergency notice if public-safety, accuracy, or privacy concerns arise.

10.3 **Termination.** Any Party may withdraw from this MOU upon **thirty (30) days'** written notice to the other Parties, without affecting open-source software licenses or archived public research publications.

---

## ANNEX A — TECHNICAL SCHEDULE OF FEEDS, ENDPOINTS & POLLING BUDGETS

| Agency | Integration Module | Authorized Dataset / Endpoint | Max Polling Interval | Auth Mechanism | Fallback SLA Behavior |
| --- | --- | --- | --- | --- | --- |
| **NDRRMA / BIPAD** | `src/integrations/bipad.py` | `/api/v1/{alert,incident,river,rain,earthquake}/` + bilateral moderation sync | `[60 min monsoon / 7 d dry]` | `[Registered API Key / Token]` | Degrade to `cached` via `ProvenanceEnvelope` |
| **DHM** | `src/integrations/dhm.py` | 15-min river telemetry, hourly AWS rain, CAP v1.2 bulletins | `[15–30 min monsoon]` | `[Scoped Read-Only Token]` | Degrade to `stale` / `unavailable`; never blend with GloFAS |
| **DMG / NEMRC** | `src/integrations/nemrc.py` | Local $M_L \ge 3.5$ seismic JSON / FDSN QuakeML | `[15 min / webhook]` | `[Scoped Read-Only Token]` | Retain live USGS FDSN with explicit agency label |
| **DoR** | `src/integrations/roads_authority.py` | SRN highway blockage & bridge status JSON | `[60 min monsoon]` | `[Scoped Read-Only Token]` | Retain static OSM isolation screening with disclaimer |
| **Pilot DEOCs** | `src/moderation.py` & `src/cap_relay.py` | Authenticated moderation queue + CAP v1.2 Exercise/Pilot sign-off | On-demand officer action | `[MFA Officer SSO / Agency ID]` | Hard-locked to `Exercise` & `relay_enabled: false` until sign-off |

---

## ANNEX B — DESIGNATED NODAL OFFICERS & SIGNATORIES

| Party | Authorized Signatory Name & Title | Designated Technical Nodal Officer & Email | Signature & Seal | Date |
| --- | --- | --- | --- | --- |
| **NDRRMA (GoN)** | `[Name, Joint Secretary / Chief Executive]` | `[Name, BIPAD/NEOC Focal Point]` | `___________________` | `[YYYY-MM-DD]` |
| **DHM (GoN)** | `[Name, Director General]` | `[Name, Flood Forecasting Section]` | `___________________` | `[YYYY-MM-DD]` |
| **DMG / NEMRC (GoN)** | `[Name, Director General / Chief]` | `[Name, NEMRC Seismologist]` | `___________________` | `[YYYY-MM-DD]` |
| **DoR (GoN)** | `[Name, Director General]` | `[Name, Maintenance / SRN Focal Point]` | `___________________` | `[YYYY-MM-DD]` |
| **Pilot Municipality / DEOC** | `[Name, Chief District Officer / Chair]` | `[Name, DEOC Information Officer]` | `___________________` | `[YYYY-MM-DD]` |
| **Nepal TRĀYA Collaborator** | `[Prajwal Ghimire / Host Institution Lead]` | `prajwal.1.ghimire@kcl.ac.uk` | `___________________` | `[YYYY-MM-DD]` |
