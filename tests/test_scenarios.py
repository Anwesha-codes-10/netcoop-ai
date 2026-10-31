"""Tests for loading and validating all benchmark scenario sample files."""

import json
from pathlib import Path
import pytest

from netcoop.data.scenarios import ScenarioBuilder
from netcoop.protocol.validators import ErrorCode, TelemetryValidator


@pytest.fixture
def samples_directory():
    # Relative to netcoop_ai root
    p = Path("data/samples")
    if not p.exists():
        # Try finding from file path
        p = Path(__file__).parent.parent / "data" / "samples"
    return p


def test_all_scenario_files_exist(samples_directory):
    expected_files = [
        "normal.json",
        "link_congestion.json",
        "weak_wifi.json",
        "interface_fault.json",
        "dns_failure.json",
        "dhcp_failure.json",
        "upstream_congestion.json",
        "device_cpu_overload.json",
        "ambiguous_insufficient.json",
        "legacy_schema_0_9.json",
        "mixed_units.json",
        "missing_fields.json",
        "unknown_schema_version.json",
        "corrupted_json.json",
    ]
    for fname in expected_files:
        fpath = samples_directory / fname
        assert fpath.exists(), f"Sample scenario file {fname} is missing"


def test_corrupted_json_scenario(samples_directory):
    validator = TelemetryValidator()
    raw = (samples_directory / "corrupted_json.json").read_text(encoding="utf-8")
    parsed, res = validator.validate_json_string(raw)
    assert not res.ok
    assert parsed is None
    assert any(e.code == ErrorCode.ERR_CORRUPTED_JSON for e in res.errors)


def test_missing_fields_scenario(samples_directory):
    validator = TelemetryValidator()
    raw = (samples_directory / "missing_fields.json").read_text(encoding="utf-8")
    parsed, res_json = validator.validate_json_string(raw)
    assert res_json.ok

    batch_res = validator.validate_telemetry_batch(parsed)
    assert not batch_res.ok
    assert any(e.code == ErrorCode.ERR_MISSING_REQUIRED_FIELD for e in batch_res.errors)


def test_unknown_schema_version_scenario(samples_directory):
    validator = TelemetryValidator()
    raw = (samples_directory / "unknown_schema_version.json").read_text(encoding="utf-8")
    parsed, _ = validator.validate_json_string(raw)
    batch_res = validator.validate_telemetry_batch(parsed)
    assert not batch_res.ok
    assert any(e.code == ErrorCode.ERR_UNKNOWN_SCHEMA_VERSION for e in batch_res.errors)


def test_normal_and_fault_scenarios_parse(samples_directory):
    validator = TelemetryValidator()
    valid_scenarios = [
        "normal.json",
        "link_congestion.json",
        "weak_wifi.json",
        "interface_fault.json",
        "dns_failure.json",
        "dhcp_failure.json",
        "upstream_congestion.json",
        "device_cpu_overload.json",
        "ambiguous_insufficient.json",
    ]

    for fname in valid_scenarios:
        raw = (samples_directory / fname).read_text(encoding="utf-8")
        parsed, res_json = validator.validate_json_string(raw)
        assert res_json.ok, f"{fname} failed JSON parse"
        assert isinstance(parsed, list), f"{fname} content should be a list"
        assert len(parsed) > 0, f"{fname} list is empty"
