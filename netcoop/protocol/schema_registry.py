"""NetCoop AI Protocol - Schema Registry.

Supports schema versions "0.9" (legacy flat telemetry) and "1.0" (canonical).
Unknown schema versions are flagged as errors and NEVER guessed.
"""

from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Set


@dataclass(frozen=True)
class SchemaVersionSpec:
    """Specification of a schema version."""

    version: str
    status: str  # "current", "deprecated", "experimental"
    description: str
    alias_map: Dict[str, str] = field(default_factory=dict)


# Mapping of legacy v0.9 flat metric names to canonical v1.0 names
LEGACY_0_9_ALIAS_MAP: Dict[str, str] = {
    "lat": "latency_ms",
    "rtt": "latency_ms",
    "util": "link_utilization_pct",
    "loss": "packet_loss_pct",
    "signal": "rssi_dbm",
    "cpu": "cpu_pct",
    "mem": "memory_pct",
    "drops": "queue_drops",
    "errs": "interface_errors",
    "bw": "bandwidth_mbps",
    "tput": "throughput_mbps",
    "retrans": "retransmission_pct",
    "dns_ms": "dns_resolution_ms",
    "dhcp_err": "dhcp_failures",
    "status": "device_status",
    "dev": "device_id",
    "time": "timestamp",
}

SCHEMA_REGISTRY: Dict[str, SchemaVersionSpec] = {
    "1.0": SchemaVersionSpec(
        version="1.0",
        status="current",
        description="Canonical NetCoop AI protocol schema v1.0",
        alias_map={},
    ),
    "0.9": SchemaVersionSpec(
        version="0.9",
        status="deprecated",
        description="Legacy flat telemetry schema v0.9 (campus sensor prototype)",
        alias_map=LEGACY_0_9_ALIAS_MAP,
    ),
}

SUPPORTED_VERSIONS: Set[str] = set(SCHEMA_REGISTRY.keys())
CANONICAL_VERSION = "1.0"


class UnknownSchemaVersionError(ValueError):
    """Raised when an unapproved or unknown schema version is detected."""

    def __init__(self, version: Any):
        super().__init__(
            f"Unsupported schema version: '{version}'. Supported versions are: {sorted(list(SUPPORTED_VERSIONS))}. "
            "Versions are never guessed."
        )
        self.version = version


def is_version_supported(version: Optional[str]) -> bool:
    """Check if a schema version string is supported."""
    if not version:
        return False
    return str(version).strip() in SUPPORTED_VERSIONS


def get_schema_spec(version: str) -> SchemaVersionSpec:
    """Retrieve SchemaVersionSpec for a given version or raise UnknownSchemaVersionError."""
    ver_clean = str(version).strip()
    if ver_clean not in SCHEMA_REGISTRY:
        raise UnknownSchemaVersionError(version)
    return SCHEMA_REGISTRY[ver_clean]


def list_supported_versions() -> List[str]:
    """Return sorted list of supported schema versions."""
    return sorted(list(SUPPORTED_VERSIONS))
