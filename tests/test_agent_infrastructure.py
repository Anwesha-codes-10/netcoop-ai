"""Tests for InfrastructureHealthAgent.

Covers helper unit tests (status flapping, sustained check, trend),
domain scenario verifications, synthetic hardware failures,
CPU-high-with-queue-drops contradiction tests, missing/empty data,
malformed message rejection, and evidence queries with/without context.
"""

import asyncio
from datetime import datetime, timezone
import pytest

from netcoop.agents.infrastructure_agent import InfrastructureHealthAgent
from netcoop.protocol.causes import CauseCode
from netcoop.protocol.messages import (
    EvidenceQueryPayload,
    EvidenceResponsePayload,
    FindingPayload,
    MessageEnvelope,
    MessageType,
    TaskRequestPayload,
)
from tests.helpers import scenario_task_request


# -----------------------------------------------------------------------------
# Unit Tests for Helper Functions
# -----------------------------------------------------------------------------


def test_helper_status_flapping():
    agent = InfrastructureHealthAgent()
    # Flapping pattern: up -> degraded -> up -> degraded (3 transitions)
    statuses_flapping = ["up", "degraded", "up", "degraded"]
    trans, is_flap = agent.detect_status_flapping(statuses_flapping)
    assert trans == 3
    assert is_flap is True

    # Stable pattern: up -> up -> up (0 transitions)
    statuses_stable = ["up", "up", "up"]
    trans_s, is_flap_s = agent.detect_status_flapping(statuses_stable)
    assert trans_s == 0
    assert is_flap_s is False

    # Empty list
    assert agent.detect_status_flapping([]) == (0, False)


def test_helper_sustained_condition():
    agent = InfrastructureHealthAgent()
    # Sustained >= 75%: [80, 85, 90, 70] has a 3-consecutive run
    vals_sustained = [80.0, 85.0, 90.0, 70.0]
    assert agent.check_sustained_condition(vals_sustained, threshold=75.0, min_consecutive=2) is True

    # Intermittent: [80, 50, 85, 40] -> no 2 consecutive matches
    vals_intermittent = [80.0, 50.0, 85.0, 40.0]
    assert agent.check_sustained_condition(vals_intermittent, threshold=75.0, min_consecutive=2) is False

    # Short list
    assert agent.check_sustained_condition([90.0], threshold=75.0, min_consecutive=2) is False


def test_helper_counter_trend():
    agent = InfrastructureHealthAgent()
    t0 = datetime(2026, 10, 31, 10, 0, 0, tzinfo=timezone.utc)
    timestamps = [
        t0,
        datetime(2026, 10, 31, 10, 1, 0, tzinfo=timezone.utc),
        datetime(2026, 10, 31, 10, 2, 0, tzinfo=timezone.utc),
    ]
    # Errors rising: +10 errors per minute = +600 errors per hour
    values = [100.0, 110.0, 120.0]
    slope = agent.calculate_counter_trend(timestamps, values)
    assert round(slope, 1) == 600.0

    # Flat counter
    flat_slope = agent.calculate_counter_trend(timestamps, [50.0, 50.0, 50.0])
    assert abs(flat_slope) < 1e-4


def test_helper_rate_of_change():
    agent = InfrastructureHealthAgent()
    t0 = datetime(2026, 10, 31, 10, 0, 0, tzinfo=timezone.utc)
    timestamps = [
        t0,
        datetime(2026, 10, 31, 10, 2, 0, tzinfo=timezone.utc),
    ]
    # Queue drops change by 120 in 2 minutes = 60 drops per minute
    values = [10.0, 130.0]
    rate = agent.calculate_rate_of_change(timestamps, values)
    assert round(rate, 1) == 60.0


def test_helper_downtime_fraction():
    agent = InfrastructureHealthAgent()
    assert agent.calculate_downtime_fraction(["up", "up", "up"]) == 0.0
    assert agent.calculate_downtime_fraction(["degraded", "degraded"]) == 1.0
    assert agent.calculate_downtime_fraction(["up", "degraded", "up", "down", "up"]) == 0.4


def test_helper_zscore():
    agent = InfrastructureHealthAgent()
    vals = [20.0, 22.0, 24.0, 26.0, 28.0]
    z = agent.calculate_zscore(vals, baseline=20.0)
    assert z > 0.5


# -----------------------------------------------------------------------------
# Scenario Evaluation Tests via handle()
# -----------------------------------------------------------------------------


def test_scenario_device_cpu_overload():
    agent = InfrastructureHealthAgent()
    req = scenario_task_request("device_cpu_overload", "infrastructure_agent")
    responses = asyncio.run(agent.handle(req))
    assert len(responses) == 1
    payload: FindingPayload = responses[0].payload  # type: ignore
    top = payload.hypothesis_candidates[0]
    assert top.cause_code == CauseCode.DEVICE_CPU_OVERLOAD
    assert top.score >= 0.75
    assert "ACC_SW_LHC_01" in payload.scope.device_ids


def test_scenario_link_congestion():
    agent = InfrastructureHealthAgent()
    req = scenario_task_request("link_congestion", "infrastructure_agent")
    responses = asyncio.run(agent.handle(req))
    assert len(responses) == 1
    payload: FindingPayload = responses[0].payload  # type: ignore
    top = payload.hypothesis_candidates[0]
    # Queue drops are high while CPU is normal -> LINK_CONGESTION top
    assert top.cause_code == CauseCode.LINK_CONGESTION
    assert top.score >= 0.70
    # DEVICE_CPU_OVERLOAD must NOT win
    cpu_cand = next(c for c in payload.hypothesis_candidates if c.cause_code == CauseCode.DEVICE_CPU_OVERLOAD)
    assert cpu_cand.score <= 0.30


def test_scenario_upstream_congestion():
    agent = InfrastructureHealthAgent()
    req = scenario_task_request("upstream_congestion", "infrastructure_agent")
    responses = asyncio.run(agent.handle(req))
    assert len(responses) == 1
    payload: FindingPayload = responses[0].payload  # type: ignore
    top = payload.hypothesis_candidates[0]
    # GW_NKN_ISP queue drops (~3000) with normal CPU
    assert top.cause_code == CauseCode.LINK_CONGESTION
    assert top.score >= 0.70
    cpu_cand = next(c for c in payload.hypothesis_candidates if c.cause_code == CauseCode.DEVICE_CPU_OVERLOAD)
    assert cpu_cand.score <= 0.30


def test_scenario_weak_wifi():
    agent = InfrastructureHealthAgent()
    req = scenario_task_request("weak_wifi", "infrastructure_agent")
    responses = asyncio.run(agent.handle(req))
    assert len(responses) == 1
    payload: FindingPayload = responses[0].payload  # type: ignore
    top = payload.hypothesis_candidates[0]
    assert top.cause_code == CauseCode.WEAK_WIFI_SIGNAL
    assert top.score >= 0.75
    assert "AP_HOSTEL_A_FL2" in payload.scope.device_ids


def test_scenario_interface_fault():
    agent = InfrastructureHealthAgent()
    req = scenario_task_request("interface_fault", "infrastructure_agent")
    responses = asyncio.run(agent.handle(req))
    assert len(responses) == 1
    payload: FindingPayload = responses[0].payload  # type: ignore
    top = payload.hypothesis_candidates[0]
    assert top.cause_code == CauseCode.INTERFACE_FAULT
    assert top.score >= 0.75
    assert "ACC_SW_CSE_01" in payload.scope.device_ids


def test_scenario_normal():
    agent = InfrastructureHealthAgent()
    req = scenario_task_request("normal", "infrastructure_agent")
    responses = asyncio.run(agent.handle(req))
    assert len(responses) == 1
    payload: FindingPayload = responses[0].payload  # type: ignore
    top = payload.hypothesis_candidates[0]
    assert top.cause_code == CauseCode.NORMAL
    assert top.score >= 0.70


def test_scenario_dns_failure():
    agent = InfrastructureHealthAgent()
    req = scenario_task_request("dns_failure", "infrastructure_agent")
    responses = asyncio.run(agent.handle(req))
    assert len(responses) == 1
    payload: FindingPayload = responses[0].payload  # type: ignore
    top = payload.hypothesis_candidates[0]
    # Infrastructure hardware metrics are healthy
    assert top.cause_code == CauseCode.NORMAL or top.score < 0.50


def test_scenario_dhcp_failure():
    agent = InfrastructureHealthAgent()
    req = scenario_task_request("dhcp_failure", "infrastructure_agent")
    responses = asyncio.run(agent.handle(req))
    assert len(responses) == 1
    payload: FindingPayload = responses[0].payload  # type: ignore
    top = payload.hypothesis_candidates[0]
    assert top.cause_code == CauseCode.NORMAL or top.score < 0.50


def test_scenario_ambiguous_insufficient():
    agent = InfrastructureHealthAgent()
    req = scenario_task_request("ambiguous_insufficient", "infrastructure_agent")
    responses = asyncio.run(agent.handle(req))
    assert len(responses) == 1
    payload: FindingPayload = responses[0].payload  # type: ignore
    # Borderline metrics and missing drops/errors -> every candidate below 0.50
    for cand in payload.hypothesis_candidates:
        assert cand.score < 0.50
    assert payload.confidence < 0.50


def test_scenario_legacy_schema_0_9():
    agent = InfrastructureHealthAgent()
    req = scenario_task_request("legacy_schema_0_9", "infrastructure_agent")
    responses = asyncio.run(agent.handle(req))
    assert len(responses) == 1
    payload: FindingPayload = responses[0].payload  # type: ignore
    top = payload.hypothesis_candidates[0]
    assert top.cause_code == CauseCode.LINK_CONGESTION
    assert top.score >= 0.70


def test_scenario_mixed_units():
    agent = InfrastructureHealthAgent()
    req = scenario_task_request("mixed_units", "infrastructure_agent")
    responses = asyncio.run(agent.handle(req))
    assert len(responses) == 1
    payload: FindingPayload = responses[0].payload  # type: ignore
    top = payload.hypothesis_candidates[0]
    assert top.cause_code == CauseCode.LINK_CONGESTION
    assert top.score >= 0.70


def test_scenario_missing_fields():
    agent = InfrastructureHealthAgent()
    req_missing = scenario_task_request("missing_fields", "infrastructure_agent")
    req_norm = scenario_task_request("normal", "infrastructure_agent")

    res_missing = asyncio.run(agent.handle(req_missing))[0].payload
    res_norm = asyncio.run(agent.handle(req_norm))[0].payload

    assert res_missing.data_quality.completeness < res_norm.data_quality.completeness
    assert res_missing.confidence < res_norm.confidence


# -----------------------------------------------------------------------------
# Domain Edge Cases, Synthetic Fixtures, and Determinism Tests
# -----------------------------------------------------------------------------


def test_synthetic_hardware_failure():
    agent = InfrastructureHealthAgent()
    # Create synthetic telemetry for a device with hardware crash / down state
    telemetry = {
        "CORE_RTR_02": [
            {
                "timestamp": "2026-10-31T10:00:00Z",
                "device_status": "down",
                "cpu_pct": 99.9,
                "memory_pct": 95.0,
                "queue_drops": 8000,
                "interface_errors": 500,
            },
            {
                "timestamp": "2026-10-31T10:01:00Z",
                "device_status": "down",
                "cpu_pct": 99.9,
                "memory_pct": 95.0,
                "queue_drops": 9000,
                "interface_errors": 520,
            },
        ]
    }
    msg = MessageEnvelope(
        incident_id="INC-HW-FAIL-01",
        sender="orchestrator",
        recipient="infrastructure_agent",
        message_type=MessageType.TASK_REQUEST,
        payload=TaskRequestPayload(task="analyze", telemetry=telemetry),
    )
    responses = asyncio.run(agent.handle(msg))
    assert len(responses) == 1
    payload: FindingPayload = responses[0].payload  # type: ignore
    top = payload.hypothesis_candidates[0]
    assert top.cause_code == CauseCode.HARDWARE_FAILURE
    assert top.score >= 0.75
    assert "CORE_RTR_02" in payload.scope.device_ids


def test_cpu_high_with_queue_drops_contradiction():
    agent = InfrastructureHealthAgent()
    # High CPU (95%) AND massive queue drops (5000 pkts)
    telemetry = {
        "ACC_SW_TEST_01": [
            {
                "timestamp": "2026-10-31T10:00:00Z",
                "device_status": "degraded",
                "cpu_pct": 95.0,
                "memory_pct": 85.0,
                "queue_drops": 5000,
                "interface_errors": 0,
            },
            {
                "timestamp": "2026-10-31T10:01:00Z",
                "device_status": "degraded",
                "cpu_pct": 96.0,
                "memory_pct": 86.0,
                "queue_drops": 5500,
                "interface_errors": 0,
            },
        ]
    }
    msg = MessageEnvelope(
        incident_id="INC-CONTRADICT-01",
        sender="orchestrator",
        recipient="infrastructure_agent",
        message_type=MessageType.TASK_REQUEST,
        payload=TaskRequestPayload(task="analyze", telemetry=telemetry),
    )
    responses = asyncio.run(agent.handle(msg))
    payload: FindingPayload = responses[0].payload  # type: ignore
    cpu_cand = next(c for c in payload.hypothesis_candidates if c.cause_code == CauseCode.DEVICE_CPU_OVERLOAD)

    # Queue drops must appear in contradicting metrics
    contradicting_names = [m.metric for m in cpu_cand.contradicting_metrics]
    assert "queue_drops" in contradicting_names


def test_missing_metric_in_telemetry():
    agent = InfrastructureHealthAgent()
    telemetry = {
        "ACC_SW_HOSTEL_A": [
            {
                "timestamp": "2026-10-31T10:00:00Z",
                "device_status": "up",
                "cpu_pct": 25.0,
                # memory_pct, interface_errors, and queue_drops are omitted
            }
        ]
    }
    msg = MessageEnvelope(
        incident_id="INC-MISS-INFRA-01",
        sender="orchestrator",
        recipient="infrastructure_agent",
        message_type=MessageType.TASK_REQUEST,
        payload=TaskRequestPayload(task="analyze", telemetry=telemetry),
    )
    responses = asyncio.run(agent.handle(msg))
    assert len(responses) == 1
    payload: FindingPayload = responses[0].payload  # type: ignore
    assert "memory_pct" in payload.data_quality.missing_fields
    assert "interface_errors" in payload.data_quality.missing_fields
    assert "queue_drops" in payload.data_quality.missing_fields


def test_empty_telemetry():
    agent = InfrastructureHealthAgent()
    msg = MessageEnvelope(
        incident_id="INC-EMPTY-INFRA-01",
        sender="orchestrator",
        recipient="infrastructure_agent",
        message_type=MessageType.TASK_REQUEST,
        payload=TaskRequestPayload(task="analyze", telemetry={}),
    )
    responses = asyncio.run(agent.handle(msg))
    assert len(responses) == 1
    payload: FindingPayload = responses[0].payload  # type: ignore
    assert payload.confidence == 0.0
    assert payload.data_quality.completeness == 0.0
    assert len(payload.hypothesis_candidates) == 0


def test_malformed_message_gives_error():
    agent = InfrastructureHealthAgent()
    responses = asyncio.run(agent.handle("unparseable_malformed_json_here"))
    assert len(responses) == 1
    assert responses[0].message_type == MessageType.ERROR


def test_evidence_query_with_context():
    agent = InfrastructureHealthAgent()
    inc_id = "INC-QUERY-INFRA-01"

    task_req = scenario_task_request("device_cpu_overload", "infrastructure_agent")
    task_req.incident_id = inc_id
    asyncio.run(agent.handle(task_req))

    q_msg = MessageEnvelope(
        incident_id=inc_id,
        sender="correlation_agent",
        recipient="infrastructure_agent",
        message_type=MessageType.EVIDENCE_QUERY,
        payload=EvidenceQueryPayload(
            target_agent="infrastructure_agent",
            cause_code=CauseCode.DEVICE_CPU_OVERLOAD,
            device_ids=["ACC_SW_LHC_01"],
            metrics=["cpu_pct", "memory_pct", "queue_drops"],
        ),
    )
    responses = asyncio.run(agent.handle(q_msg))
    assert len(responses) == 1
    resp = responses[0]
    assert resp.message_type == MessageType.EVIDENCE_RESPONSE
    resp_payload: EvidenceResponsePayload = resp.payload  # type: ignore
    assert resp_payload.supports is True
    assert resp_payload.confidence >= 0.70
    assert len(resp_payload.answers) >= 3


def test_evidence_query_without_context():
    agent = InfrastructureHealthAgent()
    q_msg = MessageEnvelope(
        incident_id="INC-NO-CACHE-INFRA-99",
        sender="correlation_agent",
        recipient="infrastructure_agent",
        message_type=MessageType.EVIDENCE_QUERY,
        payload=EvidenceQueryPayload(
            target_agent="infrastructure_agent",
            cause_code=CauseCode.DEVICE_CPU_OVERLOAD,
            device_ids=["ACC_SW_LHC_01"],
        ),
    )
    responses = asyncio.run(agent.handle(q_msg))
    assert len(responses) == 1
    resp_payload: EvidenceResponsePayload = responses[0].payload  # type: ignore
    assert resp_payload.supports is None
    assert resp_payload.confidence == 0.0
    assert "No cached telemetry context" in resp_payload.notes


def test_determinism():
    agent1 = InfrastructureHealthAgent()
    agent2 = InfrastructureHealthAgent()

    req1 = scenario_task_request("device_cpu_overload", "infrastructure_agent")
    req2 = scenario_task_request("device_cpu_overload", "infrastructure_agent")

    res1 = asyncio.run(agent1.handle(req1))[0].payload
    res2 = asyncio.run(agent2.handle(req2))[0].payload

    assert res1.confidence == res2.confidence
    assert len(res1.hypothesis_candidates) == len(res2.hypothesis_candidates)
    for c1, c2 in zip(res1.hypothesis_candidates, res2.hypothesis_candidates):
        assert c1.cause_code == c2.cause_code
        assert c1.score == c2.score