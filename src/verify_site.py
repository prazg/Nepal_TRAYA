#!/usr/bin/env python3
"""
Nepal TRAYA — Automated CI & Local Pre-Deploy Verification Gate.

Pure Python 3.12 standard library ONLY (zero third-party dependencies).
Runs in < 2 seconds locally and in GitHub Actions (pages.yml & weekly-refresh.yml).

Verifies:
  1. GitHub Actions workflow hardening (zero Node 20 actions, safe concurrency,
     pre-deploy verification, .nojekyll, full asset/data/vendor staging).
  2. Byte-for-byte identity between index.html and src/template.html.
  3. HTML security & CSP compliance (Content-Security-Policy, no-referrer,
     zero inline <script>/<style>/on*= attributes, zero Google Fonts or
     external third-party <script>/<link> loads, local asset resolution).
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
    "routes.json",
    "exposure.json",
    "eq_history_m6.json",
    "glof_history.json",
    "faults.json",
    "rivers_watch.json",
    "landslides.json",
    "hydromet_weekly.json",
    "gdacs_alerts.json",
    "validation.json",
    "districts.json",
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
    print("\n[1/5] GitHub Actions Workflows (Node 24 & Hardening)")
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
    print("\n[2/5] HTML Template Synchronisation")
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
    print("\n[3/5] HTML Security, CSP, Emergency Hotlines & Suite Links")
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

    # Referrer policy
    record(
        "no-referrer" in audit.referrer_values,
        "<meta name='referrer' content='no-referrer'> present",
        f"found {audit.referrer_values}" if audit.referrer_values else "missing",
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


def check_data() -> None:
    print("\n[4/5] Data JSON Payloads & Geographic/Text Hygiene")
    data_dir = ROOT / "data"
    if not data_dir.is_dir():
        record(False, "data/ directory exists", f"missing {data_dir}")
        return

    json_files = sorted(data_dir.glob("*.json"))
    parsed: dict[str, Any] = {}
    parse_errors: list[str] = []
    bagamati_hits: list[str] = []

    for jf in json_files:
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
        f"{len(parsed)} JSON files parsed"
        if (not parse_errors and not missing_req)
        else "; ".join(
            ([f"missing={missing_req}"] if missing_req else [])
            + ([f"parse_errors={parse_errors}"] if parse_errors else [])
        ),
    )

    has_core_prov_files = "lakes.json" in parsed and "districts.json" in parsed
    record(
        has_core_prov_files and not bagamati_hits,
        "canonical 'Bagmati Province' spelling (zero 'Bagamati' in data/*.json)",
        "clean across all data/*.json"
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


# ===========================================================================
# 5. ES Modules Static Analysis (Balance, Imports/Exports, XSS Sinks)
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


def check_assets() -> None:
    print("\n[5/5] ES Modules Static Analysis (Balance, Imports/Exports & XSS Audit)")
    assets_dir = ROOT / "assets"
    if not assets_dir.is_dir():
        record(False, "assets/ directory exists", f"missing {assets_dir}")
        return

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

        # Check referenced data/*.json literals exist on disk
        for m in re.finditer(r"['\"](?:\./)?(data/[A-Za-z0-9_.-]+\.json)['\"]", code_only):
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


# ===========================================================================
# Main
# ===========================================================================
def main() -> int:
    print(f"=== Nepal TRAYA Verification Gate ({ROOT}) ===")
    check_workflows()
    check_template_sync()
    check_html()
    check_data()
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
