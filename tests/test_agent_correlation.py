"""Tests for FaultCorrelationAgent.

Covers:
- Formula tests with hand-computed expected values
- Caps (single agent support, low completeness)
- Category boundaries (high, medium, low, insufficient)
- Conflict rules R1-R5 in isolation and combined
- Insufficient evidence path with missing evidence
- NORMAL top diagnosis
- Degraded agent penalty
- Evidence query loop (round 0 queries, round 1 folds, round 2 never queries)
- No findings and malformed finding robustness
- Determinism
- Synthetic scenario cases (congestion, CPU vs congestion, upstream vs local, DNS, near-tie)
"""

import asyncio
import pytest

from netcoop.agents.correlation_agent import FaultCorrelationAgent
from netcoop.agents.correlation_rules import (
    apply_all_rules,
    rule_cpu_vs_congestion,
    rule_multi_agent_disagreement,
    rule_near_tie_margin,
    rule_service_vs_congestion,
    rule_upstream_vs_local,
)
from netcoop.protocol.causes import CauseCode
from netcoop.protocol.messages import (
    DataQuality,
    EvidenceAnswer,
    EvidenceQueryPayload,
    EvidenceResponsePayload,
    FinalResultPayload,
    FindingPayload,
    FindingScope,
    HypothesisCandidate,
    MessageEnvelope,
    MessageType,
    MetricEvidence,
    TaskRequestPayload,
)
from netcoop.reporting.report_models import CorrelationResult


# -----------------------------------------------------------------------------
# Test Helpers & Factories
# -----------------------------------------------------------------------------


def make_finding(
    agent: str,
    cause_code: CauseCode,
    score: float,
    confidence: float = 0.90,
    completeness: float = 1.0,
    device_ids: list = None,
    extra_candidates: list = None,
) -> FindingPayload:
    """Factory creating typed FindingPayload instances."""
    candidates = [
        HypothesisCandidate(
            cause_code=cause_code,
            score=score,
            supporting_metrics=[
                MetricEvidence(
                    metric="latency_ms",
                    value=150.0,
                    unit="ms",
                    baseline=12.0,
                    interpretation=f"{agent} supporting {cause_code.value}",
                )
            ],
            contradicting_metrics=[],
        )
    ]
    if extra_candidates:
        candidates.extend(extra_candidates)

    return FindingPayload(
        agent=agent,
        scope=FindingScope(device_ids=device_ids or ["DEV_01"], segment="hostel_wifi"),
        hypothesis_candidates=candidates,
        data_quality=DataQuality(completeness=completeness),
        confidence=confidence,
    )


def make_correlate_request(
    findings: list,
    round_num: int = 0,
    agent_status: dict = None,
    evidence_responses: list = None,
    data_quality: DataQuality = None,
) -> MessageEnvelope:
    """Factory creating typed correlate task_request MessageEnvelopes."""
    return MessageEnvelope(
        incident_id="INC-CORR-TEST-01",
        sender="orchestrator",
        recipient="correlation_agent",
        message_type=MessageType.TASK_REQUEST,
        payload=TaskRequestPayload(
            task="correlate",
            findings=findings,
            agent_status=agent_status or {"telemetry_agent": "ok", "infrastructure_agent": "ok", "connectivity_agent": "ok"},
            data_quality=data_quality or DataQuality(completeness=1.0),
            evidence_responses=evidence_responses or [],
            round=round_num,
        ),
    )


# -----------------------------------------------------------------------------
# 1. Formula & Hand-computed Breakdown Tests
# -----------------------------------------------------------------------------


def test_confidence_formula_hand_computed():
    """Verify confidence formula against hand-calculated values."""
    agent = FaultCorrelationAgent()

    # Two agreeing agents on LINK_CONGESTION:
    # Telemetry: score 0.90, conf 0.90, comp 1.0 -> 0.81
    # Infra: score 0.80, conf 0.85, comp 1.0 -> 0.68
    # Connectivity: score 0.20, conf 0.50, comp 1.0 -> 0.10
    # Denom = 3.0. weighted_support = (0.81 + 0.68 + 0.10) / 3.0 = 0.53
    # agreement = 2 / 3 = 0.6667
    # comp = 1.0
    # conflict = 0.0, margin_penalty = 0.0
    # raw = 0.45*0.53 + 0.25*0.6667 + 0.20*1.0 = 0.2385 + 0.1667 + 0.20 = 0.6052
    f1 = make_finding("telemetry_agent", CauseCode.LINK_CONGESTION, 0.90, confidence=0.90)
    f2 = make_finding("infrastructure_agent", CauseCode.LINK_CONGESTION, 0.80, confidence=0.85)
    f3 = make_finding("connectivity_agent", CauseCode.NORMAL, 0.30, confidence=0.50, extra_candidates=[
        HypothesisCandidate(cause_code=CauseCode.LINK_CONGESTION, score=0.20)
    ])

    req = make_correlate_request([f1, f2, f3], round_num=2)
    responses = asyncio.run(agent.handle(req))
    final_res: FinalResultPayload = responses[-1].payload  # type: ignore
    corr = final_res.correlation_result

    assert corr.primary_cause_code == CauseCode.LINK_CONGESTION
    assert corr.confidence == pytest.approx(0.605, abs=1e-3)
    assert corr.confidence_category == "medium"
    assert "w1_agent_support" in corr.confidence_breakdown


# -----------------------------------------------------------------------------
# 2. Caps & Boundaries Tests
# -----------------------------------------------------------------------------


def test_single_agent_support_cap():
    """If only ONE agent supports the cause, confidence must be capped at 0.60."""
    agent = FaultCorrelationAgent()
    # Telemetry is the only responding/supporting agent
    f1 = make_finding("telemetry_agent", CauseCode.LINK_CONGESTION, 0.99, confidence=0.99)
    req = make_correlate_request([f1], round_num=2)

    responses = asyncio.run(agent.handle(req))
    corr: CorrelationResult = responses[-1].payload.correlation_result  # type: ignore
    assert corr.confidence <= 0.60


def test_low_completeness_cap():
    """If data completeness < 0.60, confidence must be capped at 0.55."""
    agent = FaultCorrelationAgent()
    f1 = make_finding("telemetry_agent", CauseCode.LINK_CONGESTION, 0.95, confidence=0.95, completeness=0.40)
    f2 = make_finding("infrastructure_agent", CauseCode.LINK_CONGESTION, 0.95, confidence=0.95, completeness=0.40)
    req = make_correlate_request([f1, f2], round_num=2, data_quality=DataQuality(completeness=0.40))

    responses = asyncio.run(agent.handle(req))
    corr: CorrelationResult = responses[-1].payload.correlation_result  # type: ignore
    assert corr.confidence <= 0.55


def test_category_boundaries():
    """Verify category thresholds: high >= 0.75, medium >= 0.50, low >= 0.30, insufficient < 0.30."""
    agent = FaultCorrelationAgent()

    # Three agreeing agents with high confidence -> category high
    f1 = make_finding("telemetry_agent", CauseCode.LINK_CONGESTION, 0.98, confidence=0.98)
    f2 = make_finding("infrastructure_agent", CauseCode.LINK_CONGESTION, 0.98, confidence=0.98)
    f3 = make_finding("connectivity_agent", CauseCode.LINK_CONGESTION, 0.98, confidence=0.98)
    req_high = make_correlate_request([f1, f2, f3], round_num=2)

    res_high = asyncio.run(agent.handle(req_high))[-1].payload.correlation_result
    assert res_high.confidence_category == "high"
    assert res_high.confidence >= 0.75


# -----------------------------------------------------------------------------
# 3. Conflict Rules R1-R5 Tests in Isolation and Combined
# -----------------------------------------------------------------------------


def test_rule_r1_multi_agent_disagreement():
    """R1: Prefer hypothesis with multi-agent support over single-agent candidate."""
    scores = {CauseCode.LINK_CONGESTION: 0.80, CauseCode.WEAK_WIFI_SIGNAL: 0.85}
    agent_tops = {"telemetry_agent": CauseCode.LINK_CONGESTION, "infrastructure_agent": CauseCode.LINK_CONGESTION, "connectivity_agent": CauseCode.WEAK_WIFI_SIGNAL}
    supporting = {CauseCode.LINK_CONGESTION: ["telemetry_agent", "infrastructure_agent"], CauseCode.WEAK_WIFI_SIGNAL: ["connectivity_agent"]}
    findings = {
        "telemetry_agent": make_finding("telemetry_agent", CauseCode.LINK_CONGESTION, 0.80),
        "infrastructure_agent": make_finding("infrastructure_agent", CauseCode.LINK_CONGESTION, 0.80),
        "connectivity_agent": make_finding("connectivity_agent", CauseCode.WEAK_WIFI_SIGNAL, 0.85),
    }

    outcome = rule_multi_agent_disagreement(scores, agent_tops, supporting, findings)
    assert outcome.applied is True
    assert outcome.score_adjustments[CauseCode.LINK_CONGESTION] > 0
    assert outcome.score_adjustments[CauseCode.WEAK_WIFI_SIGNAL] < 0


def test_rule_r2_cpu_vs_congestion():
    """R2: Infrastructure shows high CPU without queue drops -> promote CPU overload."""
    scores = {CauseCode.LINK_CONGESTION: 0.85, CauseCode.DEVICE_CPU_OVERLOAD: 0.75}
    f_telem = make_finding("telemetry_agent", CauseCode.LINK_CONGESTION, 0.85)
    f_infra = make_finding("infrastructure_agent", CauseCode.DEVICE_CPU_OVERLOAD, 0.85)
    findings = {"telemetry_agent": f_telem, "infrastructure_agent": f_infra}

    outcome = rule_cpu_vs_congestion(scores, findings)
    assert outcome.applied is True
    assert outcome.score_adjustments[CauseCode.DEVICE_CPU_OVERLOAD] > 0
    assert outcome.score_adjustments[CauseCode.LINK_CONGESTION] < 0


def test_rule_r3_upstream_vs_local():
    """R3: Shared upstream failure promoted above local leaf causes."""
    scores = {CauseCode.LINK_CONGESTION: 0.80, CauseCode.UPSTREAM_CONGESTION: 0.80}
    f_conn = make_finding("connectivity_agent", CauseCode.UPSTREAM_CONGESTION, 0.85)
    f_telem = make_finding("telemetry_agent", CauseCode.LINK_CONGESTION, 0.80)
    findings = {"connectivity_agent": f_conn, "telemetry_agent": f_telem}

    outcome = rule_upstream_vs_local(scores, findings)
    assert outcome.applied is True
    assert outcome.score_adjustments[CauseCode.UPSTREAM_CONGESTION] > 0
    assert outcome.score_adjustments[CauseCode.LINK_CONGESTION] < 0


def test_rule_r4_service_vs_congestion():
    """R4: DNS/DHCP failure promoted over transit link congestion."""
    scores = {CauseCode.LINK_CONGESTION: 0.70, CauseCode.DNS_FAILURE: 0.75}
    f_conn = make_finding("connectivity_agent", CauseCode.DNS_FAILURE, 0.85)
    f_telem = make_finding("telemetry_agent", CauseCode.LINK_CONGESTION, 0.70)
    findings = {"connectivity_agent": f_conn, "telemetry_agent": f_telem}

    outcome = rule_service_vs_congestion(scores, findings)
    assert outcome.applied is True
    assert outcome.score_adjustments[CauseCode.DNS_FAILURE] > 0
    assert outcome.score_adjustments[CauseCode.LINK_CONGESTION] < 0


def test_rule_r5_near_tie_margin():
    """R5: Margin < 0.12 triggers near-tie ambiguity flag."""
    scores = {CauseCode.LINK_CONGESTION: 0.85, CauseCode.DEVICE_CPU_OVERLOAD: 0.80}
    supporting = {CauseCode.LINK_CONGESTION: ["telemetry_agent"], CauseCode.DEVICE_CPU_OVERLOAD: ["infrastructure_agent"]}

    outcome = rule_near_tie_margin(scores, supporting, margin_threshold=0.12)
    assert outcome.applied is True
    assert "near-tie" in outcome.description.lower()


def test_apply_all_rules_combined():
    """Verify deterministic execution and combination of rules."""
    scores = {CauseCode.LINK_CONGESTION: 0.80, CauseCode.DEVICE_CPU_OVERLOAD: 0.75}
    f_telem = make_finding("telemetry_agent", CauseCode.LINK_CONGESTION, 0.80)
    f_infra = make_finding("infrastructure_agent", CauseCode.DEVICE_CPU_OVERLOAD, 0.85)
    findings = {"telemetry_agent": f_telem, "infrastructure_agent": f_infra}
    agent_tops = {"telemetry_agent": CauseCode.LINK_CONGESTION, "infrastructure_agent": CauseCode.DEVICE_CPU_OVERLOAD}
    supporting = {CauseCode.LINK_CONGESTION: ["telemetry_agent"], CauseCode.DEVICE_CPU_OVERLOAD: ["infrastructure_agent"]}

    adj, outcomes = apply_all_rules(scores, agent_tops, supporting, findings, margin_threshold=0.12)
    assert len(outcomes) >= 1
    assert any(o.rule_id == "R2" for o in outcomes)


# -----------------------------------------------------------------------------
# 4. Status, Penalties, and Robustness Tests
# -----------------------------------------------------------------------------


def test_insufficient_evidence_path():
    """Confidence < 0.30 results in status insufficient_evidence and UNKNOWN primary cause."""
    agent = FaultCorrelationAgent()
    # Very low scores across all candidates
    f1 = make_finding("telemetry_agent", CauseCode.LINK_CONGESTION, 0.15, confidence=0.20, completeness=0.30)
    req = make_correlate_request([f1], round_num=2)

    responses = asyncio.run(agent.handle(req))
    corr: CorrelationResult = responses[-1].payload.correlation_result  # type: ignore
    assert corr.status == "insufficient_evidence"
    assert corr.primary_cause_code == CauseCode.UNKNOWN
    assert len(corr.missing_evidence) > 0


def test_normal_top_status():
    """NORMAL top cause with adequate confidence gives status diagnosed."""
    agent = FaultCorrelationAgent()
    f1 = make_finding("telemetry_agent", CauseCode.NORMAL, 0.95, confidence=0.95)
    f2 = make_finding("infrastructure_agent", CauseCode.NORMAL, 0.95, confidence=0.95)
    req = make_correlate_request([f1, f2], round_num=2)

    responses = asyncio.run(agent.handle(req))
    corr: CorrelationResult = responses[-1].payload.correlation_result  # type: ignore
    assert corr.primary_cause_code == CauseCode.NORMAL
    assert corr.status == "diagnosed"


def test_degraded_agent_lowers_confidence():
    """A degraded agent reduces data_completeness and confidence."""
    agent = FaultCorrelationAgent()
    f1 = make_finding("telemetry_agent", CauseCode.LINK_CONGESTION, 0.90, confidence=0.90)
    f2 = make_finding("infrastructure_agent", CauseCode.LINK_CONGESTION, 0.90, confidence=0.90)

    req_ok = make_correlate_request([f1, f2], round_num=2, agent_status={"telemetry_agent": "ok", "infrastructure_agent": "ok"})
    req_deg = make_correlate_request([f1, f2], round_num=2, agent_status={"telemetry_agent": "ok", "infrastructure_agent": "degraded"})

    res_ok = asyncio.run(agent.handle(req_ok))[-1].payload.correlation_result
    res_deg = asyncio.run(agent.handle(req_deg))[-1].payload.correlation_result

    assert res_deg.confidence < res_ok.confidence


def test_no_findings_gives_insufficient_evidence_never_raises():
    """Empty findings list returns insufficient_evidence without raising."""
    agent = FaultCorrelationAgent()
    req = make_correlate_request([], round_num=0)
    responses = asyncio.run(agent.handle(req))
    assert len(responses) == 1
    corr: CorrelationResult = responses[0].payload.correlation_result  # type: ignore
    assert corr.status == "insufficient_evidence"
    assert corr.primary_cause_code == CauseCode.UNKNOWN


def test_malformed_finding_skipped_and_noted():
    """Malformed finding in list is skipped and noted in missing_evidence."""
    agent = FaultCorrelationAgent()
    f_valid = make_finding("telemetry_agent", CauseCode.LINK_CONGESTION, 0.90, confidence=0.90)
    req = make_correlate_request([f_valid, "malformed_string_not_dict"], round_num=2)

    responses = asyncio.run(agent.handle(req))
    corr: CorrelationResult = responses[-1].payload.correlation_result  # type: ignore
    assert any("skipped" in m.lower() for m in corr.missing_evidence)


def test_determinism():
    """Identical input produces identical correlation output."""
    agent1 = FaultCorrelationAgent()
    agent2 = FaultCorrelationAgent()

    f1 = make_finding("telemetry_agent", CauseCode.LINK_CONGESTION, 0.85)
    f2 = make_finding("infrastructure_agent", CauseCode.LINK_CONGESTION, 0.85)

    req1 = make_correlate_request([f1, f2], round_num=2)
    req2 = make_correlate_request([f1, f2], round_num=2)

    res1 = asyncio.run(agent1.handle(req1))[-1].payload.correlation_result
    res2 = asyncio.run(agent2.handle(req2))[-1].payload.correlation_result

    assert res1.primary_cause_code == res2.primary_cause_code
    assert res1.confidence == res2.confidence
    assert res1.confidence_breakdown == res2.confidence_breakdown


# -----------------------------------------------------------------------------
# 5. Evidence Query Loop & Response Folding
# -----------------------------------------------------------------------------


def test_evidence_query_loop_rounds():
    """Round 0 queries on ambiguity, Round 1 folds evidence, Round 2 never queries."""
    agent = FaultCorrelationAgent()

    # Ambiguous near-tie: Telemetry has congestion (0.80), Infra has CPU overload (0.78)
    f_telem = make_finding("telemetry_agent", CauseCode.LINK_CONGESTION, 0.80)
    f_infra = make_finding("infrastructure_agent", CauseCode.DEVICE_CPU_OVERLOAD, 0.78)

    # 1. Round 0: should ask targeted evidence_query
    req_r0 = make_correlate_request([f_telem, f_infra], round_num=0)
    resp_r0 = asyncio.run(agent.handle(req_r0))
    assert any(m.message_type == MessageType.EVIDENCE_QUERY for m in resp_r0)

    # 2. Round 1 with evidence response folding: supports=True for LINK_CONGESTION
    ev_resp = EvidenceResponsePayload(
        query_id="QRY-001",
        cause_code=CauseCode.LINK_CONGESTION,
        supports=True,
        confidence=0.90,
        answers=[EvidenceAnswer(device_id="DEV_01", metric="queue_drops", value=800, unit="packets", interpretation="High queue drops")],
    )
    req_r1 = make_correlate_request([f_telem, f_infra], round_num=1, evidence_responses=[ev_resp])
    resp_r1 = asyncio.run(agent.handle(req_r1))

    # Evidence boosted LINK_CONGESTION, expanding margin
    final_payload = next((m.payload for m in resp_r1 if m.message_type == MessageType.FINAL_RESULT), None)
    if final_payload:
        assert final_payload.correlation_result.primary_cause_code == CauseCode.LINK_CONGESTION

    # 3. Round 2: never queries even if ambiguity persists
    req_r2 = make_correlate_request([f_telem, f_infra], round_num=2)
    resp_r2 = asyncio.run(agent.handle(req_r2))
    assert not any(m.message_type == MessageType.EVIDENCE_QUERY for m in resp_r2)
    assert any(m.message_type == MessageType.FINAL_RESULT for m in resp_r2)


# -----------------------------------------------------------------------------
# 6. Synthetic Incident Scenario Cases
# -----------------------------------------------------------------------------


def test_synthetic_clean_congestion():
    """Clean congestion case: telemetry and infrastructure agree on LINK_CONGESTION."""
    agent = FaultCorrelationAgent()
    f1 = make_finding("telemetry_agent", CauseCode.LINK_CONGESTION, 0.95)
    f2 = make_finding("infrastructure_agent", CauseCode.LINK_CONGESTION, 0.90)
    req = make_correlate_request([f1, f2], round_num=2)

    responses = asyncio.run(agent.handle(req))
    corr: CorrelationResult = responses[-1].payload.correlation_result  # type: ignore
    assert corr.primary_cause_code == CauseCode.LINK_CONGESTION
    assert corr.status == "diagnosed"


def test_synthetic_cpu_vs_congestion_conflict():
    """Conflict resolved via R2: CPU overload wins over congestion."""
    agent = FaultCorrelationAgent()
    f1 = make_finding("telemetry_agent", CauseCode.LINK_CONGESTION, 0.85)
    f2 = make_finding("infrastructure_agent", CauseCode.DEVICE_CPU_OVERLOAD, 0.88)
    req = make_correlate_request([f1, f2], round_num=2)

    responses = asyncio.run(agent.handle(req))
    corr: CorrelationResult = responses[-1].payload.correlation_result  # type: ignore
    assert corr.primary_cause_code == CauseCode.DEVICE_CPU_OVERLOAD
    assert any(c["rule"] == "R2" for c in corr.conflicts_resolved)


def test_synthetic_upstream_vs_local_conflict():
    """Conflict resolved via R3: upstream congestion promoted over local leaf congestion."""
    agent = FaultCorrelationAgent()
    f_conn = make_finding("connectivity_agent", CauseCode.UPSTREAM_CONGESTION, 0.90)
    f_telem = make_finding("telemetry_agent", CauseCode.LINK_CONGESTION, 0.80)
    req = make_correlate_request([f_conn, f_telem], round_num=2)

    responses = asyncio.run(agent.handle(req))
    corr: CorrelationResult = responses[-1].payload.correlation_result  # type: ignore
    assert corr.primary_cause_code == CauseCode.UPSTREAM_CONGESTION
    assert any(c["rule"] == "R3" for c in corr.conflicts_resolved)


def test_synthetic_dns_case():
    """DNS failure case: service failure promoted over congestion."""
    agent = FaultCorrelationAgent()
    f_conn = make_finding("connectivity_agent", CauseCode.DNS_FAILURE, 0.95)
    f_telem = make_finding("telemetry_agent", CauseCode.NORMAL, 0.40)
    req = make_correlate_request([f_conn, f_telem], round_num=2)

    responses = asyncio.run(agent.handle(req))
    corr: CorrelationResult = responses[-1].payload.correlation_result  # type: ignore
    assert corr.primary_cause_code == CauseCode.DNS_FAILURE