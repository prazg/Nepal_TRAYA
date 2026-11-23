"""
Governed 6-Language OASIS CAP v1.2 & SMS/IVR Exercise Relay Generator for
Nepal TRĀYA 2.0 (`TRAYA-013` / Issue #10).

Supported Nepal Languages (6):
  1. `en`  — English (Latin, `reviewed_baseline`)
  2. `ne`  — नेपाली / Nepali (Devanagari, `reviewed_baseline`)
  3. `mai` — मैथिली / Maithili (Devanagari, `draft_pending_native_municipal_review`)
  4. `bho` — भोजपुरी / Bhojpuri (Devanagari, `draft_pending_native_municipal_review`)
  5. `thr` — थारू / Tharu (Devanagari, `draft_pending_native_municipal_review`)
  6. `taj` — तामाङ / Tamang (Devanagari, `draft_pending_native_municipal_review`)

Hard Governance & Safety Invariants:
  * Strictly emits OASIS CAP v1.2 (`urn:oasis:names:tc:emergency:cap:1.2`)
    payloads with `<status>Exercise</status>` (NEVER `Actual` prior to Wave D MOU).
  * `relay_governance.relay_enabled` is hard-locked to `False` with
    `requires_signed_mou: True` and `statutory_warning: False`.
  * Enforces GSM-7 ASCII SMS <= 160 chars (`en`) and UCS-2 Devanagari SMS <= 140 chars
    (`ne`, `mai`, `bho`, `thr`, `taj`), plus 25–35 s spoken IVR scripts referencing
    official Nepal emergency hotlines (`1155`, `1149`, `1114`, `100`, `102`).

Pure Python 3.12 standard library only (zero third-party dependencies).
Outputs:
  * `data/cap_drafts.json`         (all Exercise advisories + 6-language SMS/IVR + provenance)
  * `data/cap_exercise_latest.xml` (well-formed OASIS CAP v1.2 XML for top Exercise advisory)
"""
from __future__ import annotations

import argparse
import datetime as dt
import json
import math
import os
import re
import sys
import tempfile
import xml.etree.ElementTree as ET
from pathlib import Path
from typing import Any

SRC_DIR = os.path.dirname(os.path.abspath(__file__))
if SRC_DIR not in sys.path:
    sys.path.insert(0, SRC_DIR)

import config as C
import refresh_weekly as RW
from integrations import provenance as PROV

CAP_XMLNS = "urn:oasis:names:tc:emergency:cap:1.2"
SCHEMA_VERSION = "cap_v12_advisory.v1"
SCHEMA_REF = "schemas/cap_v12_advisory.schema.json"
CAP_SENDER = "traya-exercise-sandbox@prazg.github.io"
CAP_WEB_URL = "https://prazg.github.io/Nepal_TRAYA/"
CAP_CONTACT = (
    "Official Nepal Statutory Hotlines: DHM 1155 | NDRRMA/NEOC 1149 | "
    "APF Rescue 1114 | Nepal Police 100 | Ambulance 102"
)

NPT_TZ = dt.timezone(dt.timedelta(hours=5, minutes=45))
ELEVATED_RIVER_TIERS = frozenset({"elevated", "q2_watch", "q5_warning", "q20_severe"})
REQUIRED_HOTLINES = ("1155", "1149", "1114", "100", "102")

SUPPORTED_LANGUAGES: tuple[dict[str, Any], ...] = (
    {
        "code": "en",
        "name_en": "English",
        "name_native": "English",
        "script": "Latin",
        "linguistic_review_status": "reviewed_baseline",
        "sms_encoding": "GSM-7",
        "sms_max_chars": 160,
        "speaking_rate_wpm": 135,
        "target_provinces": list(C.CANONICAL_PROVINCES),
    },
    {
        "code": "ne",
        "name_en": "Nepali",
        "name_native": "नेपाली",
        "script": "Devanagari",
        "linguistic_review_status": "reviewed_baseline",
        "sms_encoding": "UCS-2",
        "sms_max_chars": 140,
        "speaking_rate_wpm": 130,
        "target_provinces": list(C.CANONICAL_PROVINCES),
    },
    {
        "code": "mai",
        "name_en": "Maithili",
        "name_native": "मैथिली",
        "script": "Devanagari",
        "linguistic_review_status": "draft_pending_native_municipal_review",
        "sms_encoding": "UCS-2",
        "sms_max_chars": 140,
        "speaking_rate_wpm": 130,
        "target_provinces": ["Madhesh Province", "Koshi Province"],
    },
    {
        "code": "bho",
        "name_en": "Bhojpuri",
        "name_native": "भोजपुरी",
        "script": "Devanagari",
        "linguistic_review_status": "draft_pending_native_municipal_review",
        "sms_encoding": "UCS-2",
        "sms_max_chars": 140,
        "speaking_rate_wpm": 130,
        "target_provinces": ["Madhesh Province", "Lumbini Province"],
    },
    {
        "code": "thr",
        "name_en": "Tharu",
        "name_native": "थारू",
        "script": "Devanagari",
        "linguistic_review_status": "draft_pending_native_municipal_review",
        "sms_encoding": "UCS-2",
        "sms_max_chars": 140,
        "speaking_rate_wpm": 130,
        "target_provinces": ["Sudurpashchim Province", "Lumbini Province", "Bagmati Province", "Koshi Province"],
    },
    {
        "code": "taj",
        "name_en": "Tamang",
        "name_native": "तामाङ",
        "script": "Devanagari",
        "linguistic_review_status": "draft_pending_native_municipal_review",
        "sms_encoding": "UCS-2",
        "sms_max_chars": 140,
        "speaking_rate_wpm": 130,
        "target_provinces": ["Bagmati Province", "Koshi Province", "Gandaki Province"],
    },
)

LANG_META_BY_CODE: dict[str, dict[str, Any]] = {m["code"]: m for m in SUPPORTED_LANGUAGES}

DEVA_DIGITS = str.maketrans("0123456789", "०१२३४५६७८९")

# District name aliases for matching BIPAD alert titles cleanly
_DISTRICT_ALIASES: dict[str, str] = {
    "dhanusa": "Dhanusha",
    "kavrepalanchok": "Kabhrepalanchok",
    "kapilbastu": "Kapilvastu",
    "makawanpur": "Makwanpur",
    "nawalparasi east": "Nawalpur",
    "nawalparasi west": "Parasi",
    "sindhupalchowk": "Sindhupalchok",
}


def _default_relay_governance() -> dict[str, Any]:
    return {
        "relay_enabled": False,
        "requires_signed_mou": True,
        "statutory_warning": False,
        "cap_status": "Exercise",
        "officer_signoff_required": True,
        "authorizing_agencies_required": ["NDRRMA", "DHM", "DMG/NEMRC", "DoR"],
    }


def _to_deva_num(val: int | str) -> str:
    return str(val).translate(DEVA_DIGITS)


def _format_cap_npt(ts: dt.datetime) -> str:
    """Format an aware datetime as OASIS CAP v1.2 compliant NPT string (+05:45)."""
    return ts.astimezone(NPT_TZ).strftime("%Y-%m-%dT%H:%M:%S+05:45")


def _district_ne(name: str) -> str:
    return RW.DISTRICT_NE.get(name, name)


def _districts_short_en(districts: list[str], limit: int = 2) -> str:
    if not districts:
        return "Nepal"
    if len(districts) <= limit:
        return ", ".join(districts)
    return f"{', '.join(districts[:limit])} +{len(districts) - limit}"


def _districts_short_deva(districts: list[str], limit: int = 2) -> str:
    if not districts:
        return "नेपाल"
    ne_list = [_district_ne(d) for d in districts]
    if len(ne_list) <= limit:
        return ", ".join(ne_list)
    return f"{', '.join(ne_list[:limit])} (+{_to_deva_num(len(ne_list) - limit)})"


def _districts_full_deva(districts: list[str]) -> str:
    if not districts:
        return "नेपाल क्षेत्र"
    return ", ".join(_district_ne(d) for d in districts)


def _sms_segments(text: str, encoding: str) -> int:
    n = len(text)
    if encoding == "GSM-7":
        return 1 if n <= 160 else math.ceil(n / 153)
    return 1 if n <= 70 else math.ceil(n / 67)


def _build_sms_draft(text: str, lang_code: str) -> dict[str, Any]:
    meta = LANG_META_BY_CODE[lang_code]
    encoding = meta["sms_encoding"]
    max_chars = int(meta["sms_max_chars"])
    clean = re.sub(r"\s+", " ", text).strip()

    if encoding == "GSM-7":
        # Guarantee pure ASCII for GSM-7 English SMS
        clean = (
            clean.replace("—", "-")
            .replace("–", "-")
            .replace("’", "'")
            .replace("“", '"')
            .replace("”", '"')
            .replace("→", "->")
            .replace("≥", ">=")
            .replace("Ā", "A")
            .replace("ā", "a")
        )
        clean = clean.encode("ascii", "ignore").decode("ascii")

    if len(clean) > max_chars:
        # Preserve mandatory hotline suffix while safely shortening middle
        suffix_match = re.search(r"((?:Info|Official|सूचना):[^।.]*102[।.]?)$", clean)
        if suffix_match:
            suffix = suffix_match.group(1)
            head_budget = max_chars - len(suffix) - 2
            head = clean[: max(10, head_budget)].rstrip(" ,;:-।.")
            clean = f"{head}. {suffix}" if encoding == "GSM-7" else f"{head}। {suffix}"
        if len(clean) > max_chars:
            clean = clean[:max_chars].rstrip()

    n_chars = len(clean)
    return {
        "text": clean,
        "encoding": encoding,
        "char_count": n_chars,
        "max_chars_budget": max_chars,
        "sms_segments": _sms_segments(clean, encoding),
        "within_budget": n_chars <= max_chars,
    }


def _build_ivr_script(text: str, lang_code: str, repeat_prompt: str) -> dict[str, Any]:
    meta = LANG_META_BY_CODE[lang_code]
    wpm = int(meta["speaking_rate_wpm"])
    clean = re.sub(r"\s+", " ", text).strip()
    words = [w for w in re.split(r"\s+", clean) if w]
    word_count = len(words)
    dur_sec = round((word_count / float(wpm)) * 60.0, 1)
    return {
        "text": clean,
        "word_count": word_count,
        "speaking_rate_wpm": wpm,
        "estimated_duration_sec": dur_sec,
        "repeat_key_instruction": repeat_prompt,
    }


# ---------------------------------------------------------------------------
# Multilingual 6-language content catalog (authentic, respectful phrasing)
# ---------------------------------------------------------------------------
_SENDER_NAMES: dict[str, str] = {
    "en": "Nepal TRAYA Exercise Sandbox (Not Official Warning)",
    "ne": "नेपाल त्राय अभ्यास परीक्षण प्रणाली (आधिकारिक चेतावनी होइन)",
    "mai": "नेपाल त्राय अभ्यास परीक्षण प्रणाली (आधिकारिक चेतावनी नहि)",
    "bho": "नेपाल त्राय अभ्यास परीक्षण प्रणाली (सरकारी चेतावनी ना ह)",
    "thr": "नेपाल त्राय अभ्यास परीक्षण प्रणाली (सरकारी चेतावनी नाइ हो)",
    "taj": "नेपाल त्राय अभ्यास परीक्षण प्रणाली (सरकारी चेतावनी आहिन)",
}

_REPEAT_PROMPTS: dict[str, str] = {
    "en": "Press 1 to hear this exercise guidance again, or press 2 for Nepal emergency numbers.",
    "ne": "यो अभ्यास सन्देश फेरि सुन्न १ थिच्नुहोस्, वा आपतकालीन नम्बरका लागि २ थिच्नुहोस्।",
    "mai": "ई अभ्यास सन्देश फेर सुनबाक लेल १ दबाउ, वा आपतकालीन नम्बरक लेल २ दबाउ।",
    "bho": "ई अभ्यास संदेश फिर से सुने खातिर १ दबाईं, भा आपातकालीन नंबर खातिर २ दबाईं।",
    "thr": "यी अभ्यास सन्देश फेर सुनेक लाग १ दबाऊ, वा आपतकालीन नम्बरक लाग २ दबाऊ।",
    "taj": "चु अभ्यास सन्देश दोसि ङ्यान्बारि १ थिच्गो, अथवा आपतकालीन नम्बरला लागि २ थिच्गो।",
}

# Per-hazard localized templates covering all 6 languages
_HAZARD_TEMPLATES: dict[str, dict[str, dict[str, str]]] = {
    "quake_coseismic": {
        "en": {
            "event": "Earthquake & Coseismic Slope-Hazard Screening (Exercise)",
            "event_short": "Quake-Slope Watch",
            "headline": "[EXERCISE] Coseismic Landslide & Corridor Screening: {dist_short}",
            "desc": (
                "EXERCISE DRAFT ONLY (NOT AN OFFICIAL WARNING). TRĀYA multi-hazard screening detected "
                "recent M >= 4.5 seismicity near steep mountain corridors and high-hazard glacial lakes "
                "across {dist_full}. {detail_en} Verify all seismic bulletins with DMG/NEMRC and NDRRMA."
            ),
            "instr": (
                "Stay clear of loose rock slopes, cracked hillsides, and narrow river gorges after shaking. "
                "Inspect access trails and bridges cautiously. For official Nepal bulletins and emergencies "
                "contact DHM 1155, NDRRMA/NEOC 1149, APF Rescue 1114, Nepal Police 100, or Ambulance 102."
            ),
            "sms_action": "Avoid steep slopes & gorges",
            "ivr": (
                "Attention please. This is a Nepal TRAYA disaster preparedness exercise message, not an official "
                "government warning. Recent earthquake activity has been noted near steep mountain slopes and "
                "high-altitude glacial valleys in {dist_short}. Please stay away from cracked hillsides, falling "
                "rocks, and narrow river valleys, and watch for aftershocks. Check official updates from the "
                "National Earthquake Monitoring Centre and NDRRMA. For help call 1155, 1149, 1114, 100, or 102. "
                "Press 1 to repeat."
            ),
        },
        "ne": {
            "event": "भूकम्प तथा भूकम्प-प्रेरित पहिरो स्क्रिनिङ (अभ्यास)",
            "event_short": "भूकम्प-पहिरो निगरानी",
            "headline": "[अभ्यास] भूकम्प-प्रेरित पहिरो र करिडोर निगरानी: {dist_short}",
            "desc": (
                "यो अभ्यास मस्यौदा मात्र हो, आधिकारिक सरकारी चेतावनी होइन। त्राय बहु-प्रकोप स्क्रिनिङले "
                "{dist_full} का पहाडी करिडोर र उच्च-जोखिम हिमताल नजिक हालैको भूकम्पीय गतिविधि पहिचान गरेको छ। "
                "कृपया राष्ट्रिय भूकम्प मापन केन्द्र (NEMRC) र NDRRMA को आधिकारिक सूचना अवश्य हेर्नुहोस्।"
            ),
            "instr": (
                "भूकम्पपछि चर्किएका भिराला जमिन, ढुङ्गा खस्ने पाखा र साँघुरा नदी किनारबाट सुरक्षित टाढा रहनुहोस्। "
                "सडक र पुल पार गर्नुअघि सावधानी अपनाउनुहोस्। आधिकारिक सूचना र आपतकालीन सहयोगका लागि "
                "DHM 1155, NEOC 1149, सशस्त्र प्रहरी उद्धार 1114, प्रहरी 100 वा एम्बुलेन्स 102 मा फोन गर्नुहोस्।"
            ),
            "sms_action": "भिरालो र नदी किनारबाट टाढा रहनुहोस्",
            "ivr": (
                "नमस्कार, कृपया ध्यान दिनुहोस्। यो नेपाल त्रायको विपद् पूर्वतयारी अभ्यास सन्देश हो, आधिकारिक "
                "सरकारी चेतावनी होइन। {dist_short} क्षेत्रका पहाडी भूभाग र हिमताल आसपास हालै भूकम्प अभिलेख "
                "भएको छ। कृपया चर्किएका भिराला पाखा, पहिरो सम्भावित सडक र नदी किनारबाट सुरक्षित टाढा रहनुहोस्। "
                "आधिकारिक जानकारीका लागि राष्ट्रिय भूकम्प मापन केन्द्र तथा NDRRMA को सूचना हेर्नुहोस्। "
                "आकस्मिक सहयोगका लागि 1155, 1149, 1114, 100 वा 102 मा फोन गर्नुहोस्। फेरि सुन्न १ थिच्नुहोस्।"
            ),
        },
        "mai": {
            "event": "भूकम्प आ पहिरो जोखिम निगरानी (अभ्यास)",
            "event_short": "भूकम्प-पहिरो निगरानी",
            "headline": "[अभ्यास] भूकम्प आ पहिरो निगरानी: {dist_short}",
            "desc": (
                "ई अभ्यास मस्यौदा मात्र अछि, आधिकारिक सरकारी चेतावनी नहि अछि। त्राय जोखिम अवलोकन मे "
                "{dist_full} जिला सभक पहाड़ी क्षेत्र आ हिमताल लग हालक भूकम्प दर्ज भेल अछि। "
                "आधिकारिक जानकारीक लेल राष्ट्रीय भूकम्प मापन केन्द्र आ NDRRMA केर सूचना अवश्य देखू।"
            ),
            "instr": (
                "भूकम्पक बाद कमजोर पहाड़ी ढलान, पत्थर खसबाक स्थान आ नदी किनार सँ सुरक्षित दूर रहू। "
                "सड़क आ पुल पार करबाक समय विशेष सावधानी राखू। सरकारी सूचना आ आपतकालीन सहायताक लेल "
                "DHM 1155, NEOC 1149, सशस्त्र प्रहरी 1114, पुलिस 100 वा एम्बुलेन्स 102 पर फोन करू।"
            ),
            "sms_action": "ढलान आ नदी किनार सँ दूर रहू",
            "ivr": (
                "प्रणाम, कृपया ध्यान दिअ। ई नेपाल त्राय केर विपद् पूर्वतयारी अभ्यास सन्देश अछि, ई आधिकारिक "
                "सरकारी चेतावनी नहि अछि। {dist_short} क्षेत्रक पहाड़ी मार्ग आ हिमताल लग हाल भूकम्प दर्ज "
                "भेल अछि। कृपया कमजोर ढलान, पहिरो वाला सड़क आ नदी किनार सँ सुरक्षित दूर रहू आ आपन "
                "परिवार केँ सुरक्षित राखू। सरकारी जानकारीक लेल 1155, 1149, 1114, 100 वा 102 पर फोन करू। "
                "ई सन्देश फेर सुनबाक लेल १ दबाउ।"
            ),
        },
        "bho": {
            "event": "भूकम्प आ पहिरो खतरा निगरानी (अभ्यास)",
            "event_short": "भूकम्प-पहिरो निगरानी",
            "headline": "[अभ्यास] भूकम्प आ पहिरो निगरानी: {dist_short}",
            "desc": (
                "ई खाली अभ्यास संदेश ह, आधिकारिक सरकारी चेतावनी ना ह। त्राय जोखिम जांच में {dist_full} "
                "जिला सब के पहाड़ी इलाका आ हिमताल लगे हाल में भूकम्प दर्ज भइल बा। आधिकारिक जानकारी "
                "खातिर राष्ट्रीय भूकम्प मापन केन्द्र आ NDRRMA के सूचना जरूर देखीं।"
            ),
            "instr": (
                "भूकम्प के बाद दरार पड़ल पहाड़, चट्टान खसे वाला जगह आ नदी किनार से सुरक्षित दूर रहीं। "
                "सड़क आ पुल पार करत समय सावधानी बरतीं। सरकारी सूचना आ आपातकालीन मदद खातिर "
                "DHM 1155, NEOC 1149, सशस्त्र पुलिस 1114, पुलिस 100 भा एम्बुलेन्स 102 पर फोन करीं।"
            ),
            "sms_action": "ढलान आ नदी किनार से दूर रहीं",
            "ivr": (
                "प्रणाम, कृपया ध्यान दीं। ई नेपाल त्राय के विपद् तैयारी अभ्यास संदेश ह, आधिकारिक सरकारी "
                "चेतावनी ना ह। {dist_short} इलाका के पहाड़ी रास्ता आ हिमताल लगे हाल में भूकम्प आइल बा। "
                "कृपया कमजोर ढलान, पहिरो वाला सड़क आ नदी किनार से सुरक्षित दूर रहीं आ अपना परिवार के "
                "ध्यान राखीं। आधिकारिक जानकारी आ मदद खातिर 1155, 1149, 1114, 100 भा 102 पर फोन करीं। "
                "संदेश फिर से सुने खातिर १ दबाईं।"
            ),
        },
        "thr": {
            "event": "भुइँचाल व पहिरो जोखिम निगरानी (अभ्यास)",
            "event_short": "भुइँचाल-पहिरो निगरानी",
            "headline": "[अभ्यास] भुइँचाल व पहिरो निगरानी: {dist_short}",
            "desc": (
                "यी केवल अभ्यास सन्देश हो, सरकारी चेतावनी नाइ हो। त्राय जोखिम जाँचमे {dist_full} "
                "जिल्लामनक पहाडी क्षेत्र व हिमताल लग्गे हाल भुइँचाल अभिलेख हुइल बा। सरकारी जानकारीक "
                "लाग राष्ट्रिय भूकम्प मापन केन्द्र व NDRRMA के सूचना जरुर हेरू।"
            ),
            "instr": (
                "भुइँचाल पाछे चर्कल पहाड, ढुङ्गा खस्ने ठाउँ व नदी किनारसे सुरक्षित दूर रहू। "
                "सडक व पुल पार करबेर होसियार रहू। सरकारी जानकारी व आपतकालीन मददक लाग "
                "DHM 1155, NEOC 1149, सशस्त्र प्रहरी 1114, प्रहरी 100 वा एम्बुलेन्स 102 मे फोन करू।"
            ),
            "sms_action": "भिरालो व नदी किनारसे दूर रहू",
            "ivr": (
                "नमस्कार, सबै जने ध्यान देऊ। यी नेपाल त्राय के विपद् पूर्वतयारी अभ्यास सन्देश हो, आधिकारिक "
                "सरकारी चेतावनी नाइ हो। {dist_short} क्षेत्रक पहाडी बाटो व हिमताल लग्गे हाल भुइँचाल आयल "
                "बा। कृपया कमजोर भिरालो पाखा, पहिरो क्षेत्र व नदी किनारसे सुरक्षित दूर रहू व अपन परिवारके "
                "सुरक्षित राखू। सरकारी जानकारी व सहयोगक लाग 1155, 1149, 1114, 100 वा 102 मे फोन करू। "
                "सन्देश फेर सुनेक लाग १ दबाऊ।"
            ),
        },
        "taj": {
            "event": "भूकम्प (सागुल) र पहिरो निगरानी (अभ्यास)",
            "event_short": "भूकम्प-पहिरो निगरानी",
            "headline": "[अभ्यास] भूकम्प (सागुल) र पहिरो निगरानी: {dist_short}",
            "desc": (
                "चु अभ्यास सन्देश जेन हिन्ना, सरकारी चेतावनी आहिन। त्राय जोखिम जाँचरि {dist_full} "
                "जिल्लाकादेरि गाङ्ला ग्याम र हिमताल छ्यउरि हाल भूकम्प (सागुल) रेकर्ड ताबा मुला। "
                "सरकारी सूचनाला लागि राष्ट्रिय भूकम्प मापन केन्द्र र NDRRMA ला सूचना च्यागो।"
            ),
            "instr": (
                "भूकम्प लिच्छा चर्कबा गाङ्, युङ्बा ख्लाबा ग्ला र स्योङ् छ्यउरि था निगो। "
                "सडक र साँघु तारिमा होसियार टिगो। सरकारी सूचना र आपतकालीन सहयोगला लागि "
                "DHM 1155, NEOC 1149, सशस्त्र प्रहरी 1114, प्रहरी 100 अथवा एम्बुलेन्स 102 रि फोन ल्हागो।"
            ),
            "sms_action": "भिरालो र स्योङ् छ्यउरि था निगो",
            "ivr": (
                "लास्सो, कृपया ध्यान पिङ्गो। चु नेपाल त्रायला विपद् पूर्वतयारी अभ्यास सन्देश हिन्ना, सरकारी "
                "चेतावनी आहिन। {dist_short} क्षेत्रला पहाडी ग्याम र हिमताल छ्यउरि हाल भूकम्प (सागुल) "
                "रेकर्ड ताबा मुला। कृपया कमजोर भिरालो ग्ला, पहिरो ग्याम र स्योङ् छ्यउरि था निगो। ह्राङ्ला "
                "परिवारदा सुरक्षित थान्गो। सरकारी जानकारी र सहयोगला लागि 1155, 1149, 1114, 100 अथवा "
                "102 रि फोन ल्हागो। सन्देश दोसि ङ्यान्बारि १ थिच्गो।"
            ),
        },
    },
    "glof_stress": {
        "en": {
            "event": "Glacial Lake Valley Stress & Corridor Screening (Exercise)",
            "event_short": "GLOF Corridor Watch",
            "headline": "[EXERCISE] Glacial Lake Corridor Screening: {dist_short}",
            "desc": (
                "EXERCISE DRAFT ONLY (NOT AN OFFICIAL WARNING). TRĀYA screening highlights glacial lake "
                "susceptibility with thermal or seismic stress indicators along downstream valleys in "
                "{dist_full}. {detail_en} This is a screening watch, not a breach forecast."
            ),
            "instr": (
                "Monitor official DHM river-level advisories along high-mountain valleys and know higher-ground "
                "evacuation routes away from riverbanks and bridges. For official updates and emergencies call "
                "DHM 1155, NDRRMA/NEOC 1149, APF Rescue 1114, Nepal Police 100, or Ambulance 102."
            ),
            "sms_action": "Stay alert near glacial rivers",
            "ivr": (
                "Attention please. This is a Nepal TRAYA disaster preparedness exercise message, not an official "
                "government warning. Screening indicators show glacial lake environmental stress along mountain "
                "river valleys in {dist_short}. This is not a lake breach forecast, but residents near glacial "
                "rivers and bridges should know safe high ground and follow official Department of Hydrology "
                "and Meteorology bulletins. For official help call 1155, 1149, 1114, 100, or 102. Press 1 to repeat."
            ),
        },
        "ne": {
            "event": "हिमताल करिडोर संवेदनशीलता तथा नदी निगरानी (अभ्यास)",
            "event_short": "हिमताल करिडोर निगरानी",
            "headline": "[अभ्यास] हिमताल तथा नदी करिडोर निगरानी: {dist_short}",
            "desc": (
                "यो अभ्यास मस्यौदा मात्र हो, आधिकारिक सरकारी चेतावनी होइन। त्राय स्क्रिनिङले {dist_full} का "
                "तल्लो तटीय उपत्यकामा हिमताल संवेदनशीलता र तापीय वा भूकम्पीय चाप देखाएको छ। यो हिमताल "
                "विस्फोटनको पूर्वानुमान होइन; आधिकारिक सूचनाका लागि DHM र NDRRMA सँग सम्पर्कमा रहनुहोस्।"
            ),
            "instr": (
                "हिमनदी किनार र पुल आसपासका बासिन्दाले अग्लो सुरक्षित स्थानको पहिचान गरी सचेत रहनुहोस् "
                "र नदीको बहाव अस्वाभाविक घटे वा बढेमा तुरुन्त माथिल्लो भागमा जानुहोस्। आधिकारिक सूचनाका लागि "
                "DHM 1155, NEOC 1149, सशस्त्र प्रहरी 1114, प्रहरी 100 वा एम्बुलेन्स 102 मा फोन गर्नुहोस्।"
            ),
            "sms_action": "हिमनदी किनारमा सचेत रहनुहोस्",
            "ivr": (
                "नमस्कार, कृपया ध्यान दिनुहोस्। यो नेपाल त्रायको विपद् पूर्वतयारी अभ्यास सन्देश हो, आधिकारिक "
                "सरकारी चेतावनी होइन। {dist_short} क्षेत्रका हिमाली नदी करिडोरमा हिमताल जोखिम स्क्रिनिङ सूचक "
                "सक्रिय देखिएको छ। यो विस्फोटनको पूर्वानुमान होइन, तर नदी किनार र पुल नजिकका बासिन्दाले "
                "सुरक्षित अग्लो स्थान थाहा राख्नुहोस् र DHM को आधिकारिक सूचना हेर्नुहोस्। सहयोगका लागि "
                "1155, 1149, 1114, 100 वा 102 मा फोन गर्नुहोस्। फेरि सुन्न १ थिच्नुहोस्।"
            ),
        },
        "mai": {
            "event": "हिमताल आ नदी किनार निगरानी (अभ्यास)",
            "event_short": "हिमताल-नदी निगरानी",
            "headline": "[अभ्यास] हिमताल आ नदी करिडोर निगरानी: {dist_short}",
            "desc": (
                "ई अभ्यास मस्यौदा मात्र अछि, आधिकारिक सरकारी चेतावनी नहि अछि। त्राय स्क्रिनिङ मे {dist_full} "
                "जिला सभक पहाड़ी नदी घाटी मे हिमताल संवेदनशीलता सूचक देखल गेल अछि। ई आधिकारिक बाढ़ि "
                "चेतावनी नहि अछि; सरकारी जानकारीक लेल DHM आ NDRRMA केर सूचना अवश्य देखू।"
            ),
            "instr": (
                "नदी किनार आ पुल लग रहनिहार लोकनि सुरक्षित ऊँच स्थानक जानकारी राखू आ नदीक जलस्तर पर ध्यान दिअ। "
                "आधिकारिक सूचना आ आपतकालीन सहायताक लेल DHM 1155, NEOC 1149, सशस्त्र प्रहरी 1114, "
                "पुलिस 100 वा एम्बुलेन्स 102 पर फोन करू।"
            ),
            "sms_action": "नदी किनार मे सचेत रहू",
            "ivr": (
                "प्रणाम, कृपया ध्यान दिअ। ई नेपाल त्राय केर विपद् पूर्वतयारी अभ्यास सन्देश अछि, आधिकारिक "
                "सरकारी चेतावनी नहि अछि। {dist_short} क्षेत्रक नदी घाटी मे हिमताल जोखिम सूचक देखल गेल "
                "अछि। ई विस्फोटनक पूर्वानुमान नहि अछि, मुदा नदी किनार आ पुल लग रहनिहार परिवार सुरक्षित "
                "ऊँच स्थानक जानकारी राखू आ DHM केर सूचना देखू। सहायताक लेल 1155, 1149, 1114, 100 वा "
                "102 पर फोन करू। फेर सुनबाक लेल १ दबाउ।"
            ),
        },
        "bho": {
            "event": "हिमताल आ नदी किनार निगरानी (अभ्यास)",
            "event_short": "हिमताल-नदी निगरानी",
            "headline": "[अभ्यास] हिमताल आ नदी किनार निगरानी: {dist_short}",
            "desc": (
                "ई खाली अभ्यास संदेश ह, आधिकारिक सरकारी चेतावनी ना ह। त्राय जांच में {dist_full} जिला "
                "सब के नदी घाटी में हिमताल संवेदनशीलता के संकेत मिलल बा। ई सरकारी चेतावनी ना ह; "
                "आधिकारिक जानकारी खातिर DHM आ NDRRMA के सूचना जरूर देखीं।"
            ),
            "instr": (
                "नदी किनार आ पुल लगे रहे वाला लोग ऊँच आ सुरक्षित जगह के जानकारी राखीं आ पानी के स्तर पर "
                "ध्यान दीं। आधिकारिक सूचना आ आपातकालीन मदद खातिर DHM 1155, NEOC 1149, सशस्त्र पुलिस 1114, "
                "पुलिस 100 भा एम्बुलेन्स 102 पर फोन करीं।"
            ),
            "sms_action": "नदी किनार पर सावधान रहीं",
            "ivr": (
                "प्रणाम, कृपया ध्यान दीं। ई नेपाल त्राय के विपद् तैयारी अभ्यास संदेश ह, सरकारी चेतावनी "
                "ना ह। {dist_short} के नदी घाटी में हिमताल जोखिम संकेत मिलल बा। ई पक्का भविष्यवाणी ना ह, "
                "लेकिन नदी किनार आ पुल लगे रहे वाला लोग सुरक्षित ऊँच जगह जान के राखीं आ DHM के सूचना "
                "देखीं। मदद खातिर 1155, 1149, 1114, 100 भा 102 पर फोन करीं। फिर सुने खातिर १ दबाईं।"
            ),
        },
        "thr": {
            "event": "हिमताल व नदी किनार निगरानी (अभ्यास)",
            "event_short": "हिमताल-नदी निगरानी",
            "headline": "[अभ्यास] हिमताल व नदी किनार निगरानी: {dist_short}",
            "desc": (
                "यी केवल अभ्यास सन्देश हो, सरकारी चेतावनी नाइ हो। त्राय जाँचमे {dist_full} जिल्लामनक "
                "नदी करिडोरमे हिमताल संवेदनशीलता सूचक देखल गइल बा। यी सरकारी चेतावनी नाइ हो; "
                "सरकारी जानकारीक लाग DHM व NDRRMA के सूचना जरुर हेरू।"
            ),
            "instr": (
                "नदी किनार व पुल लग्गे बसैना मनै उच्च सुरक्षित ठाउँ चिन्हके राखू व पानीक बहावमे ध्यान देऊ। "
                "सरकारी जानकारी व आपतकालीन मददक लाग DHM 1155, NEOC 1149, सशस्त्र प्रहरी 1114, "
                "प्रहरी 100 वा एम्बुलेन्स 102 मे फोन करू।"
            ),
            "sms_action": "नदी किनारमे होसियार रहू",
            "ivr": (
                "नमस्कार, सबै जने ध्यान देऊ। यी नेपाल त्राय के विपद् पूर्वतयारी अभ्यास सन्देश हो, आधिकारिक "
                "सरकारी चेतावनी नाइ हो। {dist_short} क्षेत्रक नदी घाटीमे हिमताल जोखिम सूचक सक्रिय देखल "
                "गइल बा। यी विस्फोटनक पक्का भविष्यवाणी नाइ हो, तर नदी किनार व पुल लग्गे बसैना मनै उच्च "
                "सुरक्षित ठाउँ जानके राखू व DHM के सूचना हेरू। मददक लाग 1155, 1149, 1114, 100 वा 102 "
                "मे फोन करू। फेर सुनेक लाग १ दबाऊ।"
            ),
        },
        "taj": {
            "event": "हिमताल र स्योङ् (नदी) करिडोर निगरानी (अभ्यास)",
            "event_short": "हिमताल-स्योङ् निगरानी",
            "headline": "[अभ्यास] हिमताल र स्योङ् करिडोर निगरानी: {dist_short}",
            "desc": (
                "चु अभ्यास सन्देश जेन हिन्ना, सरकारी चेतावनी आहिन। त्राय जाँचरि {dist_full} जिल्लाकादेला "
                "स्योङ् (नदी) करिडोररि हिमताल संवेदनशीलता सूचक म्राङ्बा मुला। चु विस्फोटनला पूर्वानुमान "
                "आहिन; सरकारी सूचनाला लागि DHM र NDRRMA ला सूचना च्यागो।"
            ),
            "instr": (
                "स्योङ् छ्यउ र साँघु छ्यउरि टिबा म्हिसे नोबा सुरक्षित ग्ला ङोसेसि होसियार टिगो। "
                "क्युइ (पानी) ला बहाव फरक म्राङ्मा तुरुन्त माथि निगो। सरकारी सूचना र सहयोगला लागि "
                "DHM 1155, NEOC 1149, सशस्त्र प्रहरी 1114, प्रहरी 100 अथवा एम्बुलेन्स 102 रि फोन ल्हागो।"
            ),
            "sms_action": "स्योङ् छ्यउरि होसियार टिगो",
            "ivr": (
                "लास्सो, कृपया ध्यान पिङ्गो। चु नेपाल त्रायला विपद् पूर्वतयारी अभ्यास सन्देश हिन्ना, सरकारी "
                "चेतावनी आहिन। {dist_short} क्षेत्रला स्योङ् करिडोररि हिमताल जोखिम सूचक म्राङ्बा मुला। "
                "चु विस्फोटनला पूर्वानुमान आहिन, तर स्योङ् छ्यउ र साँघु छ्यउरि टिबा म्हिसे सुरक्षित नोबा "
                "ग्ला थाहा थान्गो र DHM ला सरकारी सूचना च्यागो। सहयोगला लागि 1155, 1149, 1114, 100 "
                "अथवा 102 रि फोन ल्हागो। दोसि ङ्यान्बारि १ थिच्गो।"
            ),
        },
    },
    "rain_landslide_road": {
        "en": {
            "event": "Rainfall, Landslide & Road-Isolation Screening (Exercise)",
            "event_short": "Landslide-Road Watch",
            "headline": "[EXERCISE] Landslide & Corridor Access Screening: {dist_short}",
            "desc": (
                "EXERCISE DRAFT ONLY (NOT AN OFFICIAL WARNING). TRĀYA screening notes recent dated "
                "landslide activity or heavy rainfall signals with road and bridge corridor exposure in "
                "{dist_full}. {detail_en} Confirm highway status with DoR and NDRRMA BIPAD."
            ),
            "instr": (
                "Avoid unnecessary night travel on steep mountain highways and watch for falling debris "
                "or muddy stream surges. Verify road status before travel. For official warnings and help "
                "call DHM 1155, NDRRMA/NEOC 1149, APF Rescue 1114, Nepal Police 100, or Ambulance 102."
            ),
            "sms_action": "Use caution on hill roads",
            "ivr": (
                "Attention please. This is a Nepal TRAYA disaster preparedness exercise message, not an official "
                "government warning. Recent dated landslides or rainfall hazard indicators overlap steep hill "
                "roads and bridges in {dist_short}. Please avoid unnecessary night travel along landslide-prone "
                "highways, stay clear of unstable slopes and muddy streams, and confirm road conditions with "
                "the Department of Roads and NDRRMA. For help call 1155, 1149, 1114, 100, or 102. Press 1 to repeat."
            ),
        },
        "ne": {
            "event": "वर्षा, पहिरो तथा सडक अवरोध स्क्रिनिङ (अभ्यास)",
            "event_short": "पहिरो-सडक निगरानी",
            "headline": "[अभ्यास] पहिरो तथा सडक पहुँच निगरानी: {dist_short}",
            "desc": (
                "यो अभ्यास मस्यौदा मात्र हो, आधिकारिक सरकारी चेतावनी होइन। त्राय स्क्रिनिङमा {dist_full} "
                "जिल्लामा हालैका पहिरो घटना वा वर्षा सूचक र पहाडी सडक-पुल करिडोर जोखिम देखिएको छ। "
                "यात्रा गर्नुअघि सडक विभाग (DoR), DHM र NDRRMA को आधिकारिक सूचना जाँच गर्नुहोस्।"
            ),
            "instr": (
                "पहिरो सम्भावित पहाडी राजमार्गमा रात्रिकालीन र अनावश्यक यात्रा नगर्नुहोस्। लेदोसहितको खोला "
                "तथा भिरालो पाखाबाट सुरक्षित रहनुहोस्। आधिकारिक सूचना र आपतकालीन सहयोगका लागि "
                "DHM 1155, NEOC 1149, सशस्त्र प्रहरी 1114, प्रहरी 100 वा एम्बुलेन्स 102 मा फोन गर्नुहोस्।"
            ),
            "sms_action": "पहाडी सडकमा सावधानी अपनाउनुहोस्",
            "ivr": (
                "नमस्कार, कृपया ध्यान दिनुहोस्। यो नेपाल त्रायको विपद् पूर्वतयारी अभ्यास सन्देश हो, आधिकारिक "
                "सरकारी चेतावनी होइन। {dist_short} जिल्लाका पहाडी सडक र पुल क्षेत्रमा हालैका पहिरो तथा वर्षा "
                "जोखिम सूचक देखिएको छ। कृपया पहिरो सम्भावित सडकमा अनावश्यक र रात्रिकालीन यात्रा नगर्नुहोस् "
                "तथा यात्राअघि सडक विभाग र NDRRMA को आधिकारिक सूचना बुझ्नुहोस्। आकस्मिक सहयोगका लागि "
                "1155, 1149, 1114, 100 वा 102 मा फोन गर्नुहोस्। फेरि सुन्न १ थिच्नुहोस्।"
            ),
        },
        "mai": {
            "event": "वर्षा, पहिरो आ सड़क अवरोध निगरानी (अभ्यास)",
            "event_short": "पहिरो-सड़क निगरानी",
            "headline": "[अभ्यास] पहिरो आ सड़क पहुँच निगरानी: {dist_short}",
            "desc": (
                "ई अभ्यास मस्यौदा मात्र अछि, आधिकारिक सरकारी चेतावनी नहि अछि। त्राय स्क्रिनिङ मे {dist_full} "
                "जिला मे हालक पहिरो वा वर्षा सूचक संग सड़क आ पुल जोखिम देखल गेल अछि। यात्रा सँ पहिने "
                "सड़क विभाग, DHM आ NDRRMA केर आधिकारिक सूचना अवश्य देखू।"
            ),
            "instr": (
                "पहिरो संभावित पहाड़ी सड़क पर रातिक यात्रा आ अनावश्यक आवागमन सँ बचू। कमजोर ढलान आ तेज बहाव "
                "सँ दूर रहू। आधिकारिक जानकारी आ आपतकालीन सहायताक लेल DHM 1155, NEOC 1149, "
                "सशस्त्र प्रहरी 1114, पुलिस 100 वा एम्बुलेन्स 102 पर फोन करू।"
            ),
            "sms_action": "पहाड़ी सड़क पर सावधानी राखू",
            "ivr": (
                "प्रणाम, कृपया ध्यान दिअ। ई नेपाल त्राय केर विपद् पूर्वतयारी अभ्यास सन्देश अछि, आधिकारिक "
                "सरकारी चेतावनी नहि अछि। {dist_short} जिलाक पहाड़ी सड़क आ पुल क्षेत्र मे हालक पहिरो वा "
                "वर्षा जोखिम सूचक देखल गेल अछि। कृपया पहिरो वाला मार्ग मे रातिक यात्रा सँ बचू आ यात्रा सँ "
                "पहिने सरकारी सूचना अवश्य देखू। आपतकालीन सहायताक लेल 1155, 1149, 1114, 100 वा 102 पर "
                "फोन करू। फेर सुनबाक लेल १ दबाउ।"
            ),
        },
        "bho": {
            "event": "बरसात, पहिरो आ सड़क रुकावट निगरानी (अभ्यास)",
            "event_short": "पहिरो-सड़क निगरानी",
            "headline": "[अभ्यास] पहिरो आ सड़क निगरानी: {dist_short}",
            "desc": (
                "ई खाली अभ्यास संदेश ह, आधिकारिक सरकारी चेतावनी ना ह। त्राय जांच में {dist_full} जिला "
                "में हाल के पहिरो भा बरसात के संकेत आ पहाड़ी सड़क-पुल जोखिम देखल गइल बा। यात्रा से पहिले "
                "सड़क विभाग, DHM आ NDRRMA के सरकारी सूचना जरूर देखीं।"
            ),
            "instr": (
                "पहिरो वाला पहाड़ी रास्ता पर रात में आ बेवजह यात्रा से बचीं। कमजोर पहाड़ी ढलान आ तेज "
                "नाला से दूर रहीं। आधिकारिक सूचना आ आपातकालीन मदद खातिर DHM 1155, NEOC 1149, "
                "सशस्त्र पुलिस 1114, पुलिस 100 भा एम्बुलेन्स 102 पर फोन करीं।"
            ),
            "sms_action": "पहाड़ी सड़क पर सावधानी बरतीं",
            "ivr": (
                "प्रणाम, कृपया ध्यान दीं। ई नेपाल त्राय के विपद् तैयारी अभ्यास संदेश ह, आधिकारिक सरकारी "
                "चेतावनी ना ह। {dist_short} जिला के पहाड़ी सड़क आ पुल इलाका में हाल के पहिरो भा बरसात "
                "के जोखिम संकेत देखल गइल बा। कृपया पहिरो वाला सड़क पर रात के यात्रा से बचीं आ निकले से "
                "पहिले सरकारी सूचना पता करीं। मदद खातिर 1155, 1149, 1114, 100 भा 102 पर फोन करीं। "
                "फिर सुने खातिर १ दबाईं।"
            ),
        },
        "thr": {
            "event": "बर्खा, पहिरो व सडक अवरोध निगरानी (अभ्यास)",
            "event_short": "पहिरो-सडक निगरानी",
            "headline": "[अभ्यास] पहिरो व सडक निगरानी: {dist_short}",
            "desc": (
                "यी केवल अभ्यास सन्देश हो, सरकारी चेतावनी नाइ हो। त्राय जाँचमे {dist_full} जिल्लामे "
                "हालक पहिरो वा बर्खा सूचक सँगे पहाडी सडक व पुल जोखिम देखल गइल बा। यात्रा करसे पहिले "
                "सडक विभाग, DHM व NDRRMA के सरकारी सूचना जरुर हेरू।"
            ),
            "instr": (
                "पहिरो लग्ने पहाडी बाटोमे रातिक व अनावश्यक यात्रा नाइ करू। कमजोर पाखा व लेदो खोलासे दूर रहू। "
                "सरकारी जानकारी व आपतकालीन मददक लाग DHM 1155, NEOC 1149, सशस्त्र प्रहरी 1114, "
                "प्रहरी 100 वा एम्बुलेन्स 102 मे फोन करू।"
            ),
            "sms_action": "पहाडी सडकमे होसियार रहू",
            "ivr": (
                "नमस्कार, सबै जने ध्यान देऊ। यी नेपाल त्राय के विपद् पूर्वतयारी अभ्यास सन्देश हो, आधिकारिक "
                "सरकारी चेतावनी नाइ हो। {dist_short} जिल्लाक पहाडी सडक व पुल क्षेत्रमे हालक पहिरो वा बर्खा "
                "जोखिम सूचक देखल गइल बा। कृपया पहिरो लग्ने बाटोमे रातिक यात्रा नाइ करू व यात्रा करसे पहिले "
                "सरकारी सूचना जरुर बुझू। आपतकालीन मददक लाग 1155, 1149, 1114, 100 वा 102 मे फोन करू। "
                "फेर सुनेक लाग १ दबाऊ।"
            ),
        },
        "taj": {
            "event": "नाम्सा (वर्षा), पहिरो र सडक अवरोध निगरानी (अभ्यास)",
            "event_short": "पहिरो-सडक निगरानी",
            "headline": "[अभ्यास] पहिरो र सडक निगरानी: {dist_short}",
            "desc": (
                "चु अभ्यास सन्देश जेन हिन्ना, सरकारी चेतावनी आहिन। त्राय जाँचरि {dist_full} जिल्लाकादेरि "
                "हालला पहिरो वा वर्षा सूचक र पहाडी सडक-साँघु जोखिम म्राङ्बा मुला। यात्रा ल्हाबा ङाच्छा "
                "सडक विभाग, DHM र NDRRMA ला सरकारी सूचना च्यागो।"
            ),
            "instr": (
                "पहिरो ख्लाबा पहाडी ग्यामर म्हुन (रात) र अनावश्यक यात्रा था ल्हागो। कमजोर भिरालो ग्ला र "
                "स्योङ् छ्यउरि था निगो। सरकारी सूचना र सहयोगला लागि DHM 1155, NEOC 1149, "
                "सशस्त्र प्रहरी 1114, प्रहरी 100 अथवा एम्बुलेन्स 102 रि फोन ल्हागो।"
            ),
            "sms_action": "पहाडी सडकग्यामर होसियार टिगो",
            "ivr": (
                "लास्सो, कृपया ध्यान पिङ्गो। चु नेपाल त्रायला विपद् पूर्वतयारी अभ्यास सन्देश हिन्ना, सरकारी "
                "चेतावनी आहिन। {dist_short} जिल्लाकादेला पहाडी सडक र साँघु क्षेत्ररि हालला पहिरो वा वर्षा "
                "जोखिम सूचक म्राङ्बा मुला। कृपया पहिरो ख्लाबा ग्यामर रातला यात्रा था ल्हागो र यात्रा ङाच्छा "
                "सरकारी सूचना ङ्यान्गो। सहयोगला लागि 1155, 1149, 1114, 100 अथवा 102 रि फोन ल्हागो। "
                "दोसि ङ्यान्बारि १ थिच्गो।"
            ),
        },
    },
    "flood_context": {
        "en": {
            "event": "River Flood Context Relay (Exercise)",
            "event_short": "River Flood Watch",
            "headline": "[EXERCISE] River Flood Context Advisory: {dist_short}",
            "desc": (
                "EXERCISE DRAFT ONLY (NOT AN OFFICIAL WARNING). Contextual CAP exercise generated from "
                "published river monitoring records for {dist_full}. {detail_en} Always verify live river "
                "stage directly at DHM hydrology.gov.np and NDRRMA BIPAD Portal."
            ),
            "instr": (
                "Keep away from swollen riverbanks, low-lying floodplains, and submerged causeways. "
                "Prepare essential documents and move livestock and family to higher ground if DHM issues "
                "an official alert. Call DHM 1155, NEOC 1149, APF Rescue 1114, Police 100, or Ambulance 102."
            ),
            "sms_action": "Stay clear of rising rivers",
            "ivr": (
                "Attention please. This is a Nepal TRAYA disaster preparedness exercise message, not an official "
                "government warning. Contextual flood monitoring records note elevated river levels in "
                "{dist_short}. Please stay away from swollen riverbanks and flooded crossings, keep emergency "
                "supplies ready, and follow official Department of Hydrology and Meteorology flood bulletins. "
                "For official help call 1155, 1149, 1114, 100, or 102. Press 1 to repeat this message."
            ),
        },
        "ne": {
            "event": "नदी बाढी सन्दर्भ निगरानी (अभ्यास)",
            "event_short": "नदी बाढी निगरानी",
            "headline": "[अभ्यास] नदी बाढी सन्दर्भ सूचना: {dist_short}",
            "desc": (
                "यो अभ्यास मस्यौदा मात्र हो, आधिकारिक सरकारी चेतावनी होइन। {dist_full} क्षेत्रको प्रकाशित "
                "नदी निगरानी अभिलेखमा आधारित अभ्यास सूचना तयार गरिएको छ। प्रत्यक्ष र आधिकारिक नदी जलसतह "
                "जानकारीका लागि सधैँ जल तथा मौसम विज्ञान विभाग (DHM) र BIPAD पोर्टल हेर्नुहोस्।"
            ),
            "instr": (
                "बढ्दो नदी किनार, होचो डुबान क्षेत्र र पानी भरिएको कजवेबाट टाढा रहनुहोस्। आधिकारिक चेतावनी "
                "आएमा परिवार र आवश्यक कागजातसहित सुरक्षित अग्लो स्थानमा जानुहोस्। आधिकारिक सूचना र सहयोगका "
                "लागि DHM 1155, NEOC 1149, सशस्त्र प्रहरी 1114, प्रहरी 100 वा एम्बुलेन्स 102 मा फोन गर्नुहोस्।"
            ),
            "sms_action": "नदी किनार र डुबान क्षेत्रबाट टाढा रहनुहोस्",
            "ivr": (
                "नमस्कार, कृपया ध्यान दिनुहोस्। यो नेपाल त्रायको विपद् पूर्वतयारी अभ्यास सन्देश हो, आधिकारिक "
                "सरकारी चेतावनी होइन। {dist_short} क्षेत्रको नदी अनुगमन अभिलेखमा जलसतह वृद्धिको सन्दर्भ "
                "देखिएको छ। कृपया नदी किनार र डुबान सम्भावित होचो स्थानबाट सुरक्षित टाढा रहनुहोस् र जल तथा "
                "मौसम विज्ञान विभागको आधिकारिक सूचना पालना गर्नुहोस्। सहयोगका लागि 1155, 1149, 1114, "
                "100 वा 102 मा फोन गर्नुहोस्। फेरि सुन्न १ थिच्नुहोस्।"
            ),
        },
        "mai": {
            "event": "नदी बाढ़ि सन्दर्भ निगरानी (अभ्यास)",
            "event_short": "नदी बाढ़ि निगरानी",
            "headline": "[अभ्यास] नदी बाढ़ि सन्दर्भ सूचना: {dist_short}",
            "desc": (
                "ई अभ्यास मस्यौदा मात्र अछि, आधिकारिक सरकारी चेतावनी नहि अछि। {dist_full} जिलाक प्रकाशित "
                "नदी निगरानी अभिलेखक आधार पर ई अभ्यास सूचना तैयार कएल गेल अछि। प्रत्यक्ष सरकारी जलस्तर "
                "जानकारीक लेल DHM आ NDRRMA BIPAD पोर्टल अवश्य देखू।"
            ),
            "instr": (
                "बढ़ैत नदी किनार, नीच डुबान क्षेत्र आ जलमग्न सड़क सँ सुरक्षित दूर रहू। आधिकारिक चेतावनी "
                "अएला पर परिवार सहित ऊँच सुरक्षित स्थान पर जाउ। सरकारी सूचना आ सहायताक लेल DHM 1155, "
                "NEOC 1149, सशस्त्र प्रहरी 1114, पुलिस 100 वा एम्बुलेन्स 102 पर फोन करू।"
            ),
            "sms_action": "नदी किनार आ डुबान सँ दूर रहू",
            "ivr": (
                "प्रणाम, कृपया ध्यान दिअ। ई नेपाल त्राय केर विपद् पूर्वतयारी अभ्यास सन्देश अछि, आधिकारिक "
                "सरकारी चेतावनी नहि अछि। {dist_short} जिलाक नदी अभिलेख मे जलस्तर बढ़बाक सन्दर्भ देखल "
                "गेल अछि। कृपया नदी किनार आ डुबान क्षेत्र सँ सुरक्षित दूर रहू, जरूरी कागजात तैयार राखू आ "
                "DHM केर आधिकारिक सूचना मानू। सहायताक लेल 1155, 1149, 1114, 100 वा 102 पर फोन करू। "
                "फेर सुनबाक लेल १ दबाउ।"
            ),
        },
        "bho": {
            "event": "नदी बाढ़ संदर्भ निगरानी (अभ्यास)",
            "event_short": "नदी बाढ़ निगरानी",
            "headline": "[अभ्यास] नदी बाढ़ संदर्भ सूचना: {dist_short}",
            "desc": (
                "ई खाली अभ्यास संदेश ह, आधिकारिक सरकारी चेतावनी ना ह। {dist_full} जिला के प्रकाशित नदी "
                "निगरानी रिकार्ड के आधार पर ई अभ्यास सूचना बनावल गइल बा। ताजा आ सरकारी जलस्तर जानकारी "
                "खातिर हमेशा DHM आ NDRRMA BIPAD पोर्टल देखीं।"
            ),
            "instr": (
                "बढ़त नदी किनार, निचला डुबान इलाका आ पानी भरल पुलिया से सुरक्षित दूर रहीं। सरकारी चेतावनी "
                "मिलला पर परिवार संग ऊँच सुरक्षित जगह पर चली जाईं। आधिकारिक जानकारी आ मदद खातिर DHM 1155, "
                "NEOC 1149, सशस्त्र पुलिस 1114, पुलिस 100 भा एम्बुलेन्स 102 पर फोन करीं।"
            ),
            "sms_action": "नदी किनार आ डुबान से दूर रहीं",
            "ivr": (
                "प्रणाम, कृपया ध्यान दीं। ई नेपाल त्राय के विपद् तैयारी अभ्यास संदेश ह, आधिकारिक सरकारी "
                "चेतावनी ना ह। {dist_short} जिला के नदी रिकार्ड में पानी बढ़े के संदर्भ देखल गइल बा। "
                "कृपया नदी किनार आ डुबान वाला निचला इलाका से सुरक्षित दूर रहीं आ DHM के आधिकारिक सूचना "
                "पर ध्यान दीं। आपातकालीन मदद खातिर 1155, 1149, 1114, 100 भा 102 पर फोन करीं। "
                "फिर सुने खातिर १ दबाईं।"
            ),
        },
        "thr": {
            "event": "नदी बाढ सन्दर्भ निगरानी (अभ्यास)",
            "event_short": "नदी बाढ निगरानी",
            "headline": "[अभ्यास] नदी बाढ सन्दर्भ सूचना: {dist_short}",
            "desc": (
                "यी केवल अभ्यास सन्देश हो, सरकारी चेतावनी नाइ हो। {dist_full} जिल्लाक प्रकाशित नदी "
                "अनुगमन अभिलेखक आधारमे यी अभ्यास सूचना बनल बा। ताजा सरकारी जलसतह जानकारीक लाग सधैँ "
                "DHM व NDRRMA BIPAD पोर्टल हेरू।"
            ),
            "instr": (
                "बढल नदी किनार, होचो डुबान ठाउँ व पानी भरल बाटोसे सुरक्षित दूर रहू। सरकारी चेतावनी "
                "आयले अपन परिवार सँगे उच्च सुरक्षित ठाउँमे जाउ। सरकारी सूचना व मददक लाग DHM 1155, "
                "NEOC 1149, सशस्त्र प्रहरी 1114, प्रहरी 100 वा एम्बुलेन्स 102 मे फोन करू।"
            ),
            "sms_action": "नदी किनार व डुबानसे दूर रहू",
            "ivr": (
                "नमस्कार, सबै जने ध्यान देऊ। यी नेपाल त्राय के विपद् पूर्वतयारी अभ्यास सन्देश हो, आधिकारिक "
                "सरकारी चेतावनी नाइ हो। {dist_short} जिल्लाक नदी अभिलेखमे पानी बढेक सन्दर्भ देखल गइल बा। "
                "कृपया नदी किनार व डुबान ठाउँसे सुरक्षित दूर रहू, जरुरी सामान तयार राखू व DHM के सरकारी "
                "सूचना मानू। आपतकालीन मददक लाग 1155, 1149, 1114, 100 वा 102 मे फोन करू। "
                "फेर सुनेक लाग १ दबाऊ।"
            ),
        },
        "taj": {
            "event": "स्योङ् (नदी) बाढी सन्दर्भ निगरानी (अभ्यास)",
            "event_short": "स्योङ् बाढी निगरानी",
            "headline": "[अभ्यास] स्योङ् (नदी) बाढी सन्दर्भ सूचना: {dist_short}",
            "desc": (
                "चु अभ्यास सन्देश जेन हिन्ना, सरकारी चेतावनी आहिन। {dist_full} जिल्लाकादेला प्रकाशित स्योङ् "
                "अनुगमन अभिलेखरि आधारित अभ्यास सूचना तयार ल्हाबा मुला। प्रत्यक्ष सरकारी जानकारीला लागि "
                "सधैँ DHM र NDRRMA BIPAD पोर्टल च्यागो।"
            ),
            "instr": (
                "बढेबा स्योङ् छ्यउ, होचो डुबान ग्ला र क्युइ भरेबा ग्यामर था निगो। सरकारी चेतावनी खामा "
                "परिवार सँगे नोबा सुरक्षित ग्लारि निगो। सरकारी सूचना र सहयोगला लागि DHM 1155, NEOC 1149, "
                "सशस्त्र प्रहरी 1114, प्रहरी 100 अथवा एम्बुलेन्स 102 रि फोन ल्हागो।"
            ),
            "sms_action": "स्योङ् छ्यउ र डुबान ग्ला था निगो",
            "ivr": (
                "लास्सो, कृपया ध्यान पिङ्गो। चु नेपाल त्रायला विपद् पूर्वतयारी अभ्यास सन्देश हिन्ना, सरकारी "
                "चेतावनी आहिन। {dist_short} जिल्लाकादेला स्योङ् अभिलेखरि क्युइ बढेबा सन्दर्भ म्राङ्बा मुला। "
                "कृपया स्योङ् छ्यउ र होचो डुबान ग्लारि था निगो र DHM ला सरकारी सूचना ङ्यान्गो। आपतकालीन "
                "सहयोगला लागि 1155, 1149, 1114, 100 अथवा 102 रि फोन ल्हागो। दोसि ङ्यान्बारि १ थिच्गो।"
            ),
        },
    },
}


def _map_severity(sev: str) -> str:
    s = str(sev or "").lower()
    if s == "critical":
        return "Severe"
    if s in ("high", "q5_warning", "q20_severe"):
        return "Moderate"
    if s in ("moderate", "watch", "elevated", "q2_watch"):
        return "Minor"
    return "Minor"


def _map_urgency(sev: str, status: str) -> str:
    if status == "active_dynamic" and str(sev or "").lower() in ("critical", "high"):
        return "Expected"
    return "Future"


def _map_certainty(evidence_types: list[str]) -> str:
    if "observed" in evidence_types:
        return "Possible"
    return "Possible"


def _extract_district_from_text(text: str) -> list[str]:
    low = str(text or "").lower()
    found: list[str] = []
    for d in RW.DISTRICT_NE:
        if re.search(rf"\b{re.escape(d.lower())}\b", low):
            found.append(d)
    for alias, canon in _DISTRICT_ALIASES.items():
        if re.search(rf"\b{re.escape(alias)}\b", low) and canon not in found:
            found.append(canon)
    return sorted(found)


def _build_cap_advisory(
    *,
    identifier: str,
    sent_dt: dt.datetime,
    expires_hours: int,
    source_dataset: str,
    scenario_id: str,
    hazard_kind: str,
    cap_category: str,
    severity_tier: str,
    scenario_status: str,
    evidence_types: list[str],
    districts: list[str],
    provinces: list[str],
    detail_en: str,
) -> dict[str, Any]:
    """Build one complete 6-language OASIS CAP v1.2 Exercise advisory object."""
    sent_str = _format_cap_npt(sent_dt)
    expires_str = _format_cap_npt(sent_dt + dt.timedelta(hours=expires_hours))
    tpl_group = _HAZARD_TEMPLATES[hazard_kind]

    cap_severity = _map_severity(severity_tier)
    cap_urgency = _map_urgency(severity_tier, scenario_status)
    cap_certainty = _map_certainty(evidence_types)

    dist_en_short = _districts_short_en(districts, limit=2)
    dist_en_full = ", ".join(districts) if districts else "Nepal region"
    dist_deva_short = _districts_short_deva(districts, limit=2)
    dist_deva_full = _districts_full_deva(districts)

    geocodes = [
        {"valueName": "NEPAL_DISTRICT", "value": d}
        for d in (districts or ["Nepal"])
    ]

    gov = _default_relay_governance()
    info_blocks: list[dict[str, Any]] = []

    for lang_meta in SUPPORTED_LANGUAGES:
        lc = lang_meta["code"]
        t = tpl_group[lc]
        is_en = lc == "en"
        d_short = dist_en_short if is_en else dist_deva_short
        d_full = dist_en_full if is_en else dist_deva_full

        headline = t["headline"].format(dist_short=d_short)
        description = t["desc"].format(dist_full=d_full, detail_en=detail_en)
        instruction = t["instr"]

        if is_en:
            sms_raw = (
                f"[EXERCISE-NOT OFFICIAL] {t['event_short']}: {d_short}. "
                f"{t['sms_action']}. Official: 1155/1149/1114/100/102."
            )
        elif lc == "ne":
            sms_raw = (
                f"[अभ्यास-आधिकारिक होइन] {d_short}: {t['event_short']}। "
                f"{t['sms_action']}। सूचना: 1155/1149/1114/100/102"
            )
        elif lc == "mai":
            sms_raw = (
                f"[अभ्यास-सरकारी नहि] {d_short}: {t['event_short']}। "
                f"{t['sms_action']}। सूचना: 1155/1149/1114/100/102"
            )
        elif lc == "bho":
            sms_raw = (
                f"[अभ्यास-सरकारी ना ह] {d_short}: {t['event_short']}। "
                f"{t['sms_action']}। सूचना: 1155/1149/1114/100/102"
            )
        elif lc == "thr":
            sms_raw = (
                f"[अभ्यास-सरकारी नाइ] {d_short}: {t['event_short']}। "
                f"{t['sms_action']}। सूचना: 1155/1149/1114/100/102"
            )
        else:  # taj
            sms_raw = (
                f"[अभ्यास-सरकारी आहिन] {d_short}: {t['event_short']}। "
                f"{t['sms_action']}। सूचना: 1155/1149/1114/100/102"
            )

        sms_draft = _build_sms_draft(sms_raw, lc)
        ivr_text = t["ivr"].format(dist_short=d_short)
        ivr_script = _build_ivr_script(ivr_text, lc, _REPEAT_PROMPTS[lc])

        area_desc = (
            f"Nepal districts: {dist_en_full}"
            if is_en
            else f"नेपाल जिल्लाहरू: {dist_deva_full}"
        )

        params = [
            {"valueName": "linguistic_review_status", "value": lang_meta["linguistic_review_status"]},
            {"valueName": "relay_enabled", "value": "false"},
            {"valueName": "requires_signed_mou", "value": "true"},
            {"valueName": "statutory_warning", "value": "false"},
            {"valueName": "traya_scenario_id", "value": scenario_id},
            {"valueName": "sms_draft", "value": sms_draft["text"]},
            {"valueName": "sms_segments", "value": str(sms_draft["sms_segments"])},
            {"valueName": "ivr_duration_sec", "value": str(ivr_script["estimated_duration_sec"])},
        ]

        info_blocks.append(
            {
                "language": lc,
                "language_name_native": lang_meta["name_native"],
                "script": lang_meta["script"],
                "linguistic_review_status": lang_meta["linguistic_review_status"],
                "category": cap_category,
                "event": t["event"],
                "responseType": ["Monitor", "Prepare"],
                "urgency": cap_urgency,
                "severity": cap_severity,
                "certainty": cap_certainty,
                "effective": sent_str,
                "expires": expires_str,
                "senderName": _SENDER_NAMES[lc],
                "headline": headline,
                "description": description,
                "instruction": instruction,
                "web": CAP_WEB_URL,
                "contact": CAP_CONTACT,
                "parameter": params,
                "area": [
                    {
                        "areaDesc": area_desc,
                        "geocode": geocodes,
                    }
                ],
                "sms_draft": sms_draft,
                "ivr_voice_script": ivr_script,
            }
        )

    return {
        "xmlns": CAP_XMLNS,
        "identifier": identifier,
        "sender": CAP_SENDER,
        "sent": sent_str,
        "status": "Exercise",
        "msgType": "Alert",
        "scope": "Restricted",
        "restriction": (
            "TRĀYA Wave D Exercise Draft — Pre-MOU Sandbox Only; "
            "Not Authorized for Live Public Broadcast or Telecom Relay."
        ),
        "source": f"Nepal TRĀYA 2.0 ({source_dataset})",
        "note": (
            "NON-OPERATIONAL EXERCISE PAYLOAD (गैर-सञ्चालनात्मक अभ्यास सूचना): "
            "Generated strictly for OASIS CAP v1.2 interoperability testing and Wave D DEOC "
            "multilingual UAT. Official warnings in Nepal are issued solely by DHM (1155), "
            "NDRRMA/NEOC (1149), and DMG/NEMRC."
        ),
        "code": [
            "TRAYA-EXERCISE-ONLY",
            "NEPAL-CAP-v1.2-DRAFT",
            "PRE-MOU-SANDBOX",
        ],
        "scenario_ref": {
            "source_dataset": source_dataset,
            "scenario_id": scenario_id,
            "hazard_kind": hazard_kind,
            "severity_tier": severity_tier,
            "evidence_types": list(evidence_types),
            "affected_districts": list(districts),
            "affected_provinces": list(provinces),
        },
        "relay_governance": gov,
        "info": info_blocks,
    }


def advisory_to_cap_xml(advisory: dict[str, Any]) -> str:
    """Serialize a CAP v1.2 Exercise advisory dict into strictly ordered OASIS CAP v1.2 XML."""
    if advisory.get("status") not in ("Exercise", "Test"):
        raise ValueError(
            f"Refusing to serialize CAP status {advisory.get('status')!r}; "
            "only 'Exercise' or 'Test' permitted prior to signed Wave D MOU."
        )

    ET.register_namespace("", CAP_XMLNS)

    def _tag(name: str) -> str:
        return f"{{{CAP_XMLNS}}}{name}"

    def _sub(parent: ET.Element, name: str, text: str) -> ET.Element:
        el = ET.SubElement(parent, _tag(name))
        el.text = text
        return el

    root = ET.Element(_tag("alert"))
    # Strict OASIS CAP v1.2 XSD child order for <alert>
    _sub(root, "identifier", str(advisory["identifier"]))
    _sub(root, "sender", str(advisory["sender"]))
    _sub(root, "sent", str(advisory["sent"]))
    _sub(root, "status", str(advisory["status"]))
    _sub(root, "msgType", str(advisory["msgType"]))
    _sub(root, "source", str(advisory["source"]))
    _sub(root, "scope", str(advisory["scope"]))
    if advisory.get("restriction"):
        _sub(root, "restriction", str(advisory["restriction"]))
    for code_val in advisory.get("code") or []:
        _sub(root, "code", str(code_val))
    _sub(root, "note", str(advisory["note"]))

    for info in advisory.get("info") or []:
        info_el = ET.SubElement(root, _tag("info"))
        # Strict OASIS CAP v1.2 XSD child order for <info>
        _sub(info_el, "language", str(info["language"]))
        _sub(info_el, "category", str(info["category"]))
        _sub(info_el, "event", str(info["event"]))
        for rt in info.get("responseType") or []:
            _sub(info_el, "responseType", str(rt))
        _sub(info_el, "urgency", str(info["urgency"]))
        _sub(info_el, "severity", str(info["severity"]))
        _sub(info_el, "certainty", str(info["certainty"]))
        _sub(info_el, "effective", str(info["effective"]))
        _sub(info_el, "expires", str(info["expires"]))
        _sub(info_el, "senderName", str(info["senderName"]))
        _sub(info_el, "headline", str(info["headline"]))
        _sub(info_el, "description", str(info["description"]))
        _sub(info_el, "instruction", str(info["instruction"]))
        _sub(info_el, "web", str(info["web"]))
        _sub(info_el, "contact", str(info["contact"]))
        for param in info.get("parameter") or []:
            p_el = ET.SubElement(info_el, _tag("parameter"))
            _sub(p_el, "valueName", str(param["valueName"]))
            _sub(p_el, "value", str(param["value"]))
        for area in info.get("area") or []:
            a_el = ET.SubElement(info_el, _tag("area"))
            _sub(a_el, "areaDesc", str(area["areaDesc"]))
            for gc in area.get("geocode") or []:
                g_el = ET.SubElement(a_el, _tag("geocode"))
                _sub(g_el, "valueName", str(gc["valueName"]))
                _sub(g_el, "value", str(gc["value"]))

    ET.indent(root, space="  ")
    xml_body = ET.tostring(root, encoding="unicode", xml_declaration=False)
    return '<?xml version="1.0" encoding="UTF-8"?>\n' + xml_body + "\n"


def validate_cap_advisory(advisory: dict[str, Any]) -> list[str]:
    """Validate an advisory payload against `schemas/cap_v12_advisory.schema.json` invariants."""
    errs: list[str] = []
    if advisory.get("xmlns") != CAP_XMLNS:
        errs.append(f"invalid xmlns: {advisory.get('xmlns')!r}")
    if advisory.get("status") not in ("Exercise", "Test"):
        errs.append(f"CAP status must be Exercise|Test, got {advisory.get('status')!r}")
    gov = advisory.get("relay_governance") or {}
    if gov.get("relay_enabled") is not False:
        errs.append("relay_governance.relay_enabled must be False")
    if gov.get("requires_signed_mou") is not True:
        errs.append("relay_governance.requires_signed_mou must be True")
    if gov.get("statutory_warning") is not False:
        errs.append("relay_governance.statutory_warning must be False")
    if gov.get("cap_status") not in ("Exercise", "Test"):
        errs.append(f"invalid relay_governance.cap_status: {gov.get('cap_status')!r}")

    infos = advisory.get("info") or []
    langs = [i.get("language") for i in infos]
    expected_langs = [m["code"] for m in SUPPORTED_LANGUAGES]
    if langs != expected_langs:
        errs.append(f"expected languages {expected_langs}, got {langs}")

    for info in infos:
        lc = info.get("language")
        expected_rev = (
            "reviewed_baseline"
            if lc in ("en", "ne")
            else "draft_pending_native_municipal_review"
        )
        if info.get("linguistic_review_status") != expected_rev:
            errs.append(
                f"{lc}: linguistic_review_status={info.get('linguistic_review_status')!r} "
                f"(expected {expected_rev!r})"
            )
        instr = str(info.get("instruction") or "")
        for hl in REQUIRED_HOTLINES:
            if hl not in instr:
                errs.append(f"{lc}: instruction missing hotline {hl}")
        sms = info.get("sms_draft") or {}
        sms_txt = str(sms.get("text") or "")
        budget = 160 if lc == "en" else 140
        if len(sms_txt) > budget or sms.get("char_count") != len(sms_txt):
            errs.append(f"{lc}: SMS exceeds {budget} chars ({len(sms_txt)})")
        if lc == "en" and not sms_txt.isascii():
            errs.append("en: SMS must be pure ASCII (GSM-7)")
        ivr = info.get("ivr_voice_script") or {}
        dur = float(ivr.get("estimated_duration_sec") or 0.0)
        if not (20.0 <= dur <= 40.0):
            errs.append(f"{lc}: IVR duration {dur}s outside 20..40s envelope")
    return errs


def validate_cap_xml(xml_text: str) -> list[str]:
    """Parse and verify well-formed OASIS CAP v1.2 Exercise XML via ElementTree."""
    errs: list[str] = []
    try:
        root = ET.fromstring(xml_text)
    except ET.ParseError as exc:
        return [f"XML parse error: {exc}"]

    if root.tag != f"{{{CAP_XMLNS}}}alert":
        errs.append(f"unexpected root tag: {root.tag!r}")

    ns = {"cap": CAP_XMLNS}
    status_el = root.find("cap:status", ns)
    if status_el is None or status_el.text != "Exercise":
        errs.append(f"<status> must be 'Exercise', got {status_el.text if status_el is not None else None!r}")

    note_el = root.find("cap:note", ns)
    if note_el is None or not (note_el.text or "").strip():
        errs.append("missing non-operational <note>")

    infos = root.findall("cap:info", ns)
    if len(infos) != 6:
        errs.append(f"expected 6 <info> language blocks, found {len(infos)}")
    else:
        found_langs = [el.findtext("cap:language", default="", namespaces=ns) for el in infos]
        if set(found_langs) != {"en", "ne", "mai", "bho", "thr", "taj"}:
            errs.append(f"incomplete language set in XML: {found_langs}")
    return errs


def _atomic_write_text(path: str | os.PathLike[str], content: str) -> int:
    target = os.path.abspath(os.fspath(path))
    parent = os.path.dirname(target)
    os.makedirs(parent, exist_ok=True)
    fd, tmp_path = tempfile.mkstemp(dir=parent, prefix=".tmp_", suffix=".xml")
    try:
        with os.fdopen(fd, "w", encoding="utf-8", newline="\n") as fh:
            fh.write(content)
        os.replace(tmp_path, target)
    except Exception:
        if os.path.exists(tmp_path):
            try:
                os.remove(tmp_path)
            except OSError:
                pass
        raise
    return os.path.getsize(target)


def _load_json_optional(path: Path) -> dict[str, Any] | None:
    if not path.is_file():
        return None
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        return data if isinstance(data, dict) else None
    except Exception:
        return None


def build_cap_drafts(
    repo_root: str | os.PathLike[str] = C.ROOT,
    *,
    write: bool = True,
) -> dict[str, Any]:
    """Generate 6-language OASIS CAP v1.2 Exercise advisories, JSON drafts, and XML."""
    root = Path(repo_root).resolve()
    now_utc = dt.datetime.now(dt.timezone.utc)
    now_iso = now_utc.strftime("%Y-%m-%dT%H:%M:%SZ")
    now_npt = _format_cap_npt(now_utc)
    stamp = now_utc.strftime("%Y%m%dT%H%M%SZ")

    cascades = _load_json_optional(root / "data" / "cascades.json") or {}
    rivers = _load_json_optional(root / "data" / "rivers_watch.json") or {}
    bipad = _load_json_optional(root / "data" / "bipad_official.json") or {}

    advisories: list[dict[str, Any]] = []
    n_cascades = 0
    n_rivers = 0
    n_bipad = 0

    # 1. Active scenarios from data/cascades.json
    chain_to_kind_cat: dict[str, tuple[str, str]] = {
        "quake_coseismic_isolation": ("quake_coseismic", "Geo"),
        "glof_infra_isolation": ("glof_stress", "Geo"),
        "rain_landslide_dam_road": ("rain_landslide_road", "Geo"),
    }
    for idx, scn in enumerate(cascades.get("active_scenarios") or [], start=1):
        if not isinstance(scn, dict):
            continue
        chain_id = str(scn.get("chain_id") or "")
        hazard_kind, cap_cat = chain_to_kind_cat.get(chain_id, ("rain_landslide_road", "Geo"))
        scn_id = str(scn.get("scenario_id") or f"SCN-CASCADE-{idx}")
        districts = [str(d) for d in (scn.get("affected_districts") or []) if d]
        provinces = [str(p) for p in (scn.get("affected_provinces") or []) if p]
        ev_types = [str(e) for e in (scn.get("evidence_types") or ["modelled_static"])]
        detail_en = str(scn.get("summary_en") or "").strip()

        adv = _build_cap_advisory(
            identifier=f"urn:traya:cap:exercise:{scn_id.lower()}:{stamp}",
            sent_dt=now_utc,
            expires_hours=24,
            source_dataset="data/cascades.json",
            scenario_id=scn_id,
            hazard_kind=hazard_kind,
            cap_category=cap_cat,
            severity_tier=str(scn.get("severity") or "moderate"),
            scenario_status=str(scn.get("status") or "active_dynamic"),
            evidence_types=ev_types,
            districts=districts,
            provinces=provinces,
            detail_en=detail_en,
        )
        advisories.append(adv)
        n_cascades += 1

    # 2. Elevated river basins from data/rivers_watch.json
    for basin in rivers.get("basins") or []:
        if not isinstance(basin, dict):
            continue
        st_now = str(basin.get("status_now") or "normal")
        st_14d = str(basin.get("status_14d") or "normal")
        if st_now not in ELEVATED_RIVER_TIERS and st_14d not in ELEVATED_RIVER_TIERS:
            continue
        bid = str(basin.get("id") or "basin")
        bname = str(basin.get("name") or bid)
        dist = [str(basin["district"])] if basin.get("district") else []
        prov = [str(basin["prov"])] if basin.get("prov") else []
        sev = st_now if st_now in ELEVATED_RIVER_TIERS else st_14d
        detail_en = (
            f"Copernicus EMS GloFAS screening for {bname} ({basin.get('dhm_ref') or 'DHM ref'}): "
            f"current {basin.get('current_m3s')} m3/s, 14-day peak median {basin.get('peak_14d_median_m3s')} m3/s "
            f"(status_now={st_now}, status_14d={st_14d})."
        )
        adv = _build_cap_advisory(
            identifier=f"urn:traya:cap:exercise:glofas-{bid}:{stamp}",
            sent_dt=now_utc,
            expires_hours=24,
            source_dataset="data/rivers_watch.json",
            scenario_id=f"GLOFAS-{bid.upper()}",
            hazard_kind="flood_context",
            cap_category="Met",
            severity_tier=sev,
            scenario_status="active_dynamic",
            evidence_types=["forecast"],
            districts=dist,
            provinces=prov,
            detail_en=detail_en,
        )
        advisories.append(adv)
        n_rivers += 1

    # 3. Latest verified DHM/BIPAD public flood or rainfall alert from data/bipad_official.json
    for al in bipad.get("alerts") or []:
        if not isinstance(al, dict):
            continue
        if not al.get("public", True):
            continue
        hz = al.get("hazard")
        title = str(al.get("title") or "").strip()
        if hz not in (11, 14, 28) and "flood" not in title.lower():
            continue
        dists = _extract_district_from_text(title)
        if not dists:
            continue
        al_id = al.get("id") or "latest"
        desc_clean = re.sub(r"\s+", " ", str(al.get("description") or "")).strip()
        started = str(al.get("startedOn") or "")
        detail_en = (
            f"Contextual exercise mirror of published BIPAD/DHM record #{al_id}: "
            f"{title} ({desc_clean}; startedOn={started})."
        )
        adv = _build_cap_advisory(
            identifier=f"urn:traya:cap:exercise:bipad-alert-{al_id}:{stamp}",
            sent_dt=now_utc,
            expires_hours=12,
            source_dataset="data/bipad_official.json",
            scenario_id=f"BIPAD-ALERT-{al_id}",
            hazard_kind="flood_context",
            cap_category="Met",
            severity_tier="moderate",
            scenario_status="contextual_bipad_exercise",
            evidence_types=["observed"],
            districts=dists,
            provinces=[],
            detail_en=detail_en,
        )
        advisories.append(adv)
        n_bipad += 1
        break  # Include latest verified BIPAD contextual alert as exercise exemplar

    # Fallback routine readiness exercise if all inputs are empty/baseline
    if not advisories:
        advisories.append(
            _build_cap_advisory(
                identifier=f"urn:traya:cap:exercise:routine-readiness:{stamp}",
                sent_dt=now_utc,
                expires_hours=24,
                source_dataset="data/cascades.json",
                scenario_id="SCN-ROUTINE-READINESS",
                hazard_kind="flood_context",
                cap_category="Safety",
                severity_tier="baseline",
                scenario_status="routine_exercise",
                evidence_types=["modelled_static"],
                districts=["Dolakha", "Ramechhap", "Dhanusha", "Kailali"],
                provinces=["Bagmati Province", "Madhesh Province", "Sudurpashchim Province"],
                detail_en="Routine 6-language OASIS CAP v1.2 readiness exercise (no active elevated hazards).",
            )
        )

    # Validate every generated advisory before writing
    for adv in advisories:
        errs = validate_cap_advisory(adv)
        if errs:
            raise ValueError(f"CAP advisory {adv['identifier']} failed validation: {errs}")

    latest_xml = advisory_to_cap_xml(advisories[0])
    xml_errs = validate_cap_xml(latest_xml)
    if xml_errs:
        raise ValueError(f"Generated CAP v1.2 XML failed validation: {xml_errs}")

    envelope = PROV.make_envelope(
        source="Nepal TRĀYA OASIS CAP v1.2 Multilingual Exercise Generator (Pre-MOU Sandbox)",
        dataset="cap_v12_multilingual_exercise_drafts",
        data_class="static_assessment",
        retrieved_at_utc=now_iso,
        observation_time_utc=cascades.get("generated_utc") or now_iso,
        valid_until_utc=(now_utc + dt.timedelta(hours=24)).strftime("%Y-%m-%dT%H:%M:%SZ"),
        status="available",
        fallback_used=False,
        license_ref=(
            "MIT (TRĀYA CAP generator & schemas); upstream BIPAD NDRRMA statutory context, "
            "GloFAS CC-BY-4.0, USGS Public Domain, ODbL 1.0"
        ),
        sla_hours=168,
        record_count=len(advisories),
        notes=(
            "Exercise-only OASIS CAP v1.2 (urn:oasis:names:tc:emergency:cap:1.2) and 6-language "
            "(en/ne/mai/bho/thr/taj) SMS/IVR drafts. Live relay is hard-disabled "
            "(`relay_enabled: false`) pending signed Wave D MOUs and native municipal review."
        ),
        requires_institutional_agreement=True,
    )

    payload: dict[str, Any] = {
        "schema_version": SCHEMA_VERSION,
        "schema_ref": SCHEMA_REF,
        "generated_utc": now_iso,
        "generated_npt": now_npt,
        "cap_namespace": CAP_XMLNS,
        "latest_xml_path": "data/cap_exercise_latest.xml",
        "relay_governance": _default_relay_governance(),
        "supported_languages": [dict(m) for m in SUPPORTED_LANGUAGES],
        "summary": {
            "n_advisories": len(advisories),
            "n_languages": len(SUPPORTED_LANGUAGES),
            "n_info_blocks": sum(len(a["info"]) for a in advisories),
            "n_cascades_advisories": n_cascades,
            "n_river_watch_advisories": n_rivers,
            "n_bipad_context_advisories": n_bipad,
            "all_cap_status_exercise": all(a["status"] == "Exercise" for a in advisories),
        },
        "advisories": advisories,
        "provenance": envelope,
    }

    if write:
        PROV.atomic_write_json(root / "data" / "cap_drafts.json", payload, indent=2)
        _atomic_write_text(root / "data" / "cap_exercise_latest.xml", latest_xml)

    return payload


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(
        description="Nepal TRĀYA 2.0 6-language OASIS CAP v1.2 & SMS/IVR Exercise generator"
    )
    ap.add_argument(
        "--repo-root",
        default=C.ROOT,
        help="Repository root directory (defaults to TRĀYA repo root)",
    )
    args = ap.parse_args(argv)

    payload = build_cap_drafts(args.repo_root, write=True)
    s = payload["summary"]
    root = Path(args.repo_root).resolve()
    print(
        f"[cap_relay] wrote {root / 'data' / 'cap_drafts.json'} and "
        f"{root / 'data' / 'cap_exercise_latest.xml'}: "
        f"advisories={s['n_advisories']}, languages={s['n_languages']}, "
        f"info_blocks={s['n_info_blocks']}, all_exercise={s['all_cap_status_exercise']}"
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
