"""
Institutional adapter stub for the Department of Hydrology and Meteorology (DHM),
Government of Nepal (https://hydrology.gov.np).

Status: UNAVAILABLE (direct institutional feed requires a formal data-sharing
agreement with DHM; see `docs/INSTITUTIONAL_INTEGRATION_SPEC.md`).

BIPAD Relay Availability:
  Partial public DHM real-time river-level telemetry, rain-gauge 1h/3h/6h/12h/24h
  accumulations, and official DHM flood/weather alerts ARE relayed via the
  NDRRMA BIPAD Portal public API (`src/integrations/bipad.py`, endpoints
  `/api/v1/alert/`, `/api/v1/river/`, `/api/v1/rain/`). Direct DHM integration
  remains stubbed here for future high-frequency 15-minute telemetric station
  series, stage-discharge rating curves, weather radar mosaics, and statutory
  CAP-v1.2 alert feeds.

Pure Python 3.12 standard library only (zero third-party dependencies).
"""
from __future__ import annotations

from typing import Any

from .provenance import make_envelope, utc_now_iso

AGENCY = "Department of Hydrology and Meteorology (DHM), Government of Nepal"
DATASET = "dhm_direct_hydrology_meteorology_api"
STATUS = "unavailable"
DATA_CLASS = "unavailable"
REQUIRES_INSTITUTIONAL_AGREEMENT = True
SPEC_REF = "docs/INSTITUTIONAL_INTEGRATION_SPEC.md"
OFFICIAL_PORTAL = "https://hydrology.gov.np"
LICENSE_REF = "Government of Nepal / DHM Institutional Data Sharing Agreement Required"
SLA_HOURS = 24

BIPAD_RELAY_AVAILABLE = True
BIPAD_RELAY_MODULE = "src/integrations/bipad.py"
BIPAD_RELAY_ENDPOINTS: tuple[str, ...] = (
    "/api/v1/alert/",
    "/api/v1/river/",
    "/api/v1/rain/",
)

EXPECTED_DATASETS: tuple[str, ...] = (
    "15-minute telemetric river stage and discharge observations",
    "Hourly Automated Weather Station (AWS) rainfall and air-temperature series",
    "Stage-discharge rating curves and official station warning/danger thresholds",
    "DHM CAP-v1.2 statutory flood and severe weather bulletins",
    "Surkhet / Palpa / Udayapur Doppler weather radar mosaics",
)


def get_adapter_spec() -> dict[str, Any]:
    """Return static institutional onboarding metadata for DHM direct integration."""
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
    """Return canonical unavailable ProvenanceEnvelope for direct DHM integration."""
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
            "Public DHM river, rain-gauge, and alert relays are available via "
            "src/integrations/bipad.py (NDRRMA BIPAD Portal)."
        ),
        requires_institutional_agreement=True,
    )


def fetch_dhm_telemetry(offline: bool = True, **_: Any) -> dict[str, Any]:
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
