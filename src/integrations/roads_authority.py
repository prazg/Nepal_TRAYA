"""
Institutional adapter stub for the Department of Roads (DoR), Ministry of
Physical Infrastructure and Transport, Government of Nepal (https://dor.gov.np).

Status: UNAVAILABLE (authoritative Strategic Road Network / SSRN real-time
highway blockage, reopening, and bridge structural-status feeds require a
formal institutional agreement with DoR; see
`docs/INSTITUTIONAL_INTEGRATION_SPEC.md`).

BIPAD Relay Availability:
  No structured live highway-closure / detour status endpoint is currently
  exposed via the public BIPAD Portal API (`bipad_relay_available = False`).
  Post-event counts of damaged roads and bridges occasionally appear inside
  BIPAD incident loss records (`src/integrations/bipad.py`, `/api/v1/incident/`),
  and static OpenStreetMap bridge/road-corridor inventories are loaded via
  `src/integrations/osm.py`.

Pure Python 3.12 standard library only (zero third-party dependencies).
"""
from __future__ import annotations

from typing import Any

from .provenance import make_envelope, utc_now_iso

AGENCY = "Department of Roads (DoR), Ministry of Physical Infrastructure and Transport, Government of Nepal"
DATASET = "dor_ssrn_highway_closures_and_bridges_api"
STATUS = "unavailable"
DATA_CLASS = "unavailable"
REQUIRES_INSTITUTIONAL_AGREEMENT = True
SPEC_REF = "docs/INSTITUTIONAL_INTEGRATION_SPEC.md"
OFFICIAL_PORTAL = "https://dor.gov.np"
LICENSE_REF = "Government of Nepal / DoR Institutional Data Sharing Agreement Required"
SLA_HOURS = 24

BIPAD_RELAY_AVAILABLE = False
BIPAD_RELAY_NOTE = (
    "No structured real-time DoR highway-status API is exposed on BIPAD; "
    "post-event road/bridge damage counts are partially captured in BIPAD "
    "incident loss records (src/integrations/bipad.py)."
)

EXPECTED_DATASETS: tuple[str, ...] = (
    "Strategic Road Network (SSRN) monsoon landslide/flood blockage & one-way status feed",
    "Authoritative highway bridge inventory, span clearance, and scour-vulnerability ratings",
    "Validated emergency diversion corridors and heavy-equipment staging depots",
    "Estimated clearance / reopening timestamps for blocked Himalayan highway corridors",
)


def get_adapter_spec() -> dict[str, Any]:
    """Return static institutional onboarding metadata for DoR road-closure integration."""
    return {
        "agency": AGENCY,
        "dataset": DATASET,
        "status": STATUS,
        "data_class": DATA_CLASS,
        "requires_institutional_agreement": REQUIRES_INSTITUTIONAL_AGREEMENT,
        "spec_ref": SPEC_REF,
        "official_portal": OFFICIAL_PORTAL,
        "bipad_relay_available": BIPAD_RELAY_AVAILABLE,
        "bipad_relay_note": BIPAD_RELAY_NOTE,
        "expected_datasets": list(EXPECTED_DATASETS),
    }


def get_provenance(retrieved_at_utc: str | None = None) -> dict[str, Any]:
    """Return canonical unavailable ProvenanceEnvelope for DoR road-closure integration."""
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
            f"{BIPAD_RELAY_NOTE}"
        ),
        requires_institutional_agreement=True,
    )


def fetch_road_closures(offline: bool = True, **_: Any) -> dict[str, Any]:
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
        "bipad_relay_note": BIPAD_RELAY_NOTE,
        "expected_datasets": list(EXPECTED_DATASETS),
        "records": [],
    }
