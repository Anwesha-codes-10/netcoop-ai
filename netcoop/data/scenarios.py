"""NetCoop AI Data - Scenario Builders and Sample File Generator.

Builds realistic incident scenarios for IIT Bhubaneswar campus network:
- Root cause scenarios:
    normal, link_congestion, weak_wifi, interface_fault, dns_failure,
    dhcp_failure, upstream_congestion, device_cpu_overload, ambiguous_insufficient.
- Interoperability scenarios:
    legacy_schema_0_9, mixed_units, missing_fields, unknown_schema_version, corrupted_json.
"""

from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
import json
from pathlib import Path
from typing import Any, Dict, List, Optional, Union

from netcoop.data.generator import TelemetryGenerator
from netcoop.data.topology import CampusTopology
from netcoop.protocol.causes import CauseCode


@dataclass
class Scenario:
    """Represents a packaged network incident scenario."""

    name: str
    description: str
    expected_root_cause: Optional[CauseCode]
    target_devices: List[str]
    records: Union[List[Dict[str, Any]], Dict[str, Any], str]
    is_valid_json: bool = True
    is_valid_telemetry: bool = True


class ScenarioBuilder:
    """Constructs benchmark scenarios for NetCoop AI diagnosis evaluation."""

    def __init__(self, seed: int = 42, topology: Optional[CampusTopology] = None):
        self.seed = seed
        self.topology = topology or CampusTopology.build_iit_bhubaneswar_topology()
        self.generator = TelemetryGenerator(seed=seed)

    def _get_fixed_start_time(self) -> datetime:
        """Return a deterministic start timestamp for repeatable scenario files."""
        return datetime(2026, 10, 31, 10, 0, 0, tzinfo=timezone.utc)

    def build_normal_scenario(self) -> Scenario:
        """Healthy baseline scenario across campus switches, APs, and servers."""
        self.generator.reseed(self.seed + 1)
        start_ts = self._get_fixed_start_time()
        records: List[Dict[str, Any]] = []

        devices = [
            ("CORE_RTR_01", "core_router", 10000.0),
            ("DIST_SW_HOSTEL", "distribution_switch", 10000.0),
            ("ACC_SW_HOSTEL_A", "access_switch", 1000.0),
            ("AP_HOSTEL_A_FL1", "access_point", 1000.0),
            ("SRV_DNS_01", "server", 10000.0),
        ]

        for dev_id, dev_type, bw in devices:
            series = self.generator.generate_time_series(
                device_id=dev_id,
                device_type=dev_type,
                fault_type="normal",
                steps=5,
                interval_seconds=60,
                start_time=start_ts,
                bandwidth_mbps=bw,
            )
            records.extend(series)

        return Scenario(
            name="normal",
            description="All campus devices operating within nominal baseline parameters",
            expected_root_cause=CauseCode.NORMAL,
            target_devices=[d[0] for d in devices],
            records=records,
        )

    def build_link_congestion_scenario(self) -> Scenario:
        """Hostel distribution link to core saturated due to heavy student traffic."""
        self.generator.reseed(self.seed + 2)
        start_ts = self._get_fixed_start_time()
        records: List[Dict[str, Any]] = []

        # Congested distribution switch
        congested_series = self.generator.generate_time_series(
            device_id="DIST_SW_HOSTEL",
            device_type="distribution_switch",
            fault_type="link_congestion",
            steps=5,
            interval_seconds=60,
            start_time=start_ts,
            bandwidth_mbps=10000.0,
        )
        records.extend(congested_series)

        # Downstream switches experiencing elevated latency
        for dev_id in ["ACC_SW_HOSTEL_A", "AP_HOSTEL_A_FL1"]:
            series = self.generator.generate_time_series(
                device_id=dev_id,
                device_type="access_switch" if "ACC" in dev_id else "access_point",
                fault_type="normal",
                steps=5,
                interval_seconds=60,
                start_time=start_ts,
            )
            # Add secondary latency impact
            for r in series:
                r["metrics"]["latency_ms"] = round(r["metrics"]["latency_ms"] + 80.0, 2)
            records.extend(series)

        return Scenario(
            name="link_congestion",
            description="Severe link saturation and queue drops on DIST_SW_HOSTEL uplink",
            expected_root_cause=CauseCode.LINK_CONGESTION,
            target_devices=["DIST_SW_HOSTEL", "ACC_SW_HOSTEL_A", "AP_HOSTEL_A_FL1"],
            records=records,
        )

    def build_weak_wifi_scenario(self) -> Scenario:
        """Severe Wi-Fi signal attenuation on Hostel Block A 2nd floor AP."""
        self.generator.reseed(self.seed + 3)
        start_ts = self._get_fixed_start_time()
        records: List[Dict[str, Any]] = []

        # Faulty AP
        ap_series = self.generator.generate_time_series(
            device_id="AP_HOSTEL_A_FL2",
            device_type="access_point",
            fault_type="weak_wifi",
            steps=5,
            interval_seconds=60,
            start_time=start_ts,
            bandwidth_mbps=1000.0,
        )
        records.extend(ap_series)

        # Upstream switch is healthy
        sw_series = self.generator.generate_time_series(
            device_id="ACC_SW_HOSTEL_A",
            device_type="access_switch",
            fault_type="normal",
            steps=5,
            interval_seconds=60,
            start_time=start_ts,
            bandwidth_mbps=1000.0,
        )
        records.extend(sw_series)

        return Scenario(
            name="weak_wifi",
            description="Severe RF degradation, low RSSI (-86dBm) and high retransmissions on AP_HOSTEL_A_FL2",
            expected_root_cause=CauseCode.WEAK_WIFI_SIGNAL,
            target_devices=["AP_HOSTEL_A_FL2", "ACC_SW_HOSTEL_A"],
            records=records,
        )

    def build_interface_fault_scenario(self) -> Scenario:
        """Physical FCS/CRC errors and frame drops on CSE access switch port."""
        self.generator.reseed(self.seed + 4)
        start_ts = self._get_fixed_start_time()
        records: List[Dict[str, Any]] = []

        sw_series = self.generator.generate_time_series(
            device_id="ACC_SW_CSE_01",
            device_type="access_switch",
            fault_type="interface_fault",
            steps=5,
            interval_seconds=60,
            start_time=start_ts,
            bandwidth_mbps=1000.0,
        )
        records.extend(sw_series)

        return Scenario(
            name="interface_fault",
            description="Physical link interface CRC framing errors and packet drops on ACC_SW_CSE_01",
            expected_root_cause=CauseCode.INTERFACE_FAULT,
            target_devices=["ACC_SW_CSE_01"],
            records=records,
        )

    def build_dns_failure_scenario(self) -> Scenario:
        """Campus primary DNS server responding with excessive resolution latency."""
        self.generator.reseed(self.seed + 5)
        start_ts = self._get_fixed_start_time()
        records: List[Dict[str, Any]] = []

        dns_series = self.generator.generate_time_series(
            device_id="SRV_DNS_01",
            device_type="server",
            fault_type="dns_failure",
            steps=5,
            interval_seconds=60,
            start_time=start_ts,
            bandwidth_mbps=10000.0,
        )
        records.extend(dns_series)

        return Scenario(
            name="dns_failure",
            description="Primary DNS server SRV_DNS_01 query timeouts and elevated resolution latency",
            expected_root_cause=CauseCode.DNS_FAILURE,
            target_devices=["SRV_DNS_01"],
            records=records,
        )

    def build_dhcp_failure_scenario(self) -> Scenario:
        """Hostel subnet DHCP scope exhaustion leading to failed lease allocations."""
        self.generator.reseed(self.seed + 6)
        start_ts = self._get_fixed_start_time()
        records: List[Dict[str, Any]] = []

        dhcp_series = self.generator.generate_time_series(
            device_id="SRV_DHCP_01",
            device_type="server",
            fault_type="dhcp_failure",
            steps=5,
            interval_seconds=60,
            start_time=start_ts,
            bandwidth_mbps=10000.0,
        )
        records.extend(dhcp_series)

        return Scenario(
            name="dhcp_failure",
            description="DHCP pool exhaustion causing rapid spikes in lease failure events",
            expected_root_cause=CauseCode.DHCP_FAILURE,
            target_devices=["SRV_DHCP_01"],
            records=records,
        )

    def build_upstream_congestion_scenario(self) -> Scenario:
        """Campus border NKN ISP gateway experiencing extreme upstream bottleneck."""
        self.generator.reseed(self.seed + 7)
        start_ts = self._get_fixed_start_time()
        records: List[Dict[str, Any]] = []

        gw_series = self.generator.generate_time_series(
            device_id="GW_NKN_ISP",
            device_type="uplink",
            fault_type="upstream_congestion",
            steps=5,
            interval_seconds=60,
            start_time=start_ts,
            bandwidth_mbps=20000.0,
        )
        records.extend(gw_series)

        # Core router observing high RTT
        core_series = self.generator.generate_time_series(
            device_id="CORE_RTR_01",
            device_type="core_router",
            fault_type="normal",
            steps=5,
            interval_seconds=60,
            start_time=start_ts,
            bandwidth_mbps=10000.0,
        )
        for r in core_series:
            r["metrics"]["latency_ms"] = round(r["metrics"]["latency_ms"] + 150.0, 2)
        records.extend(core_series)

        return Scenario(
            name="upstream_congestion",
            description="Border gateway GW_NKN_ISP saturated with upstream traffic",
            expected_root_cause=CauseCode.UPSTREAM_CONGESTION,
            target_devices=["GW_NKN_ISP", "CORE_RTR_01"],
            records=records,
        )

    def build_device_cpu_overload_scenario(self) -> Scenario:
        """Lecture Hall Complex access switch CPU exhausted by rogue multicast traffic."""
        self.generator.reseed(self.seed + 8)
        start_ts = self._get_fixed_start_time()
        records: List[Dict[str, Any]] = []

        cpu_series = self.generator.generate_time_series(
            device_id="ACC_SW_LHC_01",
            device_type="access_switch",
            fault_type="device_cpu_overload",
            steps=5,
            interval_seconds=60,
            start_time=start_ts,
            bandwidth_mbps=1000.0,
        )
        records.extend(cpu_series)

        return Scenario(
            name="device_cpu_overload",
            description="Control plane CPU utilization at 98% on ACC_SW_LHC_01 causing queue drops",
            expected_root_cause=CauseCode.DEVICE_CPU_OVERLOAD,
            target_devices=["ACC_SW_LHC_01"],
            records=records,
        )

    def build_ambiguous_insufficient_scenario(self) -> Scenario:
        """Sparse telemetry with borderline metrics and omitted fields."""
        self.generator.reseed(self.seed + 9)
        start_ts = self._get_fixed_start_time()
        records: List[Dict[str, Any]] = []

        series = self.generator.generate_time_series(
            device_id="ACC_SW_LIB_01",
            device_type="access_switch",
            fault_type="ambiguous_insufficient",
            steps=3,
            interval_seconds=60,
            start_time=start_ts,
            bandwidth_mbps=1000.0,
        )
        # Strip some metrics to simulate sparse observation
        for r in series:
            del r["metrics"]["queue_drops"]
            del r["metrics"]["interface_errors"]
        records.extend(series)

        return Scenario(
            name="ambiguous_insufficient",
            description="Borderline telemetry with missing key fields preventing definitive diagnosis",
            expected_root_cause=CauseCode.UNKNOWN,
            target_devices=["ACC_SW_LIB_01"],
            records=records,
        )

    # -------------------------------------------------------------------------
    # Interoperability Edge Cases
    # -------------------------------------------------------------------------

    def build_legacy_schema_0_9_scenario(self) -> Scenario:
        """Telemetry formatted according to legacy schema v0.9 flat keys."""
        start_ts = self._get_fixed_start_time()
        records: List[Dict[str, Any]] = []

        # Generate 4 flat records with legacy keys
        for i in range(4):
            step_ts = (start_ts + timedelta(seconds=i * 60)).isoformat()
            records.append({
                "schema_version": "0.9",
                "dev": "DIST_SW_HOSTEL",
                "time": step_ts,
                "lat": 185.4,
                "rtt": 190.2,
                "util": 94.6,
                "loss": 2.1,
                "cpu": 48.0,
                "mem": 52.0,
                "drops": 450,
                "errs": 0,
                "bw": 10000.0,
                "tput": 9460.0,
                "status": "degraded",
            })

        return Scenario(
            name="legacy_schema_0_9",
            description="Telemetry generated using legacy sensor schema v0.9 flat field names",
            expected_root_cause=CauseCode.LINK_CONGESTION,
            target_devices=["DIST_SW_HOSTEL"],
            records=records,
        )

    def build_mixed_units_scenario(self) -> Scenario:
        """Telemetry with non-canonical units (seconds, Gbps, fraction ratio)."""
        start_ts = self._get_fixed_start_time()
        records: List[Dict[str, Any]] = []

        for i in range(3):
            step_ts = (start_ts + timedelta(seconds=i * 60)).isoformat()
            records.append({
                "device_id": "DIST_SW_HOSTEL",
                "timestamp": step_ts,
                "schema_version": "1.0",
                "status": "degraded",
                "units": {
                    "latency": "s",
                    "bandwidth": "Gbps",
                    "packet_loss": "fraction",
                },
                "metrics": {
                    "latency_s": 0.22,               # 0.22 seconds = 220 ms
                    "bandwidth_gbps": 10.0,          # 10 Gbps = 10000 Mbps
                    "packet_loss_ratio": 0.035,      # 0.035 ratio = 3.5%
                    "link_utilization_pct": "95.5%", # String with percent symbol
                    "throughput_mbps": "9550Mbps",   # String with Mbps symbol
                    "queue_drops": 600,
                    "cpu_pct": 45.0,
                },
            })

        return Scenario(
            name="mixed_units",
            description="Telemetry specifying non-standard units (seconds, Gbps, fraction ratios)",
            expected_root_cause=CauseCode.LINK_CONGESTION,
            target_devices=["DIST_SW_HOSTEL"],
            records=records,
        )

    def build_missing_fields_scenario(self) -> Scenario:
        """Telemetry missing mandatory fields like device_id or timestamp."""
        records: List[Dict[str, Any]] = [
            {
                # Missing device_id
                "timestamp": self._get_fixed_start_time().isoformat(),
                "schema_version": "1.0",
                "metrics": {"latency_ms": 15.0, "link_utilization_pct": 30.0},
            },
            {
                # Missing timestamp
                "device_id": "ACC_SW_HOSTEL_A",
                "schema_version": "1.0",
                "metrics": {"latency_ms": 14.5, "link_utilization_pct": 32.0},
            },
        ]

        return Scenario(
            name="missing_fields",
            description="Records deliberately missing required schema identifiers",
            expected_root_cause=None,
            target_devices=["ACC_SW_HOSTEL_A"],
            records=records,
            is_valid_telemetry=False,
        )

    def build_unknown_schema_version_scenario(self) -> Scenario:
        """Payload tagged with unsupported/experimental schema version."""
        records: List[Dict[str, Any]] = [
            {
                "device_id": "CORE_RTR_01",
                "timestamp": self._get_fixed_start_time().isoformat(),
                "schema_version": "2.5-beta",  # Unknown / unsupported schema version
                "metrics": {"latency_ms": 10.0, "link_utilization_pct": 20.0},
            }
        ]

        return Scenario(
            name="unknown_schema_version",
            description="Payload tagged with unrecognized schema version '2.5-beta'",
            expected_root_cause=None,
            target_devices=["CORE_RTR_01"],
            records=records,
            is_valid_telemetry=False,
        )

    def build_corrupted_json_scenario(self) -> Scenario:
        """Syntactically malformed JSON string (unclosed braces, trailing garbage)."""
        raw_text = """{
  "schema_version": "1.0",
  "device_id": "DIST_SW_HOSTEL",
  "timestamp": "2026-10-31T10:00:00Z",
  "metrics": {
    "latency_ms": 150.0,
    "packet_loss_pct": 2.5,
    "link_utilization_pct": 92.0
  // MALFORMED_JSON_SYNTAX_ERROR: unclosed brace and invalid comment
"""
        return Scenario(
            name="corrupted_json",
            description="Malformed JSON string with syntax error to test parser resilience",
            expected_root_cause=None,
            target_devices=["DIST_SW_HOSTEL"],
            records=raw_text,
            is_valid_json=False,
            is_valid_telemetry=False,
        )

    def build_all(self) -> List[Scenario]:
        """Construct all standard and interoperability benchmark scenarios."""
        return [
            self.build_normal_scenario(),
            self.build_link_congestion_scenario(),
            self.build_weak_wifi_scenario(),
            self.build_interface_fault_scenario(),
            self.build_dns_failure_scenario(),
            self.build_dhcp_failure_scenario(),
            self.build_upstream_congestion_scenario(),
            self.build_device_cpu_overload_scenario(),
            self.build_ambiguous_insufficient_scenario(),
            self.build_legacy_schema_0_9_scenario(),
            self.build_mixed_units_scenario(),
            self.build_missing_fields_scenario(),
            self.build_unknown_schema_version_scenario(),
            self.build_corrupted_json_scenario(),
        ]

    def save_all(self, samples_dir: Union[str, Path], topology_path: Optional[Union[str, Path]] = None) -> List[Path]:
        """Export all scenarios to data/samples/ and topology to data/topology.json."""
        s_dir = Path(samples_dir)
        s_dir.mkdir(parents=True, exist_ok=True)

        if topology_path:
            t_path = Path(topology_path)
            self.topology.save_to_json(t_path)

        saved_files: List[Path] = []
        for scenario in self.build_all():
            out_file = s_dir / f"{scenario.name}.json"
            if isinstance(scenario.records, str):
                with open(out_file, "w", encoding="utf-8") as f:
                    f.write(scenario.records)
            else:
                with open(out_file, "w", encoding="utf-8") as f:
                    json.dump(scenario.records, f, indent=2)
            saved_files.append(out_file)

        return saved_files
