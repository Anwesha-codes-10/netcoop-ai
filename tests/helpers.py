"""NetCoop AI Test Helpers.

Standardized scenario loaders, expected cause mapping, and task request builders
for multi-agent diagnostic testing across all Round 2 components.
"""

from pathlib import Path
from typing import List, Optional

from netcoop.data.topology import CampusTopology
from netcoop.ingest import IngestResult, ingest
from netcoop.protocol.causes import CauseCode
from netcoop.protocol.messages import MessageEnvelope, MessageType, TaskRequestPayload

SCENARIO_CAUSE_MAP = {
    "normal": CauseCode.NORMAL,
    "link_congestion": CauseCode.LINK_CONGESTION,
    "weak_wifi": CauseCode.WEAK_WIFI_SIGNAL,
    "interface_fault": CauseCode.INTERFACE_FAULT,
    "dns_failure": CauseCode.DNS_FAILURE,
    "dhcp_failure": CauseCode.DHCP_FAILURE,
    "upstream_congestion": CauseCode.UPSTREAM_CONGESTION,
    "device_cpu_overload": CauseCode.DEVICE_CPU_OVERLOAD,
    "ambiguous_insufficient": CauseCode.UNKNOWN,
    "legacy_schema_0_9": CauseCode.LINK_CONGESTION,
    "mixed_units": CauseCode.LINK_CONGESTION,
    "missing_fields": None,
    "unknown_schema_version": None,
    "corrupted_json": None,
}


def scenario_names() -> List[str]:
    """Return all valid/non-corrupted scenario names for diagnostic evaluation."""
    return [
        "normal",
        "link_congestion",
        "weak_wifi",
        "interface_fault",
        "dns_failure",
        "dhcp_failure",
        "upstream_congestion",
        "device_cpu_overload",
        "ambiguous_insufficient",
        "legacy_schema_0_9",
        "mixed_units",
        "missing_fields",
    ]


def expected_cause(name: str) -> Optional[CauseCode]:
    """Return expected root cause CauseCode for a scenario name, or None."""
    return SCENARIO_CAUSE_MAP.get(name)


def ingest_scenario(name: str) -> IngestResult:
    """Run ingestion pipeline on a scenario sample file with IIT Bhubaneswar topology."""
    samples_dir = Path("data/samples")
    if not samples_dir.exists():
        samples_dir = Path(__file__).resolve().parent.parent / "data" / "samples"
    file_path = samples_dir / f"{name}.json"
    topo = CampusTopology.build_iit_bhubaneswar_topology()
    return ingest(file_path, topology=topo)


def scenario_task_request(
    name: str,
    recipient: str,
    task: str = "analyze",
) -> MessageEnvelope:
    """Build a fully validated task_request MessageEnvelope carrying normalized telemetry."""
    ingest_res = ingest_scenario(name)
    topo = CampusTopology.build_iit_bhubaneswar_topology()
    payload = TaskRequestPayload(
        task=task,
        target_device_ids=list(ingest_res.normalized_telemetry.keys()),
        telemetry=ingest_res.normalized_telemetry,
        topology=topo.to_dict(),
        data_quality=ingest_res.data_quality,
        normalization_log=ingest_res.normalization_log,
    )
    return MessageEnvelope(
        incident_id=ingest_res.incident_id,
        sender="orchestrator",
        recipient=recipient,
        message_type=MessageType.TASK_REQUEST,
        payload=payload,
    )