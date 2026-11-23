# Security Policy

## Supported Versions

**Nepal TRĀYA** is deployed continuously from the `main` branch to GitHub Pages
(`https://prazg.github.io/Nepal_TRAYA/`). Security fixes are applied directly to
`main`.

| Branch / Version | Supported |
| --- | --- |
| `main` (live GitHub Pages deployment) | Yes |
| Older commits / archived forks | No |

## Reporting a Vulnerability

If you discover a security vulnerability in Nepal TRĀYA — including cross-site
scripting (XSS) in live API renderers, Content-Security-Policy (CSP) bypasses,
unsafe URL handling, dependency/supply-chain flaws, or GitHub Actions workflow
misconfigurations — please report it **privately** rather than opening a public
GitHub issue.

### Preferred Channels

1. **GitHub Security Advisories (Recommended):**
   Submit a private vulnerability report directly through the repository's
   [GitHub Security Advisories](https://github.com/prazg/Nepal_TRAYA/security/advisories/new)
   portal.
2. **Direct Email:**
   Email **Prajwal Ghimire** at `prajwal.ghimire@crick.ac.uk` with the subject
   line `[SECURITY] Nepal_TRAYA: <brief summary>`.

### What to Include

- A clear description of the vulnerability and affected file(s), endpoint(s), or
  workflow(s).
- Steps to reproduce or a minimal proof-of-concept (without targeting third-party
  upstream APIs such as USGS, Open-Meteo, Element84 STAC, or GDACS).
- Any suggested remediation or patch, if available.

## Response Timeline & Disclosure Process

- **Acknowledgement:** Within **72 hours** (3 business days).
- **Initial Triage & Severity Assessment:** Within **7 calendar days**.
- **Remediation & Verification:** Validated fixes are verified through the
  automated pre-deploy gate (`python src/verify_site.py`) and pure-stdlib unit
  tests (`python src/test_pipeline.py --unit-only`) prior to deployment on
  `main`.
- **Coordinated Disclosure:** Once a fix is deployed, reporters will be credited
  in the advisory/release notes upon request.

## Security Controls in This Repository

- **Static-only frontend:** Hosted on GitHub Pages with no server-side secrets,
  no user accounts, and zero third-party JavaScript or font CDNs (Leaflet 1.9.4
  is vendored under `vendor/leaflet/`).
- **Browser hardening:** Strict `<meta http-equiv="Content-Security-Policy">`
  (no `'unsafe-inline'` scripts, no `'unsafe-eval'`),
  `<meta name="referrer" content="no-referrer">`, zero inline `<script>`,
  `<style>`, or `on*=` attributes, and explicit HTML escaping + URL-scheme
  validation for external API payloads.
- **Automated CI verification gate:** Every deployment runs
  `python src/verify_site.py` to enforce CSP, HTML/template synchronisation,
  Node 24-native workflows, data hygiene, and ES module static XSS checks.
- **Least-privilege CI/CD:** GitHub Actions workflows scope `contents: write`
  strictly to the scheduled data-refresh job and `pages: write` /
  `id-token: write` strictly to the Pages deployment job.

## Non-Security Issues & Operational Emergencies

- For scientific bugs, data anomalies, or stale upstream feeds, please open a
  standard [GitHub Issue](https://github.com/prazg/Nepal_TRAYA/issues).
- **Nepal TRĀYA is NOT an operational early warning system.** For real-time
  emergencies in Nepal, contact official statutory services directly:
  **Police `100`**, **Ambulance `102`**, **Armed Police Force `1114`**,
  **NDRRMA / NEOC `1149`** ([bipadportal.gov.np](https://bipadportal.gov.np/)),
  **DHM Flood Hotline `1155`** ([hydrology.gov.np](https://hydrology.gov.np/)),
  and **DMG / NEMRC** ([seismonepal.gov.np](https://seismonepal.gov.np/)).
