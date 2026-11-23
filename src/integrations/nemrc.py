"""
Institutional adapter stub for the National Earthquake Monitoring and Research
Center (NEMRC / NSC), Department of Mines and Geology (DMG), Government of Nepal
(https://seismonepal.gov.np).

Status: UNAVAILABLE (direct low-latency local seismic network integration
requires a formal institutional agreement with DMG/NEMRC; see
`docs/INSTITUTIONAL_INTEGRATION_SPEC.md`).

BIPAD Relay & Open Fallback Availability:
  * Official NSC/NEMRC local-magnitude (ML >= 4.0) Nepal earthquake bulletins
    are publicly relayed via the NDRRMA BIPAD Portal API
    (`src/integrations/bipad.py`, endpoint `/api/v1/earthquake/`).
  * Global teleseismic M >= 2.5 recent events, M >= 4.0 historical catalogue,
    ShakeMap MMI, and Ground Failure products are integrated via USGS FDSN
    (`src/integrations/usgs.py`).
  * Direct NEMRC integration remains stubbed here for future ML < 4.0
    microseismicity, local strong-motion accelerograph (PGA/PGV) records, and
    low-latency local epicentral solutions.

Pure Python 3.12 standard library only (zero third-party dependencies).
"""
from __future__ import annotations

from typing import Any

from .provenance import make_envelope, utc_now_iso

AGENCY = "National Earthquake Monitoring and Research Center (NEMRC / NSC), DMG, Government of Nepal"
DATASET = "nemrc_direct_local_seismic_network_api"
STATUS = "unavailable"
DATA_CLASS = "unavailable"
REQUIRES_INSTITUTIONAL_AGREEMENT = True
SPEC_REF = "docs/INSTITUTIONAL_INTEGRATION_SPEC.md"
OFFICIAL_PORTAL = "https://seismonepal.gov.np"
LICENSE_REF = "Government of Nepal / DMG-NEMRC Institutional Data Sharing Agreement Required"
SLA_HOURS = 24

BIPAD_RELAY_AVAILABLE = True
BIPAD_RELAY_MODULE = "src/integrations/bipad.py"
BIPAD_RELAY_ENDPOINTS: tuple[str, ...] = ("/api/v1/earthquake/",)

EXPECTED_DATASETS: tuple[str, ...] = (
    "Low-latency local-magnitude (ML) Nepal seismic bulletins including ML < 4.0 microseismicity",
    "Strong-motion accelerograph PGA/PGV station observations",
    "Local Himalayan focal mechanism and aftershock sequence bulletins",
    "Authoritative NEMRC CAP / QuakeML seismic event feeds",
)


def get_adapter_spec() -> dict[str, Any]:
    """Return static institutional onboarding metadata for NEMRC direct integration."""
    return {
        "agency": AGENCY,
        "dataset": DATASET,
        "status": STATUS,
        "data_class": DATA_CLASS,
        "requires_institutional_agreement": REQUIRES_INSTITUTIONAL_AGREEMENT,
        "spec_ref": SPEC_REF,
        "official_portal": OFFICIAL_PORTAL,
        "bipad_relay_available": BIPAD_RELAY_AVAILABLE,
        "bipad_relay_module": BIPAD_RELAY_MODULE,
        "bipad_relay_endpoints": list(BIPAD_RELAY_ENDPOINTS),
        "expected_datasets": list(EXPECTED_DATASETS),
    }


def get_provenance(retrieved_at_utc: str | None = None) -> dict[str, Any]:
    """Return canonical unavailable ProvenanceEnvelope for direct NEMRC integration."""
    return make_envelope(
        source=AGENCY,
        dataset=DATASET,
        data_class=DATA_CLASS,
        retrieved_at_utc=retrieved_at_utc or utc_now_iso(),
        observation_time_utc=None,
        valid_until_utc=None,
        status=STATUS,
        fallback_used=False,
        license_ref=LICENSE_REF,
        sla_hours=SLA_HOURS,
        record_count=0,
        notes=(
            f"Institutional stub (requires_institutional_agreement=True; see {SPEC_REF}). "
            "Official NSC/NEMRC ML>=4.0 earthquake bulletins are partially relayed via "
            "src/integrations/bipad.py (/api/v1/earthquake/), complemented by USGS FDSN "
            "in src/integrations/usgs.py."
        ),
        requires_institutional_agreement=True,
    )


def fetch_nemrc_seismicity(offline: bool = True, **_: Any) -> dict[str, Any]:
    """Stub entry point returning a standardized unavailable institutional response."""
    _ = offline
    env = get_provenance()
    return {
        "provenance": env,
        "status": STATUS,
        "data_class": DATA_CLASS,
        "requires_institutional_agreement": REQUIRES_INSTITUTIONAL_AGREEMENT,
        "spec_ref": SPEC_REF,
        "official_portal": OFFICIAL_PORTAL,
        "bipad_relay_available": BIPAD_RELAY_AVAILABLE,
        "bipad_relay_module": BIPAD_RELAY_MODULE,
        "bipad_relay_endpoints": list(BIPAD_RELAY_ENDPOINTS),
        "expected_datasets": list(EXPECTED_DATASETS),
        "records": [],
    }
