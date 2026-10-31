"""Tests for NetCoop AI protocol messages, envelope, and Pydantic models."""

from datetime import datetime, timezone
import json
import pytest

from netcoop.protocol.causes import CauseCode
from netcoop.protocol.messages import (
    ConflictNoticePayload,
    DataQuality,
    ErrorPayload,
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
    parse_message,
)


def test_task_request_round_trip():
    payload = TaskRequestPayload(
        task_id="TASK-101",
        target_device_ids=["DIST_SW_HOSTEL", "ACC_SW_HOSTEL_A"],
        target_segment="hostel_wifi",
        parameters={"priority": "high"},
    )
    envelope = MessageEnvelope(
        incident_id="INC-1001",
        sender="orchestrator",
        recipient="wifi_subsystem_agent",
        message_type=MessageType.TASK_REQUEST,
        payload=payload,
    )

    json_str = envelope.to_json()
    parsed = parse_message(json_str)

    assert parsed.incident_id == "INC-1001"
    assert parsed.message_type == MessageType.TASK_REQUEST
    assert isinstance(parsed.payload, TaskRequestPayload)
    assert parsed.payload.task_id == "TASK-101"
    assert parsed.payload.target_device_ids == ["DIST_SW_HOSTEL", "ACC_SW_HOSTEL_A"]


def test_finding_round_trip():
    finding = FindingPayload(
        agent="wifi_agent",
        scope=FindingScope(device_ids=["AP_HOSTEL_A_FL2"], segment="hostel_wifi"),
        hypothesis_candidates=[
            HypothesisCandidate(
                cause_code=CauseCode.WEAK_WIFI_SIGNAL,
                score=0.95,
                supporting_metrics=[
                    MetricEvidence(
                        metric="rssi_dbm",
                        value=-86.0,
                        unit="dBm",
                        baseline=-55.0,
                        interpretation="Severe signal attenuation",
                    )
                ],
                contradicting_metrics=[],
            )
        ],
        data_quality=DataQuality(
            completeness=0.98,
            stale_fields=[],
            missing_fields=[],
            assumptions=["Antenna misaligned"],
        ),
        confidence=0.92,
    )

    envelope = MessageEnvelope(
        incident_id="INC-1002",
        sender="wifi_agent",
        recipient="orchestrator",
        message_type=MessageType.FINDING,
        payload=finding,
    )

    json_str = envelope.to_json()
    parsed = parse_message(json_str)

    assert parsed.message_type == MessageType.FINDING
    assert isinstance(parsed.payload, FindingPayload)
    assert parsed.payload.confidence == 0.92
    assert parsed.payload.hypothesis_candidates[0].cause_code == CauseCode.WEAK_WIFI_SIGNAL
    assert parsed.payload.hypothesis_candidates[0].score == 0.95


def test_evidence_query_and_response_round_trip():
    query_payload = EvidenceQueryPayload(
        query_id="QRY-500",
        requested_by="wifi_agent",
        device_ids=["ACC_SW_HOSTEL_A"],
        metrics=["link_utilization_pct", "queue_drops"],
    )
    query_env = MessageEnvelope(
        incident_id="INC-1003",
        sender="wifi_agent",
        recipient="switch_agent",
        message_type=MessageType.EVIDENCE_QUERY,
        payload=query_payload,
    )
    parsed_q = parse_message(query_env.to_json())
    assert isinstance(parsed_q.payload, EvidenceQueryPayload)
    assert parsed_q.payload.query_id == "QRY-500"

    resp_payload = EvidenceResponsePayload(
        query_id="QRY-500",
        device_telemetry=[{"device_id": "ACC_SW_HOSTEL_A", "link_utilization_pct": 25.0}],
        matched_records_count=1,
    )
    resp_env = MessageEnvelope(
        incident_id="INC-1003",
        sender="switch_agent",
        recipient="wifi_agent",
        message_type=MessageType.EVIDENCE_RESPONSE,
        correlation_id=query_env.message_id,
        payload=resp_payload,
    )
    parsed_r = parse_message(resp_env.to_json())
    assert isinstance(parsed_r.payload, EvidenceResponsePayload)
    assert parsed_r.payload.matched_records_count == 1
    assert parsed_r.correlation_id == query_env.message_id


def test_conflict_notice_round_trip():
    payload = ConflictNoticePayload(
        conflict_id="CONF-101",
        conflicting_hypotheses=[
            {"agent": "wifi_agent", "cause": "WEAK_WIFI_SIGNAL"},
            {"agent": "switch_agent", "cause": "LINK_CONGESTION"},
        ],
        contending_agents=["wifi_agent", "switch_agent"],
        disputed_metrics=["link_utilization_pct"],
        resolution_strategy="prioritize_core",
    )
    env = MessageEnvelope(
        incident_id="INC-1004",
        sender="orchestrator",
        recipient="broadcast",
        message_type=MessageType.CONFLICT_NOTICE,
        payload=payload,
    )
    parsed = parse_message(env.to_json())
    assert isinstance(parsed.payload, ConflictNoticePayload)
    assert parsed.payload.conflict_id == "CONF-101"
    assert "wifi_agent" in parsed.payload.contending_agents


def test_error_payload_round_trip():
    payload = ErrorPayload(
        error_code="ERR_UNKNOWN_SCHEMA_VERSION",
        error_message="Unsupported version: 2.0",
        details={"schema_version": "2.0"},
        retryable=False,
    )
    env = MessageEnvelope(
        incident_id="INC-1005",
        sender="ingest_pipeline",
        recipient="orchestrator",
        message_type=MessageType.ERROR,
        payload=payload,
    )
    parsed = parse_message(env.to_json())
    assert isinstance(parsed.payload, ErrorPayload)
    assert parsed.payload.error_code == "ERR_UNKNOWN_SCHEMA_VERSION"
    assert not parsed.payload.retryable


def test_final_result_round_trip():
    payload = FinalResultPayload(
        incident_id="INC-1006",
        primary_root_cause=CauseCode.LINK_CONGESTION,
        confidence=0.96,
        affected_devices=["DIST_SW_HOSTEL"],
        affected_segment="hostel_wifi",
        remediation_recommendations=["Upgrade uplink to 20G or apply rate limiting"],
        summary="Hostel distribution uplink saturated due to peak evening traffic.",
        contributing_findings=[],
    )
    env = MessageEnvelope(
        incident_id="INC-1006",
        sender="orchestrator",
        recipient="broadcast",
        message_type=MessageType.FINAL_RESULT,
        payload=payload,
    )
    parsed = parse_message(env.to_json())
    assert isinstance(parsed.payload, FinalResultPayload)
    assert parsed.payload.primary_root_cause == CauseCode.LINK_CONGESTION
    assert parsed.payload.confidence == 0.96


def test_invalid_incident_id_raises():
    with pytest.raises(Exception):
        MessageEnvelope(
            incident_id="INVALID_ID_WITHOUT_PREFIX",
            sender="orchestrator",
            recipient="broadcast",
            message_type=MessageType.FINAL_RESULT,
            payload={},
        )


def test_invalid_schema_version_raises():
    with pytest.raises(Exception):
        MessageEnvelope(
            incident_id="INC-1007",
            schema_version="99.9",
            sender="orchestrator",
            recipient="broadcast",
            message_type=MessageType.FINAL_RESULT,
            payload={},
        )


def test_empty_recipient_raises():
    with pytest.raises(Exception):
        MessageEnvelope(
            incident_id="INC-1008",
            sender="orchestrator",
            recipient="   ",
            message_type=MessageType.FINAL_RESULT,
            payload={},
        )
