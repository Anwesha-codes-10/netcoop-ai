"""Tests for ConnectivityAnalysisAgent.

Covers graph helpers (LCA, SPOF, downstream fraction),
scenario evaluations through handle(), synthetic hardware failures,
unknown device isolation, missing topology fallback, empty telemetry,
malformed message rejection, peer evidence queries, and determinism.
"""

import asyncio
import pytest

from netcoop.agents.connectivity_agent import ConnectivityAnalysisAgent
from netcoop.data.topology import CampusTopology
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
# Unit Tests for Graph Helper Functions
# -----------------------------------------------------------------------------


def test_helper_common_ancestor():
    agent = ConnectivityAnalysisAgent()
    topo = CampusTopology.build_iit_bhubaneswar_topology()
    graph = agent.build_graph_from_topology(topo.to_dict())

    # Two APs in Hostel A should have ACC_SW_HOSTEL_A as lowest common ancestor
    affected = ["AP_HOSTEL_A_FL1", "AP_HOSTEL_A_FL2"]
    lca, paths = agent.find_lowest_common_ancestor(graph, affected)
    assert lca == "ACC_SW_HOSTEL_A"
    assert "AP_HOSTEL_A_FL1" in paths

    # Two access switches in Hostel should have DIST_SW_HOSTEL as LCA
    affected_sw = ["ACC_SW_HOSTEL_A", "ACC_SW_HOSTEL_B"]
    lca_sw, _ = agent.find_lowest_common_ancestor(graph, affected_sw)
    assert lca_sw == "DIST_SW_HOSTEL"


def test_helper_spof():
    agent = ConnectivityAnalysisAgent()
    topo = CampusTopology.build_iit_bhubaneswar_topology()
    graph = agent.build_graph_from_topology(topo.to_dict())

    # ACC_SW_HOSTEL_A is single point of failure for its downstream APs
    downstream = agent.get_downstream_nodes(graph, "ACC_SW_HOSTEL_A")
    assert "AP_HOSTEL_A_FL1" in downstream
    assert "AP_HOSTEL_A_FL2" in downstream

    is_spof = agent.is_single_point_of_failure(graph, "ACC_SW_HOSTEL_A", downstream)
    assert is_spof is True


def test_helper_downstream_fraction():
    agent = ConnectivityAnalysisAgent()
    topo = CampusTopology.build_iit_bhubaneswar_topology()
    graph = agent.build_graph_from_topology(topo.to_dict())

    # Only 1 of 2 downstream APs affected
    affected = ["AP_HOSTEL_A_FL1"]
    frac = agent.calculate_downstream_affected_fraction(graph, "ACC_SW_HOSTEL_A", affected)
    assert frac == 0.5

    # Both affected
    affected_all = ["AP_HOSTEL_A_FL1", "AP_HOSTEL_A_FL2"]
    frac_all = agent.calculate_downstream_affected_fraction(graph, "ACC_SW_HOSTEL_A", affected_all)
    assert frac_all == 1.0


# -----------------------------------------------------------------------------
# Scenario Evaluation Tests via handle()
# -----------------------------------------------------------------------------


def test_scenario_upstream_congestion():
    agent = ConnectivityAnalysisAgent()
    req = scenario_task_request("upstream_congestion", "connectivity_agent")
    responses = asyncio.run(agent.handle(req))
    assert len(responses) == 1
    payload: FindingPayload = responses[0].payload  # type: ignore

    top = payload.hypothesis_candidates[0]
    assert top.cause_code == CauseCode.UPSTREAM_CONGESTION
    assert top.score >= 0.80
    assert "GW_NKN_ISP" in payload.scope.device_ids
    assert any("widespread" in a.lower() or "segment" in a.lower() for a in payload.data_quality.assumptions)


def test_scenario_dns_failure():
    agent = ConnectivityAnalysisAgent()
    req = scenario_task_request("dns_failure", "connectivity_agent")
    responses = asyncio.run(agent.handle(req))
    assert len(responses) == 1
    payload: FindingPayload = responses[0].payload  # type: ignore

    top = payload.hypothesis_candidates[0]
    assert top.cause_code == CauseCode.DNS_FAILURE
    assert top.score >= 0.80
    assert "SRV_DNS_01" in payload.scope.device_ids


def test_scenario_dhcp_failure():
    agent = ConnectivityAnalysisAgent()
    req = scenario_task_request("dhcp_failure", "connectivity_agent")
    responses = asyncio.run(agent.handle(req))
    assert len(responses) == 1
    payload: FindingPayload = responses[0].payload  # type: ignore

    top = payload.hypothesis_candidates[0]
    assert top.cause_code == CauseCode.DHCP_FAILURE
    assert top.score >= 0.80
    assert "SRV_DHCP_01" in payload.scope.device_ids


def test_scenario_weak_wifi():
    agent = ConnectivityAnalysisAgent()
    req = scenario_task_request("weak_wifi", "connectivity_agent")
    responses = asyncio.run(agent.handle(req))
    assert len(responses) == 1
    payload: FindingPayload = responses[0].payload  # type: ignore

    # Isolated leaf fault: scope must be isolated, no UPSTREAM_CONGESTION above 0.5
    assert any("isolated" in a.lower() for a in payload.data_quality.assumptions)
    up_cand = next((c for c in payload.hypothesis_candidates if c.cause_code == CauseCode.UPSTREAM_CONGESTION), None)
    if up_cand:
        assert up_cand.score <= 0.50


def test_scenario_interface_fault():
    agent = ConnectivityAnalysisAgent()
    req = scenario_task_request("interface_fault", "connectivity_agent")
    responses = asyncio.run(agent.handle(req))
    assert len(responses) == 1
    payload: FindingPayload = responses[0].payload  # type: ignore

    assert any("isolated" in a.lower() for a in payload.data_quality.assumptions)
    up_cand = next((c for c in payload.hypothesis_candidates if c.cause_code == CauseCode.UPSTREAM_CONGESTION), None)
    if up_cand:
        assert up_cand.score <= 0.50


def test_scenario_device_cpu_overload():
    agent = ConnectivityAnalysisAgent()
    req = scenario_task_request("device_cpu_overload", "connectivity_agent")
    responses = asyncio.run(agent.handle(req))
    assert len(responses) == 1
    payload: FindingPayload = responses[0].payload  # type: ignore

    assert any("isolated" in a.lower() for a in payload.data_quality.assumptions)
    up_cand = next((c for c in payload.hypothesis_candidates if c.cause_code == CauseCode.UPSTREAM_CONGESTION), None)
    if up_cand:
        assert up_cand.score <= 0.50


def test_scenario_link_congestion():
    agent = ConnectivityAnalysisAgent()
    req = scenario_task_request("link_congestion", "connectivity_agent")
    responses = asyncio.run(agent.handle(req))
    assert len(responses) == 1
    payload: FindingPayload = responses[0].payload  # type: ignore

    # Local link congestion on DIST_SW_HOSTEL must not be diagnosed as UPSTREAM_CONGESTION (>0.5)
    up_cand = next((c for c in payload.hypothesis_candidates if c.cause_code == CauseCode.UPSTREAM_CONGESTION), None)
    if up_cand:
        assert up_cand.score <= 0.50


def test_scenario_normal():
    agent = ConnectivityAnalysisAgent()
    req = scenario_task_request("normal", "connectivity_agent")
    responses = asyncio.run(agent.handle(req))
    assert len(responses) == 1
    payload: FindingPayload = responses[0].payload  # type: ignore

    top = payload.hypothesis_candidates[0]
    assert top.cause_code == CauseCode.NORMAL
    assert top.score >= 0.70


def test_scenario_ambiguous_insufficient():
    agent = ConnectivityAnalysisAgent()
    req = scenario_task_request("ambiguous_insufficient", "connectivity_agent")
    responses = asyncio.run(agent.handle(req))
    assert len(responses) == 1
    payload: FindingPayload = responses[0].payload  # type: ignore

    for cand in payload.hypothesis_candidates:
        assert cand.score < 0.50
    assert payload.confidence < 0.50


def test_scenario_legacy_schema_0_9():
    agent = ConnectivityAnalysisAgent()
    req = scenario_task_request("legacy_schema_0_9", "connectivity_agent")
    responses = asyncio.run(agent.handle(req))
    assert len(responses) == 1
    payload: FindingPayload = responses[0].payload  # type: ignore

    up_cand = next((c for c in payload.hypothesis_candidates if c.cause_code == CauseCode.UPSTREAM_CONGESTION), None)
    if up_cand:
        assert up_cand.score <= 0.50


def test_scenario_mixed_units():
    agent = ConnectivityAnalysisAgent()
    req = scenario_task_request("mixed_units", "connectivity_agent")
    responses = asyncio.run(agent.handle(req))
    assert len(responses) == 1
    payload: FindingPayload = responses[0].payload  # type: ignore

    up_cand = next((c for c in payload.hypothesis_candidates if c.cause_code == CauseCode.UPSTREAM_CONGESTION), None)
    if up_cand:
        assert up_cand.score <= 0.50


def test_scenario_missing_fields():
    agent = ConnectivityAnalysisAgent()
    req_missing = scenario_task_request("missing_fields", "connectivity_agent")
    req_norm = scenario_task_request("normal", "connectivity_agent")

    res_missing = asyncio.run(agent.handle(req_missing))[0].payload
    res_norm = asyncio.run(agent.handle(req_norm))[0].payload

    assert res_missing.data_quality.completeness < res_norm.data_quality.completeness


# -----------------------------------------------------------------------------
# Edge Cases, Synthetic Fixtures, and Peer Queries
# -----------------------------------------------------------------------------


def test_synthetic_hardware_failure():
    agent = ConnectivityAnalysisAgent()
    topo = CampusTopology.build_iit_bhubaneswar_topology()

    # Synthetic: parent distribution switch DIST_SW_HOSTEL goes completely down
    telemetry = {
        "DIST_SW_HOSTEL": [
            {
                "timestamp": "2026-10-31T10:00:00Z",
                "device_status": "down",
                "latency_ms": 999.0,
                "packet_loss_pct": 50.0,
                "link_utilization_pct": 0.0,
            }
        ],
        "ACC_SW_HOSTEL_A": [
            {
                "timestamp": "2026-10-31T10:00:00Z",
                "device_status": "degraded",
                "latency_ms": 500.0,
                "packet_loss_pct": 30.0,
                "link_utilization_pct": 10.0,
            }
        ],
    }
    msg = MessageEnvelope(
        incident_id="INC-HW-FAIL-TOPO-01",
        sender="orchestrator",
        recipient="connectivity_agent",
        message_type=MessageType.TASK_REQUEST,
        payload=TaskRequestPayload(task="analyze", telemetry=telemetry, topology=topo.to_dict()),
    )
    responses = asyncio.run(agent.handle(msg))
    assert len(responses) == 1
    payload: FindingPayload = responses[0].payload  # type: ignore

    top = payload.hypothesis_candidates[0]
    assert top.cause_code == CauseCode.HARDWARE_FAILURE
    assert top.score >= 0.70


def test_unknown_device_isolated_from_graph():
    agent = ConnectivityAnalysisAgent()
    topo = CampusTopology.build_iit_bhubaneswar_topology()

    telemetry = {
        "ROGUE_UNREGISTERED_DEVICE_99": [
            {
                "timestamp": "2026-10-31T10:00:00Z",
                "latency_ms": 250.0,
                "packet_loss_pct": 10.0,
            }
        ]
    }
    msg = MessageEnvelope(
        incident_id="INC-ROGUE-01",
        sender="orchestrator",
        recipient="connectivity_agent",
        message_type=MessageType.TASK_REQUEST,
        payload=TaskRequestPayload(task="analyze", telemetry=telemetry, topology=topo.to_dict()),
    )
    responses = asyncio.run(agent.handle(msg))
    assert len(responses) == 1
    payload: FindingPayload = responses[0].payload  # type: ignore

    assert "ROGUE_UNREGISTERED_DEVICE_99" in payload.data_quality.missing_fields
    assert any("not found in campus topology" in a for a in payload.data_quality.assumptions)


def test_missing_topology_fallback():
    agent = ConnectivityAnalysisAgent()
    telemetry = {
        "GW_NKN_ISP": [
            {
                "timestamp": "2026-10-31T10:00:00Z",
                "latency_ms": 300.0,
                "packet_loss_pct": 5.0,
                "link_utilization_pct": 98.0,
                "device_status": "degraded",
            }
        ]
    }
    # No topology payload provided
    msg = MessageEnvelope(
        incident_id="INC-NO-TOPO-01",
        sender="orchestrator",
        recipient="connectivity_agent",
        message_type=MessageType.TASK_REQUEST,
        payload=TaskRequestPayload(task="analyze", telemetry=telemetry, topology=None),
    )
    responses = asyncio.run(agent.handle(msg))
    assert len(responses) == 1
    payload: FindingPayload = responses[0].payload  # type: ignore

    # Completeness must reflect missing topology penalty
    assert payload.data_quality.completeness <= 0.75
    assert any("no topology graph" in a.lower() for a in payload.data_quality.assumptions)


def test_empty_telemetry():
    agent = ConnectivityAnalysisAgent()
    msg = MessageEnvelope(
        incident_id="INC-EMPTY-TOPO-01",
        sender="orchestrator",
        recipient="connectivity_agent",
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
    agent = ConnectivityAnalysisAgent()
    responses = asyncio.run(agent.handle("invalid_syntax_json_string"))
    assert len(responses) == 1
    assert responses[0].message_type == MessageType.ERROR


def test_evidence_query_with_context():
    agent = ConnectivityAnalysisAgent()
    inc_id = "INC-QUERY-CONN-01"

    task_req = scenario_task_request("upstream_congestion", "connectivity_agent")
    task_req.incident_id = inc_id
    asyncio.run(agent.handle(task_req))

    q_msg = MessageEnvelope(
        incident_id=inc_id,
        sender="correlation_agent",
        recipient="connectivity_agent",
        message_type=MessageType.EVIDENCE_QUERY,
        payload=EvidenceQueryPayload(
            target_agent="connectivity_agent",
            cause_code=CauseCode.UPSTREAM_CONGESTION,
            device_ids=["GW_NKN_ISP"],
            metrics=["device_status"],
        ),
    )
    responses = asyncio.run(agent.handle(q_msg))
    assert len(responses) == 1
    resp = responses[0]
    assert resp.message_type == MessageType.EVIDENCE_RESPONSE
    resp_payload: EvidenceResponsePayload = resp.payload  # type: ignore
    assert resp_payload.supports is True
    assert resp_payload.confidence >= 0.70
    assert len(resp_payload.answers) >= 1


def test_evidence_query_without_context():
    agent = ConnectivityAnalysisAgent()
    q_msg = MessageEnvelope(
        incident_id="INC-NO-CACHE-CONN-99",
        sender="correlation_agent",
        recipient="connectivity_agent",
        message_type=MessageType.EVIDENCE_QUERY,
        payload=EvidenceQueryPayload(
            target_agent="connectivity_agent",
            cause_code=CauseCode.UPSTREAM_CONGESTION,
            device_ids=["GW_NKN_ISP"],
        ),
    )
    responses = asyncio.run(agent.handle(q_msg))
    assert len(responses) == 1
    resp_payload: EvidenceResponsePayload = responses[0].payload  # type: ignore
    assert resp_payload.supports is None
    assert resp_payload.confidence == 0.0
    assert "No cached telemetry context" in resp_payload.notes


def test_determinism():
    agent1 = ConnectivityAnalysisAgent()
    agent2 = ConnectivityAnalysisAgent()

    req1 = scenario_task_request("upstream_congestion", "connectivity_agent")
    req2 = scenario_task_request("upstream_congestion", "connectivity_agent")

    res1 = asyncio.run(agent1.handle(req1))[0].payload
    res2 = asyncio.run(agent2.handle(req2))[0].payload

    assert res1.confidence == res2.confidence
    assert len(res1.hypothesis_candidates) == len(res2.hypothesis_candidates)
    for c1, c2 in zip(res1.hypothesis_candidates, res2.hypothesis_candidates):
        assert c1.cause_code == c2.cause_code
        assert c1.score == c2.score