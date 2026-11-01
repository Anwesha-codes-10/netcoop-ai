"""Tests for NetCoop AI structured telemetry and envelope validators.

Ensures every ErrorCode is covered and non-crashing behavior is verified.
"""

from datetime import datetime, timedelta, timezone
import math
from pathlib import Path
import pytest

from netcoop.protocol.validators import (
    ErrorCode,
    TelemetryValidator,
    parse_iso_timestamp,
)


@pytest.fixture
def sample_topology_devices():
    return {"CORE_RTR_01", "DIST_SW_HOSTEL", "ACC_SW_HOSTEL_A", "AP_HOSTEL_A_FL1"}


def test_err_corrupted_json():
    validator = TelemetryValidator()
    raw = "{ 'invalid_json': true, unclosed... "
    parsed, result = validator.validate_json_string(raw)
    assert not result.ok
    assert parsed is None
    assert any(e.code == ErrorCode.ERR_CORRUPTED_JSON for e in result.errors)


def test_err_empty_input():
    validator = TelemetryValidator()
    # Empty string
    parsed, res_str = validator.validate_json_string("   ")
    assert not res_str.ok
    assert any(e.code == ErrorCode.ERR_EMPTY_INPUT for e in res_str.errors)

    # Empty batch
    res_batch = validator.validate_telemetry_batch([])
    assert not res_batch.ok
    assert any(e.code == ErrorCode.ERR_EMPTY_INPUT for e in res_batch.errors)


def test_err_missing_required_field():
    validator = TelemetryValidator()
    # Record missing timestamp
    records = [{"device_id": "CORE_RTR_01", "metrics": {"latency_ms": 10.0}}]
    res = validator.validate_telemetry_batch(records)
    assert not res.ok
    assert any(e.code == ErrorCode.ERR_MISSING_REQUIRED_FIELD and e.field == "timestamp" for e in res.errors)

    # Envelope missing incident_id
    env_res = validator.validate_envelope({
        "message_id": "123",
        "schema_version": "1.0",
        "timestamp": "2026-10-31T10:00:00Z",
        "sender": "a",
        "recipient": "b",
        "message_type": "finding",
        "payload": {},
    })
    assert not env_res.ok
    assert any(e.code == ErrorCode.ERR_MISSING_REQUIRED_FIELD and e.field == "incident_id" for e in env_res.errors)


def test_err_wrong_type():
    validator = TelemetryValidator()
    # Record where metric is non-numeric string
    records = [{
        "device_id": "CORE_RTR_01",
        "timestamp": "2026-10-31T10:00:00Z",
        "metrics": {"latency_ms": "not_a_number"},
    }]
    res = validator.validate_telemetry_batch(records)
    assert not res.ok
    assert any(e.code == ErrorCode.ERR_WRONG_TYPE for e in res.errors)


def test_err_out_of_range():
    validator = TelemetryValidator()
    # Link utilization > 100%, negative latency, negative queue drops
    records = [{
        "device_id": "CORE_RTR_01",
        "timestamp": "2026-10-31T10:00:00Z",
        "metrics": {
            "link_utilization_pct": 142.5,   # Max is 100.0
            "latency_ms": -15.0,             # Min is 0.0
            "queue_drops": -5,               # Min is 0
        },
    }]
    res = validator.validate_telemetry_batch(records)
    assert not res.ok
    out_of_range_fields = [e.field for e in res.errors if e.code == ErrorCode.ERR_OUT_OF_RANGE]
    assert "link_utilization_pct" in out_of_range_fields
    assert "latency_ms" in out_of_range_fields
    assert "queue_drops" in out_of_range_fields


def test_err_nan_or_null():
    validator = TelemetryValidator()
    records = [{
        "device_id": "CORE_RTR_01",
        "timestamp": "2026-10-31T10:00:00Z",
        "metrics": {
            "latency_ms": float("nan"),
            "cpu_pct": None,
        },
    }]
    res = validator.validate_telemetry_batch(records)
    assert not res.ok
    nan_fields = [e.field for e in res.errors if e.code == ErrorCode.ERR_NAN_OR_NULL]
    assert "latency_ms" in nan_fields
    assert "cpu_pct" in nan_fields


def test_err_timestamp_duplicate():
    validator = TelemetryValidator()
    ts = "2026-10-31T10:00:00Z"
    records = [
        {"device_id": "CORE_RTR_01", "timestamp": ts, "metrics": {"latency_ms": 10.0}},
        {"device_id": "CORE_RTR_01", "timestamp": ts, "metrics": {"latency_ms": 11.0}},
    ]
    res = validator.validate_telemetry_batch(records)
    assert not res.ok
    assert any(e.code == ErrorCode.ERR_TIMESTAMP_DUPLICATE for e in res.errors)


def test_err_timestamp_out_of_order():
    validator = TelemetryValidator()
    records = [
        {"device_id": "CORE_RTR_01", "timestamp": "2026-10-31T10:02:00Z", "metrics": {"latency_ms": 10.0}},
        {"device_id": "CORE_RTR_01", "timestamp": "2026-10-31T10:01:00Z", "metrics": {"latency_ms": 11.0}},
    ]
    res = validator.validate_telemetry_batch(records)
    assert not res.ok
    assert any(e.code == ErrorCode.ERR_TIMESTAMP_OUT_OF_ORDER for e in res.errors)


def test_err_stale_data():
    validator = TelemetryValidator(stale_window_seconds=300)
    ref_time = datetime(2026, 10, 31, 10, 10, 0, tzinfo=timezone.utc)
    old_time = "2026-10-31T10:00:00Z"  # 600s older than ref_time
    records = [{"device_id": "CORE_RTR_01", "timestamp": old_time, "metrics": {"latency_ms": 10.0}}]

    res = validator.validate_telemetry_batch(records, reference_time=ref_time)
    assert not res.ok
    assert any(e.code == ErrorCode.ERR_STALE_DATA for e in res.errors)


def test_err_unknown_device_id(sample_topology_devices):
    validator = TelemetryValidator(allowed_topology_devices=sample_topology_devices)
    records = [{
        "device_id": "ROGUE_UNREGISTERED_SWITCH_99",
        "timestamp": "2026-10-31T10:00:00Z",
        "metrics": {"latency_ms": 10.0},
    }]
    res = validator.validate_telemetry_batch(records)
    assert not res.ok
    assert any(e.code == ErrorCode.ERR_UNKNOWN_DEVICE_ID for e in res.errors)


def test_err_unknown_schema_version():
    validator = TelemetryValidator()
    records = [{
        "device_id": "CORE_RTR_01",
        "timestamp": "2026-10-31T10:00:00Z",
        "schema_version": "2.5-beta",
        "metrics": {"latency_ms": 10.0},
    }]
    res = validator.validate_telemetry_batch(records)
    assert not res.ok
    assert any(e.code == ErrorCode.ERR_UNKNOWN_SCHEMA_VERSION for e in res.errors)


def test_err_mixed_units():
    validator = TelemetryValidator()
    records = [
        {
            "device_id": "DIST_SW_HOSTEL",
            "timestamp": "2026-10-31T10:00:00Z",
            "units": {"latency": "s"},
            "metrics": {"latency": 0.1},
        },
        {
            "device_id": "DIST_SW_HOSTEL",
            "timestamp": "2026-10-31T10:01:00Z",
            "units": {"latency": "ms"},
            "metrics": {"latency": 100.0},
        },
    ]
    res = validator.validate_telemetry_batch(records)
    assert not res.ok
    assert any(e.code == ErrorCode.ERR_MIXED_UNITS for e in res.errors)


def test_validate_json_exact_corrupted_json_sample():
    validator = TelemetryValidator()
    sample_path = Path(__file__).parent.parent / "data" / "samples" / "corrupted_json.json"
    raw = sample_path.read_text(encoding="utf-8")
    parsed, res = validator.validate_json_string(raw)
    assert not res.ok
    assert parsed is None
    assert res.completeness == 0.0
    assert any(e.code == ErrorCode.CORRUPTED_JSON for e in res.errors)
    assert any("line" in e.message.lower() and "column" in e.message.lower() for e in res.errors)


def test_validate_json_truncated_object():
    validator = TelemetryValidator()
    raw = '{"device_id": "DIST_SW_HOSTEL", "metrics": {'
    parsed, res = validator.validate_json_string(raw)
    assert not res.ok
    assert parsed is None
    assert res.completeness == 0.0
    assert any(e.code == ErrorCode.CORRUPTED_JSON for e in res.errors)
    assert any("line" in e.message.lower() and "column" in e.message.lower() for e in res.errors)


def test_validate_json_empty_string():
    validator = TelemetryValidator()
    parsed, res = validator.validate_json_string("")
    assert not res.ok
    assert parsed is None
    assert res.completeness == 0.0
    assert any(e.code == ErrorCode.EMPTY_INPUT for e in res.errors)


def test_validate_json_whitespace_only():
    validator = TelemetryValidator()
    parsed, res = validator.validate_json_string("   \n\t  \r\n  ")
    assert not res.ok
    assert parsed is None
    assert res.completeness == 0.0
    assert any(e.code == ErrorCode.EMPTY_INPUT for e in res.errors)


def test_validate_json_null():
    validator = TelemetryValidator()
    parsed, res = validator.validate_json_string("null")
    assert not res.ok
    assert parsed is None
    assert res.completeness == 0.0
    assert any(e.code == ErrorCode.EMPTY_INPUT for e in res.errors)


def test_validate_json_empty_array():
    validator = TelemetryValidator()
    parsed, res = validator.validate_json_string("[]")
    assert not res.ok
    assert parsed == []
    assert res.completeness == 0.0
    assert any(e.code == ErrorCode.EMPTY_INPUT for e in res.errors)


def test_validate_json_empty_object():
    validator = TelemetryValidator()
    parsed, res = validator.validate_json_string("{}")
    assert not res.ok
    assert parsed == {}
    assert res.completeness == 0.0
    assert any(e.code == ErrorCode.EMPTY_INPUT for e in res.errors)