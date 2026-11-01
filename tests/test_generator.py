"""Tests for NetCoop AI synthetic telemetry generator and determinism."""

from datetime import datetime, timezone
import pytest

from netcoop.data.generator import TelemetryGenerator, generate_colab_telemetry


def test_generator_determinism():
    gen1 = TelemetryGenerator(seed=42)
    gen2 = TelemetryGenerator(seed=42)

    fixed_time = datetime(2026, 10, 31, 12, 0, 0, tzinfo=timezone.utc)

    rec1 = gen1.generate_record(device_id="DIST_SW_HOSTEL", fault_type="link_congestion", timestamp=fixed_time)
    rec2 = gen2.generate_record(device_id="DIST_SW_HOSTEL", fault_type="link_congestion", timestamp=fixed_time)

    assert rec1 == rec2
    assert rec1["metrics"]["latency_ms"] == rec2["metrics"]["latency_ms"]
    assert rec1["metrics"]["link_utilization_pct"] == rec2["metrics"]["link_utilization_pct"]
    assert rec1["metrics"]["queue_drops"] == rec2["metrics"]["queue_drops"]


def test_colab_telemetry_determinism_and_port():
    res1 = generate_colab_telemetry(fault_type="hardware_failure", seed=100)
    res2 = generate_colab_telemetry(fault_type="hardware_failure", seed=100)

    assert res1["device_id"] == res2["device_id"]
    assert res1["status"] == "Critical"
    assert res1["metrics"] == res2["metrics"]
    assert res1["metrics"]["cpu_utilization_pct"] == 99.9


def test_time_series_chronological_order():
    gen = TelemetryGenerator(seed=77)
    start_ts = datetime(2026, 10, 31, 10, 0, 0, tzinfo=timezone.utc)
    series = gen.generate_time_series(
        device_id="ACC_SW_HOSTEL_A",
        steps=6,
        interval_seconds=60,
        start_time=start_ts,
    )

    assert len(series) == 6
    for i in range(len(series) - 1):
        t1 = datetime.fromisoformat(series[i]["timestamp"])
        t2 = datetime.fromisoformat(series[i + 1]["timestamp"])
        assert t2 > t1
        assert (t2 - t1).total_seconds() == 60


def test_fault_profiles_generation():
    gen = TelemetryGenerator(seed=88)

    # Test weak wifi
    wifi_rec = gen.generate_record(device_id="AP_HOSTEL_A_FL1", device_type="access_point", fault_type="weak_wifi")
    assert wifi_rec["metrics"]["rssi_dbm"] < -75.0
    assert wifi_rec["metrics"]["snr_db"] < 15.0
    assert wifi_rec["metrics"]["retransmission_pct"] > 20.0

    # Test interface fault
    iface_rec = gen.generate_record(device_id="ACC_SW_CSE_01", fault_type="interface_fault")
    assert iface_rec["metrics"]["interface_errors"] > 100
    assert iface_rec["metrics"]["packet_loss_pct"] > 3.0

    # Test DNS failure
    dns_rec = gen.generate_record(device_id="SRV_DNS_01", device_type="server", fault_type="dns_failure")
    assert dns_rec["metrics"]["dns_resolution_ms"] > 2000.0

    # Test DHCP failure
    dhcp_rec = gen.generate_record(device_id="SRV_DHCP_01", device_type="server", fault_type="dhcp_failure")
    assert dhcp_rec["metrics"]["dhcp_failures"] > 25
