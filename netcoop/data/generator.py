"""NetCoop AI Data - Deterministic Synthetic Telemetry Generator.

Ports and wraps the Colab telemetry generator with deterministic seeding,
full time-series generation, and comprehensive support for all 16 canonical metrics.
"""

from datetime import datetime, timedelta, timezone
from pathlib import Path
import random
from typing import Any, Dict, List, Optional, Union
import yaml


def generate_colab_telemetry(fault_type: str = "normal", seed: Optional[int] = None) -> Dict[str, Any]:
    """Port and wrap the original Colab telemetry generator with a seed parameter."""
    rng = random.Random(seed) if seed is not None else random.Random()
    now_utc = datetime.now(timezone.utc).isoformat()

    data: Dict[str, Any] = {
        "timestamp": now_utc,
        "device_id": f"SW_CAMPUS_{rng.randint(1, 10)}",
        "metrics": {},
    }

    if fault_type == "latency_spike":
        data["metrics"] = {
            "cpu_utilization_pct": round(rng.uniform(40, 70), 2),
            "link_utilization_pct": round(rng.uniform(60, 85), 2),
            "packet_loss_pct": round(rng.uniform(0.1, 1.5), 2),
            "latency_ms": round(rng.uniform(150, 400), 2),  # Spike
            "jitter_ms": round(rng.uniform(30, 80), 2),
            "queue_drops": rng.randint(0, 50),
        }
        data["status"] = "Warning"
    elif fault_type == "hardware_failure":
        data["metrics"] = {
            "cpu_utilization_pct": 99.9,
            "link_utilization_pct": 100.0,
            "packet_loss_pct": round(rng.uniform(15, 30), 2),
            "latency_ms": round(rng.uniform(500, 1000), 2),
            "queue_drops": rng.randint(5000, 15000),
            "interface_errors": rng.randint(100, 500),
        }
        data["status"] = "Critical"
    else:
        data["metrics"] = {
            "cpu_utilization_pct": round(rng.uniform(10, 35), 2),
            "link_utilization_pct": round(rng.uniform(20, 50), 2),
            "packet_loss_pct": 0.0,
            "latency_ms": round(rng.uniform(5, 20), 2),
            "jitter_ms": round(rng.uniform(1, 5), 2),
            "queue_drops": 0,
        }
        data["status"] = "Healthy"

    return data


class TelemetryGenerator:
    """Deterministic synthetic network telemetry generator for campus topologies."""

    def __init__(
        self,
        seed: int = 42,
        thresholds_path: Optional[Union[str, Path]] = None,
    ):
        self.seed = seed
        self.rng = random.Random(seed)
        self.thresholds = self._load_thresholds(thresholds_path)

    def _load_thresholds(self, path: Optional[Union[str, Path]]) -> Dict[str, Any]:
        """Load thresholds config if available, else use safe defaults."""
        if path:
            p = Path(path)
            if p.exists():
                with open(p, "r", encoding="utf-8") as f:
                    return yaml.safe_load(f) or {}

        # Default fallbacks
        return {
            "metrics": {
                "latency_ms": {"baseline": 12.0},
                "jitter_ms": {"baseline": 2.5},
                "link_utilization_pct": {"baseline": 35.0},
                "cpu_pct": {"baseline": 25.0},
                "memory_pct": {"baseline": 40.0},
                "rssi_dbm": {"baseline": -55.0},
                "snr_db": {"baseline": 35.0},
            }
        }

    def reseed(self, seed: int) -> None:
        """Reset RNG seed for repeatability."""
        self.seed = seed
        self.rng = random.Random(seed)

    def generate_record(
        self,
        device_id: str,
        device_type: str = "access_switch",
        fault_type: str = "normal",
        timestamp: Optional[datetime] = None,
        bandwidth_mbps: float = 1000.0,
    ) -> Dict[str, Any]:
        """Generate a single canonical telemetry record for a device."""
        if timestamp is None:
            timestamp = datetime.now(timezone.utc)
        elif timestamp.tzinfo is None:
            timestamp = timestamp.replace(tzinfo=timezone.utc)

        ts_str = timestamp.isoformat()

        # Generate base healthy metrics
        metrics: Dict[str, Any] = {
            "bandwidth_mbps": bandwidth_mbps,
            "latency_ms": round(self.rng.uniform(6.0, 18.0), 2),
            "jitter_ms": round(self.rng.uniform(1.0, 4.0), 2),
            "packet_loss_pct": 0.0,
            "link_utilization_pct": round(self.rng.uniform(20.0, 45.0), 2),
            "cpu_pct": round(self.rng.uniform(15.0, 35.0), 2),
            "memory_pct": round(self.rng.uniform(35.0, 50.0), 2),
            "queue_drops": 0,
            "interface_errors": 0,
            "retransmission_pct": round(self.rng.uniform(0.1, 1.2), 2),
            "device_status": "up",
        }

        # Calculate throughput based on utilization
        metrics["throughput_mbps"] = round(
            (metrics["link_utilization_pct"] / 100.0) * bandwidth_mbps, 2
        )

        # Wireless specific metrics for Access Points
        if device_type == "access_point" or "AP" in device_id:
            metrics["rssi_dbm"] = round(self.rng.uniform(-62.0, -52.0), 1)
            metrics["snr_db"] = round(self.rng.uniform(32.0, 42.0), 1)
            metrics["retransmission_pct"] = round(self.rng.uniform(0.5, 2.5), 2)

        # Server specific metrics
        if "DNS" in device_id or device_type == "server":
            metrics["dns_resolution_ms"] = round(self.rng.uniform(8.0, 22.0), 2)
        if "DHCP" in device_id:
            metrics["dhcp_failures"] = 0

        # Inject Fault Profiles
        if fault_type == "link_congestion":
            metrics["link_utilization_pct"] = round(self.rng.uniform(92.0, 98.5), 2)
            metrics["throughput_mbps"] = round((metrics["link_utilization_pct"] / 100.0) * bandwidth_mbps, 2)
            metrics["queue_drops"] = self.rng.randint(250, 1500)
            metrics["latency_ms"] = round(self.rng.uniform(140.0, 320.0), 2)
            metrics["jitter_ms"] = round(self.rng.uniform(35.0, 85.0), 2)
            metrics["packet_loss_pct"] = round(self.rng.uniform(1.2, 4.0), 2)
            metrics["device_status"] = "degraded"

        elif fault_type == "weak_wifi":
            metrics["rssi_dbm"] = round(self.rng.uniform(-89.0, -82.0), 1)  # Very weak signal
            metrics["snr_db"] = round(self.rng.uniform(8.0, 14.0), 1)       # Poor SNR
            metrics["retransmission_pct"] = round(self.rng.uniform(25.0, 48.0), 2)
            metrics["packet_loss_pct"] = round(self.rng.uniform(5.0, 16.0), 2)
            metrics["latency_ms"] = round(self.rng.uniform(90.0, 240.0), 2)
            metrics["jitter_ms"] = round(self.rng.uniform(25.0, 60.0), 2)
            metrics["device_status"] = "degraded"

        elif fault_type == "interface_fault":
            metrics["interface_errors"] = self.rng.randint(200, 1500)  # High CRC/frame errors
            metrics["packet_loss_pct"] = round(self.rng.uniform(4.0, 14.0), 2)
            metrics["retransmission_pct"] = round(self.rng.uniform(10.0, 25.0), 2)
            metrics["latency_ms"] = round(self.rng.uniform(25.0, 55.0), 2)
            metrics["device_status"] = "degraded"

        elif fault_type == "device_cpu_overload":
            metrics["cpu_pct"] = round(self.rng.uniform(95.0, 99.8), 2)
            metrics["memory_pct"] = round(self.rng.uniform(88.0, 96.0), 2)
            metrics["queue_drops"] = self.rng.randint(150, 900)
            metrics["latency_ms"] = round(self.rng.uniform(220.0, 550.0), 2)
            metrics["jitter_ms"] = round(self.rng.uniform(45.0, 95.0), 2)
            metrics["packet_loss_pct"] = round(self.rng.uniform(2.0, 7.0), 2)
            metrics["device_status"] = "degraded"

        elif fault_type == "upstream_congestion":
            metrics["link_utilization_pct"] = round(self.rng.uniform(96.0, 99.9), 2)
            metrics["throughput_mbps"] = round((metrics["link_utilization_pct"] / 100.0) * bandwidth_mbps, 2)
            metrics["queue_drops"] = self.rng.randint(800, 4500)
            metrics["latency_ms"] = round(self.rng.uniform(250.0, 480.0), 2)
            metrics["jitter_ms"] = round(self.rng.uniform(50.0, 110.0), 2)
            metrics["packet_loss_pct"] = round(self.rng.uniform(3.0, 8.5), 2)
            metrics["device_status"] = "degraded"

        elif fault_type == "dns_failure":
            metrics["dns_resolution_ms"] = round(self.rng.uniform(2500.0, 9000.0), 2)
            metrics["device_status"] = "degraded"

        elif fault_type == "dhcp_failure":
            metrics["dhcp_failures"] = self.rng.randint(35, 180)
            metrics["device_status"] = "degraded"

        elif fault_type == "hardware_failure":
            metrics["cpu_pct"] = 99.9
            metrics["link_utilization_pct"] = 100.0
            metrics["packet_loss_pct"] = round(self.rng.uniform(20.0, 38.0), 2)
            metrics["latency_ms"] = round(self.rng.uniform(600.0, 1200.0), 2)
            metrics["queue_drops"] = self.rng.randint(6000, 16000)
            metrics["interface_errors"] = self.rng.randint(300, 800)
            metrics["device_status"] = "down"

        elif fault_type == "ambiguous_insufficient":
            # Borderline values with some omitted metrics
            metrics["link_utilization_pct"] = round(self.rng.uniform(75.0, 82.0), 2)
            metrics["cpu_pct"] = round(self.rng.uniform(70.0, 78.0), 2)
            metrics["latency_ms"] = round(self.rng.uniform(70.0, 85.0), 2)
            metrics["packet_loss_pct"] = round(self.rng.uniform(1.0, 1.8), 2)
            metrics["queue_drops"] = self.rng.randint(5, 20)
            metrics["device_status"] = "degraded"

        return {
            "device_id": device_id,
            "device_type": device_type,
            "timestamp": ts_str,
            "status": metrics["device_status"],
            "schema_version": "1.0",
            "metrics": metrics,
        }

    def generate_time_series(
        self,
        device_id: str,
        device_type: str = "access_switch",
        fault_type: str = "normal",
        steps: int = 10,
        interval_seconds: int = 60,
        start_time: Optional[datetime] = None,
        bandwidth_mbps: float = 1000.0,
    ) -> List[Dict[str, Any]]:
        """Generate chronological time series of telemetry for a device."""
        if start_time is None:
            start_time = datetime.now(timezone.utc) - timedelta(seconds=steps * interval_seconds)
        elif start_time.tzinfo is None:
            start_time = start_time.replace(tzinfo=timezone.utc)

        records: List[Dict[str, Any]] = []
        for i in range(steps):
            step_ts = start_time + timedelta(seconds=i * interval_seconds)
            rec = self.generate_record(
                device_id=device_id,
                device_type=device_type,
                fault_type=fault_type,
                timestamp=step_ts,
                bandwidth_mbps=bandwidth_mbps,
            )
            records.append(rec)
        return records
