"""End-to-End Benchmark Tests for NetCoop AI.

Executes all 14 Round 1 scenario files through the full multi-agent orchestrator pipeline
and verifies that predicted root causes, confidence levels, and status codes match ground truth.
"""

from pathlib import Path
import pytest

from netcoop.data.topology import CampusTopology
from netcoop.orchestrator import run_diagnosis_sync
from netcoop.protocol.causes import CauseCode


@pytest.fixture(scope="module")
def topology():
    topo_path = Path("data/topology.json")
    if topo_path.exists():
        return CampusTopology.load_from_json(topo_path)
    return CampusTopology.build_iit_bhubaneswar_topology()


@pytest.fixture(scope="module")
def sample_path():
    p = Path("data/samples")
    if not p.exists():
        p = Path(__file__).resolve().parent.parent / "data" / "samples"
    return p


def test_e2e_normal(sample_path, topology):
    report = run_diagnosis_sync(sample_path / "normal.json", topology=topology)
    assert report.root_cause_code == CauseCode.NORMAL
    assert report.status == "diagnosed"
    assert report.suspected_root_cause == "No fault detected"
    assert report.confidence >= 0.70


def test_e2e_link_congestion(sample_path, topology):
    report = run_diagnosis_sync(sample_path / "link_congestion.json", topology=topology)
    assert report.root_cause_code == CauseCode.LINK_CONGESTION
    assert report.status == "diagnosed"
    assert report.confidence >= 0.75
    assert "DIST_SW_HOSTEL" in report.affected_devices


def test_e2e_weak_wifi(sample_path, topology):
    report = run_diagnosis_sync(sample_path / "weak_wifi.json", topology=topology)
    assert report.root_cause_code == CauseCode.WEAK_WIFI_SIGNAL
    assert report.status == "diagnosed"
    assert report.confidence >= 0.75
    assert "AP_HOSTEL_A_FL2" in report.affected_devices


def test_e2e_interface_fault(sample_path, topology):
    report = run_diagnosis_sync(sample_path / "interface_fault.json", topology=topology)
    assert report.root_cause_code == CauseCode.INTERFACE_FAULT
    assert report.status == "diagnosed"
    assert report.confidence >= 0.75
    assert "ACC_SW_CSE_01" in report.affected_devices


def test_e2e_dns_failure(sample_path, topology):
    report = run_diagnosis_sync(sample_path / "dns_failure.json", topology=topology)
    assert report.root_cause_code == CauseCode.DNS_FAILURE
    assert report.status == "diagnosed"
    assert report.confidence >= 0.60
    assert "SRV_DNS_01" in report.affected_devices


def test_e2e_dhcp_failure(sample_path, topology):
    report = run_diagnosis_sync(sample_path / "dhcp_failure.json", topology=topology)
    assert report.root_cause_code == CauseCode.DHCP_FAILURE
    assert report.status == "diagnosed"
    assert report.confidence >= 0.60
    assert "SRV_DHCP_01" in report.affected_devices


def test_e2e_upstream_congestion(sample_path, topology):
    report = run_diagnosis_sync(sample_path / "upstream_congestion.json", topology=topology)
    assert report.root_cause_code == CauseCode.UPSTREAM_CONGESTION
    assert report.status == "diagnosed"
    assert report.confidence >= 0.75
    assert "GW_NKN_ISP" in report.affected_devices


def test_e2e_device_cpu_overload(sample_path, topology):
    report = run_diagnosis_sync(sample_path / "device_cpu_overload.json", topology=topology)
    assert report.root_cause_code == CauseCode.DEVICE_CPU_OVERLOAD
    assert report.status == "diagnosed"
    assert report.confidence >= 0.70
    assert "ACC_SW_LHC_01" in report.affected_devices


def test_e2e_ambiguous_insufficient(sample_path, topology):
    report = run_diagnosis_sync(sample_path / "ambiguous_insufficient.json", topology=topology)
    assert report.status == "insufficient_evidence"
    assert report.root_cause_code == CauseCode.UNKNOWN
    assert report.suspected_root_cause == "Undetermined"
    assert report.confidence < 0.50


def test_e2e_legacy_schema_0_9(sample_path, topology):
    report = run_diagnosis_sync(sample_path / "legacy_schema_0_9.json", topology=topology)
    assert report.root_cause_code == CauseCode.LINK_CONGESTION
    assert report.status == "diagnosed"
    assert len(report.normalization_log) > 0


def test_e2e_mixed_units(sample_path, topology):
    report = run_diagnosis_sync(sample_path / "mixed_units.json", topology=topology)
    assert report.root_cause_code == CauseCode.LINK_CONGESTION
    assert report.status == "diagnosed"
    assert len(report.normalization_log) > 0


def test_e2e_missing_fields(sample_path, topology):
    report = run_diagnosis_sync(sample_path / "missing_fields.json", topology=topology)
    # Missing required fields must produce lower completeness and partial status
    assert report.status == "partial"
    assert report.confidence < 0.80
    assert len(report.limitations) > 0


def test_e2e_unknown_schema_version(sample_path, topology):
    report = run_diagnosis_sync(sample_path / "unknown_schema_version.json", topology=topology)
    assert report.status == "invalid_input"
    assert report.suspected_root_cause == "Undetermined"


def test_e2e_corrupted_json(sample_path, topology):
    report = run_diagnosis_sync(sample_path / "corrupted_json.json", topology=topology)
    assert report.status == "invalid_input"
    assert report.suspected_root_cause == "Undetermined"