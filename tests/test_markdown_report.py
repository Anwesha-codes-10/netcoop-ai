"""Tests for netcoop.reporting.markdown_report."""

from pathlib import Path

import pytest

from netcoop.orchestrator import run_diagnosis_sync
from netcoop.protocol.causes import CauseCode
from netcoop.reporting.markdown_report import render_markdown
from netcoop.reporting.report_models import FinalReport, RecommendedAction

SAMPLES = Path(__file__).resolve().parent.parent / "data" / "samples"


@pytest.fixture
def isolated_logs(tmp_path, monkeypatch):
    """Run diagnoses from a temp cwd so logs/ never pollutes the repo."""
    monkeypatch.chdir(tmp_path)
    return tmp_path


def _minimal(**overrides) -> FinalReport:
    data = dict(
        incident_id="INC-TEST0001",
        status="diagnosed",
        suspected_root_cause="Link Congestion",
        root_cause_code=CauseCode.LINK_CONGESTION,
        confidence=0.8,
        confidence_category="high",
    )
    data.update(overrides)
    return FinalReport(**data)


def test_diagnosed_real_report_has_all_sections(isolated_logs):
    report = run_diagnosis_sync(SAMPLES / "link_congestion.json")
    md = render_markdown(report)
    assert md.startswith(f"# Incident {report.incident_id} - Diagnosed")
    for heading in (
        "## Suspected Cause",
        "## Affected Devices and Segments",
        "## Supporting Evidence",
        "## Alternative Causes",
        "## Recommended Actions",
        "## Simulated Remediation Preview",
        "## Conflicts Resolved",
        "## Limitations",
        "## Data Quality",
        "## Normalization Log",
        "## Agent Status",
        "## Trace Reference",
    ):
        assert heading in md
    assert "LINK_CONGESTION" in md
    assert "DIST_SW_HOSTEL" in md
    assert "| Metric | Value | Unit | Device | Source agent | Interpretation |" in md
    assert "requires human review" in md
    assert report.message_trace_ref in md


def test_no_emojis_and_ascii_only_structure(isolated_logs):
    md = render_markdown(run_diagnosis_sync(SAMPLES / "dns_failure.json"))
    assert all(ord(ch) < 0x2190 for ch in md), "unexpected pictographic characters"


def test_actions_in_priority_order():
    report = _minimal(
        recommended_actions=[
            RecommendedAction(priority=2, action="second step", rationale="r2"),
            RecommendedAction(priority=1, action="first step", rationale="r1"),
        ]
    )
    md = render_markdown(report)
    assert md.index("first step") < md.index("second step")


def test_pipe_escaped_in_table_cells():
    report = _minimal(
        supporting_evidence=[
            {
                "metric": "a|b",
                "value": 1.5,
                "unit": "%",
                "device_id": "DEV|1",
                "source_agent": "telemetry_agent",
                "interpretation": "x | y\nnewline",
            }
        ]
    )
    md = render_markdown(report)
    assert "a\\|b" in md
    assert "DEV\\|1" in md
    assert "x \\| y newline" in md
    row = next(line for line in md.splitlines() if "telemetry_agent" in line)
    assert row.replace("\\|", "").count("|") == 7  # 6 cells -> 7 unescaped separators


def test_empty_sections_handled_gracefully():
    md = render_markdown(_minimal())
    assert "No supporting evidence recorded." in md
    assert "No alternative causes recorded." in md
    assert "No actions recommended." in md
    assert "No remediation preview available." in md
    assert "No conflicts between agents were detected." in md
    assert "No normalization performed." in md
    assert "No agents ran for this incident." in md
    assert "No trace reference recorded." in md
    assert "None identified." in md
    assert "None" not in md.replace("None identified.", "").replace("None recorded.", "")


def test_normalization_log_summarises_identity_rows():
    report = _minimal(
        normalization_log=[
            {"field_original": "latency_s", "canonical_field": "latency_ms", "original_value": 0.2,
             "original_unit": "s", "canonical_value": 200.0, "canonical_unit": "ms", "rule": "seconds_to_ms"},
            {"field_original": "bandwidth_mbps", "canonical_field": "bandwidth_mbps", "original_value": 1000.0,
             "original_unit": "Mbps", "canonical_value": 1000.0, "canonical_unit": "Mbps", "rule": "identity"},
        ]
    )
    md = render_markdown(report)
    assert "seconds_to_ms" in md
    assert "1 field value(s) were already canonical" in md


def test_insufficient_evidence_report_is_plain(isolated_logs):
    report = run_diagnosis_sync(SAMPLES / "ambiguous_insufficient.json")
    assert report.status == "insufficient_evidence"
    md = render_markdown(report)
    assert "Insufficient evidence" in md.splitlines()[0]
    assert "No diagnosis is asserted." in md
    assert "Hypotheses Considered (not conclusions)" in md
    assert "**Cause code:**" not in md
    cause_section = md.split("## Suspected Cause")[1].split("## ")[0]
    assert "UNKNOWN" not in cause_section


def test_invalid_input_report_is_plain(isolated_logs):
    report = run_diagnosis_sync(SAMPLES / "corrupted_json.json")
    assert report.status == "invalid_input"
    md = render_markdown(report)
    assert md.splitlines()[0].endswith("Invalid input")
    assert "No diagnosis was produced" in md
    assert "line 9 column 3" in md
    assert "## Supporting Evidence" not in md
    assert "**Cause code:**" not in md


def test_partial_report_does_not_claim_a_cause(isolated_logs):
    report = run_diagnosis_sync(SAMPLES / "missing_fields.json")
    assert report.status == "partial"
    md = render_markdown(report)
    assert "none is asserted" in md
    assert "**Cause code:**" not in md


def test_conflicts_resolved_rendered(isolated_logs):
    report = run_diagnosis_sync(SAMPLES / "upstream_congestion.json")
    assert report.conflicts_resolved
    md = render_markdown(report)
    rule = report.conflicts_resolved[0]["rule"]
    assert rule in md.split("## Conflicts Resolved")[1]


def test_ends_with_single_newline():
    md = render_markdown(_minimal())
    assert md.endswith("\n") and not md.endswith("\n\n")
