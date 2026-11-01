"""Tests for RecommendationReportingAgent and build_invalid_input_report.

Covers:
- One test per canonical CauseCode (action list non-empty, ordered, requires_human_review True, preview starts with SIMULATED)
- Insufficient evidence report (cause Undetermined, actions about collecting evidence, missing_evidence in limitations)
- Near-tie report with alternative causes and verification action
- Degraded agent gives status 'partial' with agent named in limitations
- Low completeness gives status 'partial'
- NORMAL gives 'No fault detected'
- Supporting evidence ordering and capping
- build_invalid_input_report for corrupted_json, empty input, unknown schema
- Full report JSON round-trip
- Malformed task_request gives error
- Output determinism
"""

import asyncio
import json
import pytest

from netcoop.agents.reporting_agent import (
    RecommendationReportingAgent,
    build_invalid_input_report,
)
from netcoop.protocol.causes import CauseCode
from netcoop.protocol.messages import (
    DataQuality,
    FinalResultPayload,
    MessageEnvelope,
    MessageType,
    TaskRequestPayload,
)
from netcoop.protocol.validators import ErrorCode, ValidationIssue, ValidationResult
from netcoop.reporting.report_models import (
    CorrelationResult,
    FinalReport,
    RankedHypothesis,
    RecommendedAction,
)


# -----------------------------------------------------------------------------
# Helpers & Factories
# -----------------------------------------------------------------------------


def make_correlation_result(
    primary_cause_code: CauseCode,
    confidence: float = 0.85,
    status: str = "diagnosed",
    confidence_category: str = "high",
    conflicts_resolved: list = None,
    missing_evidence: list = None,
    runner_up: CauseCode = None,
) -> CorrelationResult:
    """Factory creating typed CorrelationResult instances."""
    ranked = [
        RankedHypothesis(
            cause_code=primary_cause_code,
            score=confidence,
            supporting_agents=["telemetry_agent", "infrastructure_agent"],
            supporting_evidence=[
                {
                    "metric": "link_utilization_pct",
                    "value": 95.0,
                    "unit": "%",
                    "interpretation": "Critical link saturation",
                    "device_id": "DIST_SW_HOSTEL",
                    "source_agent": "telemetry_agent",
                }
            ],
            contradicting_evidence=[],
        )
    ]
    if runner_up:
        ranked.append(
            RankedHypothesis(
                cause_code=runner_up,
                score=round(confidence - 0.05, 2),
                supporting_agents=["connectivity_agent"],
                supporting_evidence=[],
                contradicting_evidence=[
                    {
                        "metric": "cpu_pct",
                        "value": 25.0,
                        "unit": "%",
                        "interpretation": "CPU is nominal, contradicting overload",
                    }
                ],
            )
        )

    return CorrelationResult(
        ranked_hypotheses=ranked,
        primary_cause_code=primary_cause_code,
        confidence=confidence,
        confidence_category=confidence_category,
        status=status,
        conflicts_resolved=conflicts_resolved or [],
        missing_evidence=missing_evidence or [],
        affected_devices=["DIST_SW_HOSTEL"],
        affected_segments=["hostel_wifi"],
        agent_support={"telemetry_agent": 0.90, "infrastructure_agent": 0.85},
        query_rounds_used=0,
        confidence_breakdown={"w1": 0.4, "w2": 0.25, "w3": 0.2},
    )


def make_report_request(
    correlation_result: CorrelationResult,
    agent_status: dict = None,
    data_quality: DataQuality = None,
    normalization_log: list = None,
) -> MessageEnvelope:
    """Factory creating typed report task_request MessageEnvelopes."""
    return MessageEnvelope(
        incident_id="INC-REPORT-001",
        sender="orchestrator",
        recipient="reporting_agent",
        message_type=MessageType.TASK_REQUEST,
        payload=TaskRequestPayload(
            task="report",
            correlation_result=correlation_result,
            agent_status=agent_status or {"telemetry_agent": "ok", "infrastructure_agent": "ok"},
            data_quality=data_quality or DataQuality(completeness=1.0),
            normalization_log=normalization_log or [],
            message_trace_ref="TRACE-001",
        ),
    )


# -----------------------------------------------------------------------------
# 1. Cause-Specific Recommendations & Preview Tests (All 10 CauseCodes)
# -----------------------------------------------------------------------------


@pytest.mark.parametrize(
    "cause_code",
    [
        CauseCode.LINK_CONGESTION,
        CauseCode.WEAK_WIFI_SIGNAL,
        CauseCode.INTERFACE_FAULT,
        CauseCode.DEVICE_CPU_OVERLOAD,
        CauseCode.UPSTREAM_CONGESTION,
        CauseCode.DNS_FAILURE,
        CauseCode.DHCP_FAILURE,
        CauseCode.HARDWARE_FAILURE,
        CauseCode.NORMAL,
        CauseCode.UNKNOWN,
    ],
)
def test_actions_for_every_cause_code(cause_code):
    """Verify that every canonical CauseCode produces non-empty actions and valid SIMULATED: previews."""
    agent = RecommendationReportingAgent()
    corr = make_correlation_result(primary_cause_code=cause_code)
    req = make_report_request(corr)

    responses = asyncio.run(agent.handle(req))
    assert len(responses) == 1
    final_payload: FinalResultPayload = responses[0].payload  # type: ignore
    report: FinalReport = final_payload.report  # type: ignore

    # Verify actions
    assert len(report.recommended_actions) > 0
    for i in range(len(report.recommended_actions) - 1):
        assert report.recommended_actions[i].priority <= report.recommended_actions[i + 1].priority
    assert all(a.requires_human_review is True for a in report.recommended_actions)

    # Verify simulated remediation preview
    assert report.simulated_remediation_preview is not None
    lines = report.simulated_remediation_preview.strip().split("\n")
    assert len(lines) > 0
    for line in lines:
        assert line.startswith("SIMULATED:"), f"Line '{line}' does not start with SIMULATED:"


# -----------------------------------------------------------------------------
# 2. Status & Condition Tests
# -----------------------------------------------------------------------------


def test_insufficient_evidence_report():
    """Verify that insufficient_evidence produces Undetermined cause, missing evidence actions & limitations."""
    agent = RecommendationReportingAgent()
    corr = make_correlation_result(
        primary_cause_code=CauseCode.UNKNOWN,
        confidence=0.20,
        status="insufficient_evidence",
        confidence_category="insufficient",
        missing_evidence=["queue drop counters for DIST_SW_HOSTEL"],
    )
    req = make_report_request(corr)

    report: FinalReport = asyncio.run(agent.handle(req))[0].payload.report  # type: ignore
    assert report.status == "insufficient_evidence"
    assert report.suspected_root_cause == "Undetermined"
    assert any("queue drop" in a.action.lower() for a in report.recommended_actions)
    assert any("queue drop" in lim.lower() for lim in report.limitations)


def test_near_tie_report_with_verification_action():
    """Verify that R5 near-tie appends verification action for runner-up and details alternative cause."""
    agent = RecommendationReportingAgent()
    corr = make_correlation_result(
        primary_cause_code=CauseCode.LINK_CONGESTION,
        confidence=0.80,
        runner_up=CauseCode.DEVICE_CPU_OVERLOAD,
        conflicts_resolved=[{"rule": "R5", "description": "Near-tie conflict between top two", "effect": "Flagged ambiguity"}],
    )
    req = make_report_request(corr)

    report: FinalReport = asyncio.run(agent.handle(req))[0].payload.report  # type: ignore
    assert len(report.alternative_causes) > 0
    assert report.alternative_causes[0]["cause"] == CauseCode.DEVICE_CPU_OVERLOAD.value
    assert len(report.alternative_causes[0]["why_less_likely"]) > 0

    # Verification action for runner-up
    assert any(CauseCode.DEVICE_CPU_OVERLOAD.value in a.action for a in report.recommended_actions)


def test_degraded_agent_gives_status_partial():
    """Verify that a degraded or timed out agent shifts status to 'partial' and is named in limitations."""
    agent = RecommendationReportingAgent()
    corr = make_correlation_result(primary_cause_code=CauseCode.LINK_CONGESTION)
    req = make_report_request(corr, agent_status={"telemetry_agent": "ok", "infrastructure_agent": "degraded"})

    report: FinalReport = asyncio.run(agent.handle(req))[0].payload.report  # type: ignore
    assert report.status == "partial"
    assert any("infrastructure_agent" in lim and "degraded" in lim for lim in report.limitations)


def test_low_completeness_gives_status_partial():
    """Verify that data completeness below threshold gives status 'partial'."""
    agent = RecommendationReportingAgent()
    corr = make_correlation_result(primary_cause_code=CauseCode.LINK_CONGESTION)
    req = make_report_request(corr, data_quality=DataQuality(completeness=0.45))

    report: FinalReport = asyncio.run(agent.handle(req))[0].payload.report  # type: ignore
    assert report.status == "partial"
    assert any("completeness" in lim.lower() for lim in report.limitations)


def test_normal_gives_no_fault_detected():
    """Verify that CauseCode.NORMAL outputs 'No fault detected' and diagnosed status."""
    agent = RecommendationReportingAgent()
    corr = make_correlation_result(primary_cause_code=CauseCode.NORMAL)
    req = make_report_request(corr)

    report: FinalReport = asyncio.run(agent.handle(req))[0].payload.report  # type: ignore
    assert report.suspected_root_cause == "No fault detected"
    assert report.status == "diagnosed"


# -----------------------------------------------------------------------------
# 3. Evidence Formatting & Capping Tests
# -----------------------------------------------------------------------------


def test_supporting_evidence_ordering_and_cap():
    """Verify supporting evidence is formatted correctly and capped at configured limit."""
    agent = RecommendationReportingAgent()
    # 8 evidence items
    ev_list = [
        {"metric": "latency_ms", "value": 100.0 + i, "unit": "ms", "interpretation": f"Item {i}"}
        for i in range(8)
    ]
    corr = make_correlation_result(primary_cause_code=CauseCode.LINK_CONGESTION)
    corr.ranked_hypotheses[0].supporting_evidence = ev_list

    req = make_report_request(corr)
    report: FinalReport = asyncio.run(agent.handle(req))[0].payload.report  # type: ignore

    # Capped at max_supporting_evidence (6)
    assert len(report.supporting_evidence) <= 6
    for item in report.supporting_evidence:
        assert "metric" in item
        assert "value" in item
        assert "unit" in item
        assert "interpretation" in item
        assert "device_id" in item
        assert "source_agent" in item


# -----------------------------------------------------------------------------
# 4. build_invalid_input_report Tests
# -----------------------------------------------------------------------------


def test_build_invalid_input_report_corrupted_json():
    """Verify invalid_input report generation for corrupted JSON errors."""
    v_issue = ValidationIssue(code=ErrorCode.CORRUPTED_JSON, message="Corrupted JSON syntax: line 5 col 10")
    report = build_invalid_input_report("INC-INVALID-01", [v_issue])

    assert report.status == "invalid_input"
    assert report.suspected_root_cause == "Undetermined"
    assert report.confidence == 0.0
    assert report.confidence_category == "insufficient"
    assert any("Corrupted JSON" in lim for lim in report.limitations)
    assert len(report.recommended_actions) > 0
    assert report.simulated_remediation_preview.startswith("SIMULATED:")


def test_build_invalid_input_report_empty_input():
    """Verify invalid_input report generation for empty input."""
    v_res = ValidationResult(
        ok=False,
        errors=[ValidationIssue(code=ErrorCode.EMPTY_INPUT, message="Input JSON is empty")],
        completeness=0.0,
    )
    report = build_invalid_input_report("INC-INVALID-02", v_res)
    assert report.status == "invalid_input"
    assert any("empty" in lim.lower() for lim in report.limitations)


def test_build_invalid_input_report_unknown_schema():
    """Verify invalid_input report generation for unknown schema version."""
    v_issue = ValidationIssue(code=ErrorCode.UNKNOWN_SCHEMA_VERSION, message="Unsupported schema version '2.5-beta'")
    report = build_invalid_input_report("INC-INVALID-03", [v_issue])
    assert report.status == "invalid_input"
    assert any("2.5-beta" in lim for lim in report.limitations)


# -----------------------------------------------------------------------------
# 5. Serialization & Robustness Tests
# -----------------------------------------------------------------------------


def test_json_round_trip_full_report():
    """Verify JSON round-trip serialization of FinalReport via to_json and from_json."""
    agent = RecommendationReportingAgent()
    corr = make_correlation_result(primary_cause_code=CauseCode.LINK_CONGESTION)
    req = make_report_request(corr)

    report: FinalReport = asyncio.run(agent.handle(req))[0].payload.report  # type: ignore
    json_str = report.to_json()
    assert isinstance(json_str, str)

    loaded = FinalReport.from_json(json_str)
    assert loaded.incident_id == report.incident_id
    assert loaded.status == report.status
    assert loaded.root_cause_code == report.root_cause_code
    assert loaded.confidence == report.confidence
    assert len(loaded.recommended_actions) == len(report.recommended_actions)


def test_malformed_input_gives_error():
    """Verify that a task_request missing correlation_result yields an error envelope without raising."""
    agent = RecommendationReportingAgent()
    bad_req = MessageEnvelope(
        incident_id="INC-BAD-01",
        sender="orchestrator",
        recipient="reporting_agent",
        message_type=MessageType.TASK_REQUEST,
        payload=TaskRequestPayload(task="report", correlation_result=None),
    )
    responses = asyncio.run(agent.handle(bad_req))
    assert len(responses) == 1
    assert responses[0].message_type == MessageType.ERROR


def test_determinism():
    """Verify that identical inputs produce identical reports."""
    agent1 = RecommendationReportingAgent()
    agent2 = RecommendationReportingAgent()

    corr = make_correlation_result(primary_cause_code=CauseCode.LINK_CONGESTION)
    req1 = make_report_request(corr)
    req2 = make_report_request(corr)

    rep1: FinalReport = asyncio.run(agent1.handle(req1))[0].payload.report  # type: ignore
    rep2: FinalReport = asyncio.run(agent2.handle(req2))[0].payload.report  # type: ignore

    assert rep1.to_json() == rep2.to_json()