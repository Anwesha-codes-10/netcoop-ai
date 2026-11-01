"""Tests for Orchestrator, MessageBus, StateStore, and Error Resilience.

Covers:
- Fake slow agent (timeout handling)
- Fake crashing agent (exception handling)
- Fake agent returning error message
- All analysis agents failing gracefully (no crash)
- Evidence query loop capping at max_query_rounds (2)
- MessageLog JSONL validation and summary formatting
- StateStore checkpointing and resumption
- Invalid input pipeline termination without calling analysis agents
- Synchronous run_diagnosis_sync execution
"""

import asyncio
import json
from pathlib import Path
import pytest

from netcoop.agents.base import BaseAgent
from netcoop.orchestrator import (
    InProcessBus,
    MessageLog,
    Orchestrator,
    StateStore,
    run_diagnosis_sync,
)
from netcoop.protocol.causes import CauseCode
from netcoop.protocol.messages import (
    DataQuality,
    EvidenceQueryPayload,
    FinalResultPayload,
    FindingPayload,
    FindingScope,
    HypothesisCandidate,
    MessageEnvelope,
    MessageType,
    TaskRequestPayload,
)
from netcoop.reporting.report_models import CorrelationResult, FinalReport


# -----------------------------------------------------------------------------
# Mock Agents for Fault Injection Tests
# -----------------------------------------------------------------------------


class FakeSlowAgent(BaseAgent):
    """Simulates an agent that hangs and triggers bus timeout."""

    def __init__(self, delay_s: float = 2.0):
        super().__init__()
        self.name = "telemetry_agent"

    async def _process(self, message: MessageEnvelope):
        await asyncio.sleep(2.0)
        return []


class FakeCrashingAgent(BaseAgent):
    """Simulates an agent that raises an unhandled exception."""

    def __init__(self):
        super().__init__()
        self.name = "infrastructure_agent"

    async def _process(self, message: MessageEnvelope):
        raise RuntimeError("Fatal hardware sensor interface fault")


class FakeErrorReturningAgent(BaseAgent):
    """Simulates an agent returning an explicit error message envelope."""

    def __init__(self):
        super().__init__()
        self.name = "connectivity_agent"

    async def _process(self, message: MessageEnvelope):
        return [self.make_error(error_code="ERR_INTERNAL_DEGRADED", error_message="Sensor degraded")]


class FakeAlwaysQueryCorrelationAgent(BaseAgent):
    """Simulates a correlation agent that continually asks evidence queries."""

    def __init__(self):
        super().__init__()
        self.name = "correlation_agent"
        self.query_count = 0

    async def _process(self, message: MessageEnvelope):
        self.query_count += 1
        # Always asks for queries
        q_payload = EvidenceQueryPayload(
            target_agent="telemetry_agent",
            cause_code=CauseCode.LINK_CONGESTION,
            question="Need more queue drop data",
            device_ids=["DIST_SW_HOSTEL"],
        )
        return [self.make_message(recipient="telemetry_agent", message_type=MessageType.EVIDENCE_QUERY, payload=q_payload)]


# -----------------------------------------------------------------------------
# Test Cases
# -----------------------------------------------------------------------------


def test_orchestrator_handles_slow_agent_timeout(tmp_path):
    """A slow agent triggers timeout, is marked 'timeout', and diagnosis completes."""
    bus = InProcessBus(timeout_s=0.2, message_log=MessageLog(tmp_path))
    orch = Orchestrator(bus=bus, state_store=StateStore(tmp_path))

    # Replace telemetry_agent with slow agent
    orch.register_agent(FakeSlowAgent(delay_s=1.0))

    telemetry = {"DIST_SW_HOSTEL": [{"timestamp": "2026-10-31T10:00:00Z", "latency_ms": 100.0, "link_utilization_pct": 95.0}]}
    report = asyncio.run(orch.run_diagnosis(telemetry))

    assert isinstance(report, FinalReport)
    assert "telemetry_agent" in report.agent_status
    assert report.agent_status["telemetry_agent"] == "timeout"
    assert any("telemetry_agent" in lim and "timeout" in lim for lim in report.limitations)


def test_orchestrator_handles_crashing_agent(tmp_path):
    """A crashing agent is caught, marked 'degraded', and diagnosis completes."""
    bus = InProcessBus(timeout_s=1.0, message_log=MessageLog(tmp_path))
    orch = Orchestrator(bus=bus, state_store=StateStore(tmp_path))

    orch.register_agent(FakeCrashingAgent())

    telemetry = {"DIST_SW_HOSTEL": [{"timestamp": "2026-10-31T10:00:00Z", "latency_ms": 100.0, "link_utilization_pct": 95.0}]}
    report = asyncio.run(orch.run_diagnosis(telemetry))

    assert isinstance(report, FinalReport)
    assert report.agent_status["infrastructure_agent"] == "degraded"


def test_orchestrator_handles_error_returning_agent(tmp_path):
    """An agent returning an error message is marked 'degraded'."""
    bus = InProcessBus(timeout_s=1.0, message_log=MessageLog(tmp_path))
    orch = Orchestrator(bus=bus, state_store=StateStore(tmp_path))

    orch.register_agent(FakeErrorReturningAgent())

    telemetry = {"DIST_SW_HOSTEL": [{"timestamp": "2026-10-31T10:00:00Z", "latency_ms": 100.0, "link_utilization_pct": 95.0}]}
    report = asyncio.run(orch.run_diagnosis(telemetry))

    assert isinstance(report, FinalReport)
    assert report.agent_status["connectivity_agent"] == "degraded"


def test_all_analysis_agents_failing_gives_report_never_crashes(tmp_path):
    """If all three analysis agents fail, orchestrator still returns a report without crashing."""
    bus = InProcessBus(timeout_s=0.2, message_log=MessageLog(tmp_path))
    orch = Orchestrator(bus=bus, state_store=StateStore(tmp_path))

    orch.register_agent(FakeSlowAgent())
    orch.register_agent(FakeCrashingAgent())
    orch.register_agent(FakeErrorReturningAgent())

    telemetry = {"DIST_SW_HOSTEL": [{"timestamp": "2026-10-31T10:00:00Z", "latency_ms": 100.0, "link_utilization_pct": 95.0}]}
    report = asyncio.run(orch.run_diagnosis(telemetry))

    assert isinstance(report, FinalReport)
    assert report.status in ["insufficient_evidence", "partial"]
    assert report.suspected_root_cause in ["Undetermined", "Link Congestion & Bandwidth Saturation"]


def test_evidence_query_loop_stops_at_max_rounds(tmp_path):
    """Orchestrator hard caps correlation evidence queries at max_query_rounds (2)."""
    bus = InProcessBus(timeout_s=1.0, message_log=MessageLog(tmp_path))
    orch = Orchestrator(bus=bus, state_store=StateStore(tmp_path))

    fake_corr = FakeAlwaysQueryCorrelationAgent()
    orch.register_agent(fake_corr)

    telemetry = {"DIST_SW_HOSTEL": [{"timestamp": "2026-10-31T10:00:00Z", "latency_ms": 100.0, "link_utilization_pct": 95.0}]}
    report = asyncio.run(orch.run_diagnosis(telemetry))

    assert isinstance(report, FinalReport)
    # The query loop must have terminated (at round <= 2)
    assert fake_corr.query_count <= 3


def test_message_log_jsonl_and_summaries(tmp_path):
    """Verify that message logs append valid JSONL and format human-readable summaries."""
    log = MessageLog(log_dir=tmp_path)
    msg = MessageEnvelope(
        incident_id="INC-LOG-TEST-01",
        sender="telemetry_agent",
        recipient="correlation_agent",
        message_type=MessageType.FINDING,
        payload=FindingPayload(
            agent="telemetry_agent",
            scope=FindingScope(device_ids=["DIST_SW_HOSTEL"]),
            hypothesis_candidates=[HypothesisCandidate(cause_code=CauseCode.LINK_CONGESTION, score=0.82)],
            data_quality=DataQuality(completeness=1.0),
            confidence=0.82,
        ),
    )

    log.log_message(msg)

    # Check files exist and contain valid JSON
    msg_file = tmp_path / "messages_INC-LOG-TEST-01.jsonl"
    find_file = tmp_path / "findings_INC-LOG-TEST-01.jsonl"
    assert msg_file.exists()
    assert find_file.exists()

    with open(msg_file, "r", encoding="utf-8") as f:
        data = json.loads(f.readline().strip())
        assert data["incident_id"] == "INC-LOG-TEST-01"

    # Verify summary string
    summary = log.summarize(msg)
    assert "telemetry_agent -> correlation_agent" in summary
    assert "LINK_CONGESTION" in summary
    assert "0.82" in summary


def test_state_store_checkpoint_and_resume(tmp_path):
    """Verify state checkpointing across stages and resumption."""
    store = StateStore(log_dir=tmp_path)
    inc_id = "INC-STATE-01"

    store.checkpoint(inc_id, "ingested", {"step": 1})
    store.checkpoint(inc_id, "analysed", {"step": 2})

    loaded = store.load(inc_id)
    assert loaded["last_stage"] == "analysed"
    assert loaded["ingested"]["step"] == 1
    assert loaded["analysed"]["step"] == 2

    resumed = store.resume(inc_id)
    assert resumed["last_stage"] == "analysed"


def test_invalid_input_produces_invalid_input_without_agents(tmp_path):
    """Corrupted JSON halts immediately at ingestion and returns invalid_input report."""
    bus = InProcessBus(timeout_s=1.0, message_log=MessageLog(tmp_path))
    orch = Orchestrator(bus=bus, state_store=StateStore(tmp_path))

    corrupted_json = '{"device_id": "DIST_SW_HOSTEL", "metrics": {'
    report = asyncio.run(orch.run_diagnosis(corrupted_json))

    assert report.status == "invalid_input"
    assert report.suspected_root_cause == "Undetermined"
    assert report.confidence == 0.0


def test_run_diagnosis_sync_execution():
    """Verify run_diagnosis_sync wrapper works directly from normal sync tests."""
    telemetry = {
        "DIST_SW_HOSTEL": [
            {
                "timestamp": "2026-10-31T10:00:00Z",
                "latency_ms": 150.0,
                "packet_loss_pct": 2.0,
                "link_utilization_pct": 95.0,
                "throughput_mbps": 9500.0,
                "bandwidth_mbps": 10000.0,
            }
        ]
    }
    report = run_diagnosis_sync(telemetry)
    print("REPORT STATUS:", report.status)
    print("ROOT CAUSE:", report.root_cause_code)
    print("REPORT DETAILS:", report)
    assert isinstance(report, FinalReport)
    assert report.root_cause_code == CauseCode.LINK_CONGESTION
    assert report.status == "diagnosed"