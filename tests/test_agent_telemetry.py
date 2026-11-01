"""Tests for TelemetryPerformanceAgent.

Covers statistical helpers, scenario evaluations, peer evidence queries,
handling missing/empty data, malformed payloads, and seed determinism.
"""

import asyncio
from datetime import datetime, timezone
import pytest

from netcoop.agents.telemetry_agent import TelemetryPerformanceAgent
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


def test_helper_zscore():
    agent = TelemetryPerformanceAgent()
    # Baseline comparison with variance
    vals = [10.0, 12.0, 14.0, 16.0, 18.0]
    z = agent.calculate_zscore(vals, baseline=10.0)
    assert z > 0.5

    # Zero variance handling
    flat_vals = [20.0, 20.0, 20.0]
    z_flat = agent.calculate_zscore(flat_vals, baseline=20.0)
    assert abs(z_flat) < 1e-4

    # Empty list
    assert agent.calculate_zscore([]) == 0.0


def test_helper_trend_slope():
    agent = TelemetryPerformanceAgent()
    t0 = datetime(2026, 10, 31, 10, 0, 0, tzinfo=timezone.utc)
    timestamps = [
        t0,
        datetime(2026, 10, 31, 10, 1, 0, tzinfo=timezone.utc),
        datetime(2026, 10, 31, 10, 2, 0, tzinfo=timezone.utc),
    ]
    # Increasing trend: +10 ms per minute = +600 ms per hour
    values = [10.0, 20.0, 30.0]
    slope = agent.calculate_trend_slope(timestamps, values)
    assert round(slope, 1) == 600.0

    # Flat line
    flat_slope = agent.calculate_trend_slope(timestamps, [15.0, 15.0, 15.0])
    assert abs(flat_slope) < 1e-4


def test_helper_spike_counting():
    agent = TelemetryPerformanceAgent()
    values = [1.0, 1.2, 0.9, 15.0, 1.1, 22.0, 0.8]
    count, max_spike = agent.count_spikes(values, threshold=4.0)
    assert count == 2
    assert max_spike == 18.0  # 22.0 - 4.0

    c_empty, m_empty = agent.count_spikes([])
    assert c_empty == 0 and m_empty == 0.0


def test_helper_saturation():
    agent = TelemetryPerformanceAgent()
    # Saturated: 95% utilization and 94% capacity throughput
    assert agent.detect_throughput_saturation(throughput=9400.0, bandwidth=10000.0, utilization=95.0) is True

    # High throughput but low utilization (contradictory/unsat)
    assert agent.detect_throughput_saturation(throughput=9400.0, bandwidth=10000.0, utilization=40.0) is False

    # Low throughput and low utilization
    assert agent.detect_throughput_saturation(throughput=300.0, bandwidth=1000.0, utilization=30.0) is False


def test_helper_wireless_detection():
    agent = TelemetryPerformanceAgent()
    # By AP naming prefix
    assert agent.is_wireless_device("AP_HOSTEL_A_FL1") is True
    assert agent.is_wireless_device("DIST_SW_HOSTEL") is False

    # By topology node attributes
    topo = {"nodes": [{"id": "CUSTOM_NODE_01", "device_type": "access_point"}]}
    assert agent.is_wireless_device("CUSTOM_NODE_01", topology=topo) is True


# -----------------------------------------------------------------------------
# Scenario Evaluation Tests via handle()
# -----------------------------------------------------------------------------


def test_scenario_normal():
    agent = TelemetryPerformanceAgent()
    req = scenario_task_request("normal", "telemetry_agent")
    responses = asyncio.run(agent.handle(req))
    assert len(responses) == 1
    resp = responses[0]
    assert resp.message_type == MessageType.FINDING
    payload: FindingPayload = resp.payload  # type: ignore
    top = payload.hypothesis_candidates[0]
    assert top.cause_code == CauseCode.NORMAL
    assert top.score >= 0.70


def test_scenario_link_congestion():
    agent = TelemetryPerformanceAgent()
    req = scenario_task_request("link_congestion", "telemetry_agent")
    responses = asyncio.run(agent.handle(req))
    assert len(responses) == 1
    payload: FindingPayload = responses[0].payload  # type: ignore
    top = payload.hypothesis_candidates[0]
    assert top.cause_code == CauseCode.LINK_CONGESTION
    assert top.score >= 0.80
    assert "DIST_SW_HOSTEL" in payload.scope.device_ids


def test_scenario_upstream_congestion():
    agent = TelemetryPerformanceAgent()
    req = scenario_task_request("upstream_congestion", "telemetry_agent")
    responses = asyncio.run(agent.handle(req))
    assert len(responses) == 1
    payload: FindingPayload = responses[0].payload  # type: ignore
    top = payload.hypothesis_candidates[0]
    assert top.cause_code == CauseCode.LINK_CONGESTION
    assert top.score >= 0.80
    assert "GW_NKN_ISP" in payload.scope.device_ids


def test_scenario_weak_wifi():
    agent = TelemetryPerformanceAgent()
    req = scenario_task_request("weak_wifi", "telemetry_agent")
    responses = asyncio.run(agent.handle(req))
    assert len(responses) == 1
    payload: FindingPayload = responses[0].payload  # type: ignore
    top = payload.hypothesis_candidates[0]
    assert top.cause_code == CauseCode.WEAK_WIFI_SIGNAL
    assert top.score >= 0.70
    assert "AP_HOSTEL_A_FL2" in payload.scope.device_ids


def test_scenario_interface_fault():
    agent = TelemetryPerformanceAgent()
    req = scenario_task_request("interface_fault", "telemetry_agent")
    responses = asyncio.run(agent.handle(req))
    assert len(responses) == 1
    payload: FindingPayload = responses[0].payload  # type: ignore
    top = payload.hypothesis_candidates[0]
    assert top.cause_code == CauseCode.INTERFACE_FAULT
    assert top.score >= 0.70
    assert "ACC_SW_CSE_01" in payload.scope.device_ids


def test_scenario_dns_failure():
    agent = TelemetryPerformanceAgent()
    req = scenario_task_request("dns_failure", "telemetry_agent")
    responses = asyncio.run(agent.handle(req))
    assert len(responses) == 1
    payload: FindingPayload = responses[0].payload  # type: ignore
    top = payload.hypothesis_candidates[0]
    # Transport layer metrics are healthy on DNS server
    assert top.cause_code == CauseCode.NORMAL
    assert top.score >= 0.70


def test_scenario_dhcp_failure():
    agent = TelemetryPerformanceAgent()
    req = scenario_task_request("dhcp_failure", "telemetry_agent")
    responses = asyncio.run(agent.handle(req))
    assert len(responses) == 1
    payload: FindingPayload = responses[0].payload  # type: ignore
    top = payload.hypothesis_candidates[0]
    # Transport layer metrics are healthy on DHCP server
    assert top.cause_code == CauseCode.NORMAL
    assert top.score >= 0.70


def test_scenario_device_cpu_overload():
    agent = TelemetryPerformanceAgent()
    req = scenario_task_request("device_cpu_overload", "telemetry_agent")
    responses = asyncio.run(agent.handle(req))
    assert len(responses) == 1
    payload: FindingPayload = responses[0].payload  # type: ignore
    link_cand = next(c for c in payload.hypothesis_candidates if c.cause_code == CauseCode.LINK_CONGESTION)
    # Link utilization is low (~35%), so LINK_CONGESTION must NOT score above 0.5
    assert link_cand.score <= 0.50


def test_scenario_ambiguous_insufficient():
    agent = TelemetryPerformanceAgent()
    req = scenario_task_request("ambiguous_insufficient", "telemetry_agent")
    responses = asyncio.run(agent.handle(req))
    assert len(responses) == 1
    payload: FindingPayload = responses[0].payload  # type: ignore
    # Every candidate must be below 0.5 and confidence low
    for cand in payload.hypothesis_candidates:
        assert cand.score < 0.50
    assert payload.confidence < 0.50


def test_scenario_legacy_schema_0_9():
    agent = TelemetryPerformanceAgent()
    req = scenario_task_request("legacy_schema_0_9", "telemetry_agent")
    responses = asyncio.run(agent.handle(req))
    assert len(responses) == 1
    payload: FindingPayload = responses[0].payload  # type: ignore
    top = payload.hypothesis_candidates[0]
    assert top.cause_code == CauseCode.LINK_CONGESTION
    assert top.score >= 0.80


def test_scenario_mixed_units():
    agent = TelemetryPerformanceAgent()
    req = scenario_task_request("mixed_units", "telemetry_agent")
    responses = asyncio.run(agent.handle(req))
    assert len(responses) == 1
    payload: FindingPayload = responses[0].payload  # type: ignore
    top = payload.hypothesis_candidates[0]
    assert top.cause_code == CauseCode.LINK_CONGESTION
    assert top.score >= 0.80


def test_scenario_missing_fields():
    agent = TelemetryPerformanceAgent()
    req_missing = scenario_task_request("missing_fields", "telemetry_agent")
    req_link = scenario_task_request("link_congestion", "telemetry_agent")

    res_missing = asyncio.run(agent.handle(req_missing))[0].payload
    res_link = asyncio.run(agent.handle(req_link))[0].payload

    # Missing fields must reflect lower completeness and lower confidence
    assert res_missing.data_quality.completeness < res_link.data_quality.completeness
    assert res_missing.confidence < res_link.confidence


# -----------------------------------------------------------------------------
# Edge Cases, Peer Queries, and Determinism Tests
# -----------------------------------------------------------------------------


def test_missing_metric_in_telemetry():
    agent = TelemetryPerformanceAgent()
    # Provide telemetry missing latency_ms and jitter_ms
    telemetry = {
        "DIST_SW_HOSTEL": [
            {"timestamp": "2026-10-31T10:00:00Z", "link_utilization_pct": 30.0, "packet_loss_pct": 0.0}
        ]
    }
    msg = MessageEnvelope(
        incident_id="INC-MISS-01",
        sender="orchestrator",
        recipient="telemetry_agent",
        message_type=MessageType.TASK_REQUEST,
        payload=TaskRequestPayload(task="analyze", telemetry=telemetry),
    )
    responses = asyncio.run(agent.handle(msg))
    assert len(responses) == 1
    payload: FindingPayload = responses[0].payload  # type: ignore
    assert "latency_ms" in payload.data_quality.missing_fields
    assert "jitter_ms" in payload.data_quality.missing_fields


def test_empty_telemetry():
    agent = TelemetryPerformanceAgent()
    msg = MessageEnvelope(
        incident_id="INC-EMPTY-01",
        sender="orchestrator",
        recipient="telemetry_agent",
        message_type=MessageType.TASK_REQUEST,
        payload=TaskRequestPayload(task="analyze", telemetry={}),
    )
    responses = asyncio.run(agent.handle(msg))
    assert len(responses) == 1
    payload: FindingPayload = responses[0].payload  # type: ignore
    assert payload.confidence == 0.0
    assert payload.data_quality.completeness == 0.0
    # NORMAL / UNKNOWN must be absent
    assert len(payload.hypothesis_candidates) == 0


def test_malformed_message_gives_error():
    agent = TelemetryPerformanceAgent()
    # Pass malformed string
    responses = asyncio.run(agent.handle("{ unparseable raw json ..."))
    assert len(responses) == 1
    assert responses[0].message_type == MessageType.ERROR


def test_evidence_query_with_context():
    agent = TelemetryPerformanceAgent()
    inc_id = "INC-QUERY-01"

    # 1. Ingest task request to populate agent incident cache
    task_req = scenario_task_request("link_congestion", "telemetry_agent")
    task_req.incident_id = inc_id
    asyncio.run(agent.handle(task_req))

    # 2. Query evidence regarding link congestion on DIST_SW_HOSTEL
    q_msg = MessageEnvelope(
        incident_id=inc_id,
        sender="correlation_agent",
        recipient="telemetry_agent",
        message_type=MessageType.EVIDENCE_QUERY,
        payload=EvidenceQueryPayload(
            target_agent="telemetry_agent",
            cause_code=CauseCode.LINK_CONGESTION,
            device_ids=["DIST_SW_HOSTEL"],
            metrics=["link_utilization_pct", "latency_ms"],
        ),
    )
    q_responses = asyncio.run(agent.handle(q_msg))
    assert len(q_responses) == 1
    resp = q_responses[0]
    assert resp.message_type == MessageType.EVIDENCE_RESPONSE
    resp_payload: EvidenceResponsePayload = resp.payload  # type: ignore
    assert resp_payload.supports is True
    assert resp_payload.confidence >= 0.70
    assert len(resp_payload.answers) >= 2


def test_evidence_query_without_context():
    agent = TelemetryPerformanceAgent()
    q_msg = MessageEnvelope(
        incident_id="INC-NO-CACHE-99",
        sender="correlation_agent",
        recipient="telemetry_agent",
        message_type=MessageType.EVIDENCE_QUERY,
        payload=EvidenceQueryPayload(
            target_agent="telemetry_agent",
            cause_code=CauseCode.LINK_CONGESTION,
            device_ids=["DIST_SW_HOSTEL"],
        ),
    )
    responses = asyncio.run(agent.handle(q_msg))
    assert len(responses) == 1
    resp_payload: EvidenceResponsePayload = responses[0].payload  # type: ignore
    assert resp_payload.supports is None
    assert resp_payload.confidence == 0.0
    assert "No cached telemetry context" in resp_payload.notes


def test_determinism():
    agent1 = TelemetryPerformanceAgent()
    agent2 = TelemetryPerformanceAgent()

    req1 = scenario_task_request("link_congestion", "telemetry_agent")
    req2 = scenario_task_request("link_congestion", "telemetry_agent")

    res1 = asyncio.run(agent1.handle(req1))[0].payload
    res2 = asyncio.run(agent2.handle(req2))[0].payload

    assert res1.confidence == res2.confidence
    assert len(res1.hypothesis_candidates) == len(res2.hypothesis_candidates)
    for c1, c2 in zip(res1.hypothesis_candidates, res2.hypothesis_candidates):
        assert c1.cause_code == c2.cause_code
        assert c1.score == c2.score