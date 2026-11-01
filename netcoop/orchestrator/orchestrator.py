"""NetCoop AI Orchestrator - Master Coordination Engine.

Coordinates the full end-to-end diagnostic workflow:
1. Ingests raw telemetry and validates syntax / schema integrity.
2. Dispatches task_requests in parallel to Telemetry, Infrastructure, and Connectivity agents.
3. Coordinates correlation rounds, arbitrating conflicts and handling peer evidence queries.
4. Synthesizes consensus report via RecommendationReportingAgent.
5. Captures all messages in MessageLog and checkpoints state across every stage.
"""

import asyncio
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional, Union

from netcoop.agents.base import BaseAgent
from netcoop.agents.connectivity_agent import ConnectivityAnalysisAgent
from netcoop.agents.correlation_agent import FaultCorrelationAgent
from netcoop.agents.infrastructure_agent import InfrastructureHealthAgent
from netcoop.agents.reporting_agent import (
    RecommendationReportingAgent,
    build_invalid_input_report,
)
from netcoop.agents.telemetry_agent import TelemetryPerformanceAgent
from netcoop.config import agent_config, load_config
from netcoop.data.topology import CampusTopology
from netcoop.ingest import IngestResult, ingest
from netcoop.orchestrator.message_bus import InProcessBus, MessageBus, MessageLog
from netcoop.orchestrator.state_store import StateStore
from netcoop.protocol.messages import (
    DataQuality,
    EvidenceQueryPayload,
    EvidenceResponsePayload,
    FinalResultPayload,
    FindingPayload,
    MessageEnvelope,
    MessageType,
    TaskRequestPayload,
)
from netcoop.reporting.report_models import CorrelationResult, FinalReport


def build_default_agents(config: Optional[Dict[str, Any]] = None) -> List[BaseAgent]:
    """Instantiate and return the five specialized NetCoop AI autonomous agents."""
    return [
        TelemetryPerformanceAgent(config=config),
        InfrastructureHealthAgent(config=config),
        ConnectivityAnalysisAgent(config=config),
        FaultCorrelationAgent(config=config),
        RecommendationReportingAgent(config=config),
    ]


class Orchestrator:
    """Master workflow orchestrator managing concurrent multi-agent fault diagnosis."""

    def __init__(
        self,
        bus: Optional[MessageBus] = None,
        state_store: Optional[StateStore] = None,
        config: Optional[Dict[str, Any]] = None,
        agents: Optional[List[BaseAgent]] = None,
    ):
        self.sys_config = config or load_config()
        self.orch_config = agent_config("orchestrator")
        timeout_s = float(self.orch_config.get("agent_timeout_s", 5.0))
        log_dir = self.orch_config.get("log_dir", "logs")

        self.message_log = MessageLog(log_dir=log_dir)
        self.state_store = state_store or StateStore(log_dir=log_dir)
        self.bus = bus or InProcessBus(timeout_s=timeout_s, message_log=self.message_log)

        # Register agents
        registered_agents = agents if agents is not None else build_default_agents(config=self.sys_config)
        for agent in registered_agents:
            self.bus.register(agent)

    def register_agent(self, agent: BaseAgent) -> None:
        """Register an agent on the orchestrator bus."""
        self.bus.register(agent)

    async def run_diagnosis(
        self,
        input_path_or_dict: Union[str, Path, Dict[str, Any], List[Any]],
        topology: Optional[CampusTopology] = None,
        config: Optional[Dict[str, Any]] = None,
        resume_incident_id: Optional[str] = None,
    ) -> FinalReport:
        """Execute end-to-end multi-agent diagnosis workflow without raising uncaught exceptions."""
        cfg = config or self.sys_config
        topo = topology or CampusTopology.build_iit_bhubaneswar_topology()

        # Step 0: Check for resumption from existing checkpoint
        if resume_incident_id:
            cached_state = self.state_store.resume(resume_incident_id)
            if cached_state and "reported" in cached_state:
                rep_data = cached_state["reported"].get("final_report")
                if rep_data:
                    return FinalReport.model_validate(rep_data)

        # Step 1: Telemetry Ingestion & Syntax/Schema Validation
        try:
            ingest_res: IngestResult = ingest(input_path_or_dict, topology=topo, config=cfg)
        except Exception as ex:
            return build_invalid_input_report("INC-ERR-INGEST", str(ex))

        incident_id = ingest_res.incident_id

        # Ingestion failure (corrupted JSON, unknown schema version, empty input)
        if not ingest_res.ok:
            report = build_invalid_input_report(
                incident_id=incident_id,
                validation_result_or_errors=ingest_res.validation or ingest_res.errors,
                normalization_log=ingest_res.normalization_log,
            )
            self.state_store.checkpoint(incident_id, "ingested", {"ok": False, "report": report.model_dump()})
            return report

        # Checkpoint: Ingested
        self.state_store.checkpoint(
            incident_id,
            "ingested",
            {
                "ok": True,
                "partial": ingest_res.partial,
                "schema_version": ingest_res.schema_version,
                "data_quality": ingest_res.data_quality.model_dump(),
                "device_count": len(ingest_res.normalized_telemetry),
            },
        )

        # Step 2: Parallel Analysis Agent Dispatch (Gather)
        analysis_agent_names = ["telemetry_agent", "infrastructure_agent", "connectivity_agent"]
        agent_status: Dict[str, str] = {name: "ok" for name in analysis_agent_names}
        collected_findings: List[FindingPayload] = []

        topo_dict = topo.to_dict() if hasattr(topo, "to_dict") else {}
        target_devs = list(ingest_res.normalized_telemetry.keys())

        async def _invoke_analysis_agent(agent_name: str) -> Optional[FindingPayload]:
            req_msg = MessageEnvelope(
                incident_id=incident_id,
                sender="orchestrator",
                recipient=agent_name,
                message_type=MessageType.TASK_REQUEST,
                payload=TaskRequestPayload(
                    task="analyze",
                    target_device_ids=target_devs,
                    telemetry=ingest_res.normalized_telemetry,
                    topology=topo_dict,
                    data_quality=ingest_res.data_quality,
                    normalization_log=ingest_res.normalization_log,
                ),
            )
            responses = await self.bus.send(req_msg)
            if not responses:
                agent_status[agent_name] = "degraded"
                return None

            resp = responses[0]
            if resp.message_type == MessageType.ERROR:
                err_code = getattr(resp.payload, "error_code", "ERROR")
                agent_status[agent_name] = "timeout" if err_code == "TIMEOUT" else "degraded"
                return None

            if resp.message_type == MessageType.FINDING:
                payload = resp.payload
                return payload if isinstance(payload, FindingPayload) else FindingPayload.model_validate(payload)

            agent_status[agent_name] = "degraded"
            return None

        # Execute analysis agents concurrently
        gathered_results = await asyncio.gather(
            *[_invoke_analysis_agent(name) for name in analysis_agent_names],
            return_exceptions=True,
        )

        for name, res in zip(analysis_agent_names, gathered_results):
            if isinstance(res, Exception):
                agent_status[name] = "degraded"
            elif isinstance(res, FindingPayload):
                collected_findings.append(res)
            elif res is None:
                pass

        # Checkpoint: Analysed
        self.state_store.checkpoint(
            incident_id,
            "analysed",
            {
                "findings_count": len(collected_findings),
                "agent_status": agent_status,
                "findings": [f.model_dump() for f in collected_findings],
            },
        )

        # Step 3: Correlation Round Loop (Max 2 Rounds)
        max_query_rounds = int(self.orch_config.get("max_query_rounds", 2))
        round_num = 0
        evidence_responses: List[EvidenceResponsePayload] = []
        correlation_result: Optional[CorrelationResult] = None

        while round_num <= max_query_rounds:
            corr_req = MessageEnvelope(
                incident_id=incident_id,
                sender="orchestrator",
                recipient="correlation_agent",
                message_type=MessageType.TASK_REQUEST,
                payload=TaskRequestPayload(
                    task="correlate",
                    findings=collected_findings,
                    agent_status=agent_status,
                    data_quality=ingest_res.data_quality,
                    evidence_responses=evidence_responses,
                    round=round_num,
                ),
            )

            corr_responses = await self.bus.send(corr_req)

            # Check if correlation agent requested peer evidence queries
            queries = [m for m in corr_responses if m.message_type == MessageType.EVIDENCE_QUERY]
            final_res = next((m for m in corr_responses if m.message_type == MessageType.FINAL_RESULT), None)

            if queries and round_num < max_query_rounds:
                # Forward each evidence query to requested target agent
                for q_env in queries:
                    q_payload = (
                        q_env.payload
                        if isinstance(q_env.payload, EvidenceQueryPayload)
                        else EvidenceQueryPayload.model_validate(q_env.payload)
                    )
                    target = q_payload.target_agent or "telemetry_agent"
                    q_forward = MessageEnvelope(
                        incident_id=incident_id,
                        sender="orchestrator",
                        recipient=target,
                        message_type=MessageType.EVIDENCE_QUERY,
                        correlation_id=q_env.message_id,
                        payload=q_payload,
                    )
                    agent_answers = await self.bus.send(q_forward)
                    for a_msg in agent_answers:
                        if a_msg.message_type == MessageType.EVIDENCE_RESPONSE:
                            resp_p = (
                                a_msg.payload
                                if isinstance(a_msg.payload, EvidenceResponsePayload)
                                else EvidenceResponsePayload.model_validate(a_msg.payload)
                            )
                            evidence_responses.append(resp_p)
                round_num += 1
                continue

            if final_res and isinstance(final_res.payload, FinalResultPayload):
                raw_cr = final_res.payload.correlation_result
                if isinstance(raw_cr, CorrelationResult):
                    correlation_result = raw_cr
                elif isinstance(raw_cr, dict):
                    correlation_result = CorrelationResult.model_validate(raw_cr)
                break

            # Fallback if no final_result returned
            break

        # Checkpoint: Correlated
        if correlation_result:
            self.state_store.checkpoint(
                incident_id,
                "correlated",
                {
                    "primary_cause": correlation_result.primary_cause_code.value,
                    "confidence": correlation_result.confidence,
                    "status": correlation_result.status,
                    "rounds_used": round_num,
                    "correlation_result": correlation_result.model_dump(),
                },
            )

        # Step 4: Executive Reporting Generation
        rep_req = MessageEnvelope(
            incident_id=incident_id,
            sender="orchestrator",
            recipient="reporting_agent",
            message_type=MessageType.TASK_REQUEST,
            payload=TaskRequestPayload(
                task="report",
                correlation_result=correlation_result,
                agent_status=agent_status,
                data_quality=ingest_res.data_quality,
                normalization_log=ingest_res.normalization_log,
                message_trace_ref=f"TRACE-{incident_id}",
            ),
        )

        rep_responses = await self.bus.send(rep_req)
        final_report: Optional[FinalReport] = None

        for resp in rep_responses:
            if resp.message_type == MessageType.FINAL_RESULT and isinstance(resp.payload, FinalResultPayload):
                raw_rep = resp.payload.report
                if isinstance(raw_rep, FinalReport):
                    final_report = raw_rep
                elif isinstance(raw_rep, dict):
                    final_report = FinalReport.model_validate(raw_rep)
                break

        if not final_report:
            # Fallback safe report in case of unexpected reporting failure
            final_report = build_invalid_input_report(
                incident_id=incident_id,
                validation_result_or_errors="Reporting pipeline synthesis failure.",
                normalization_log=ingest_res.normalization_log,
            )

        # Checkpoint: Reported
        self.state_store.checkpoint(
            incident_id,
            "reported",
            {
                "status": final_report.status,
                "suspected_root_cause": final_report.suspected_root_cause,
                "confidence": final_report.confidence,
                "final_report": final_report.model_dump(),
            },
        )

        return final_report

    def run_diagnosis_sync(
        self,
        input_path_or_dict: Union[str, Path, Dict[str, Any], List[Any]],
        topology: Optional[CampusTopology] = None,
        config: Optional[Dict[str, Any]] = None,
        resume_incident_id: Optional[str] = None,
    ) -> FinalReport:
        """Synchronous wrapper for run_diagnosis."""
        return asyncio.run(
            self.run_diagnosis(
                input_path_or_dict=input_path_or_dict,
                topology=topology,
                config=config,
                resume_incident_id=resume_incident_id,
            )
        )


# Global standalone functions for convenient imports
def run_diagnosis_sync(
    input_path_or_dict: Union[str, Path, Dict[str, Any], List[Any]],
    topology: Optional[CampusTopology] = None,
    config: Optional[Dict[str, Any]] = None,
    resume_incident_id: Optional[str] = None,
) -> FinalReport:
    """Synchronously run end-to-end multi-agent diagnosis pipeline."""
    orch = Orchestrator(config=config)
    return orch.run_diagnosis_sync(
        input_path_or_dict=input_path_or_dict,
        topology=topology,
        config=config,
        resume_incident_id=resume_incident_id,
    )


async def run_diagnosis(
    input_path_or_dict: Union[str, Path, Dict[str, Any], List[Any]],
    topology: Optional[CampusTopology] = None,
    config: Optional[Dict[str, Any]] = None,
    resume_incident_id: Optional[str] = None,
) -> FinalReport:
    """Asynchronously run end-to-end multi-agent diagnosis pipeline."""
    orch = Orchestrator(config=config)
    return await orch.run_diagnosis(
        input_path_or_dict=input_path_or_dict,
        topology=topology,
        config=config,
        resume_incident_id=resume_incident_id,
    )