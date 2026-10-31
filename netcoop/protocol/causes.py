"""NetCoop AI Protocol - Fault Causes and Canonical Metric Dictionary."""

from dataclasses import dataclass
from enum import Enum
from typing import Any, Dict, List, Optional


class CauseCode(str, Enum):
    """Network fault diagnosis cause codes."""

    LINK_CONGESTION = "LINK_CONGESTION"
    WEAK_WIFI_SIGNAL = "WEAK_WIFI_SIGNAL"
    INTERFACE_FAULT = "INTERFACE_FAULT"
    DEVICE_CPU_OVERLOAD = "DEVICE_CPU_OVERLOAD"
    UPSTREAM_CONGESTION = "UPSTREAM_CONGESTION"
    DNS_FAILURE = "DNS_FAILURE"
    DHCP_FAILURE = "DHCP_FAILURE"
    HARDWARE_FAILURE = "HARDWARE_FAILURE"
    NORMAL = "NORMAL"
    UNKNOWN = "UNKNOWN"

    @property
    def label(self) -> str:
        """Return human-readable label for the cause code."""
        return CAUSE_LABELS.get(self, "Unknown Condition")


CAUSE_LABELS: Dict[CauseCode, str] = {
    CauseCode.LINK_CONGESTION: "Link Congestion & Bandwidth Saturation",
    CauseCode.WEAK_WIFI_SIGNAL: "Weak Wi-Fi Signal / Low RF Coverage",
    CauseCode.INTERFACE_FAULT: "Physical / Data-Link Interface Fault (CRC / Frame Errors)",
    CauseCode.DEVICE_CPU_OVERLOAD: "Device Control/Data Plane CPU Overload",
    CauseCode.UPSTREAM_CONGESTION: "Upstream ISP / NKN Gateway Bottleneck",
    CauseCode.DNS_FAILURE: "DNS Server Resolution Failure / High Latency",
    CauseCode.DHCP_FAILURE: "DHCP Lease Exhaustion or Handshake Failure",
    CauseCode.HARDWARE_FAILURE: "Critical Hardware Component Degradation / Crash",
    CauseCode.NORMAL: "Healthy Operational Baseline",
    CauseCode.UNKNOWN: "Unresolved / Insufficient Telemetry",
}


@dataclass(frozen=True)
class MetricDefinition:
    """Specification of a canonical network metric."""

    name: str
    unit: str
    min_val: Optional[float]
    max_val: Optional[float]
    data_type: str  # "float", "int", "enum"
    description: str
    allowed_values: Optional[List[str]] = None

    def is_valid_value(self, value: Any) -> bool:
        """Check if a given value is valid for this metric."""
        if value is None:
            return False
        if self.data_type == "enum":
            return str(value).lower() in [v.lower() for v in (self.allowed_values or [])]
        try:
            val = float(value)
        except (ValueError, TypeError):
            return False
        if self.min_val is not None and val < self.min_val:
            return False
        if self.max_val is not None and val > self.max_val:
            return False
        return True


CANONICAL_METRICS: Dict[str, MetricDefinition] = {
    "latency_ms": MetricDefinition(
        name="latency_ms",
        unit="ms",
        min_val=0.0,
        max_val=10000.0,
        data_type="float",
        description="Round-trip network delay in milliseconds",
    ),
    "jitter_ms": MetricDefinition(
        name="jitter_ms",
        unit="ms",
        min_val=0.0,
        max_val=5000.0,
        data_type="float",
        description="Variance in packet arrival time in milliseconds",
    ),
    "packet_loss_pct": MetricDefinition(
        name="packet_loss_pct",
        unit="%",
        min_val=0.0,
        max_val=100.0,
        data_type="float",
        description="Percentage of dropped or lost packets (0.0 to 100.0)",
    ),
    "throughput_mbps": MetricDefinition(
        name="throughput_mbps",
        unit="Mbps",
        min_val=0.0,
        max_val=100000.0,
        data_type="float",
        description="Observed interface transfer rate in megabits per second",
    ),
    "bandwidth_mbps": MetricDefinition(
        name="bandwidth_mbps",
        unit="Mbps",
        min_val=0.0,
        max_val=100000.0,
        data_type="float",
        description="Configured interface link capacity in megabits per second",
    ),
    "link_utilization_pct": MetricDefinition(
        name="link_utilization_pct",
        unit="%",
        min_val=0.0,
        max_val=100.0,
        data_type="float",
        description="Link bandwidth utilization percentage (0.0 to 100.0)",
    ),
    "cpu_pct": MetricDefinition(
        name="cpu_pct",
        unit="%",
        min_val=0.0,
        max_val=100.0,
        data_type="float",
        description="Device processor utilization percentage (0.0 to 100.0)",
    ),
    "memory_pct": MetricDefinition(
        name="memory_pct",
        unit="%",
        min_val=0.0,
        max_val=100.0,
        data_type="float",
        description="Device RAM memory utilization percentage (0.0 to 100.0)",
    ),
    "queue_drops": MetricDefinition(
        name="queue_drops",
        unit="packets",
        min_val=0.0,
        max_val=10000000.0,
        data_type="int",
        description="Count of buffer overflow dropped packets",
    ),
    "interface_errors": MetricDefinition(
        name="interface_errors",
        unit="errors",
        min_val=0.0,
        max_val=10000000.0,
        data_type="int",
        description="Count of physical framing or CRC errors",
    ),
    "rssi_dbm": MetricDefinition(
        name="rssi_dbm",
        unit="dBm",
        min_val=-120.0,
        max_val=0.0,
        data_type="float",
        description="Received Signal Strength Indicator in dBm (-120.0 to 0.0)",
    ),
    "snr_db": MetricDefinition(
        name="snr_db",
        unit="dB",
        min_val=0.0,
        max_val=100.0,
        data_type="float",
        description="Signal-to-Noise Ratio in decibels (0.0 to 100.0)",
    ),
    "retransmission_pct": MetricDefinition(
        name="retransmission_pct",
        unit="%",
        min_val=0.0,
        max_val=100.0,
        data_type="float",
        description="Percentage of frame or packet retransmissions (0.0 to 100.0)",
    ),
    "device_status": MetricDefinition(
        name="device_status",
        unit="enum",
        min_val=None,
        max_val=None,
        data_type="enum",
        description="Device operational status (up, down, degraded)",
        allowed_values=["up", "down", "degraded"],
    ),
    "dns_resolution_ms": MetricDefinition(
        name="dns_resolution_ms",
        unit="ms",
        min_val=0.0,
        max_val=30000.0,
        data_type="float",
        description="DNS query resolution latency in milliseconds",
    ),
    "dhcp_failures": MetricDefinition(
        name="dhcp_failures",
        unit="events",
        min_val=0.0,
        max_val=100000.0,
        data_type="int",
        description="Count of failed or timed-out DHCP leasing transactions",
    ),
}


def get_canonical_metric(name: str) -> Optional[MetricDefinition]:
    """Retrieve canonical definition for a metric name."""
    return CANONICAL_METRICS.get(name)


def is_canonical_metric(name: str) -> bool:
    """Return True if name is an official canonical metric."""
    return name in CANONICAL_METRICS
