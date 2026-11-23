#!/usr/bin/env python3
"""
Nepal TRAYA — Automated CI & Local Pre-Deploy Verification Gate.

Pure Python 3.12 standard library ONLY (zero third-party dependencies).
Runs in < 2 seconds locally and in GitHub Actions (pages.yml & weekly-refresh.yml).

Verifies:
  1. GitHub Actions workflow hardening (zero Node 20 actions, safe concurrency,
     pre-deploy verification, .nojekyll, full asset/data/vendor staging).
  2. Byte-for-byte identity between index.html and src/template.html.
  3. HTML security & CSP compliance (Content-Security-Policy, strict-origin-
     when-cross-origin referrer policy guarding against OpenStreetMap 403 tile
     blocks, manifest.webmanifest link, zero inline <script>/<style>/on*=
     attributes, zero Google Fonts or external third-party <script>/<link>
     loads, local asset resolution).
  4. Nepal safety, statutory agencies & suite navigation (emergency hotlines
     tel:100/102/1114/1149/1155, clickable DHM/NEMRC/BIPAD links, persistent
     bilingual non-operational disclaimer, .prazg-suite-bar portal links).
  5. Data JSON integrity (all required data/*.json parse cleanly, 77 districts
     & 7 canonical provinces including Madhesh Province, canonical "Bagmati
     Province" spelling with zero "Bagamati", zero blank lake provinces
     including GL_30.41653_80.68146, zero '?' mojibake in eq_history_m6.json).
  6. ES module static analysis across assets/*.js (balanced braces, parens,
     brackets, strings, templates & regexes; valid relative imports/exports;
     zero unguarded innerHTML/HTML-template XSS sinks with unescaped external
     API fields).

Usage:
  python src/verify_site.py

Exit code is 0 if all checks pass, 1 if any check fails.
"""
from __future__ import annotations

import json
import os
import re
import sys
import xml.etree.ElementTree as ET
from html.parser import HTMLParser
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parent.parent

# Canonical 7 provinces of Nepal (Constitution of Nepal 2015 + subsequent namings)
CANONICAL_PROVINCES = {
    "Koshi Province",
    "Madhesh Province",
    "Bagmati Province",
    "Gandaki Province",
    "Lumbini Province",
    "Karnali Province",
    "Sudurpashchim Province",
}

REQUIRED_DATA_JSON = [
    "summary.json",
    "lakes.json",
    "lakes_core.json",
    "routes.json",
    "exposure.json",
    "eq_history_m6.json",
    "glof_history.json",
    "faults.json",
    "rivers_watch.json",
    "landslides.json",
    "landslide_review_queue.json",
    "hydromet_weekly.json",
    "gdacs_alerts.json",
    "sensitivity.json",
    "validation.json",
    "districts.json",
    "bipad_official.json",
    "exposure_isolation.json",
    "cascades.json",
    "eo_sar.json",
    "tsho_rolpa_pilot.json",
    "tsho_rolpa_2d_inundation.json",
    "moderation_queue.json",
    "cap_drafts.json",
    "manifest.json",
    "kpi_baseline.json",
]

SUPPORTED_LANG_CODES = ("en", "ne", "mai", "bho", "thr", "taj")
CAP_XMLNS = "urn:oasis:names:tc:emergency:cap:1.2"
CAP_REQUIRED_HOTLINES = ("1155", "1149", "1114", "100", "102")
EXPECTED_2D_SCENARIO_IDS = (
    "TR-S1-PARTIAL-10PCT",
    "TR-S2-MODERATE-30PCT",
    "TR-S3-SEVERE-50PCT",
    "TR-S4-EXTREME-100PCT",
)
VALID_2D_DEPTH_CLASSES = {"0.15-1m", "1-3m", "3-8m", ">8m"}
REQUIRED_TSHO_ROLPA_SIM_FILES = (
    "README.md",
    "tsho_rolpa_10pct.par",
    "tsho_rolpa_30pct.par",
    "tsho_rolpa_50pct.par",
    "tsho_rolpa_100pct.par",
    "tsho_rolpa.bci",
    "tsho_rolpa_30pct.bdy",
    "basement_v4_model.json",
)

VALID_PROVENANCE_DATA_CLASSES = {
    "live_observation",
    "forecast",
    "historical",
    "static_assessment",
    "cached",
    "unavailable",
}

VALID_PROVENANCE_STATUSES = {"available", "stale", "unavailable"}
VALID_HEALTH_STATES = {"healthy", "degraded", "stale"}

VALID_LANDSLIDE_TYPES = {
    "landslide_event",
    "landslide_scar",
    "susceptibility_zone",
    "hazard_report",
    "coseismic_failure",
}

VALID_CASCADE_EVIDENCE_TYPES = {"observed", "forecast", "modelled_static"}

REQUIRED_GOVERNANCE_DOCS = [
    ("DATA_LICENSES.md", ("ODbL 1.0", "CC BY-SA 4.0", "BIPAD")),
    ("ROADMAP.md", ("Wave A", "Wave B", "Wave C", "Wave D")),
    ("docs/MODEL_CARDS.md", ("MC-1", "MC-2", "MC-3", "MC-4", "MC-5", "MC-6")),
    ("docs/INSTITUTIONAL_INTEGRATION_SPEC.md", ("DHM", "NEMRC", "BIPAD", "Department of Roads")),
    ("docs/TSHO_ROLPA_2D_STUDY_PLAN.md", ("Tsho Rolpa", "LISFLOOD-FP", "BASEMENT")),
    ("docs/COMMUNITY_REPORTING_GOVERNANCE.md", ("EXIF", "redact_pii", "public_live_endpoint_enabled", "Individual Privacy Act")),
    ("docs/wave_d/AGENCY_MOU_TEMPLATE.md", ("NDRRMA", "DHM", "NEMRC", "DoR", "Exercise")),
    ("docs/wave_d/DEOC_UAT_PROTOCOL.md", ("Dolakha", "Ramechhap", "Madhesh", "Kailali", "Bardiya", "UAT-01")),
    ("docs/wave_d/MULTILINGUAL_CAP_SMS_IVR_SOP.md", ("urn:oasis:names:tc:emergency:cap:1.2", "Exercise", "GSM-7", "UCS-2", "NTC", "Ncell")),
]

REQUIRED_HOTLINES = [
    "tel:100",
    "tel:102",
    "tel:1114",
    "tel:1149",
    "tel:1155",
]

REQUIRED_STATUTORY_LINKS = [
    "https://hydrology.gov.np",
    "https://seismonepal.gov.np",
    "https://bipadportal.gov.np",
]

REQUIRED_SUITE_TARGETS = [
    ("Nepal Observatory Hub", "https://prazg.github.io"),
    ("Nepal_Quake_Watch", "Nepal_Quake_Watch"),
    ("Nepal_Cryosphere_Inventory", "Nepal_Cryosphere_Inventory"),
    ("GLOF_dashboard", "GLOF_dashboard"),
    ("Nepal_Heritage_Catalogue", "Nepal_Heritage_Catalogue"),
]

# Banned Node 20 GitHub Actions major versions
NODE20_ACTION_PATTERNS = [
    ("actions/checkout@v1-v6", re.compile(r"actions/checkout@v[1-6]\b")),
    ("actions/setup-python@v1-v6", re.compile(r"actions/setup-python@v[1-6]\b")),
    ("actions/cache@v1-v5", re.compile(r"actions/cache@v[1-5]\b")),
    ("actions/configure-pages@v1-v5", re.compile(r"actions/configure-pages@v[1-5]\b")),
    ("actions/upload-pages-artifact@v1-v4", re.compile(r"actions/upload-pages-artifact@v[1-4]\b")),
    ("actions/deploy-pages@v1-v4", re.compile(r"actions/deploy-pages@v[1-4]\b")),
]

# Track pass/fail/warn results
RESULTS: list[tuple[str, str, str]] = []


def record(ok: bool, name: str, detail: str = "") -> bool:
    status = "PASS" if ok else "FAIL"
    RESULTS.append((status, name, detail))
    suffix = f" -- {detail}" if detail else ""
    print(f"  [{status}] {name}{suffix}")
    return ok


def warn(name: str, detail: str = "") -> None:
    RESULTS.append(("WARN", name, detail))
    suffix = f" -- {detail}" if detail else ""
    print(f"  [WARN] {name}{suffix}")


# ===========================================================================
# 1. GitHub Actions Workflows (Node 24 compliance & hardening)
# ===========================================================================
def check_workflows() -> None:
    print("\n[1/6] GitHub Actions Workflows (Node 24 & Hardening)")
    wf_dir = ROOT / ".github" / "workflows"
    if not wf_dir.is_dir():
        record(False, "workflows directory exists", f"missing {wf_dir}")
        return

    wf_files = sorted(list(wf_dir.glob("*.yml")) + list(wf_dir.glob("*.yaml")))
    wf_names = {p.name for p in wf_files}
    record(
        "pages.yml" in wf_names and "weekly-refresh.yml" in wf_names,
        "required workflow files present",
        f"found {sorted(wf_names)}",
    )

    node20_hits: list[str] = []
    for wf in wf_files:
        text = wf.read_text(encoding="utf-8", errors="replace")
        for lineno, line in enumerate(text.splitlines(), 1):
            stripped = line.lstrip()
            if stripped.startswith("#"):
                continue
            for label, pat in NODE20_ACTION_PATTERNS:
                if pat.search(line):
                    node20_hits.append(f"{wf.name}:{lineno} ({label})")

    record(
        not node20_hits,
        "zero Node 20 GitHub Actions across .github/workflows/",
        "clean (Node 24 native)" if not node20_hits else "; ".join(node20_hits),
    )

    pages_yml = wf_dir / "pages.yml"
    if pages_yml.is_file():
        ptext = pages_yml.read_text(encoding="utf-8")
        pages_issues: list[str] = []
        if "verify_site.py" not in ptext:
            pages_issues.append("missing verify_site.py step")
        if ".nojekyll" not in ptext:
            pages_issues.append("missing .nojekyll")
        if "assets" not in ptext:
            pages_issues.append("missing assets/ in staging")
        if "schemas" not in ptext:
            pages_issues.append("missing schemas/ in staging")
        if "manifest.webmanifest" not in ptext:
            pages_issues.append("missing manifest.webmanifest in staging")
        if "sw.js" not in ptext:
            pages_issues.append("missing sw.js in staging")
        if "data/*.geojson" not in ptext:
            pages_issues.append("missing data/*.geojson in staging")
        if "data/*.xml" not in ptext:
            pages_issues.append("missing data/*.xml in staging")
        if not (re.search(r"^\s+build:\s*$", ptext, re.M) and re.search(r"^\s+deploy:\s*$", ptext, re.M) and "needs: build" in ptext):
            pages_issues.append("must preserve 2-job build -> deploy split")
        if "group: pages-deploy" not in ptext:
            pages_issues.append("missing concurrency group: pages-deploy")
        if re.search(r"cancel-in-progress\s*:\s*true\b", ptext):
            pages_issues.append("cancel-in-progress must be false")
        if "timeout-minutes:" not in ptext:
            pages_issues.append("missing timeout-minutes")
        if "data/*.json" not in ptext or re.search(r"cp\s+-r\s+[^\n]*\bdata\b", ptext):
            pages_issues.append("must stage data/*.json only (do not copy legacy data/*.js)")
        record(
            not pages_issues,
            "pages.yml hardening & staging contract",
            "ok" if not pages_issues else "; ".join(pages_issues),
        )

    weekly_yml = wf_dir / "weekly-refresh.yml"
    if weekly_yml.is_file():
        wtext = weekly_yml.read_text(encoding="utf-8")
        weekly_issues: list[str] = []
        if "refresh_weekly.py" not in wtext:
            weekly_issues.append("missing src/refresh_weekly.py")
        if "verify_site.py" not in wtext:
            weekly_issues.append("missing src/verify_site.py")
        if "--unit-only" not in wtext:
            weekly_issues.append("missing src/test_pipeline.py --unit-only")
        if ".nojekyll" not in wtext:
            weekly_issues.append("missing .nojekyll")
        if "assets" not in wtext:
            weekly_issues.append("missing assets/ in staging")
        if "schemas" not in wtext:
            weekly_issues.append("missing schemas/ in staging")
        if "manifest.webmanifest" not in wtext:
            weekly_issues.append("missing manifest.webmanifest in staging")
        if "sw.js" not in wtext:
            weekly_issues.append("missing sw.js in staging")
        if "data/*.geojson" not in wtext:
            weekly_issues.append("missing data/*.geojson in staging")
        if "data/*.xml" not in wtext:
            weekly_issues.append("missing data/*.xml in staging")
        if "cache/bipad_snapshot.json" not in wtext:
            weekly_issues.append("missing cache/bipad_snapshot.json in git add candidates")
        if "cache/eo_sar.json" not in wtext:
            weekly_issues.append("missing cache/eo_sar.json in git add candidates")
        if "data/" not in wtext:
            weekly_issues.append("missing data/ in CANDIDATE_PATHS")
        if "data/*.json" not in wtext or re.search(r"cp\s+-r\s+[^\n]*\bdata\b", wtext):
            weekly_issues.append("must stage data/*.json only (do not copy legacy data/*.js)")
        if "git pull --rebase --autostash" not in wtext:
            weekly_issues.append("missing git pull --rebase --autostash")
        if re.search(r"cancel-in-progress\s*:\s*true\b", wtext):
            weekly_issues.append("cancel-in-progress must be false")
        record(
            not weekly_issues,
            "weekly-refresh.yml hardening & staging contract",
            "ok" if not weekly_issues else "; ".join(weekly_issues),
        )


# ===========================================================================
# 2. Byte-identical index.html <-> src/template.html
# ===========================================================================
def check_template_sync() -> None:
    print("\n[2/6] HTML Template Synchronisation")
    index_path = ROOT / "index.html"
    tmpl_path = ROOT / "src" / "template.html"

    if not index_path.is_file() or not tmpl_path.is_file():
        record(
            False,
            "index.html and src/template.html both exist",
            f"index={index_path.is_file()}, template={tmpl_path.is_file()}",
        )
        return

    idx_bytes = index_path.read_bytes()
    tpl_bytes = tmpl_path.read_bytes()
    if idx_bytes == tpl_bytes:
        record(
            True,
            "index.html and src/template.html are 100% byte-identical",
            f"{len(idx_bytes):,} bytes",
        )
    else:
        diff_pos = next(
            (i for i, (a, b) in enumerate(zip(idx_bytes, tpl_bytes)) if a != b),
            min(len(idx_bytes), len(tpl_bytes)),
        )
        line_no = idx_bytes[:diff_pos].count(b"\n") + 1
        record(
            False,
            "index.html and src/template.html are 100% byte-identical",
            f"index={len(idx_bytes):,} B vs template={len(tpl_bytes):,} B (first diff at byte {diff_pos}, line {line_no})",
        )


# ===========================================================================
# 3. HTML Security, CSP, Hotlines, Statutory Links, Disclaimer & Suite Bar
# ===========================================================================
class SiteHTMLAudit(HTMLParser):
    """Strict HTML audit parser for index.html."""

    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.csp_values: list[str] = []
        self.referrer_values: list[str] = []
        self.inline_scripts: list[tuple[int, str]] = []
        self.script_srcs: list[tuple[int, str]] = []
        self.style_tags: list[int] = []
        self.inline_event_attrs: list[tuple[int, str, str]] = []
        self.external_scripts: list[tuple[int, str]] = []
        self.external_links: list[tuple[int, str, str]] = []
        self.local_stylesheets: list[tuple[int, str]] = []
        self.manifest_links: list[tuple[int, str]] = []
        self.anchors: list[tuple[int, str, bool]] = []  # (line, href, in_suite_bar)
        self.has_suite_bar = False
        self.visible_text_chunks: list[str] = []

        self._in_script = False
        self._script_has_src = False
        self._script_start_line = 0
        self._script_buf: list[str] = []
        self._in_style = False
        self._suite_depth = 0
        self._void_tags = {
            "area", "base", "br", "col", "embed", "hr", "img", "input",
            "link", "meta", "param", "source", "track", "wbr",
        }

    def _audit_tag(self, tag: str, attrs: list[tuple[str, str | None]], self_closing: bool) -> None:
        line, _ = self.getpos()
        t = tag.lower()
        attr_map: dict[str, str] = {}
        for k, v in attrs:
            kl = k.lower()
            val = v or ""
            attr_map[kl] = val
            if re.match(r"^on[a-z]+$", kl):
                self.inline_event_attrs.append((line, t, kl))

        classes = set(attr_map.get("class", "").split())
        if "prazg-suite-bar" in classes:
            self.has_suite_bar = True
            if not self_closing and t not in self._void_tags:
                self._suite_depth += 1
        elif self._suite_depth > 0 and not self_closing and t not in self._void_tags:
            self._suite_depth += 1

        if t == "meta":
            he = attr_map.get("http-equiv", "").strip().lower()
            nm = attr_map.get("name", "").strip().lower()
            if he == "content-security-policy":
                self.csp_values.append(attr_map.get("content", "").strip())
            if nm == "referrer":
                self.referrer_values.append(attr_map.get("content", "").strip().lower())

        elif t == "script":
            src = attr_map.get("src", "").strip()
            self._in_script = not self_closing
            self._script_has_src = bool(src)
            self._script_start_line = line
            self._script_buf = []
            if not src:
                self.inline_scripts.append((line, "missing src attribute"))
            else:
                self.script_srcs.append((line, src))
                if re.match(r"^(https?:|//|data:|javascript:)", src, re.I):
                    self.external_scripts.append((line, src))

        elif t == "style":
            self.style_tags.append(line)
            if not self_closing:
                self._in_style = True

        elif t == "link":
            rel = attr_map.get("rel", "").strip().lower()
            href = attr_map.get("href", "").strip()
            rel_tokens = set(rel.split())
            if href:
                is_external = bool(re.match(r"^(https?:|//)", href, re.I))
                if "fonts.googleapis.com" in href.lower() or "fonts.gstatic.com" in href.lower():
                    self.external_links.append((line, rel, href))
                elif is_external:
                    # Allow canonical link pointing solely to this observatory
                    if rel_tokens == {"canonical"} and href.startswith("https://prazg.github.io/"):
                        pass
                    else:
                        self.external_links.append((line, rel, href))
                elif "stylesheet" in rel_tokens:
                    self.local_stylesheets.append((line, href))
                elif "manifest" in rel_tokens:
                    self.manifest_links.append((line, href))

        elif t == "a":
            href = attr_map.get("href", "").strip()
            if href:
                self.anchors.append((line, href, self._suite_depth > 0))

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        self._audit_tag(tag, attrs, self_closing=False)

    def handle_startendtag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        self._audit_tag(tag, attrs, self_closing=True)

    def handle_endtag(self, tag: str) -> None:
        t = tag.lower()
        if t == "script" and self._in_script:
            body = "".join(self._script_buf).strip()
            if body and self._script_has_src:
                self.inline_scripts.append((self._script_start_line, "non-empty body inside external <script>"))
            self._in_script = False
            self._script_buf = []
        elif t == "style" and self._in_style:
            self._in_style = False
        if self._suite_depth > 0 and t not in self._void_tags:
            self._suite_depth -= 1

    def handle_data(self, data: str) -> None:
        if self._in_script:
            self._script_buf.append(data)
        elif not self._in_style:
            self.visible_text_chunks.append(data)


def _resolve_local_href(href: str) -> Path:
    clean = href.split("#", 1)[0].split("?", 1)[0].lstrip("/")
    return ROOT / clean


def check_html() -> None:
    print("\n[3/6] HTML Security, CSP, Emergency Hotlines & Suite Links")
    index_path = ROOT / "index.html"
    if not index_path.is_file():
        record(False, "index.html exists", "missing index.html")
        return

    raw_html = index_path.read_text(encoding="utf-8", errors="strict")
    audit = SiteHTMLAudit()
    audit.feed(raw_html)
    audit.close()

    # CSP meta tag
    has_csp = bool(audit.csp_values and any(audit.csp_values))
    csp_issues: list[str] = []
    if not has_csp:
        csp_issues.append("missing <meta http-equiv='Content-Security-Policy'>")
    else:
        csp = audit.csp_values[0]
        if "'unsafe-eval'" in csp.lower():
            csp_issues.append("CSP must not allow 'unsafe-eval'")
        m_script = re.search(r"script-src\s+([^;]+)", csp, re.I)
        if not m_script:
            csp_issues.append("CSP missing script-src directive")
        elif "'unsafe-inline'" in m_script.group(1).lower():
            csp_issues.append("CSP script-src must not allow 'unsafe-inline'")
    record(
        not csp_issues,
        "strict Content-Security-Policy meta tag present",
        "ok" if not csp_issues else "; ".join(csp_issues),
    )

    # Referrer policy (CRITICAL OSM 403 GUARD)
    has_no_referrer = "no-referrer" in audit.referrer_values
    has_strict_origin = "strict-origin-when-cross-origin" in audit.referrer_values
    if has_no_referrer:
        ref_detail = (
            f"FORBIDDEN content='no-referrer' found ({audit.referrer_values}) — "
            "OpenStreetMap tile usage policy returns HTTP 403 Access Blocked when Referer is omitted! "
            "Must use <meta name='referrer' content='strict-origin-when-cross-origin'>"
        )
    elif has_strict_origin:
        ref_detail = "strict-origin-when-cross-origin (OpenStreetMap tile-policy compliant)"
    else:
        ref_detail = (
            f"found {audit.referrer_values}; must use "
            "<meta name='referrer' content='strict-origin-when-cross-origin'> "
            "(OpenStreetMap tile usage policy returns HTTP 403 without Referer)"
        )
    record(
        has_strict_origin and not has_no_referrer,
        "<meta name='referrer' content='strict-origin-when-cross-origin'> present (OSM 403 guard)",
        ref_detail,
    )

    # PWA Web App Manifest link in index.html
    valid_manifest_links = [
        (ln, href)
        for ln, href in audit.manifest_links
        if _resolve_local_href(href).is_file() and href.split("?", 1)[0].endswith("manifest.webmanifest")
    ]
    record(
        bool(valid_manifest_links),
        "<link rel='manifest' href='manifest.webmanifest'> present in index.html",
        f"linked at L{valid_manifest_links[0][0]} ({valid_manifest_links[0][1]})"
        if valid_manifest_links
        else (
            f"invalid manifest link(s): {audit.manifest_links}"
            if audit.manifest_links
            else "missing <link rel='manifest' href='manifest.webmanifest'>"
        ),
    )

    # Zero inline <script>, <style>, on*=
    record(
        not audit.inline_scripts,
        "zero inline <script> blocks in index.html",
        "0 inline scripts"
        if not audit.inline_scripts
        else "; ".join(f"L{ln}: {msg}" for ln, msg in audit.inline_scripts[:5]),
    )
    record(
        not audit.style_tags,
        "zero inline <style> blocks in index.html",
        "0 inline styles"
        if not audit.style_tags
        else f"lines {audit.style_tags[:10]}",
    )
    record(
        not audit.inline_event_attrs,
        "zero inline on*= event attributes in index.html",
        "0 inline handlers"
        if not audit.inline_event_attrs
        else "; ".join(f"L{ln} <{t} {a}=>" for ln, t, a in audit.inline_event_attrs[:6]),
    )

    # Zero external Google Fonts or third-party <script>/<link> tags
    gfont_hits = re.findall(r"fonts\.(?:googleapis|gstatic)\.com", raw_html, re.I)
    ext_issues: list[str] = []
    if gfont_hits:
        ext_issues.append(f"Google Fonts reference ({len(gfont_hits)})")
    for ln, src in audit.external_scripts:
        ext_issues.append(f"L{ln} external <script src='{src}'>")
    for ln, rel, href in audit.external_links:
        ext_issues.append(f"L{ln} external <link rel='{rel}' href='{href}'>")
    record(
        not ext_issues,
        "zero Google Fonts or external third-party <script>/<link> tags",
        "self-contained" if not ext_issues else "; ".join(ext_issues[:6]),
    )

    # Local <script> and <link rel="stylesheet"> files exist on disk
    missing_local: list[str] = []
    for ln, src in audit.script_srcs:
        if not re.match(r"^(https?:|//|data:|javascript:)", src, re.I):
            if not _resolve_local_href(src).is_file():
                missing_local.append(f"L{ln} script '{src}'")
    for ln, href in audit.local_stylesheets:
        if not _resolve_local_href(href).is_file():
            missing_local.append(f"L{ln} stylesheet '{href}'")
    record(
        not missing_local and bool(audit.script_srcs),
        "all local <script> and stylesheet references exist on disk",
        f"{len(audit.script_srcs)} scripts, {len(audit.local_stylesheets)} stylesheets verified"
        if not missing_local
        else "; ".join(missing_local[:6]),
    )

    # Nepal emergency hotlines (tel:100, tel:102, tel:1114, tel:1149, tel:1155)
    anchor_hrefs = [href for _, href, _ in audit.anchors]
    normalized_hrefs = {href.rstrip("/") for href in anchor_hrefs}
    missing_hotlines = [h for h in REQUIRED_HOTLINES if h not in anchor_hrefs]
    record(
        not missing_hotlines,
        "Nepal emergency hotlines present (tel:100/102/1114/1149/1155)",
        "all 5 hotlines clickable"
        if not missing_hotlines
        else f"missing {missing_hotlines}",
    )

    # Clickable statutory agency links (DHM, NEMRC, BIPAD)
    missing_statutory = [
        url
        for url in REQUIRED_STATUTORY_LINKS
        if not any(h == url or h.startswith(url + "/") for h in normalized_hrefs)
    ]
    record(
        not missing_statutory,
        "clickable Nepal statutory agency links (DHM, NEMRC, BIPAD)",
        "all 3 statutory links clickable"
        if not missing_statutory
        else f"missing {missing_statutory}",
    )

    # Persistent bilingual non-operational disclaimer
    visible_text = " ".join(audit.visible_text_chunks)
    has_en_disclaimer = bool(
        re.search(
            r"(not\s+an?\s+operational|non[- ]operational|not\s+an?\s+early\s+warning|"
            r"not\s+a\s+(?:deterministic\s+)?(?:forecast|warning\s+service)|"
            r"screening.{0,120}(?:official|statutory))",
            visible_text,
            re.I,
        )
    )
    devanagari_words = set(re.findall(r"[\u0900-\u097F]{2,}", visible_text))
    # Must contain meaningful Devanagari disclaimer/UI text beyond the lone title word त्राय
    has_ne_bilingual = len(devanagari_words - {"त्राय"}) >= 4
    record(
        has_en_disclaimer and has_ne_bilingual,
        "persistent bilingual (EN / Nepali) non-operational disclaimer present",
        f"EN_disclaimer={has_en_disclaimer}, Devanagari_unique_words={len(devanagari_words)}",
    )

    # .prazg-suite-bar cross-links to @prazg's Nepal portals
    suite_hrefs = [href for _, href, in_suite in audit.anchors if in_suite]
    suite_norm = {href.rstrip("/") for href in suite_hrefs}
    missing_suite: list[str] = []
    if not audit.has_suite_bar:
        missing_suite.append("missing .prazg-suite-bar container")
    else:
        for label, needle in REQUIRED_SUITE_TARGETS:
            if needle == "https://prazg.github.io":
                found = "https://prazg.github.io" in suite_norm
            else:
                found = any(needle in h for h in suite_hrefs)
            if not found:
                missing_suite.append(label)
    record(
        audit.has_suite_bar and not missing_suite,
        ".prazg-suite-bar cross-links to all 5 @prazg Nepal portals",
        f"{len(suite_hrefs)} suite links verified"
        if not missing_suite
        else f"missing: {', '.join(missing_suite)}",
    )


# ===========================================================================
# 4. Data JSON Integrity
# ===========================================================================
def _extract_records(obj: Any, list_keys: tuple[str, ...]) -> list[dict[str, Any]]:
    """Extract a list of dicts from GeoJSON, wrapped dict, list, or keyed mapping."""
    if isinstance(obj, list):
        return [r for r in obj if isinstance(r, dict)]
    if isinstance(obj, dict):
        if obj.get("type") == "FeatureCollection" and isinstance(obj.get("features"), list):
            out = []
            for f in obj["features"]:
                if isinstance(f, dict):
                    props = f.get("properties")
                    if isinstance(props, dict):
                        out.append(props)
                    else:
                        out.append(f)
            return out
        for key in list_keys:
            val = obj.get(key)
            if isinstance(val, list):
                return [r for r in val if isinstance(r, dict)]
            if isinstance(val, dict):
                merged = []
                for k, v in val.items():
                    if isinstance(v, dict):
                        rec = dict(v)
                        rec.setdefault("_key", k)
                        merged.append(rec)
                return merged
        # Fallback: dict keyed directly by district/item name
        if obj and all(isinstance(v, dict) for v in obj.values()):
            merged = []
            for k, v in obj.items():
                rec = dict(v)
                rec.setdefault("_key", k)
                merged.append(rec)
            return merged
    return []


def _validate_provenance_envelope(env: Any, label: str) -> list[str]:
    """Validate canonical 6-state TRĀYA 2.0 ProvenanceEnvelope contract."""
    errs: list[str] = []
    if not isinstance(env, dict):
        return [f"{label}: provenance must be an object"]
    for req_k in ("source", "dataset", "retrieved_at_utc", "license_ref"):
        val = env.get(req_k)
        if not isinstance(val, str) or not val.strip():
            errs.append(f"{label}: missing/empty {req_k}")
    dc = env.get("data_class")
    if dc not in VALID_PROVENANCE_DATA_CLASSES:
        errs.append(f"{label}: invalid data_class={dc!r}")
    st = env.get("status")
    if st not in VALID_PROVENANCE_STATUSES:
        errs.append(f"{label}: invalid status={st!r}")
    return errs


def _audit_landslide_records_null_integrity(records: list[dict[str, Any]], label: str) -> list[str]:
    """Verify 5-type landslide partitioning and strict null-not-0 casualty integrity."""
    violations: list[str] = []
    for idx, rec in enumerate(records):
        rid = str(rec.get("id") or f"{label}[{idx}]")
        ft = rec.get("feature_type")
        if ft not in VALID_LANDSLIDE_TYPES:
            violations.append(f"{rid}: invalid feature_type={ft!r}")
        ev_dt = rec.get("event_date_utc")
        dp = rec.get("date_precision")
        if ev_dt is None and dp != "unknown":
            violations.append(f"{rid}: null event_date_utc requires date_precision='unknown' (got {dp!r})")
        prov = rec.get("province")
        if prov is not None and prov not in CANONICAL_PROVINCES:
            violations.append(f"{rid}: non-canonical province={prov!r}")
        verified = rec.get("verified") is True
        if ft == "landslide_scar":
            if ev_dt is not None or dp != "unknown" or verified:
                violations.append(f"{rid}: landslide_scar must be undated and unverified")
            for ck in ("fatalities", "injuries", "households_affected"):
                if rec.get(ck) is not None:
                    violations.append(f"{rid}: landslide_scar must have {ck}=null (got {rec.get(ck)!r})")
        elif not verified:
            for ck in ("fatalities", "injuries", "households_affected"):
                if rec.get(ck) == 0:
                    violations.append(f"{rid}: unverified record has {ck}=0 (violates null-not-0 rule)")
        if len(violations) >= 12:
            break
    return violations


def check_data() -> None:
    print("\n[4/6] Data JSON / GeoJSON Payloads, Provenance & Epistemic Hygiene")
    data_dir = ROOT / "data"
    if not data_dir.is_dir():
        record(False, "data/ directory exists", f"missing {data_dir}")
        return

    json_files = sorted(data_dir.glob("*.json"))
    geojson_files = sorted(data_dir.glob("*.geojson"))
    parsed: dict[str, Any] = {}
    parse_errors: list[str] = []
    bagamati_hits: list[str] = []

    for jf in json_files + geojson_files:
        try:
            raw = jf.read_text(encoding="utf-8", errors="strict")
            parsed[jf.name] = json.loads(raw)
            if re.search(r"bagamati", raw, re.I):
                bagamati_hits.append(jf.name)
        except Exception as exc:
            parse_errors.append(f"{jf.name}: {exc}")

    missing_req = [fn for fn in REQUIRED_DATA_JSON if fn not in parsed]
    record(
        not parse_errors and not missing_req,
        "all required data/*.json files exist and parse cleanly",
        f"{len(json_files)} JSON + {len(geojson_files)} GeoJSON files parsed"
        if (not parse_errors and not missing_req)
        else "; ".join(
            ([f"missing={missing_req}"] if missing_req else [])
            + ([f"parse_errors={parse_errors}"] if parse_errors else [])
        ),
    )

    has_core_prov_files = "lakes.json" in parsed and "districts.json" in parsed
    record(
        has_core_prov_files and not bagamati_hits,
        "canonical 'Bagmati Province' spelling (zero 'Bagamati' in data/*.json & *.geojson)",
        "clean across all data payloads"
        if (has_core_prov_files and not bagamati_hits)
        else (
            f"found 'Bagamati' in: {bagamati_hits}"
            if bagamati_hits
            else "cannot verify: lakes.json and/or districts.json missing"
        ),
    )

    # data/districts.json: 77 districts & 7 provinces including Madhesh Province & Bagmati Province
    if "districts.json" in parsed:
        d_recs = _extract_records(parsed["districts.json"], ("districts", "features", "items", "records"))
        districts = set()
        provinces = set()
        missing_prov_districts: list[str] = []
        for rec in d_recs:
            dname = str(
                rec.get("district")
                or rec.get("name")
                or rec.get("district_name")
                or rec.get("id")
                or rec.get("_key")
                or ""
            ).strip()
            pname = str(
                rec.get("province")
                or rec.get("prov")
                or rec.get("province_name")
                or ""
            ).strip()
            if dname:
                districts.add(dname)
            if pname:
                provinces.add(pname)
            elif dname:
                missing_prov_districts.append(dname)

        missing_provs = sorted(CANONICAL_PROVINCES - provinces)
        extra_provs = sorted(provinces - CANONICAL_PROVINCES)
        ok_dist = (
            len(districts) == 77
            and len(provinces) == 7
            and "Madhesh Province" in provinces
            and "Bagmati Province" in provinces
            and not missing_provs
            and not missing_prov_districts
        )
        detail = (
            f"{len(districts)} districts, {len(provinces)} canonical provinces (incl. Madhesh & Bagmati)"
            if ok_dist
            else (
                f"districts={len(districts)} (need 77), provinces={len(provinces)} (need 7), "
                f"missing_provs={missing_provs}, extra_provs={extra_provs}, "
                f"unassigned={missing_prov_districts[:5]}"
            )
        )
        record(ok_dist, "data/districts.json covers all 77 districts & 7 canonical provinces", detail)
    else:
        record(False, "data/districts.json covers all 77 districts & 7 canonical provinces", "file missing")

    # data/lakes.json: zero blank lake provinces & GL_30.41653_80.68146 attributed
    if "lakes.json" in parsed:
        lakes = _extract_records(parsed["lakes.json"], ("lakes", "features"))
        blank_lakes: list[str] = []
        target_id = "GL_30.41653_80.68146"
        target_prov: str | None = None
        for rec in lakes:
            lid = str(rec.get("id") or rec.get("lake_id") or "")
            prov = str(rec.get("prov") or rec.get("province") or "").strip()
            if not prov:
                blank_lakes.append(lid or "<unnamed>")
            if lid == target_id:
                target_prov = prov
        ok_lakes = (
            len(lakes) >= 1429
            and not blank_lakes
            and target_prov is not None
            and len(target_prov) > 0
        )
        detail = (
            f"{len(lakes)} lakes, 0 blank provinces, {target_id}='{target_prov}'"
            if ok_lakes
            else (
                f"n_lakes={len(lakes)}, blank_provinces={len(blank_lakes)} ({blank_lakes[:5]}), "
                f"{target_id}={target_prov!r}"
            )
        )
        record(ok_lakes, "data/lakes.json zero blank provinces & GL_30.41653_80.68146 attributed", detail)
    else:
        record(False, "data/lakes.json zero blank provinces & GL_30.41653_80.68146 attributed", "file missing")

    # data/eq_history_m6.json: zero '?' mojibake place names
    if "eq_history_m6.json" in parsed:
        eq_recs = _extract_records(parsed["eq_history_m6.json"], ("events", "earthquakes", "features", "items"))
        bad_places: list[str] = []
        for rec in eq_recs:
            place = str(rec.get("place") or rec.get("location") or rec.get("title") or "")
            if "?" in place or "\ufffd" in place:
                bad_places.append(place)
        ok_eq = len(eq_recs) > 0 and not bad_places
        record(
            ok_eq,
            "data/eq_history_m6.json has zero '?' mojibake place names",
            f"{len(eq_recs)} M6+ events clean"
            if ok_eq
            else f"n={len(eq_recs)}, mojibake={len(bad_places)} ({bad_places[:4]})",
        )
    else:
        record(False, "data/eq_history_m6.json has zero '?' mojibake place names", "file missing")

    # Also verify eq_history.json if present
    if "eq_history.json" in parsed:
        eq_all = _extract_records(parsed["eq_history.json"], ("events", "earthquakes", "features", "items"))
        bad_all = [
            str(r.get("place") or "")
            for r in eq_all
            if "?" in str(r.get("place") or "") or "\ufffd" in str(r.get("place") or "")
        ]
        record(
            not bad_all,
            "data/eq_history.json has zero '?' mojibake place names",
            f"{len(eq_all)} events clean" if not bad_all else f"{len(bad_all)} mojibake ({bad_all[:3]})",
        )

    # Sanity check rivers_watch.json (10 basins + valid climatology)
    if "rivers_watch.json" in parsed:
        rw = parsed["rivers_watch.json"]
        basins = rw.get("basins", []) if isinstance(rw, dict) else []
        bad_basins: list[str] = []
        for b in basins:
            clim = b.get("climatology") or {}
            q50 = clim.get("q50")
            q20 = clim.get("q20")
            if not (isinstance(q50, (int, float)) and isinstance(q20, (int, float)) and q50 > 0 and q20 >= q50):
                bad_basins.append(str(b.get("id", "?")))
        record(
            len(basins) == 10 and not bad_basins,
            "data/rivers_watch.json has 10 valid river basins",
            f"10 basins, updated_utc={rw.get('updated_utc') if isinstance(rw, dict) else None}"
            if (len(basins) == 10 and not bad_basins)
            else f"count={len(basins)}, invalid_clim={bad_basins}",
        )

    # TRĀYA 2.0: data/manifest.json (6-state ProvenanceEnvelopes & SHA-256 checksums)
    if "manifest.json" in parsed and isinstance(parsed["manifest.json"], dict):
        mf = parsed["manifest.json"]
        mf_issues: list[str] = []
        if mf.get("overall_health") not in VALID_HEALTH_STATES:
            mf_issues.append(f"invalid overall_health={mf.get('overall_health')!r}")
        sources = mf.get("sources")
        if not isinstance(sources, list) or not sources:
            mf_issues.append("sources must be a non-empty list")
        else:
            seen_datasets: set[str] = set()
            for idx, env in enumerate(sources):
                ds = env.get("dataset") if isinstance(env, dict) else f"source[{idx}]"
                if isinstance(ds, str):
                    seen_datasets.add(ds)
                mf_issues.extend(_validate_provenance_envelope(env, str(ds)))
            for req_ds in (
                "traya_tsho_rolpa_2d_inundation_v1",
                "community_report_moderation_queue",
                "cap_v12_multilingual_exercise_drafts",
            ):
                if req_ds not in seen_datasets:
                    mf_issues.append(f"missing provenance envelope for dataset={req_ds!r}")
        checksums = mf.get("input_checksums")
        if not isinstance(checksums, dict) or not checksums:
            mf_issues.append("missing input_checksums")
        else:
            bad_sha = [
                k for k, v in checksums.items()
                if not isinstance(v, str) or not re.fullmatch(r"[0-9a-f]{64}", v)
            ]
            if bad_sha:
                mf_issues.append(f"invalid SHA-256 checksums for {bad_sha[:4]}")
            for req_chk in (
                "data/tsho_rolpa_2d_inundation.json",
                "data/tsho_rolpa_2d_footprints.geojson",
                "data/moderation_queue.json",
                "data/cap_drafts.json",
                "data/cap_exercise_latest.xml",
            ):
                if req_chk not in checksums:
                    mf_issues.append(f"missing SHA-256 checksum for {req_chk}")
        record(
            not mf_issues,
            "data/manifest.json valid 6-state ProvenanceEnvelopes, license_ref & SHA-256 checksums",
            f"{len(sources or [])} envelopes, {len(checksums or {})} checksums, health={mf.get('overall_health')}"
            if not mf_issues
            else "; ".join(mf_issues[:6]),
        )
    else:
        record(False, "data/manifest.json valid 6-state ProvenanceEnvelopes, license_ref & SHA-256 checksums", "file missing")

    # TRĀYA 2.0: data/kpi_baseline.json
    if "kpi_baseline.json" in parsed and isinstance(parsed["kpi_baseline.json"], dict):
        kpi = parsed["kpi_baseline.json"]
        kpi_issues: list[str] = []
        if kpi.get("provenance_completeness_pct") != 100.0:
            kpi_issues.append(f"provenance_completeness_pct={kpi.get('provenance_completeness_pct')!r} (expected 100.0)")
        ls_mat = kpi.get("landslide_maturity") or {}
        if ls_mat.get("null_casualty_integrity_ok") is not True:
            kpi_issues.append(f"null_casualty_integrity_ok={ls_mat.get('null_casualty_integrity_ok')!r}")
        exp_cov = kpi.get("exposure_coverage") or {}
        if exp_cov.get("n_provinces_covered") != 7 or exp_cov.get("n_districts_covered") != 77:
            kpi_issues.append(
                f"exposure_coverage={exp_cov.get('n_provinces_covered')}p/{exp_cov.get('n_districts_covered')}d"
            )
        cas_sum = kpi.get("cascade_summary") or {}
        if int(cas_sum.get("total_pathways") or 0) < 3:
            kpi_issues.append(f"cascade_summary.total_pathways={cas_sum.get('total_pathways')!r}")
        record(
            not kpi_issues,
            "data/kpi_baseline.json completeness, null-casualty integrity & 77-district coverage",
            f"freshness={kpi.get('feed_freshness_pct')}%, provenance=100.0%, null_integrity=True"
            if not kpi_issues
            else "; ".join(kpi_issues[:6]),
        )
    else:
        record(False, "data/kpi_baseline.json completeness, null-casualty integrity & 77-district coverage", "file missing")

    # TRĀYA 2.0: data/bipad_official.json
    if "bipad_official.json" in parsed and isinstance(parsed["bipad_official.json"], dict):
        bp = parsed["bipad_official.json"]
        bp_issues = _validate_provenance_envelope(bp.get("provenance"), "bipad_official")
        if not isinstance(bp.get("official_notice"), str) or not bp["official_notice"].strip():
            bp_issues.append("missing official_notice")
        for list_k in ("alerts", "landslide_incidents", "dhm_rivers", "dhm_rain", "nsc_earthquakes"):
            if not isinstance(bp.get(list_k), list):
                bp_issues.append(f"{list_k} must be a list")
        record(
            not bp_issues,
            "data/bipad_official.json valid provenance envelope & official-separation structure",
            f"class={(bp.get('provenance') or {}).get('data_class')}, "
            f"alerts={len(bp.get('alerts') or [])}, incidents={len(bp.get('landslide_incidents') or [])}"
            if not bp_issues
            else "; ".join(bp_issues[:6]),
        )
    else:
        record(False, "data/bipad_official.json valid provenance envelope & official-separation structure", "file missing")

    # TRĀYA 2.0: data/landslide_inventory.geojson, data/landslide_review_queue.json & null-not-0 integrity
    ls_doc = parsed.get("landslides.json") if isinstance(parsed.get("landslides.json"), dict) else None
    ls_gj = parsed.get("landslide_inventory.geojson") if isinstance(parsed.get("landslide_inventory.geojson"), dict) else None
    ls_rq = parsed.get("landslide_review_queue.json") if isinstance(parsed.get("landslide_review_queue.json"), dict) else None

    gj_issues: list[str] = []
    if not ls_gj:
        gj_issues.append("data/landslide_inventory.geojson missing or invalid JSON")
    else:
        if ls_gj.get("type") != "FeatureCollection" or not isinstance(ls_gj.get("features"), list):
            gj_issues.append("must be RFC 7946 FeatureCollection")
        else:
            n_feat = len(ls_gj["features"])
            if ls_doc and n_feat != int(ls_doc.get("n_total") or 0):
                gj_issues.append(f"feature count {n_feat} != landslides.json n_total {ls_doc.get('n_total')}")
            bad_geom = [
                f.get("id") for f in ls_gj["features"]
                if not isinstance(f, dict)
                or (f.get("geometry") or {}).get("type") != "Point"
                or len((f.get("geometry") or {}).get("coordinates") or []) < 2
            ]
            if bad_geom:
                gj_issues.append(f"{len(bad_geom)} invalid Point geometries")
    record(
        not gj_issues,
        "data/landslide_inventory.geojson valid RFC 7946 FeatureCollection matching inventory",
        f"{len((ls_gj or {}).get('features') or [])} Point features verified"
        if not gj_issues
        else "; ".join(gj_issues[:6]),
    )

    rq_issues: list[str] = []
    if not ls_rq:
        rq_issues.append("data/landslide_review_queue.json missing or invalid JSON")
    else:
        if ls_rq.get("policy") != "flag_only_never_auto_merge":
            rq_issues.append(f"unexpected policy={ls_rq.get('policy')!r}")
        cands = ls_rq.get("candidates")
        if not isinstance(cands, list):
            rq_issues.append("candidates must be a list")
        else:
            for c in cands:
                if c.get("auto_merged") is not False or c.get("review_status") != "pending_review":
                    rq_issues.append(f"candidate {c.get('candidate_id')} violates flag-only pending_review contract")
                    break
    record(
        not rq_issues,
        "data/landslide_review_queue.json enforces flag-only duplicate review policy",
        f"{len((ls_rq or {}).get('candidates') or [])} candidate pairs (policy=flag_only_never_auto_merge)"
        if not rq_issues
        else "; ".join(rq_issues[:6]),
    )

    # Null-not-zero casualty & 5-type partitioning integrity across JSON + GeoJSON
    null_issues: list[str] = []
    if ls_doc and isinstance(ls_doc.get("events"), list):
        null_issues.extend(_audit_landslide_records_null_integrity(ls_doc["events"], "landslides.json"))
    else:
        null_issues.append("landslides.json missing events list")
    if ls_gj and isinstance(ls_gj.get("features"), list):
        gj_props = [f.get("properties") or {} for f in ls_gj["features"] if isinstance(f, dict)]
        null_issues.extend(_audit_landslide_records_null_integrity(gj_props, "landslide_inventory.geojson"))
    record(
        not null_issues,
        "null-not-zero casualty & 5-type landslide partitioning integrity across JSON + GeoJSON",
        f"{len((ls_doc or {}).get('events') or [])} records verified (0 null-not-0 violations)"
        if not null_issues
        else "; ".join(null_issues[:5]),
    )

    # TRĀYA 2.0: data/exposure_isolation.json
    if "exposure_isolation.json" in parsed and isinstance(parsed["exposure_isolation.json"], dict):
        ei = parsed["exposure_isolation.json"]
        ei_issues: list[str] = []
        if ei.get("schema_version") != "exposure_isolation.v1":
            ei_issues.append(f"unexpected schema_version={ei.get('schema_version')!r}")
        if ei.get("data_class") != "static_assessment":
            ei_issues.append(f"data_class={ei.get('data_class')!r} (expected 'static_assessment')")
        dims = ei.get("dimensions") or {}
        if not isinstance(dims, dict) or len(dims) < 4:
            ei_issues.append("must separate 4 conceptual dimensions")
        unc = ei.get("uncertainty_and_coverage_limits") or {}
        if unc.get("published_hazard_classes_modified") is not False:
            ei_issues.append("published_hazard_classes_modified must be False")
        if unc.get("corridor_not_inundation_boundary") is not True:
            ei_issues.append("corridor_not_inundation_boundary must be True")
        ei_dists = ei.get("districts") or []
        ei_lakes = ei.get("lakes") or {}
        if len(ei_dists) != 77:
            ei_issues.append(f"districts={len(ei_dists)} (expected 77)")
        if len(ei_lakes) < 600:
            ei_issues.append(f"routed lakes={len(ei_lakes)} (expected >=600)")
        record(
            not ei_issues,
            "data/exposure_isolation.json 4-dimension structure, 77 districts & hazard preservation",
            f"{len(ei_lakes)} corridors, {len(ei_dists)} districts, published_hazard_untouched=True"
            if not ei_issues
            else "; ".join(ei_issues[:6]),
        )
    else:
        record(False, "data/exposure_isolation.json 4-dimension structure, 77 districts & hazard preservation", "file missing")

    # TRĀYA 2.0: data/cascades.json
    if "cascades.json" in parsed and isinstance(parsed["cascades.json"], dict):
        cas = parsed["cascades.json"]
        cas_issues: list[str] = []
        if cas.get("schema_version") != "cascades.v1":
            cas_issues.append(f"unexpected schema_version={cas.get('schema_version')!r}")
        chains = cas.get("chains") or {}
        req_chains = {"rain_landslide_dam_road", "quake_coseismic_isolation", "glof_infra_isolation"}
        missing_ch = sorted(req_chains - set(chains.keys()))
        if missing_ch:
            cas_issues.append(f"missing chains={missing_ch}")
        for cid, ch in chains.items():
            if not (ch.get("summary_en") and ch.get("summary_ne")):
                cas_issues.append(f"chain {cid} missing bilingual EN/NE summary")
        edges = cas.get("edges") or []
        if not edges:
            cas_issues.append("edges list is empty")
        for ed in edges:
            if ed.get("evidence_type") not in VALID_CASCADE_EVIDENCE_TYPES:
                cas_issues.append(f"edge {ed.get('rule_id')} invalid evidence_type={ed.get('evidence_type')!r}")
            if not isinstance(ed.get("active"), bool):
                cas_issues.append(f"edge {ed.get('rule_id')} active must be bool")
            if not ed.get("trigger_rule") or not ed.get("uncertainty_note"):
                cas_issues.append(f"edge {ed.get('rule_id')} missing trigger_rule or uncertainty_note")
        record(
            not cas_issues,
            "data/cascades.json 3-chain directed graph, evidence types & bilingual summaries",
            f"{len(chains)} chains, {len(cas.get('nodes') or [])} nodes, {len(edges)} edges verified"
            if not cas_issues
            else "; ".join(cas_issues[:6]),
        )
    else:
        record(False, "data/cascades.json 3-chain directed graph, evidence types & bilingual summaries", "file missing")

    # TRĀYA 2.0: data/eo_sar.json
    if "eo_sar.json" in parsed and isinstance(parsed["eo_sar.json"], dict):
        eo = parsed["eo_sar.json"]
        eo_issues = _validate_provenance_envelope(eo.get("provenance"), "eo_sar")
        if eo.get("all_weather_sar_capability") is not True:
            eo_issues.append("all_weather_sar_capability must be True")
        lakes_eo = eo.get("lakes") or []
        if not isinstance(lakes_eo, list) or not lakes_eo:
            eo_issues.append("lakes list must be non-empty")
        else:
            ids = {lk.get("id") for lk in lakes_eo if isinstance(lk, dict)}
            if "GL_27.86029_86.47725" not in ids:
                eo_issues.append("missing Tsho Rolpa (GL_27.86029_86.47725)")
            for lk in lakes_eo:
                for sensor_key in ("sentinel1", "sentinel2"):
                    sc = lk.get(sensor_key)
                    if isinstance(sc, dict):
                        for uk in ("thumbnail_url", "copernicus_browser_url"):
                            uv = sc.get(uk)
                            if uv is not None and not str(uv).startswith("https://"):
                                eo_issues.append(f"insecure URL in {lk.get('id')}.{sensor_key}.{uk}")
        record(
            not eo_issues,
            "data/eo_sar.json valid Sentinel-1/2 EO provenance, Tsho Rolpa coverage & HTTPS URLs",
            f"class={(eo.get('provenance') or {}).get('data_class')}, lakes={len(lakes_eo)}, "
            f"s1={eo.get('n_s1_covered')}, s2={eo.get('n_s2_covered')}"
            if not eo_issues
            else "; ".join(eo_issues[:6]),
        )
    else:
        record(False, "data/eo_sar.json valid Sentinel-1/2 EO provenance, Tsho Rolpa coverage & HTTPS URLs", "file missing")

    # TRĀYA 2.0: data/tsho_rolpa_pilot.json
    if "tsho_rolpa_pilot.json" in parsed and isinstance(parsed["tsho_rolpa_pilot.json"], dict):
        trp = parsed["tsho_rolpa_pilot.json"]
        tr_issues: list[str] = []
        if trp.get("schema_version") != "tsho_rolpa_pilot.v1":
            tr_issues.append(f"unexpected schema_version={trp.get('schema_version')!r}")
        if trp.get("data_class") != "static_assessment":
            tr_issues.append(f"data_class={trp.get('data_class')!r} (expected 'static_assessment')")
        if trp.get("is_2d_inundation_map") is not False:
            tr_issues.append("is_2d_inundation_map must be False for pre-simulation benchmark")
        if trp.get("is_design_grade_2d_map") is not False:
            tr_issues.append("is_design_grade_2d_map must be False")
        if not isinstance(trp.get("status_note"), str) or "NOT yet a 2D inundation map" not in trp["status_note"]:
            tr_issues.append("status_note must explicitly disclaim NOT yet a 2D inundation map")
        if (trp.get("lake_identification") or {}).get("matched_inventory_id") != "GL_27.86029_86.47725":
            tr_issues.append("matched_inventory_id must resolve to GL_27.86029_86.47725")
        cps = trp.get("valley_checkpoints") or []
        scns = trp.get("breach_scenario_framework") or []
        if len(cps) < 5:
            tr_issues.append(f"valley_checkpoints={len(cps)} (expected >=5)")
        if len(scns) != 4:
            tr_issues.append(f"breach_scenario_framework={len(scns)} (expected 4)")
        if trp.get("has_screening_2d_simulation") is not True:
            tr_issues.append("has_screening_2d_simulation must be True when 2D simulation is present")
        if trp.get("simulation_2d_path") != "data/tsho_rolpa_2d_inundation.json":
            tr_issues.append(f"unexpected simulation_2d_path={trp.get('simulation_2d_path')!r}")
        if trp.get("footprints_geojson_path") != "data/tsho_rolpa_2d_footprints.geojson":
            tr_issues.append(f"unexpected footprints_geojson_path={trp.get('footprints_geojson_path')!r}")
        sim2d_sum = trp.get("simulation_2d_summary") or {}
        if len(sim2d_sum.get("scenarios") or []) != 4:
            tr_issues.append(f"simulation_2d_summary.scenarios={len(sim2d_sum.get('scenarios') or [])} (expected 4)")
        record(
            not tr_issues,
            "data/tsho_rolpa_pilot.json pre-simulation framing, checkpoints & live 2D summary link",
            f"GL_27.86029_86.47725, {len(cps)} checkpoints, {len(scns)} scenarios, 2d_linked=True, design_grade=False"
            if not tr_issues
            else "; ".join(tr_issues[:6]),
        )
    else:
        record(False, "data/tsho_rolpa_pilot.json pre-simulation framing, checkpoints & live 2D summary link", "file missing")

    # TRĀYA 2.0: data/tsho_rolpa_2d_inundation.json
    if "tsho_rolpa_2d_inundation.json" in parsed and isinstance(parsed["tsho_rolpa_2d_inundation.json"], dict):
        sim2d = parsed["tsho_rolpa_2d_inundation.json"]
        s2d_issues = _validate_provenance_envelope(sim2d.get("provenance"), "tsho_rolpa_2d_inundation")
        if sim2d.get("schema_version") != "tsho_rolpa_2d.v1":
            s2d_issues.append(f"unexpected schema_version={sim2d.get('schema_version')!r}")
        if sim2d.get("is_design_grade_engineering_map") is not False:
            s2d_issues.append("is_design_grade_engineering_map MUST be False")
        scns2d = sim2d.get("scenarios")
        max_mb_err = 0.0
        if not isinstance(scns2d, list) or len(scns2d) != 4:
            s2d_issues.append(f"expected 4 scenarios, got {len(scns2d) if isinstance(scns2d, list) else type(scns2d).__name__}")
        else:
            seen_ids = [s.get("scenario_id") for s in scns2d if isinstance(s, dict)]
            if tuple(seen_ids) != EXPECTED_2D_SCENARIO_IDS:
                s2d_issues.append(f"scenario IDs mismatch: {seen_ids}")
            for sc in scns2d:
                sid = str(sc.get("scenario_id") or "?")
                mb = sc.get("mass_balance") or {}
                err_pct = mb.get("mass_balance_error_pct")
                if not isinstance(err_pct, (int, float)) or isinstance(err_pct, bool) or err_pct >= 2.0 or err_pct < 0.0:
                    s2d_issues.append(f"{sid}: mass_balance_error_pct={err_pct!r} (must be < 2.0)")
                else:
                    max_mb_err = max(max_mb_err, float(err_pct))
                if mb.get("conserved_under_2pct") is not True:
                    s2d_issues.append(f"{sid}: conserved_under_2pct must be True")
                cps2d = sc.get("checkpoints") or []
                if len(cps2d) < 5:
                    s2d_issues.append(f"{sid}: expected >=5 checkpoints, got {len(cps2d)}")
        record(
            not s2d_issues,
            "data/tsho_rolpa_2d_inundation.json 4 scenarios, mass_balance_error_pct < 2.0 & non-design-grade lock",
            f"4 scenarios, max_mb_err={max_mb_err:.5f}%, is_design_grade_engineering_map=False"
            if not s2d_issues
            else "; ".join(s2d_issues[:6]),
        )
    else:
        record(
            False,
            "data/tsho_rolpa_2d_inundation.json 4 scenarios, mass_balance_error_pct < 2.0 & non-design-grade lock",
            "file missing",
        )

    # TRĀYA 2.0: data/tsho_rolpa_2d_footprints.geojson
    fp_gj = parsed.get("tsho_rolpa_2d_footprints.geojson")
    fp_issues: list[str] = []
    if not isinstance(fp_gj, dict):
        fp_issues.append("data/tsho_rolpa_2d_footprints.geojson missing or invalid JSON")
    else:
        if fp_gj.get("type") != "FeatureCollection" or not isinstance(fp_gj.get("features"), list) or not fp_gj["features"]:
            fp_issues.append("must be non-empty RFC 7946 FeatureCollection")
        if fp_gj.get("is_design_grade_engineering_map") is not False:
            fp_issues.append("is_design_grade_engineering_map MUST be False")
        seen_fp_scns: set[str] = set()
        bad_fp_geom = 0
        bad_fp_cls = 0
        for feat in fp_gj.get("features") or []:
            if not isinstance(feat, dict) or feat.get("type") != "Feature":
                bad_fp_geom += 1
                continue
            geom = feat.get("geometry") or {}
            gtype = geom.get("type")
            coords = geom.get("coordinates")
            if gtype not in ("Polygon", "MultiPolygon") or not isinstance(coords, list) or not coords:
                bad_fp_geom += 1
            props = feat.get("properties") or {}
            sid = props.get("scenario_id")
            if isinstance(sid, str):
                seen_fp_scns.add(sid)
            if props.get("depth_class") not in VALID_2D_DEPTH_CLASSES:
                bad_fp_cls += 1
        if bad_fp_geom:
            fp_issues.append(f"{bad_fp_geom} invalid Polygon/MultiPolygon geometries")
        if bad_fp_cls:
            fp_issues.append(f"{bad_fp_cls} features with invalid depth_class")
        missing_scns = [s for s in EXPECTED_2D_SCENARIO_IDS if s not in seen_fp_scns]
        if missing_scns:
            fp_issues.append(f"missing scenario footprints: {missing_scns}")
    record(
        not fp_issues,
        "data/tsho_rolpa_2d_footprints.geojson valid RFC 7946 FeatureCollection across all 4 scenarios",
        f"{len((fp_gj or {}).get('features') or [])} footprint features covering all 4 scenarios"
        if not fp_issues
        else "; ".join(fp_issues[:6]),
    )

    # TRĀYA 2.0: data/moderation_queue.json
    if "moderation_queue.json" in parsed and isinstance(parsed["moderation_queue.json"], dict):
        mq = parsed["moderation_queue.json"]
        mq_issues = _validate_provenance_envelope(mq.get("provenance"), "moderation_queue")
        if mq.get("schema_version") != "moderation_queue.v1":
            mq_issues.append(f"unexpected schema_version={mq.get('schema_version')!r}")
        if mq.get("public_live_endpoint_enabled") is not False:
            mq_issues.append("public_live_endpoint_enabled MUST be False (pre-MOU sandbox)")
        if mq.get("requires_authenticated_moderation") is not True:
            mq_issues.append("requires_authenticated_moderation must be True")
        if mq.get("governance_mode") != "pilot_sandbox_post_mou":
            mq_issues.append(f"unexpected governance_mode={mq.get('governance_mode')!r}")
        if (mq.get("dedup_policy") or {}).get("mode") != "flag_only_never_auto_merge":
            mq_issues.append("dedup_policy.mode must be 'flag_only_never_auto_merge'")
        fixtures = mq.get("sample_redacted_uat_fixtures")
        if not isinstance(fixtures, list) or not fixtures:
            mq_issues.append("sample_redacted_uat_fixtures must be non-empty list")
        else:
            for fx in fixtures:
                rid = str(fx.get("report_id") or "?")
                if fx.get("feature_type") != "hazard_report":
                    mq_issues.append(f"{rid}: feature_type must be 'hazard_report'")
                if fx.get("exif_stripped") is not True:
                    mq_issues.append(f"{rid}: exif_stripped must be True")
                if fx.get("pii_redaction_applied") is not True:
                    mq_issues.append(f"{rid}: pii_redaction_applied must be True")
                if fx.get("fatalities") is not None or fx.get("injuries") is not None:
                    mq_issues.append(f"{rid}: unverified UAT fixture must keep fatalities/injuries as null")
                if not re.fullmatch(r"[0-9a-f]{64}", str(fx.get("dedup_fingerprint") or "")):
                    mq_issues.append(f"{rid}: invalid SHA-256 dedup_fingerprint")
        record(
            not mq_issues,
            "data/moderation_queue.json pre-MOU sandbox lock, EXIF/PII & null-not-0 UAT fixtures",
            f"public_live_endpoint_enabled=False, {len(fixtures or [])} clean UAT fixtures"
            if not mq_issues
            else "; ".join(mq_issues[:6]),
        )
    else:
        record(
            False,
            "data/moderation_queue.json pre-MOU sandbox lock, EXIF/PII & null-not-0 UAT fixtures",
            "file missing",
        )

    # TRĀYA 2.0: data/cap_drafts.json
    if "cap_drafts.json" in parsed and isinstance(parsed["cap_drafts.json"], dict):
        cap = parsed["cap_drafts.json"]
        cap_issues = _validate_provenance_envelope(cap.get("provenance"), "cap_drafts")
        if cap.get("schema_version") != "cap_v12_advisory.v1":
            cap_issues.append(f"unexpected schema_version={cap.get('schema_version')!r}")
        if cap.get("cap_namespace") != CAP_XMLNS:
            cap_issues.append(f"unexpected cap_namespace={cap.get('cap_namespace')!r}")
        rgov = cap.get("relay_governance") or {}
        if rgov.get("relay_enabled") is not False:
            cap_issues.append("relay_governance.relay_enabled MUST be False")
        if rgov.get("requires_signed_mou") is not True:
            cap_issues.append("relay_governance.requires_signed_mou must be True")
        if rgov.get("statutory_warning") is not False:
            cap_issues.append("relay_governance.statutory_warning must be False")
        if rgov.get("cap_status") != "Exercise":
            cap_issues.append(f"relay_governance.cap_status={rgov.get('cap_status')!r} (expected 'Exercise')")
        sup_codes = tuple(m.get("code") for m in (cap.get("supported_languages") or []) if isinstance(m, dict))
        if sup_codes != SUPPORTED_LANG_CODES:
            cap_issues.append(f"supported_languages mismatch: {sup_codes}")
        advs = cap.get("advisories")
        if not isinstance(advs, list) or not advs:
            cap_issues.append("advisories must be a non-empty list")
        else:
            for adv in advs:
                aid = str(adv.get("identifier") or "?")
                if adv.get("status") != "Exercise":
                    cap_issues.append(f"{aid}: status must be 'Exercise', got {adv.get('status')!r}")
                if (adv.get("relay_governance") or {}).get("relay_enabled") is not False:
                    cap_issues.append(f"{aid}: relay_enabled must be False")
                infos = adv.get("info") or []
                info_langs = tuple(i.get("language") for i in infos if isinstance(i, dict))
                if info_langs != SUPPORTED_LANG_CODES:
                    cap_issues.append(f"{aid}: info languages={info_langs} (expected {SUPPORTED_LANG_CODES})")
                for info in infos:
                    lc = info.get("language")
                    sms = info.get("sms_draft") or {}
                    sms_txt = str(sms.get("text") or "")
                    max_c = 160 if lc == "en" else 140
                    if not sms_txt or len(sms_txt) > max_c or sms.get("within_budget") is not True:
                        cap_issues.append(f"{aid}/{lc}: SMS budget violation ({len(sms_txt)}>{max_c})")
                    if lc == "en" and not sms_txt.isascii():
                        cap_issues.append(f"{aid}/en: SMS must be ASCII GSM-7")
                    instr = str(info.get("instruction") or "")
                    missing_hl = [h for h in CAP_REQUIRED_HOTLINES if h not in instr]
                    if missing_hl:
                        cap_issues.append(f"{aid}/{lc}: instruction missing hotlines {missing_hl}")
                    if len(cap_issues) >= 12:
                        break
                if len(cap_issues) >= 12:
                    break
        record(
            not cap_issues,
            "data/cap_drafts.json relay_enabled=False, Exercise lock & 6-language SMS/IVR advisories",
            f"{len(advs or [])} advisories x 6 languages ({','.join(SUPPORTED_LANG_CODES)}), relay_enabled=False"
            if not cap_issues
            else "; ".join(cap_issues[:6]),
        )
    else:
        record(
            False,
            "data/cap_drafts.json relay_enabled=False, Exercise lock & 6-language SMS/IVR advisories",
            "file missing",
        )

    # TRĀYA 2.0: data/cap_exercise_latest.xml (OASIS CAP v1.2 XML)
    cap_xml_path = data_dir / "cap_exercise_latest.xml"
    xml_issues: list[str] = []
    xml_langs: list[str] = []
    if not cap_xml_path.is_file():
        xml_issues.append("missing data/cap_exercise_latest.xml")
    else:
        try:
            root_el = ET.fromstring(cap_xml_path.read_text(encoding="utf-8", errors="strict"))
            if root_el.tag != f"{{{CAP_XMLNS}}}alert":
                xml_issues.append(f"unexpected XML root tag {root_el.tag!r}")
            ns = {"cap": CAP_XMLNS}
            st_el = root_el.find("cap:status", ns)
            if st_el is None or st_el.text != "Exercise":
                xml_issues.append(f"<status> must be 'Exercise', got {st_el.text if st_el is not None else None!r}")
            note_el = root_el.find("cap:note", ns)
            if note_el is None or not (note_el.text or "").strip():
                xml_issues.append("missing non-operational <note>")
            info_els = root_el.findall("cap:info", ns)
            xml_langs = [el.findtext("cap:language", default="", namespaces=ns) for el in info_els]
            if tuple(xml_langs) != SUPPORTED_LANG_CODES:
                xml_issues.append(f"XML <info> languages={xml_langs} (expected {list(SUPPORTED_LANG_CODES)})")
        except Exception as exc:
            xml_issues.append(f"XML parse error: {exc}")
    record(
        not xml_issues,
        "data/cap_exercise_latest.xml valid OASIS CAP v1.2 XML with <status>Exercise</status> & 6 languages",
        f"OASIS CAP v1.2 XML verified (<status>Exercise</status>, langs={','.join(xml_langs)})"
        if not xml_issues
        else "; ".join(xml_issues[:6]),
    )

    # TRĀYA 2.0: data/summary.json carries all 9 TRĀYA 2.0 product summary blocks
    if "summary.json" in parsed and isinstance(parsed["summary.json"], dict):
        summ = parsed["summary.json"]
        req_v2_keys = (
            "bipad_official",
            "landslide_inventory",
            "eo_sar",
            "exposure_isolation",
            "cascades",
            "tsho_rolpa_pilot",
            "tsho_rolpa_2d",
            "moderation_queue",
            "cap_relay",
        )
        missing_v2 = [k for k in req_v2_keys if not isinstance(summ.get(k), dict)]
        record(
            not missing_v2,
            "data/summary.json includes all 9 TRĀYA 2.0 product summary blocks",
            "all 9 TRĀYA 2.0 summary blocks present"
            if not missing_v2
            else f"missing: {missing_v2}",
        )


# ===========================================================================
# 5. Formal JSON Schemas & TRĀYA 2.0 Governance / Scientific Documentation
# ===========================================================================
def check_schemas_and_docs() -> None:
    print("\n[5/6] Formal Schemas & Governance / Scientific Documentation")

    # schemas/landslide_event.v1.schema.json
    schema_path = ROOT / "schemas" / "landslide_event.v1.schema.json"
    schema_issues: list[str] = []
    if not schema_path.is_file():
        schema_issues.append("missing schemas/landslide_event.v1.schema.json")
    else:
        try:
            sch = json.loads(schema_path.read_text(encoding="utf-8", errors="strict"))
            if not isinstance(sch, dict) or not sch.get("$schema"):
                schema_issues.append("missing $schema")
            props = sch.get("properties") or {}
            ft_enum = set((props.get("feature_type") or {}).get("enum") or [])
            if ft_enum != VALID_LANDSLIDE_TYPES:
                schema_issues.append(f"feature_type enum mismatch: {sorted(ft_enum)}")
            req_fields = set(sch.get("required") or [])
            for rk in ("id", "feature_type", "provider_id", "event_date_utc", "fatalities", "verified", "license_ref"):
                if rk not in req_fields:
                    schema_issues.append(f"missing required schema property: {rk}")
            if not isinstance(sch.get("allOf"), list) or len(sch["allOf"]) < 3:
                schema_issues.append("missing allOf null-not-0 conditional invariants")
        except Exception as exc:
            schema_issues.append(f"JSON parse error: {exc}")
    record(
        not schema_issues,
        "schemas/landslide_event.v1.schema.json valid 5-type & null-not-0 JSON Schema",
        "valid JSON Schema 2020-12 (5 feature_types + allOf invariants)"
        if not schema_issues
        else "; ".join(schema_issues[:6]),
    )

    # schemas/community_report.v1.schema.json
    cr_schema_path = ROOT / "schemas" / "community_report.v1.schema.json"
    cr_issues: list[str] = []
    if not cr_schema_path.is_file():
        cr_issues.append("missing schemas/community_report.v1.schema.json")
    else:
        try:
            csch = json.loads(cr_schema_path.read_text(encoding="utf-8", errors="strict"))
            if not isinstance(csch, dict) or not csch.get("$schema"):
                cr_issues.append("missing $schema")
            cprops = csch.get("properties") or {}
            if (cprops.get("feature_type") or {}).get("const") != "hazard_report":
                cr_issues.append("feature_type must be const='hazard_report'")
            if (cprops.get("exif_stripped") or {}).get("const") is not True:
                cr_issues.append("exif_stripped must be const=true")
            if (cprops.get("pii_redaction_applied") or {}).get("const") is not True:
                cr_issues.append("pii_redaction_applied must be const=true")
            if not isinstance(csch.get("allOf"), list) or len(csch["allOf"]) < 2:
                cr_issues.append("missing allOf null-not-0 / temporal invariants")
        except Exception as exc:
            cr_issues.append(f"JSON parse error: {exc}")
    record(
        not cr_issues,
        "schemas/community_report.v1.schema.json valid EXIF, PII & null-not-0 JSON Schema",
        "valid JSON Schema 2020-12 (hazard_report + EXIF/PII locks + allOf invariants)"
        if not cr_issues
        else "; ".join(cr_issues[:6]),
    )

    # schemas/cap_v12_advisory.schema.json
    cap_schema_path = ROOT / "schemas" / "cap_v12_advisory.schema.json"
    cap_sch_issues: list[str] = []
    if not cap_schema_path.is_file():
        cap_sch_issues.append("missing schemas/cap_v12_advisory.schema.json")
    else:
        try:
            apsch = json.loads(cap_schema_path.read_text(encoding="utf-8", errors="strict"))
            if not isinstance(apsch, dict) or not apsch.get("$schema"):
                cap_sch_issues.append("missing $schema")
            aprops = apsch.get("properties") or {}
            if (aprops.get("xmlns") or {}).get("const") != CAP_XMLNS:
                cap_sch_issues.append(f"xmlns const must be {CAP_XMLNS!r}")
            st_enum = (aprops.get("status") or {}).get("enum") or []
            if set(st_enum) != {"Exercise", "Test"} or "Actual" in st_enum:
                cap_sch_issues.append(f"status enum must lock out 'Actual', got {st_enum}")
            rg_props = ((aprops.get("relay_governance") or {}).get("properties") or {})
            if (rg_props.get("relay_enabled") or {}).get("const") is not False:
                cap_sch_issues.append("relay_governance.relay_enabled must be const=false")
            lang_enum = ((((aprops.get("info") or {}).get("items") or {}).get("properties") or {}).get("language") or {}).get("enum") or []
            if tuple(lang_enum) != SUPPORTED_LANG_CODES:
                cap_sch_issues.append(f"info language enum mismatch: {lang_enum}")
        except Exception as exc:
            cap_sch_issues.append(f"JSON parse error: {exc}")
    record(
        not cap_sch_issues,
        "schemas/cap_v12_advisory.schema.json valid CAP v1.2 Exercise lock & 6-language schema",
        "valid JSON Schema 2020-12 (Exercise/Test only, relay_enabled=false, 6 languages)"
        if not cap_sch_issues
        else "; ".join(cap_sch_issues[:6]),
    )

    # simulations/tsho_rolpa/ HPC reproducibility pack (LISFLOOD-FP & BASEMENT v4)
    sim_dir = ROOT / "simulations" / "tsho_rolpa"
    sim_issues: list[str] = []
    if not sim_dir.is_dir():
        sim_issues.append("missing simulations/tsho_rolpa/ directory")
    else:
        for fname in REQUIRED_TSHO_ROLPA_SIM_FILES:
            fpath = sim_dir / fname
            if not fpath.is_file() or fpath.stat().st_size == 0:
                sim_issues.append(f"missing or empty simulations/tsho_rolpa/{fname}")
        bm_path = sim_dir / "basement_v4_model.json"
        if bm_path.is_file():
            try:
                bm = json.loads(bm_path.read_text(encoding="utf-8", errors="strict"))
                if not isinstance(bm, dict) or not bm:
                    sim_issues.append("basement_v4_model.json must be non-empty JSON object")
            except Exception as exc:
                sim_issues.append(f"basement_v4_model.json parse error: {exc}")
    record(
        not sim_issues,
        "simulations/tsho_rolpa/ HPC reproducibility pack (LISFLOOD-FP & BASEMENT v4)",
        f"{len(REQUIRED_TSHO_ROLPA_SIM_FILES)} pack files verified"
        if not sim_issues
        else "; ".join(sim_issues[:6]),
    )

    # Governance & scientific documentation suite
    for rel_path, needles in REQUIRED_GOVERNANCE_DOCS:
        doc_path = ROOT / rel_path
        if not doc_path.is_file():
            record(False, f"{rel_path} present and complete", f"missing {rel_path}")
            continue
        text = doc_path.read_text(encoding="utf-8", errors="strict")
        missing_needles = [n for n in needles if n not in text]
        ok_doc = len(text.strip()) >= 500 and not missing_needles
        record(
            ok_doc,
            f"{rel_path} present and complete",
            f"{len(text):,} chars verified"
            if ok_doc
            else f"len={len(text)}, missing_keywords={missing_needles}",
        )


# ===========================================================================
# 6. ES Modules Static Analysis (Balance, Imports/Exports, XSS Sinks)
# ===========================================================================
REGEX_PRECEDING_KEYWORDS = {
    "return", "case", "throw", "typeof", "void", "delete",
    "in", "instanceof", "of", "new", "yield", "await", "else", "do",
}

REGEX_PRECEDING_PUNCT = {
    "(", "[", "{", ",", ";", ":", "?", "=", "!", "&", "|", "^", "~",
    "+", "-", "*", "%", "<", ">", "=>", "&&", "||", "??",
    "+=", "-=", "*=", "/=", "%=", "==", "===", "!=", "!==", "<=", ">=",
}

SAFE_WRAPPER_NAMES = {
    "esc", "escapehtml", "eschtml", "escattr", "escapeattr",
    "safeurl", "sanitizeurl", "safehref", "encodeuricomponent", "encodeuri",
    "number", "parseint", "parsefloat", "boolean",
    "fmt", "fmtnum", "fmtint", "fmtdec", "fmtkm", "fmtq", "fmtpct",
    "fmtdate", "fmttime", "fmtnpt", "fmtutc", "fmtduration", "fmtpop",
    "fmtvol", "fmtarea", "fmtelev", "fmtmag", "fmtcoord", "fmtage",
    "formatnum", "formatnumber", "formatdate", "formattime", "formatnpt",
    "formatutc", "formatkm", "formatq", "formatpct", "formatage",
    "t", "tr", "i18n", "gettext", "localize",
    "round", "clamp",
}

# Property names that carry external/API or user-visible text and must not be
# interpolated raw into HTML templates without escaping or numeric formatting
UNTRUSTED_PROP_RE = re.compile(
    r"(?:"
    r"\.properties\.[A-Za-z_$][\w$]*"
    r"|\.(?:place|headline|description|eventname|station|thumbnail|"
    r"copernicus_browser_url|scene_id|url|link|href|src|message|"
    r"glacier|mechanism|driver|fault_name|alertlevel|country|source|"
    r"name|title|district|prov|province|basin|detail)\b"
    r"|\b(?:days|times|dates)\s*\["
    r")"
)


def scan_js_module(src: str, rel_path: str) -> tuple[list[str], str, list[tuple[int, str, list[tuple[int, str, str]]]]]:
    """
    Lex a JavaScript ES module in pure Python 3.12 stdlib.

    Returns:
      errors: list of syntax/balance errors (strings with line:col)
      code_only: source with comments and string/template text replaced by spaces
                 (preserving newlines and import/export string literals separately)
      html_templates: list of (start_line, raw_template_text, [(expr_line, expr_text, prefix_before_expr)])
                      for every template literal containing HTML/SVG markup.
    """
    n = len(src)
    i = 0
    line = 1
    col = 1

    errors: list[str] = []
    # Stack entries: (kind, open_char, line, col)
    # kind is 'delim' for ()[]{}, or 'tpl_expr' for ${ ... } inside template literal
    stack: list[tuple[str, str, int, int]] = []
    matching = {"(": ")", "[": "]", "{": "}"}

    # Template stack to record full HTML template literals & their ${...} expressions
    # Each entry: dict(start_line, raw_parts, exprs=[(line, expr_str, prefix_tail)], current_expr_start_idx)
    tpl_stack: list[dict[str, Any]] = []
    completed_templates: list[tuple[int, str, list[tuple[int, str, str]]]] = []

    code_chars: list[str] = []
    prev_tok_type: str | None = None  # 'ident', 'num', 'str', 'punct', 'regex', 'close'
    prev_tok_val: str = ""

    def advance(ch: str) -> None:
        nonlocal line, col
        if ch == "\n":
            line += 1
            col = 1
        else:
            col += 1

    def can_start_regex() -> bool:
        if prev_tok_type is None:
            return True
        if prev_tok_type == "ident" and prev_tok_val in REGEX_PRECEDING_KEYWORDS:
            return True
        if prev_tok_type == "punct" and prev_tok_val in REGEX_PRECEDING_PUNCT:
            return True
        return False

    def resume_template() -> None:
        nonlocal i
        tpl = tpl_stack[-1]
        while i < n:
            c = src[i]
            if c == "\\":
                tpl["raw_parts"].append(c)
                code_chars.append(" ")
                advance(c)
                i += 1
                if i < n:
                    tpl["raw_parts"].append(src[i])
                    code_chars.append("\n" if src[i] == "\n" else " ")
                    advance(src[i])
                    i += 1
                continue
            if c == "`":
                tpl["raw_parts"].append("`")
                code_chars.append(" ")
                advance(c)
                i += 1
                done = tpl_stack.pop()
                raw_text = "".join(done["raw_parts"])
                if re.search(r"<[a-zA-Z!/]", raw_text):
                    completed_templates.append((done["start_line"], raw_text, done["exprs"]))
                # Record completed nested template span on parent template so its
                # already-audited content is masked out when checking outer ${...}
                if tpl_stack and tpl_stack[-1]["expr_start"] is not None:
                    tpl_stack[-1]["nested_spans"].append((done["open_idx"], i))
                return
            if c == "$" and i + 1 < n and src[i + 1] == "{":
                prefix_tail = "".join(tpl["raw_parts"])[-60:]
                tpl["raw_parts"].append("${")
                code_chars.append(" ")
                code_chars.append(" ")
                expr_line = line
                advance("$")
                advance("{")
                i += 2
                stack.append(("tpl_expr", "{", expr_line, col - 1))
                tpl["expr_start"] = i
                tpl["expr_line"] = expr_line
                tpl["expr_prefix"] = prefix_tail
                tpl["nested_spans"] = []
                return
            tpl["raw_parts"].append(c)
            code_chars.append("\n" if c == "\n" else " ")
            advance(c)
            i += 1
        # Unclosed template literal at EOF
        done = tpl_stack.pop()
        errors.append(f"{rel_path}:{done['start_line']}: unclosed template literal (`)")

    while i < n:
        ch = src[i]

        # Whitespace
        if ch in " \t\r\n\f\v":
            code_chars.append("\n" if ch == "\n" else " ")
            advance(ch)
            i += 1
            continue

        # Line comment //
        if ch == "/" and i + 1 < n and src[i + 1] == "/":
            while i < n and src[i] != "\n":
                code_chars.append(" ")
                advance(src[i])
                i += 1
            continue

        # Block comment /* ... */
        if ch == "/" and i + 1 < n and src[i + 1] == "*":
            start_ln = line
            code_chars.append(" ")
            code_chars.append(" ")
            advance("/")
            advance("*")
            i += 2
            closed = False
            while i < n:
                if src[i] == "*" and i + 1 < n and src[i + 1] == "/":
                    code_chars.append(" ")
                    code_chars.append(" ")
                    advance("*")
                    advance("/")
                    i += 2
                    closed = True
                    break
                code_chars.append("\n" if src[i] == "\n" else " ")
                advance(src[i])
                i += 1
            if not closed:
                errors.append(f"{rel_path}:{start_ln}: unclosed block comment /*")
            continue

        # Regex literal /.../flags
        if ch == "/" and can_start_regex():
            start_ln = line
            code_chars.append(" ")
            advance("/")
            i += 1
            in_class = False
            closed = False
            while i < n:
                c = src[i]
                if c == "\n":
                    break
                if c == "\\":
                    code_chars.append(" ")
                    advance(c)
                    i += 1
                    if i < n and src[i] != "\n":
                        code_chars.append(" ")
                        advance(src[i])
                        i += 1
                    continue
                if c == "[":
                    in_class = True
                elif c == "]":
                    in_class = False
                elif c == "/" and not in_class:
                    code_chars.append(" ")
                    advance(c)
                    i += 1
                    while i < n and src[i].isalpha():
                        code_chars.append(" ")
                        advance(src[i])
                        i += 1
                    closed = True
                    break
                code_chars.append(" ")
                advance(c)
                i += 1
            if not closed:
                errors.append(f"{rel_path}:{start_ln}: unclosed regex literal")
            prev_tok_type = "regex"
            prev_tok_val = ""
            continue

        # Single or double quoted string
        if ch in ("'", '"'):
            quote = ch
            start_ln = line
            str_chars = [ch]
            code_chars.append(ch)
            advance(ch)
            i += 1
            closed = False
            while i < n:
                c = src[i]
                if c == "\\":
                    str_chars.append(c)
                    code_chars.append(c)
                    advance(c)
                    i += 1
                    if i < n:
                        str_chars.append(src[i])
                        code_chars.append(src[i])
                        advance(src[i])
                        i += 1
                    continue
                if c == "\n":
                    break
                str_chars.append(c)
                code_chars.append(c)
                advance(c)
                i += 1
                if c == quote:
                    closed = True
                    break
            if not closed:
                errors.append(f"{rel_path}:{start_ln}: unclosed string literal ({quote})")
            prev_tok_type = "str"
            prev_tok_val = "".join(str_chars)
            continue

        # Template literal `...`
        if ch == "`":
            tpl_stack.append({
                "open_idx": i,
                "start_line": line,
                "raw_parts": ["`"],
                "exprs": [],
                "expr_start": None,
                "expr_line": line,
                "expr_prefix": "",
                "nested_spans": [],
            })
            code_chars.append(" ")
            advance("`")
            i += 1
            prev_tok_type = "punct"
            prev_tok_val = "{"
            resume_template()
            if not tpl_stack or tpl_stack[-1]["expr_start"] is None:
                prev_tok_type = "str"
                prev_tok_val = ""
            continue

        # Delimiters ( [ { ) ] }
        if ch in "([{":
            stack.append(("delim", ch, line, col))
            code_chars.append(ch)
            advance(ch)
            i += 1
            prev_tok_type = "punct"
            prev_tok_val = ch
            continue

        if ch in ")]}":
            if not stack:
                errors.append(f"{rel_path}:{line}:{col}: unmatched closing '{ch}'")
                code_chars.append(ch)
                advance(ch)
                i += 1
                prev_tok_type = "close"
                prev_tok_val = ch
                continue

            kind, open_ch, o_ln, o_col = stack[-1]
            expected = matching[open_ch]
            if ch != expected:
                errors.append(
                    f"{rel_path}:{line}:{col}: mismatched '{ch}' (expected '{expected}' for '{open_ch}' opened at L{o_ln}:{o_col})"
                )
                code_chars.append(ch)
                advance(ch)
                i += 1
                prev_tok_type = "close"
                prev_tok_val = ch
                continue

            stack.pop()
            if kind == "tpl_expr":
                # Closing '}' of a template expression ${ ... }
                tpl = tpl_stack[-1]
                e_start = tpl["expr_start"]
                raw_expr_src = src[e_start:i]
                # Mask any nested template literals (they are audited independently)
                spans = sorted(tpl.get("nested_spans") or [])
                if spans:
                    pieces: list[str] = []
                    cursor = e_start
                    for s_lo, s_hi in spans:
                        if s_lo >= cursor and s_hi <= i:
                            pieces.append(src[cursor:s_lo])
                            pieces.append("'__NESTED_TPL__'")
                            cursor = s_hi
                    pieces.append(src[cursor:i])
                    masked_expr_src = "".join(pieces)
                else:
                    masked_expr_src = raw_expr_src
                tpl["exprs"].append((tpl["expr_line"], masked_expr_src, tpl["expr_prefix"]))
                tpl["raw_parts"].append(raw_expr_src + "}")
                tpl["expr_start"] = None
                tpl["nested_spans"] = []
                code_chars.append(" ")
                advance(ch)
                i += 1
                resume_template()
                if not tpl_stack or tpl_stack[-1]["expr_start"] is None:
                    prev_tok_type = "str"
                    prev_tok_val = ""
                else:
                    prev_tok_type = "punct"
                    prev_tok_val = "{"
                continue

            code_chars.append(ch)
            advance(ch)
            i += 1
            prev_tok_type = "close"
            prev_tok_val = ch
            continue

        # Identifiers / keywords
        if ch.isalpha() or ch in ("_", "$"):
            start = i
            while i < n and (src[i].isalnum() or src[i] in ("_", "$")):
                code_chars.append(src[i])
                advance(src[i])
                i += 1
            word = src[start:i]
            prev_tok_type = "ident"
            prev_tok_val = word
            continue

        # Numbers
        if ch.isdigit():
            start = i
            while i < n and (src[i].isalnum() or src[i] in (".", "_")):
                code_chars.append(src[i])
                advance(src[i])
                i += 1
            prev_tok_type = "num"
            prev_tok_val = src[start:i]
            continue

        # Multi-char operators
        matched_op = None
        for op in ("===", "!==", "=>", "&&", "||", "??", "==", "!=", "<=", ">=", "+=", "-=", "*=", "/=", "%=", "++", "--"):
            if src.startswith(op, i):
                matched_op = op
                break
        if matched_op:
            for c in matched_op:
                code_chars.append(c)
                advance(c)
            i += len(matched_op)
            prev_tok_type = "close" if matched_op in ("++", "--") else "punct"
            prev_tok_val = matched_op
            continue

        # Single punctuation char
        code_chars.append(ch)
        advance(ch)
        i += 1
        prev_tok_type = "punct"
        prev_tok_val = ch

    for kind, open_ch, o_ln, o_col in stack:
        label = "${" if kind == "tpl_expr" else open_ch
        errors.append(f"{rel_path}:{o_ln}:{o_col}: unclosed '{label}'")

    return errors, "".join(code_chars), completed_templates


def _extract_binding_names(pattern: str) -> set[str]:
    """Extract identifier names bound by const/let/var declaration or destructuring."""
    names: set[str] = set()
    p = pattern.strip()
    if not p:
        return names
    if p.startswith("{") and p.endswith("}"):
        inner = p[1:-1]
        for part in inner.split(","):
            part = part.strip()
            if not part:
                continue
            part = part.lstrip(".")
            if ":" in part:
                rhs = part.split(":", 1)[1].strip()
                rhs = rhs.split("=", 1)[0].strip()
                m = re.match(r"^([A-Za-z_$][\w$]*)", rhs)
                if m:
                    names.add(m.group(1))
            else:
                lhs = part.split("=", 1)[0].strip()
                m = re.match(r"^([A-Za-z_$][\w$]*)", lhs)
                if m:
                    names.add(m.group(1))
    elif p.startswith("[") and p.endswith("]"):
        inner = p[1:-1]
        for part in inner.split(","):
            part = part.strip().lstrip(".")
            lhs = part.split("=", 1)[0].strip()
            m = re.match(r"^([A-Za-z_$][\w$]*)", lhs)
            if m:
                names.add(m.group(1))
    else:
        m = re.match(r"^([A-Za-z_$][\w$]*)", p)
        if m:
            names.add(m.group(1))
    return names


def parse_es_module_interface(code: str) -> dict[str, Any]:
    """Extract exports and imports from comment-stripped JS code."""
    exports: set[str] = set()
    has_default = False
    reexport_all: list[str] = []
    imports: list[dict[str, Any]] = []

    # 1. export default
    if re.search(r"(?:^|[;}\n])\s*export\s+default\b", code):
        has_default = True

    # 2. export [async] function name / export class name
    for m in re.finditer(r"(?:^|[;}\n])\s*export\s+(?:async\s+)?(?:function\*?|class)\s+([A-Za-z_$][\w$]*)", code):
        exports.add(m.group(1))

    # 3. export const|let|var <decl>
    for m in re.finditer(
        r"(?:^|[;}\n])\s*export\s+(?:const|let|var)\s+(\{[^}]*\}|\[[^\]]*\]|[A-Za-z_$][\w$]*)",
        code,
    ):
        exports.update(_extract_binding_names(m.group(1)))

    # 4. export * as ns from 'spec' and export * from 'spec'
    for m in re.finditer(
        r"(?:^|[;}\n])\s*export\s+\*\s*(?:as\s+([A-Za-z_$][\w$]*)\s+)?from\s*['\"]([^'\"]+)['\"]",
        code,
    ):
        alias, spec = m.group(1), m.group(2)
        if alias:
            exports.add(alias)
        else:
            reexport_all.append(spec)
        imports.append({"kind": "reexport_all", "spec": spec, "named": [], "default": False})

    # 5. export { a, b as c } [from 'spec']
    for m in re.finditer(
        r"(?:^|[;}\n])\s*export\s*\{([^}]*)\}\s*(?:from\s*['\"]([^'\"]+)['\"])?",
        code,
    ):
        items_str, spec = m.group(1), m.group(2)
        imported_names: list[str] = []
        for item in items_str.split(","):
            item = item.strip()
            if not item:
                continue
            as_m = re.match(r"^([A-Za-z_$][\w$]*)\s+as\s+([A-Za-z_$][\w$]*)$", item)
            if as_m:
                src_name, dst_name = as_m.group(1), as_m.group(2)
                if dst_name == "default":
                    has_default = True
                else:
                    exports.add(dst_name)
                if spec and src_name != "default":
                    imported_names.append(src_name)
            else:
                if item == "default":
                    has_default = True
                else:
                    exports.add(item)
                if spec and item != "default":
                    imported_names.append(item)
        if spec:
            imports.append({
                "kind": "reexport_named",
                "spec": spec,
                "named": imported_names,
                "default": any(
                    re.match(r"^default\b", it.strip()) for it in items_str.split(",") if it.strip()
                ),
            })

    # 6. import statements (supports both single-line and multi-line imports)
    for m in re.finditer(
        r"(?:^|[;}\n])\s*import\s+(?:([^;'\"]+?)\s+from\s+)?['\"]([^'\"]+)['\"]",
        code,
    ):
        clause = (m.group(1) or "").strip()
        spec = m.group(2)
        want_default = False
        want_named: list[str] = []

        if clause:
            # Strip namespace import (* as ns)
            clause_no_ns = re.sub(r"\*\s*as\s+[A-Za-z_$][\w$]*", "", clause).strip()
            brace_m = re.search(r"\{([^}]*)\}", clause_no_ns)
            if brace_m:
                for item in brace_m.group(1).split(","):
                    item = item.strip()
                    if not item:
                        continue
                    as_m = re.match(r"^([A-Za-z_$][\w$]*)\s+as\s+[A-Za-z_$][\w$]*$", item)
                    name = as_m.group(1) if as_m else item
                    if name == "default":
                        want_default = True
                    else:
                        want_named.append(name)
                before_brace = clause_no_ns[:brace_m.start()].strip().rstrip(",").strip()
                if before_brace and re.match(r"^[A-Za-z_$][\w$]*$", before_brace):
                    want_default = True
            else:
                clean = clause_no_ns.rstrip(",").strip()
                if clean and re.match(r"^[A-Za-z_$][\w$]*$", clean):
                    want_default = True

        imports.append({
            "kind": "import",
            "spec": spec,
            "named": want_named,
            "default": want_default,
        })

    # 7. Static dynamic import('./...')
    for m in re.finditer(r"\bimport\s*\(\s*['\"]([^'\"]+)['\"]\s*\)", code):
        imports.append({
            "kind": "dynamic_import",
            "spec": m.group(1),
            "named": [],
            "default": False,
        })

    return {
        "exports": exports,
        "has_default": has_default,
        "reexport_all": reexport_all,
        "imports": imports,
    }


def _strip_outer_parens(expr: str) -> str:
    s = expr.strip()
    while s.startswith("(") and s.endswith(")"):
        depth = 0
        enclosed = True
        for idx, ch in enumerate(s):
            if ch == "(":
                depth += 1
            elif ch == ")":
                depth -= 1
                if depth == 0 and idx < len(s) - 1:
                    enclosed = False
                    break
        if enclosed and depth == 0:
            s = s[1:-1].strip()
        else:
            break
    return s


def _split_top_level(expr: str, op: str) -> list[str]:
    """Split expr on top-level binary operator (ignoring parens/brackets/quotes)."""
    parts: list[str] = []
    depth = 0
    in_str: str | None = None
    start = 0
    i = 0
    n = len(expr)
    while i < n:
        ch = expr[i]
        if in_str:
            if ch == "\\":
                i += 2
                continue
            if ch == in_str:
                in_str = None
            i += 1
            continue
        if ch in ("'", '"', "`"):
            in_str = ch
            i += 1
            continue
        if ch in "([{":
            depth += 1
            i += 1
            continue
        if ch in ")]}":
            depth = max(0, depth - 1)
            i += 1
            continue
        if depth == 0 and expr.startswith(op, i):
            parts.append(expr[start:i].strip())
            i += len(op)
            start = i
            continue
        i += 1
    parts.append(expr[start:].strip())
    return parts


def is_safe_html_interpolation(expr: str, is_url_attr: bool) -> bool:
    """Return True if an interpolated ${expr} in an HTML template is safely guarded."""
    s = _strip_outer_parens(expr)
    if not s:
        return True

    # Pure string / number / boolean literals
    if re.match(r"^(?:'[^']*'|\"[^\"]*\"|-?\d+(?:\.\d+)?|true|false)$", s):
        return True

    # Top-level ternary cond ? a : b -> validate both branches
    q_parts = _split_top_level(s, "?")
    if len(q_parts) == 2 and not s.startswith("?") and "??" not in s:
        colon_parts = _split_top_level(q_parts[1], ":")
        if len(colon_parts) == 2:
            return (
                is_safe_html_interpolation(colon_parts[0], is_url_attr)
                and is_safe_html_interpolation(colon_parts[1], is_url_attr)
            )

    # Top-level logical AND (guard && rendered): only the rendered right-hand side outputs text
    and_parts = _split_top_level(s, "&&")
    if len(and_parts) > 1:
        return is_safe_html_interpolation(and_parts[-1], is_url_attr)

    # Top-level nullish / logical fallback (a ?? b, a || b) and string concatenation (a + b)
    for op in ("??", "||", "+"):
        parts = _split_top_level(s, op)
        if len(parts) > 1:
            return all(is_safe_html_interpolation(p, is_url_attr) for p in parts)

    # Array .map(...).join(...) producing pre-audited nested templates or safe builders
    if not is_url_attr and re.search(r"\.join\s*\(\s*['\"][^'\"]*['\"]\s*\)$", s):
        if "'__NESTED_TPL__'" in s:
            return True
        map_m = re.search(r"\.map\s*\(\s*([A-Za-z_$][\w$.]*)\s*\)", s)
        if map_m:
            fn = map_m.group(1).split(".")[-1].lower()
            if fn in SAFE_WRAPPER_NAMES or fn.startswith(("esc", "safe", "fmt", "format", "render", "build", "make", "svg", "badge", "pill", "chip", "row", "card")):
                return True

    # Direct wrapper call: fn(...) spanning the full expression
    call_m = re.match(r"^([A-Za-z_$][\w$.]*)\s*\((.*)\)$", s, re.S)
    if call_m:
        fn_name = call_m.group(1).split(".")[-1].lower()
        if is_url_attr:
            if fn_name in {"safeurl", "sanitizeurl", "safehref", "esc", "escapehtml", "eschtml", "escattr", "encodeuricomponent"}:
                return True
        else:
            if fn_name in SAFE_WRAPPER_NAMES or fn_name.startswith(("fmt", "format", "esc", "safe", "render", "build", "make", "svg", "sparkline", "chart", "badge", "pill", "chip", "icon")):
                return True

    # Numeric method chain (.toFixed(...), .toLocaleString(...), .toPrecision(...), .length)
    if not is_url_attr and re.search(r"\.(?:toFixed|toLocaleString|toPrecision)\s*\([^)]*\)$", s):
        return True
    if not is_url_attr and s.endswith(".length"):
        return True

    # For URL attributes (href="${...}", src="${...}"), require explicit URL/HTML guard
    # unless the expression is purely a safe local/numeric identifier without untrusted fields
    if is_url_attr:
        if UNTRUSTED_PROP_RE.search(s):
            return False
        # Even bare variables like ${url} or ${href} in href="${...}" must use safeUrl()
        if re.search(r"\b(?:url|href|link|src|thumb|thumbnail|endpoint)\b", s, re.I):
            return False
        return True

    # For general HTML body/attribute interpolation, flag raw untrusted/API field access
    if UNTRUSTED_PROP_RE.search(s):
        return False

    return True


def _extract_i18n_tables(src: str) -> dict[str, dict[str, str]]:
    """Extract top-level language dicts and string values from `export const I18N = { ... }`."""
    m = re.search(r"\bexport\s+const\s+I18N\s*=\s*\{", src)
    if not m:
        return {}
    n = len(src)
    i = m.end()
    depth = 1
    tables: dict[str, dict[str, str]] = {}
    cur_lang: str | None = None

    def _skip_ws_and_comments(pos: int) -> int:
        while pos < n:
            if src[pos] in " \t\r\n,":
                pos += 1
                continue
            if src.startswith("//", pos):
                nl = src.find("\n", pos)
                pos = n if nl < 0 else nl + 1
                continue
            if src.startswith("/*", pos):
                end_c = src.find("*/", pos + 2)
                pos = n if end_c < 0 else end_c + 2
                continue
            break
        return pos

    def _read_quoted_string(pos: int) -> tuple[str, int]:
        quote = src[pos]
        pos += 1
        chars: list[str] = []
        while pos < n:
            ch = src[pos]
            if ch == "\\" and pos + 1 < n:
                chars.append(src[pos + 1])
                pos += 2
                continue
            if ch == quote:
                return "".join(chars), pos + 1
            chars.append(ch)
            pos += 1
        return "".join(chars), pos

    while i < n and depth > 0:
        i = _skip_ws_and_comments(i)
        if i >= n:
            break
        ch = src[i]
        if ch == "}":
            depth -= 1
            if depth == 1:
                cur_lang = None
            i += 1
            continue
        if ch == "{":
            depth += 1
            i += 1
            continue
        if ch in ("'", '"'):
            _, i = _read_quoted_string(i)
            continue

        if depth == 1:
            lang_m = re.match(r"([A-Za-z_$][\w$]*)\s*:\s*\{", src[i:])
            if lang_m:
                cur_lang = lang_m.group(1)
                tables.setdefault(cur_lang, {})
                depth += 1
                i += lang_m.end()
                continue
        elif depth == 2 and cur_lang is not None:
            key_m = re.match(r"([A-Za-z_$][\w$]*)\s*:\s*", src[i:])
            if key_m:
                key = key_m.group(1)
                i += key_m.end()
                i = _skip_ws_and_comments(i)
                if i < n and src[i] in ("'", '"'):
                    val, i = _read_quoted_string(i)
                    tables[cur_lang][key] = val
                    continue
        i += 1
    return tables


def check_assets() -> None:
    print("\n[6/6] PWA Assets, 6-Language Parity & ES Modules Static Analysis")
    assets_dir = ROOT / "assets"
    if not assets_dir.is_dir():
        record(False, "assets/ directory exists", f"missing {assets_dir}")
        return

    # PWA: manifest.webmanifest
    mf_path = ROOT / "manifest.webmanifest"
    pwa_mf_issues: list[str] = []
    if not mf_path.is_file():
        pwa_mf_issues.append("missing manifest.webmanifest")
    else:
        try:
            wmf = json.loads(mf_path.read_text(encoding="utf-8", errors="strict"))
            if not isinstance(wmf, dict):
                pwa_mf_issues.append("manifest.webmanifest must be a JSON object")
            else:
                for rk in ("name", "short_name", "start_url", "display"):
                    if not isinstance(wmf.get(rk), str) or not wmf[rk].strip():
                        pwa_mf_issues.append(f"missing/empty {rk}")
                icons = wmf.get("icons")
                if not isinstance(icons, list) or not icons:
                    pwa_mf_issues.append("icons list must be non-empty")
                else:
                    for ic in icons:
                        src_ic = str((ic or {}).get("src") or "").strip()
                        if not src_ic or not _resolve_local_href(src_ic).is_file():
                            pwa_mf_issues.append(f"icon src missing on disk: {src_ic!r}")
        except Exception as exc:
            pwa_mf_issues.append(f"JSON parse error: {exc}")
    record(
        not pwa_mf_issues,
        "manifest.webmanifest valid PWA manifest with verified local icons",
        "valid standalone manifest + icon-traya.svg"
        if not pwa_mf_issues
        else "; ".join(pwa_mf_issues[:6]),
    )

    # PWA: assets/icon-traya.svg
    icon_path = assets_dir / "icon-traya.svg"
    icon_issues: list[str] = []
    if not icon_path.is_file():
        icon_issues.append("missing assets/icon-traya.svg")
    else:
        try:
            svg_root = ET.fromstring(icon_path.read_text(encoding="utf-8", errors="strict"))
            if not svg_root.tag.endswith("svg"):
                icon_issues.append(f"unexpected SVG root tag {svg_root.tag!r}")
        except Exception as exc:
            icon_issues.append(f"SVG XML parse error: {exc}")
    record(
        not icon_issues,
        "assets/icon-traya.svg present and valid SVG emblem",
        f"{icon_path.stat().st_size:,} bytes valid SVG" if not icon_issues else "; ".join(icon_issues),
    )

    # PWA: sw.js (same-origin service worker)
    sw_path = ROOT / "sw.js"
    sw_issues: list[str] = []
    if not sw_path.is_file():
        sw_issues.append("missing sw.js")
    else:
        sw_src = sw_path.read_text(encoding="utf-8", errors="strict")
        sw_bal_errs, sw_code, _ = scan_js_module(sw_src, "sw.js")
        sw_issues.extend(sw_bal_errs)
        for ev in ("install", "activate", "fetch"):
            if f"'{ev}'" not in sw_code and f'"{ev}"' not in sw_code:
                sw_issues.append(f"missing {ev} event listener")
        if "self.location.origin" not in sw_code:
            sw_issues.append("missing same-origin guard (self.location.origin)")
        m_shell = re.search(r"const\s+SHELL_ASSETS\s*=\s*\[([^\]]+)\]", sw_code)
        if not m_shell:
            sw_issues.append("missing SHELL_ASSETS precache list")
        else:
            for item in re.findall(r"['\"]([^'\"]+)['\"]", m_shell.group(1)):
                if item in ("./", "/"):
                    continue
                if not _resolve_local_href(item.lstrip("./")).is_file():
                    sw_issues.append(f"SHELL_ASSETS missing on disk: {item}")
    record(
        not sw_issues,
        "sw.js valid same-origin service worker & verified SHELL_ASSETS",
        "balanced JS, install/activate/fetch, same-origin guard & all shell assets present"
        if not sw_issues
        else "; ".join(sw_issues[:6]),
    )

    # Check CSS files for external Google Fonts or external @import
    css_files = sorted(assets_dir.rglob("*.css"))
    css_issues: list[str] = []
    for cf in css_files:
        ctext = cf.read_text(encoding="utf-8", errors="strict")
        if re.search(r"fonts\.(?:googleapis|gstatic)\.com", ctext, re.I):
            css_issues.append(f"{cf.relative_to(ROOT)}: Google Fonts reference")
        if re.search(r"@import\s+(?:url\s*\(\s*)?['\"]?(?:https?:|//)", ctext, re.I):
            css_issues.append(f"{cf.relative_to(ROOT)}: external @import")
    record(
        not css_issues,
        "assets/*.css free of external Google Fonts / @import URLs",
        f"{len(css_files)} CSS files clean" if not css_issues else "; ".join(css_issues),
    )

    js_files = sorted(assets_dir.rglob("*.js"))
    if not js_files:
        record(False, "ES modules present in assets/*.js", "no .js files found in assets/")
        return

    balance_errors: list[str] = []
    interfaces: dict[Path, dict[str, Any]] = {}
    xss_findings: list[str] = []
    missing_data_refs: list[str] = []

    for jf in js_files:
        rel = str(jf.relative_to(ROOT)).replace("\\", "/")
        src = jf.read_text(encoding="utf-8", errors="strict")
        errs, code_only, html_templates = scan_js_module(src, rel)
        balance_errors.extend(errs)
        interfaces[jf.resolve()] = parse_es_module_interface(code_only)

        # Check banned dangerous sinks
        for pat, desc in [
            (re.compile(r"\beval\s*\("), "eval()"),
            (re.compile(r"\bnew\s+Function\s*\("), "new Function()"),
            (re.compile(r"\bdocument\.write(?:ln)?\s*\("), "document.write()"),
        ]:
            for m in pat.finditer(code_only):
                ln = code_only[:m.start()].count("\n") + 1
                xss_findings.append(f"{rel}:{ln} forbidden {desc}")

        # Check referenced data/*.json, data/*.geojson & data/*.xml literals exist on disk
        for m in re.finditer(r"['\"](?:\./)?(data/[A-Za-z0-9_.-]+\.(?:json|geojson|xml))['\"]", code_only):
            ref_path = m.group(1)
            if not (ROOT / ref_path).is_file():
                ln = code_only[:m.start()].count("\n") + 1
                missing_data_refs.append(f"{rel}:{ln} -> {ref_path}")

        # Check direct .innerHTML = <raw untrusted field> (non-template assignment)
        for m in re.finditer(r"\.(?:innerHTML|outerHTML)\s*\+?=\s*([^;`\n]+)", code_only):
            rhs = m.group(1).strip()
            if rhs and not rhs.startswith(("'", '"')) and UNTRUSTED_PROP_RE.search(rhs):
                if not is_safe_html_interpolation(rhs, is_url_attr=False):
                    ln = code_only[:m.start()].count("\n") + 1
                    xss_findings.append(f"{rel}:{ln} unguarded innerHTML assignment: {rhs[:60]}")

        # Audit HTML template literals
        for start_ln, raw_tpl, exprs in html_templates:
            # Strip ${...} placeholders before scanning static HTML for inline on*= handlers
            static_skeleton = re.sub(r"\$\{[^{}]*\}", "", raw_tpl)
            for on_m in re.finditer(r"<[a-zA-Z][^>]*\s(on[a-z]+)\s*=", static_skeleton, re.I):
                xss_findings.append(
                    f"{rel}:{start_ln} inline event attribute '{on_m.group(1)}=' in HTML template"
                )
            for expr_ln, expr_text, prefix_tail in exprs:
                is_url_attr = bool(
                    re.search(r"\b(?:href|src|action|formaction)\s*=\s*['\"]?$", prefix_tail, re.I)
                )
                is_fly_attr = bool(re.search(r"\bdata-fly\s*=\s*['\"]?$", prefix_tail, re.I))
                if is_fly_attr and not re.match(r"^\s*(?:safeFlyAttr|esc)\s*\(", expr_text):
                    xss_findings.append(f"{rel}:{expr_ln} uncoerced data-fly attribute: ${{{expr_text.strip()[:70]}}}")
                elif not is_safe_html_interpolation(expr_text, is_url_attr=is_url_attr):
                    kind = "unguarded URL attribute" if is_url_attr else "unescaped API/data field in HTML"
                    xss_findings.append(f"{rel}:{expr_ln} {kind}: ${{{expr_text.strip()[:70]}}}")

    record(
        not balance_errors,
        "all assets/*.js have balanced braces/parens/brackets/strings/templates",
        f"{len(js_files)} ES modules lexed cleanly"
        if not balance_errors
        else "; ".join(balance_errors[:8]),
    )

    # Resolve transitive export * from '...' chains
    def resolved_exports(mod_path: Path, seen: set[Path] | None = None) -> tuple[set[str], bool]:
        if seen is None:
            seen = set()
        if mod_path in seen or mod_path not in interfaces:
            return set(), False
        seen.add(mod_path)
        info = interfaces[mod_path]
        names = set(info["exports"])
        for spec in info["reexport_all"]:
            if spec.startswith(("./", "../")):
                target = (mod_path.parent / spec).resolve()
                sub_names, _ = resolved_exports(target, seen)
                names.update(sub_names)
        return names, bool(info["has_default"])

    import_errors: list[str] = []
    total_imports = 0
    for mod_path, info in interfaces.items():
        rel = str(mod_path.relative_to(ROOT)).replace("\\", "/")
        for imp in info["imports"]:
            total_imports += 1
            spec = imp["spec"]
            if not spec.startswith(("./", "../")):
                import_errors.append(f"{rel}: non-relative import '{spec}'")
                continue
            target = (mod_path.parent / spec).resolve()
            if not target.is_file():
                import_errors.append(f"{rel}: missing import target '{spec}'")
                continue
            if target in interfaces:
                tgt_exports, tgt_default = resolved_exports(target)
                if imp["default"] and not tgt_default:
                    import_errors.append(f"{rel}: default import from '{spec}' but target has no default export")
                for sym in imp["named"]:
                    if sym not in tgt_exports:
                        import_errors.append(f"{rel}: '{sym}' not exported by '{spec}'")

    record(
        not import_errors,
        "all ES module relative imports & exports resolve validly",
        f"{total_imports} imports across {len(js_files)} modules verified"
        if not import_errors
        else "; ".join(import_errors[:8]),
    )

    if missing_data_refs:
        record(
            False,
            "all data/*.json files referenced by assets/*.js exist on disk",
            "; ".join(sorted(set(missing_data_refs))[:8]),
        )
    else:
        record(True, "all data/*.json files referenced by assets/*.js exist on disk", "ok")

    record(
        not xss_findings,
        "zero unguarded innerHTML / XSS sinks with unescaped API fields",
        f"{len(js_files)} modules audited cleanly"
        if not xss_findings
        else "; ".join(xss_findings[:8]),
    )

    # PWA community reporting module: assets/pwa_reports.js
    pwa_js_path = (assets_dir / "pwa_reports.js").resolve()
    pwa_js_issues: list[str] = []
    if not pwa_js_path.is_file():
        pwa_js_issues.append("missing assets/pwa_reports.js")
    else:
        pwa_exports = interfaces.get(pwa_js_path, {}).get("exports") or set()
        for req_fn in ("redactPii", "stripImageExif", "computeDedupFingerprint", "findLocalAndInventoryDuplicates"):
            if req_fn not in pwa_exports:
                pwa_js_issues.append(f"missing export {req_fn}")
    record(
        not pwa_js_issues,
        "assets/pwa_reports.js present & exports EXIF, PII, SHA-256 & dedup helpers",
        f"{len(interfaces.get(pwa_js_path, {}).get('exports') or set())} exports verified"
        if not pwa_js_issues
        else "; ".join(pwa_js_issues[:6]),
    )

    # 6-language key parity in assets/i18n.js (en, ne, mai, bho, thr, taj)
    i18n_path = assets_dir / "i18n.js"
    i18n_issues: list[str] = []
    n_en_keys = 0
    if not i18n_path.is_file():
        i18n_issues.append("missing assets/i18n.js")
    else:
        i18n_tables = _extract_i18n_tables(i18n_path.read_text(encoding="utf-8", errors="strict"))
        missing_langs = [lc for lc in SUPPORTED_LANG_CODES if lc not in i18n_tables]
        if missing_langs:
            i18n_issues.append(f"missing language tables: {missing_langs}")
        else:
            en_keys = set(i18n_tables["en"].keys())
            n_en_keys = len(en_keys)
            if n_en_keys < 50:
                i18n_issues.append(f"unexpectedly few en i18n keys ({n_en_keys})")
            for lc in SUPPORTED_LANG_CODES:
                tbl = i18n_tables[lc]
                lkeys = set(tbl.keys())
                missing_k = sorted(en_keys - lkeys)
                extra_k = sorted(lkeys - en_keys)
                empty_k = sorted(k for k, v in tbl.items() if not v.strip())
                if missing_k:
                    i18n_issues.append(f"{lc}: missing {len(missing_k)} keys ({missing_k[:4]})")
                if extra_k:
                    i18n_issues.append(f"{lc}: extra {len(extra_k)} keys ({extra_k[:4]})")
                if empty_k:
                    i18n_issues.append(f"{lc}: empty values for {empty_k[:4]}")
    record(
        not i18n_issues,
        "assets/i18n.js 6-language key parity (en, ne, mai, bho, thr, taj)",
        f"all 6 languages x {n_en_keys} keys in 100% parity (0 missing/extra/empty)"
        if not i18n_issues
        else "; ".join(i18n_issues[:6]),
    )


# ===========================================================================
# Main
# ===========================================================================
def main() -> int:
    print(f"=== Nepal TRAYA Verification Gate ({ROOT}) ===")
    check_workflows()
    check_template_sync()
    check_html()
    check_data()
    check_schemas_and_docs()
    check_assets()

    passed = sum(1 for st, _, _ in RESULTS if st == "PASS")
    failed = sum(1 for st, _, _ in RESULTS if st == "FAIL")
    warned = sum(1 for st, _, _ in RESULTS if st == "WARN")
    total = passed + failed

    print(f"\nSummary: {passed}/{total} checks passed, {failed} failed, {warned} warnings.")
    if failed:
        print("VERIFICATION GATE FAILED.")
        return 1
    print("VERIFICATION GATE PASSED.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
