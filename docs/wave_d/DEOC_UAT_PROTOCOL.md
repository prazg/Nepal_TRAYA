# DEOC Multilingual User Acceptance Testing (UAT) & Field Co-Design Protocol (`v3.0-pilot`)

**Document ID:** `TRAYA-WAVE-D-UAT` | **Milestone:** `v3.0-pilot` (Wave D Pre-Activation Gate)  
**Prerequisite Companion Docs:** [`AGENCY_MOU_TEMPLATE.md`](AGENCY_MOU_TEMPLATE.md), [`MULTILINGUAL_CAP_SMS_IVR_SOP.md`](MULTILINGUAL_CAP_SMS_IVR_SOP.md), [`../COMMUNITY_REPORTING_GOVERNANCE.md`](../COMMUNITY_REPORTING_GOVERNANCE.md), [`../TSHO_ROLPA_2D_STUDY_PLAN.md`](../TSHO_ROLPA_2D_STUDY_PLAN.md)

> **Evaluation Objective:**  
> Validate empirically — with real District Emergency Operation Centre (DEOC) officers, municipal DRR focal points, and local community listeners across four physiographic and linguistic regions of Nepal — that TRĀYA 2.0's official-vs-modelled separation, offline community reporting moderation queue, road-cut hospital isolation views, and 6-language CAP/SMS/IVR drafts are **clear, accurate, culturally respectful, usable on low-bandwidth mobile networks, and free of alert-confusion or PII-leakage hazards** prior to any Wave D pilot activation.

---

## 1. Priority Pilot DEOC Regions & Linguistic Coverage Matrix

| Pilot Cohort | Target DEOC & Municipalities | Province | Core Languages Tested | Primary Hazard & Operational Scenarios |
| --- | --- | --- | --- | --- |
| **Cohort 1 — Upper Mountain GLOF & Hill Corridor** | **Dolakha DEOC** (Charikot), **Gaurishankar RM**, **Bigu RM** | Bagmati Province | Nepali (`ne`), **Tamang (`taj`)**, English (`en`) | Tsho Rolpa GLOF corridor & Upper Tamakoshi / Singati checkpoints (`TRAYA-011`); road-cut hospital isolation; offline PWA landslide reporting (`uat_cr_dolakha_001`) during cellular blackout. |
| **Cohort 2 — Lower Gorge Cascade & Highway Access** | **Ramechhap DEOC** (Manthali), **Umakunda RM**, **Khadadevi RM** | Bagmati Province | Nepali (`ne`), **Tamang (`taj`)**, English (`en`) | Tama Koshi → Khurkot BP Highway bridge-cut isolation; multi-hazard seismic + GLOF cascade graph triage; inter-DEOC handoff with Dolakha. |
| **Cohort 3 — Eastern & Central Terai Fluvial Plains** | **Madhesh Province DEOCs** (e.g., **Dhanusha / Janakpurdham**, **Rautahat / Chandrapur**, **Bara–Parsa**) | Madhesh Province | Nepali (`ne`), **Maithili (`mai`)**, **Bhojpuri (`bho`)**, English (`en`) | Bagmati / Kamala / Lalbakaiya monsoon flooding; DHM/BIPAD official alert vs. GloFAS 30-day ensemble separation; Maithili & Bhojpuri SMS/IVR comprehension. |
| **Cohort 4 — Western Terai Major River Outlets** | **Kailali DEOC** (Dhangadhi / Tikapur) & **Bardiya DEOC** (Gulariya / Thakurdwara) | Sudurpashchim & Lumbini Provinces | Nepali (`ne`), **Tharu (`thr`)**, English (`en`) | Karnali (Chisapani `DHM-280`) & Babai (Chepang `DHM-289.95`) flood watch; Tharu spoken IVR comprehension in floodplain wards; low-bandwidth 3G mobile rendering. |

**Target Sample Size:** Minimum **4 DEOC tabletop workshops** (`6–10` officers/municipal focal points per DEOC) + **4 community listening panels** (`>= 15` native-speaker participants per regional language `mai`, `bho`, `thr`, `taj`, gender-balanced, ages 18–65+, including feature-phone users and low-literacy participants).

---

## 2. Structured UAT Test Modules & Exercise Scripts

Each DEOC workshop runs across **5 timed modules (total ~3.5 hours)** using strictly pre-labeled **`[EXERCISE]`** fixtures (`data/moderation_queue.json`, `data/cap_drafts.json`, `data/cap_exercise_latest.xml`):

### Module A — Epistemic Clarity & Official-vs-Modelled Separation (35 min)
- **Task A1:** Present side-by-side views of an official BIPAD/DHM river flood record (e.g., Chandrapur-4, Rautahat) and a GloFAS modelled river watch tier. Ask officers to identify which record is statutory authority, its exact NPT timestamp, and which hotline/agency owns escalation.
- **Task A2:** Inspect `Source Health` provenance badges (`live_observation`, `forecast`, `static_assessment`, `cached`, `unavailable` MOU stubs). Confirm officers correctly interpret `cached` weekly snapshots as non-live and never mistake an undated OSM `landslide_scar` for an active landslide event.
- **Task A3:** Inspect Tsho Rolpa corridor exposure and confirm officers recognize the 1 km buffer as a **screening corridor, NOT a 2D inundation boundary**, and notice the OSM hydropower blind spot explicitly documented for Upper Tamakoshi (456 MW).

### Module B — Low-Bandwidth & Offline Field Resilience (30 min)
- **Task B1 (Throttled 3G Test):** Load the static observatory on a mid-range Android phone throttled to `Slow 3G` (`400 kbps`, `400 ms RTT`) and measure First Contentful Paint, map/tab usability, and zero console/CSP errors.
- **Task B2 (Airplane-Mode Test):** Disconnect network completely; verify offline UI clarity, visible non-operational notice, one-tap emergency hotline links (`100 / 102 / 1114 / 1149 / 1155`), and offline IndexedDB community draft staging.

### Module C — Community Landslide Reporting & DEOC Moderation Drill (45 min)
- **Task C1 (PII Redaction & EXIF Audit):** Submit a synthetic drill narrative containing a dummy Nepal mobile number (`+977-9800000001`), email, citizenship number (`27-01-74-01234`), and `@handle`, plus a test photo carrying EXIF GPS headers. Verify:
  1. `redact_pii()` replaces all 4 PII classes with `[REDACTED_*]`;
  2. `exif_stripped` is enforced as `true` and zero EXIF tags survive;
  3. Unverified report enforces `fatalities: null`, `injuries: null` (rejecting `0`).
- **Task C2 (Duplicate Review & State Machine):** Review the synthetic Dolakha (`uat_cr_dolakha_001`) and Sindhupalchok (`uat_cr_sindhupalchok_002`) fixtures in `data/moderation_queue.json`:
  - Confirm unauthorized role (`public_user`) or blank `agency_id` is **blocked** (`PermissionError`);
  - Execute a `deoc_officer` promotion with valid `agency_id` and verify the promoted `landslide_event.v1` record passes schema validation;
  - Execute a `rejected_duplicate` action against a synthetic duplicate candidate (`auto_merged: false`).

### Module D — 6-Language CAP v1.2, SMS & IVR Comprehension Evaluation (60 min)
- **Task D1 (CAP Exercise Inspection):** Officers inspect `data/cap_exercise_latest.xml` and `data/cap_drafts.json`, verifying `<status>Exercise</status>`, `relay_enabled: false`, affected `NEPAL_DISTRICT` geocodes, and presence of all 5 hotlines (`1155 / 1149 / 1114 / 100 / 102`).
- **Task D2 (SMS Readability on Feature Phones & Smartphones):** Display `en`, `ne`, and cohort regional SMS (`taj`, `mai`, `bho`, or `thr`) on both basic feature phones and Android handsets. Verify zero mojibake, intact Devanagari conjuncts, clear `[अभ्यास]` prefix, and `<= 2` UCS-2 segments (`<= 140` chars).
- **Task D3 (Community IVR Audio Comprehension Panel):** Play the 25–35 s spoken IVR recording in the cohort's local mother tongue (`taj`, `mai`, `bho`, or `thr`) once (allowing optional `Press 1` replay). Ask each participant three standardized oral questions:
  1. *"Is this a real government emergency alert or a practice/exercise message?"*
  2. *"What hazard is mentioned, and what exact safety action should your household take?"*
  3. *"Which official phone number(s) should you call for verified information or rescue?"*
- **Task D4 (Linguistic Defect Capture):** Native reviewers flag any awkward phrasing, unfamiliar loanwords, disrespectful imperative endings, or regional dialect mismatches for template revision.

### Module E — Anti-False-Alarm & Rapid Cancellation Tabletop Drill (40 min)
- **Task E1 (Dual-Control Sign-Off Simulation):** Walk through the two-person approval checklist for a simulated `Severe` Tsho Rolpa / Karnali alert scenario.
- **Task E2 (5-Minute CAP `Cancel` Drill):** Simulate an erroneous alert draft and time how quickly duty officers locate the original CAP `<identifier>`, issue a `<msgType>Cancel</msgType>` retraction draft, and confirm clear cancellation wording across `en`, `ne`, and the local mother tongue.

---

## 3. Quantitative Pass / Fail Scoring Rubric & Wave D Exit Criteria

No pilot module may advance past sandbox status unless **ALL mandatory gates** below achieve **PASS**:

| Gate ID | Evaluation Criterion | Measurement Method | Minimum Pass Threshold | Blocking Gate? |
| --- | --- | --- | --- | --- |
| **UAT-01** | **Official-vs-Modelled Distinction** | Module A officer quiz across 4 cohorts | **`>= 90%`** correctly separate statutory BIPAD/DHM alerts from GloFAS / screening layers | **Hard Blocker** |
| **UAT-02** | **Non-Operational & Hotline Recognition** | Module A + D officer & community checks | **`100%`** identify non-operational banner & cite at least `1155` / `1149` / `100` | **Hard Blocker** |
| **UAT-03** | **Zero PII Leakage & EXIF Stripping** | Module C moderation drill audit | **`0`** unredacted phone/email/ID/handle strings & **`0`** surviving EXIF tags | **Hard Blocker** |
| **UAT-04** | **Authenticated Role Enforcement** | Module C negative authorization tests | **`100%`** unauthorized roles & missing `agency_id` promotions rejected | **Hard Blocker** |
| **UAT-05** | **6-Language SMS Encoding & Clarity** | Module D feature-phone & Android checks | **`100%`** `en <= 160` ASCII, Devanagari `<= 140` chars, `0` mojibake, `0` truncated hotlines | **Hard Blocker** |
| **UAT-06** | **Native-Speaker IVR Comprehension** | Module D community panels (`n >= 15`/lang) | **`>= 85%`** mean comprehension score in each target language (`mai`, `bho`, `thr`, `taj`) | **Hard Blocker (per language)** |
| **UAT-07** | **Low-Bandwidth & Offline Usability** | Module B throttled Slow-3G Android test | Initial usable load **`< 5.0 s`** on Slow 3G; offline draft persistence **`100%`** | Required for PWA Pilot |
| **UAT-08** | **False-Alarm Retraction Time** | Module E tabletop `Cancel` drill | CAP `Cancel` + multilingual correction drafted within **`<= 5 minutes`** | **Hard Blocker (for CAP Pilot)** |
| **UAT-09** | **DEOC Operational Value Score** | Post-workshop Likert survey (1–5 scale) | Mean usefulness & clarity score **`>= 4.0 / 5.0`** with zero unresolved Severity-1 UX defects | Required for Sign-Off |

---

## 4. Facilitator Checklist & Zero-PII Evaluation Protocol

### Pre-Session Facilitator Checklist
- [ ] Confirm all demo URLs and XML/JSON payloads are strictly in `Exercise` / `pilot_sandbox_post_mou` mode (`relay_enabled: false`, `public_live_endpoint_enabled: false`).
- [ ] Print bilingual consent briefing sheets and large-print hotline cards (`1155`, `1149`, `1114`, `100`, `102`) for every participant.
- [ ] Prepare at least 1 basic keypad feature phone (UCS-2 SMS check) and 2 Android smartphones with DevTools Slow-3G throttling.
- [ ] Pre-load locally recorded native voice clips (`25–35 s`) for the cohort's regional language (`taj` / `mai` / `bho` / `thr`) plus `ne` and `en`.
- [ ] Assign an independent note-taker who records **only anonymized participant codes** (e.g., `DLK-P01`, `MDH-P04`) — **never** participant full names, phone numbers, or citizenship numbers in UAT datasets.

### Anonymized Participant Evaluation Record Template (Zero-PII)
```text
Cohort ID: [DLK | RMC | MDH | KLB]    Participant Code: [e.g., DLK-P01]
Role Group: [DEOC Officer | Municipal DRR | Ward Volunteer | Community Listener]
Primary Mother Tongue: [ne | mai | bho | thr | taj | other]
Device Type Used: [Feature Phone | Android Smartphone | Desktop]
Module A Score (Official vs Modelled): [ /5]
Module C Moderation/PII Check: [PASS / FAIL / N/A]
Module D SMS Clarity (1-5): [ ]   IVR Comprehension (0-3): [ ]   Dialect/Word Fixes: [Notes]
Module E Cancel Drill Time: [ mm:ss ]   Overall Usefulness (1-5): [ ]
```

---

## 5. Cohort UAT Sign-Off Matrix

| Pilot Cohort | Workshop Date | Officers / Community `n` | Blocking Gates Passed (`UAT-01`–`UAT-08`) | Linguistic Promotion Status | DEOC Focal Point Sign-Off |
| --- | --- | --- | --- | --- | --- |
| **Dolakha DEOC & Gaurishankar RM** | `[YYYY-MM-DD]` | `[n_off / n_comm]` | `[Pending UAT]` | `taj`: `draft_pending_native_municipal_review` | `________________` |
| **Ramechhap DEOC & Manthali** | `[YYYY-MM-DD]` | `[n_off / n_comm]` | `[Pending UAT]` | `taj`: `draft_pending_native_municipal_review` | `________________` |
| **Madhesh DEOCs (Dhanusha / Rautahat / Bara–Parsa)** | `[YYYY-MM-DD]` | `[n_off / n_comm]` | `[Pending UAT]` | `mai`, `bho`: `draft_pending_native_municipal_review` | `________________` |
| **Kailali & Bardiya DEOCs** | `[YYYY-MM-DD]` | `[n_off / n_comm]` | `[Pending UAT]` | `thr`: `draft_pending_native_municipal_review` | `________________` |
