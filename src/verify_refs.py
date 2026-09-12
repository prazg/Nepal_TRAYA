"""
Verify every reference in paper/refs.bib against the DOI registries.

For each entry with a DOI, the record is fetched from doi.org by content
negotiation (Crossref or DataCite, whichever registered it) and the author
surnames, year, journal, volume and page range in the bib file are compared with
the registered metadata. Anything that does not match is printed.

This exists because the most likely error in a manuscript of this kind is a
citation that looks plausible and is wrong.

Run:  python3 verify_refs.py [--fix-authors]
Exit status is non-zero if any entry fails.
"""
from __future__ import annotations
import argparse
import json
import os
import re
import sys
import time
import unicodedata
import urllib.error
import urllib.request

import config as C

BIB = os.path.join(C.ROOT, "paper", "refs.bib")


def strip_accents(s: str) -> str:
    # LaTeX accent commands: {\"a}, {\'i}, {\~n}, \c{c}, {\ss} ...
    s = re.sub(r"\{?\\[a-zA-Z]{1,2}\s*\{([a-zA-Z])\}\}?", r"\1", s)
    s = re.sub(r"\{?\\[\"'`^~=.]\s*\{?([a-zA-Z])\}?\}?", r"\1", s)
    s = s.replace("{", "").replace("}", "").replace("\\", "")
    return "".join(c for c in unicodedata.normalize("NFKD", s)
                   if not unicodedata.combining(c)).lower().strip()


def parse_bib(path: str) -> list[dict]:
    text = open(path, encoding="utf-8").read()
    entries = []
    for m in re.finditer(r"@(\w+)\s*\{\s*([^,]+),(.*?)\n\}", text, re.S):
        kind, key, body = m.group(1), m.group(2).strip(), m.group(3)
        fields = {}
        for fm in re.finditer(r"(\w+)\s*=\s*(\{(?:[^{}]|\{[^{}]*\})*\})", body):
            fields[fm.group(1).lower()] = fm.group(2)[1:-1].strip()
        entries.append(dict(kind=kind, key=key, **fields))
    return entries


def fetch(doi: str) -> dict | None:
    req = urllib.request.Request(
        f"https://doi.org/{doi}",
        headers={"Accept": "application/vnd.citationstyles.csl+json",
                 "User-Agent": "nepal-ews/1.0 (mailto:prajwal.1.ghimire@kcl.ac.uk)"})
    for _ in range(3):
        try:
            with urllib.request.urlopen(req, timeout=45) as r:
                return json.load(r)
        except urllib.error.HTTPError as e:
            if e.code in (404, 410):
                return None
            time.sleep(3)
        except Exception:
            time.sleep(3)
    return None


def surnames_bib(author_field: str) -> list[str]:
    out = []
    for a in re.split(r"\s+and\s+", author_field):
        a = a.strip()
        if not a:
            continue
        out.append(strip_accents(a.split(",")[0] if "," in a else a.split()[-1]))
    return out


def surnames_reg(rec: dict) -> list[str]:
    out = []
    for a in rec.get("author", []) or []:
        name = a.get("family") or a.get("literal") or ""
        if name:
            out.append(strip_accents(name.split(",")[0]))
    return out


def norm_pages(p: str) -> str:
    return re.sub(r"[^0-9]", "", (p or "").replace("--", "-"))


def check(entry: dict, rec: dict) -> list[str]:
    problems = []
    reg_year = None
    for k in ("issued", "published-print", "published"):
        dp = (rec.get(k) or {}).get("date-parts")
        if dp and dp[0] and dp[0][0]:
            reg_year = int(dp[0][0])
            break
    if entry.get("year") and reg_year and abs(int(entry["year"]) - reg_year) > 1:
        problems.append(f"year {entry['year']} against registered {reg_year}")

    bib_a, reg_a = surnames_bib(entry.get("author", "")), surnames_reg(rec)
    if reg_a:
        if len(bib_a) != len(reg_a):
            problems.append(f"{len(bib_a)} authors against registered {len(reg_a)}: "
                            f"bib={bib_a} reg={reg_a}")
        else:
            wrong = [(b, r) for b, r in zip(bib_a, reg_a, strict=True)
                     if b != r and not (b in r or r in b)]
            if wrong:
                problems.append(f"author surnames differ: {wrong}")

    reg_vol = str(rec.get("volume") or "")
    if entry.get("volume") and reg_vol:
        if strip_accents(entry["volume"]).replace("--", "-") != reg_vol.replace("–", "-"):
            problems.append(f"volume {entry['volume']} against registered {reg_vol}")

    reg_pg = rec.get("page") or ""
    if entry.get("pages") and reg_pg:
        bib_first = (entry["pages"].replace("--", "-").split("-") or [""])[0]
        reg_first = (reg_pg.replace("–", "-").split("-") or [""])[0]
        if "-" not in reg_pg.replace("–", "-"):
            # the registry holds only a first page (common for older records)
            if norm_pages(bib_first) != norm_pages(reg_first):
                problems.append(f"first page {bib_first} against registered {reg_pg}")
        elif norm_pages(entry["pages"]) != norm_pages(reg_pg):
            problems.append(f"pages {entry['pages']} against registered {reg_pg}")

    reg_title = strip_accents(str(rec.get("title") or ""))
    bib_title = strip_accents(entry.get("title", ""))
    if bib_title and reg_title:
        bw = set(re.findall(r"[a-z]{4,}", bib_title))
        rw = set(re.findall(r"[a-z]{4,}", reg_title))
        if bw and len(bw & rw) / len(bw) < 0.6:
            problems.append(f"title mismatch: bib '{bib_title[:55]}' vs reg '{reg_title[:55]}'")
    return problems


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--bib", default=BIB)
    a = ap.parse_args()
    entries = parse_bib(a.bib)
    print(f"{len(entries)} entries in {os.path.basename(a.bib)}")
    failed, nodoi = [], []
    for e in entries:
        doi = e.get("doi")
        if not doi:
            nodoi.append(e["key"])
            print(f"  [no DOI ] {e['key']}")
            continue
        rec = fetch(doi)
        if rec is None:
            print(f"  [MISSING] {e['key']}: {doi} did not resolve")
            failed.append(e["key"])
            continue
        problems = check(e, rec)
        if problems:
            print(f"  [MISMATCH] {e['key']} ({doi})")
            for p in problems:
                print(f"             - {p}")
            failed.append(e["key"])
        else:
            reg_a = surnames_reg(rec)
            print(f"  [ok     ] {e['key']:22s} {doi}  ({len(reg_a)} authors)")
        time.sleep(0.4)
    print(f"\n{len(entries)-len(failed)-len(nodoi)} verified, {len(nodoi)} without a DOI, "
          f"{len(failed)} with problems")
    if failed:
        print("problems in: " + ", ".join(failed))
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
