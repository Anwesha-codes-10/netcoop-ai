"""Tests for NetCoop AI telemetry normalizer, alias mapping, and unit conversions."""

import pytest

from netcoop.protocol.normalizer import TelemetryNormalizer


def test_schema_0_9_legacy_alias_normalization():
    normalizer = TelemetryNormalizer()
    legacy_record = {
        "schema_version": "0.9",
        "dev": "DIST_SW_HOSTEL",
        "time": "2026-10-31T10:00:00Z",
        "lat": 185.5,
        "rtt": 190.0,
        "util": 94.2,
        "loss": 2.5,
        "signal": -82.0,
        "cpu": 65.0,
        "mem": 58.0,
        "drops": 450,
        "errs": 12,
        "bw": 10000.0,
        "tput": 9420.0,
        "retrans": 8.5,
        "dns_ms": 45.0,
        "dhcp_err": 2,
        "status": "degraded",
    }

    result = normalizer.normalize_record(legacy_record)
    data = result.normalized_data

    assert data["device_id"] == "DIST_SW_HOSTEL"
    assert data["timestamp"] == "2026-10-31T10:00:00Z"
    assert data["latency_ms"] == 190.0  # rtt normalized
    assert data["link_utilization_pct"] == 94.2
    assert data["packet_loss_pct"] == 2.5
    assert data["rssi_dbm"] == -82.0
    assert data["cpu_pct"] == 65.0
    assert data["memory_pct"] == 58.0
    assert data["queue_drops"] == 450
    assert data["interface_errors"] == 12
    assert data["bandwidth_mbps"] == 10000.0
    assert data["throughput_mbps"] == 9420.0
    assert data["retransmission_pct"] == 8.5
    assert data["dns_resolution_ms"] == 45.0
    assert data["dhcp_failures"] == 2
    assert data["device_status"] == "degraded"
    assert len(result.log) > 0


def test_unit_conversion_seconds_to_ms():
    normalizer = TelemetryNormalizer()
    record = {
        "device_id": "CORE_RTR_01",
        "metrics": {
            "latency_s": 0.25,        # Suffix detection: 0.25 s -> 250 ms
            "dns_resolution_seconds": 1.5,  # 1.5 s -> 1500 ms
        },
    }
    result = normalizer.normalize_record(record)
    assert result.normalized_data["latency_ms"] == 250.0
    assert result.normalized_data["dns_resolution_ms"] == 1500.0

    # Verify log entries
    lat_log = next(e for e in result.log if e.canonical_field == "latency_ms")
    assert lat_log.rule == "unit_convert_s_to_ms"
    assert lat_log.canonical_value == 250.0


def test_unit_conversion_bandwidth_variants():
    normalizer = TelemetryNormalizer()
    record = {
        "device_id": "GW_NKN_ISP",
        "metrics": {
            "bandwidth_gbps": 20.0,       # Gbps -> Mbps (20,000 Mbps)
            "throughput_kbps": 500000.0,  # 500,000 kbps -> 500 Mbps
        },
    }
    result = normalizer.normalize_record(record)
    assert result.normalized_data["bandwidth_mbps"] == 20000.0
    assert result.normalized_data["throughput_mbps"] == 500.0


def test_unit_conversion_fraction_to_percent():
    normalizer = TelemetryNormalizer()
    record = {
        "device_id": "ACC_SW_HOSTEL_A",
        "metrics": {
            "packet_loss_ratio": 0.045,      # 0.045 -> 4.5%
            "link_utilization_fraction": 0.88, # 0.88 -> 88.0%
        },
    }
    result = normalizer.normalize_record(record)
    assert result.normalized_data["packet_loss_pct"] == 4.5
    assert result.normalized_data["link_utilization_pct"] == 88.0


def test_explicit_units_block_parsing():
    normalizer = TelemetryNormalizer()
    record = {
        "device_id": "ACC_SW_CSE_01",
        "units": {
            "latency": "s",
            "bandwidth": "Gbps",
        },
        "metrics": {
            "latency": 0.08,
            "bandwidth": 10.0,
        },
    }
    result = normalizer.normalize_record(record)
    assert result.normalized_data["latency_ms"] == 80.0
    assert result.normalized_data["bandwidth_mbps"] == 10000.0


def test_string_embedded_units():
    normalizer = TelemetryNormalizer()
    record = {
        "device_id": "DIST_SW_HOSTEL",
        "metrics": {
            "latency_ms": "120ms",
            "throughput_mbps": "9.5Gbps",
            "packet_loss_pct": "3.2%",
        },
    }
    result = normalizer.normalize_record(record)
    assert result.normalized_data["latency_ms"] == 120.0
    assert result.normalized_data["throughput_mbps"] == 9500.0
    assert result.normalized_data["packet_loss_pct"] == 3.2


def test_ambiguous_or_unconvertible_lowers_completeness():
    normalizer = TelemetryNormalizer()
    record = {
        "device_id": "AP_HOSTEL_A_FL1",
        "units": {
            "latency": "furlongs_per_second",  # Invalid unit
        },
        "metrics": {
            "latency": "corrupted_text_value",
            "link_utilization_pct": 35.0,
        },
    }
    result = normalizer.normalize_record(record)
    assert len(result.ambiguities) > 0
    assert result.completeness < 1.0


def test_status_normalization_strings():
    normalizer = TelemetryNormalizer()
    for raw_s, expected in [("Healthy", "up"), ("OK", "up"), ("Warning", "degraded"), ("Critical", "down")]:
        rec = {"device_id": "SW_1", "metrics": {"device_status": raw_s}}
        res = normalizer.normalize_record(rec)
        assert res.normalized_data["device_status"] == expected
