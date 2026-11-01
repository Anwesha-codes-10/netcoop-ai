"""NetCoop AI - Recommendation and Reporting Agent.

Transforms multi-agent consensus correlation results into actionable,
human-readable executive diagnosis reports (FinalReport).
Constructs prioritized remediation steps from recommendations.yaml, formats alternative
hypotheses explanations, identifies operational limitations, and generates safe
simulated remediation execution previews.
"""

from pathlib import Path
from typing import Any, Dict, List, Optional, Union
import yaml

from netcoop.agents.base import BaseAgent
from netcoop.config import agent_config, get_config_dir, load_config
from netcoop.protocol.causes import CAUSE_LABELS, CauseCode
from netcoop.protocol.messages import (
    DataQuality,
    FinalResultPayload,
    MessageEnvelope,
    MessageType,
    TaskRequestPayload,
)
from netcoop.protocol.validators import ValidationIssue, ValidationResult
from netcoop.reporting.report_models import (
    CorrelationResult,
    FinalReport,
    RankedHypothesis,
    RecommendedAction,
)


def build_invalid_input_report(
    incident_id: str,
    validation_result_or_errors: Any,
    normalization_log: Optional[List[Dict[str, Any]]] = None,
) -> FinalReport:
    """Construct a standardized FinalReport for ingestion or schema validation failures."""
    limitations: List[str] = []

    if isinstance(validation_result_or_errors, ValidationResult):
        for err in validation_result_or_errors.errors:
            limitations.append(f"Validation error: {err.message}")
    elif isinstance(validation_result_or_errors, list):
        for err in validation_result_or_errors:
            if isinstance(err, ValidationIssue):
                limitations.append(f"Validation error: {err.message}")
            else:
                limitations.append(f"Validation error: {str(err)}")
    elif isinstance(validation_result_or_errors, str):
        limitations.append(f"Validation error: {validation_result_or_errors}")

    limitations.append("This diagnosis is generated from synthetic/supplied telemetry and requires human review and confirmation prior to operational changes.")

    actions = [
        RecommendedAction(
            priority=1,
            action="Verify telemetry JSON syntax, schema version ('1.0' or '0.9'), and required device/timestamp fields, then re-ingest.",
            rationale="Input telemetry payload failed validation constraints.",
            requires_human_review=True,
        )
    ]

    return FinalReport(
        incident_id=incident_id,
        status="invalid_input",
        suspected_root_cause="Undetermined",
        root_cause_code=CauseCode.UNKNOWN,
        confidence=0.0,
        confidence_category="insufficient",
        affected_devices=[],
        affected_segments=[],
        supporting_evidence=[],
        alternative_causes=[],
        recommended_actions=actions,
        evidence_sources=[],
        limitations=limitations,
        conflicts_resolved=[],
        data_quality={"completeness": 0.0, "missing_fields": [], "stale_fields": [], "assumptions": ["Payload failed schema validation; no telemetry ingested."]},
        normalization_log=normalization_log or [],
        agent_status={},
        simulated_remediation_preview="SIMULATED: Reject malformed payload and request sensor re-transmission.",
        message_trace_ref=None,
    )


class RecommendationReportingAgent(BaseAgent):
    """Autonomous agent generating executive diagnosis reports and prioritized remediation plans."""

    def __init__(self, config: Optional[Dict[str, Any]] = None):
        super().__init__(config=config)
        self.name = "reporting_agent"
        self.capabilities = [
            "recommendation_reporting",
            "remediation_preview",
            "executive_summary",
            "conflict_explanation",
        ]

        # Load configurations
        sys_cfg = load_config()
        self.scoring_cfg: Dict[str, Any] = sys_cfg.get("scoring", {})
        r_cfg = agent_config("reporting_agent")
        if config:
            r_cfg.update(config)

        self.agent_cfg: Dict[str, Any] = r_cfg
        self.max_supporting_evidence: int = int(r_cfg.get("max_supporting_evidence", 6))
        self.max_alternative_causes: int = int(r_cfg.get("max_alternative_causes", 3))
        self.completeness_threshold: float = float(
            r_cfg.get("completeness_threshold", self.scoring_cfg.get("caps", {}).get("completeness_threshold", 0.60))
        )
        self.disclaimer: str = r_cfg.get(
            "disclaimer",
            "This diagnosis is generated from synthetic/supplied telemetry and requires human review and confirmation prior to operational changes.",
        )
        self.recommendations_kb: Dict[str, Any] = self._load_recommendations_kb()

    def _load_recommendations_kb(self) -> Dict[str, Any]:
        """Load cause-specific recommendation templates from config/recommendations.yaml."""
        cfg_dir = get_config_dir()
        kb_path = cfg_dir / "recommendations.yaml"
        if kb_path.exists():
            with open(kb_path, "r", encoding="utf-8") as f:
                data = yaml.safe_load(f) or {}
                return data.get("recommendations", {})
        return {}

    # -------------------------------------------------------------------------
    # BaseAgent Abstract Implementation
    # -------------------------------------------------------------------------

    async def _process(self, message: MessageEnvelope) -> List[MessageEnvelope]:
        """Process task_request (task='report') and return final_result containing FinalReport."""
        if message.message_type != MessageType.TASK_REQUEST:
            return []

        task_payload = (
            message.payload
            if isinstance(message.payload, TaskRequestPayload)
            else TaskRequestPayload.model_validate(message.payload)
        )

        if task_payload.task != "report":
            return []

        # Validate correlation_result presence
        if not task_payload.correlation_result:
            return [
                self.make_error(
                    error_code="ERR_MISSING_REQUIRED_FIELD",
                    error_message="Task request payload missing required correlation_result.",
                    incident_id=message.incident_id,
                    recipient=message.sender,
                    correlation_id=message.message_id,
                )
            ]

        # Deserialize CorrelationResult
        try:
            corr_res = (
                task_payload.correlation_result
                if isinstance(task_payload.correlation_result, CorrelationResult)
                else CorrelationResult.model_validate(task_payload.correlation_result)
            )
        except Exception as ex:
            return [
                self.make_error(
                    error_code="ERR_WRONG_TYPE",
                    error_message=f"Failed to parse correlation_result: {ex}",
                    incident_id=message.incident_id,
                    recipient=message.sender,
                    correlation_id=message.message_id,
                )
            ]

        # Generate report
        report = self.build_report(
            incident_id=message.incident_id,
            correlation_result=corr_res,
            agent_status=task_payload.agent_status or {},
            data_quality=task_payload.data_quality,
            normalization_log=task_payload.normalization_log or [],
            message_trace_ref=task_payload.message_trace_ref,
        )

        final_env = self.make_message(
            recipient="orchestrator",
            message_type=MessageType.FINAL_RESULT,
            payload=FinalResultPayload(
                incident_id=message.incident_id,
                primary_root_cause=report.root_cause_code,
                confidence=report.confidence,
                affected_devices=report.affected_devices,
                affected_segment=report.affected_segments[0] if report.affected_segments else None,
                remediation_recommendations=[a.action for a in report.recommended_actions],
                summary=f"Incident {message.incident_id}: {report.suspected_root_cause} with {report.confidence_category} confidence ({report.confidence:.2f}).",
                stage="report",
                report=report,
            ),
            incident_id=message.incident_id,
            correlation_id=message.message_id,
        )
        return [final_env]

    # -------------------------------------------------------------------------
    # Core Report Builder
    # -------------------------------------------------------------------------

    def build_report(
        self,
        incident_id: str,
        correlation_result: CorrelationResult,
        agent_status: Dict[str, str],
        data_quality: Optional[Union[DataQuality, Dict[str, Any]]],
        normalization_log: List[Dict[str, Any]],
        message_trace_ref: Optional[str] = None,
    ) -> FinalReport:
        """Synthesize correlation result, agent health, and data quality into FinalReport."""
        # Normalize data quality
        dq_dict: Dict[str, Any] = {}
        completeness = 1.0
        missing_fields: List[str] = []
        stale_fields: List[str] = []
        assumptions: List[str] = []

        if isinstance(data_quality, DataQuality):
            dq_dict = data_quality.model_dump()
            completeness = data_quality.completeness
            missing_fields = data_quality.missing_fields
            stale_fields = data_quality.stale_fields
            assumptions = data_quality.assumptions
        elif isinstance(data_quality, dict):
            dq_dict = data_quality
            completeness = float(data_quality.get("completeness", 1.0))
            missing_fields = data_quality.get("missing_fields", [])
            stale_fields = data_quality.get("stale_fields", [])
            assumptions = data_quality.get("assumptions", [])

        # Step 1: Determine final status
        has_degraded_agent = any(st.lower() in ["degraded", "timeout"] for st in agent_status.values())
        
        if correlation_result.status == "insufficient_evidence":
            if completeness < self.completeness_threshold:
                status = "partial"
            else:
                status = "insufficient_evidence"

        elif has_degraded_agent or completeness < self.completeness_threshold:
                status = "partial"
        else:
            status = "diagnosed"

        # Step 2: Determine root cause labels
        
        if correlation_result.primary_cause_code == CauseCode.UNKNOWN:
            suspected_root_cause = "Undetermined"
            root_cause_code = CauseCode.UNKNOWN
        elif correlation_result.primary_cause_code == CauseCode.NORMAL:
            suspected_root_cause = "No fault detected"
            root_cause_code = CauseCode.NORMAL
        else:
            root_cause_code = correlation_result.primary_cause_code
            suspected_root_cause = CAUSE_LABELS.get(root_cause_code, root_cause_code.value)

        # Step 3: Format and cap supporting evidence
        supporting_evidence: List[Dict[str, Any]] = []
        primary_hypo: Optional[RankedHypothesis] = None
        for h in correlation_result.ranked_hypotheses:
            if h.cause_code == correlation_result.primary_cause_code:
                primary_hypo = h
                break

        if primary_hypo and status != "insufficient_evidence":
            for ev in primary_hypo.supporting_evidence:
                item = dict(ev)
                # Ensure device_id and source_agent are populated
                if "device_id" not in item:
                    item["device_id"] = correlation_result.affected_devices[0] if correlation_result.affected_devices else "CAMPUS_CORE"
                if "source_agent" not in item:
                    item["source_agent"] = primary_hypo.supporting_agents[0] if primary_hypo.supporting_agents else "analysis_agent"
                supporting_evidence.append(item)

        supporting_evidence = supporting_evidence[: self.max_supporting_evidence]

        # Step 4: Format alternative causes
        alternative_causes: List[Dict[str, Any]] = []
        for h in correlation_result.ranked_hypotheses:
            if h.cause_code == correlation_result.primary_cause_code:
                continue

            reason = ""
            if h.contradicting_evidence:
                c_ev = h.contradicting_evidence[0]
                reason = f"Contradicted by {c_ev.get('metric', 'telemetry')} ({c_ev.get('value', '')}{c_ev.get('unit', '')}): {c_ev.get('interpretation', 'contradicting indicator')}."
            elif h.rules_applied:
                reason = f"Subordinated by conflict arbitration rule(s): {', '.join(h.rules_applied)}."
            else:
                reason = f"Lower correlation confidence score ({h.score:.2f}) compared to primary root cause ({correlation_result.confidence:.2f})."

            alternative_causes.append({
                "cause": h.cause_code.value,
                "score": h.score,
                "why_less_likely": reason,
            })

        alternative_causes = alternative_causes[: self.max_alternative_causes]

        # Step 5: Construct recommended actions
        recommended_actions = self._build_recommended_actions(
            root_cause_code=root_cause_code,
            status=status,
            correlation_result=correlation_result,
        )

        # Step 6: Identify limitations
        limitations = self._build_limitations(
            agent_status=agent_status,
            data_quality_dict=dq_dict,
            completeness=completeness,
            missing_fields=missing_fields,
            stale_fields=stale_fields,
            assumptions=assumptions,
            correlation_result=correlation_result,
            status=status,
        )

        # Step 7: Format simulated remediation preview
        preview_text = self._build_remediation_preview(root_cause_code=root_cause_code, status=status)

        # Step 8: Evidence sources
        sources: Set[str] = set()
        if primary_hypo:
            sources.update(primary_hypo.supporting_agents)
        sources.update(correlation_result.agent_support.keys())

        return FinalReport(
            incident_id=incident_id,
            status=status,
            suspected_root_cause=suspected_root_cause,
            root_cause_code=root_cause_code,
            confidence=correlation_result.confidence,
            confidence_category=correlation_result.confidence_category,
            affected_devices=correlation_result.affected_devices,
            affected_segments=correlation_result.affected_segments,
            supporting_evidence=supporting_evidence,
            alternative_causes=alternative_causes,
            recommended_actions=recommended_actions,
            evidence_sources=sorted(list(sources)),
            limitations=limitations,
            conflicts_resolved=correlation_result.conflicts_resolved,
            data_quality=dq_dict,
            normalization_log=normalization_log,
            agent_status=agent_status,
            simulated_remediation_preview=preview_text,
            message_trace_ref=message_trace_ref,
        )

    # -------------------------------------------------------------------------
    # Helper Construction Methods
    # -------------------------------------------------------------------------

    def _build_recommended_actions(
        self,
        root_cause_code: CauseCode,
        status: str,
        correlation_result: CorrelationResult,
    ) -> List[RecommendedAction]:
        """Construct prioritized action plan based on root cause or missing evidence."""
        actions: List[RecommendedAction] = []

        if status == "insufficient_evidence" or root_cause_code == CauseCode.UNKNOWN:
            # Actions focus on missing evidence collection
            p = 1
            for miss in correlation_result.missing_evidence:
                actions.append(
                    RecommendedAction(
                        priority=p,
                        action=f"Gather telemetry evidence: {miss}",
                        rationale="Required to establish conclusive diagnosis and resolve ambiguity.",
                        requires_human_review=True,
                    )
                )
                p += 1

            if not actions:
                actions.append(
                    RecommendedAction(
                        priority=1,
                        action="Collect extended telemetry and interface packet traces from suspected switches.",
                        rationale="Current telemetry is insufficient to isolate a root cause.",
                        requires_human_review=True,
                    )
                )
            return actions

        # Look up cause-specific actions from recommendations knowledge base
        cause_entry = self.recommendations_kb.get(root_cause_code.value, {})
        kb_actions = cause_entry.get("actions", [])

        for act in kb_actions:
            actions.append(
                RecommendedAction(
                    priority=int(act.get("priority", 1)),
                    action=str(act.get("action", "")),
                    rationale=str(act.get("rationale", "")),
                    requires_human_review=True,
                )
            )

        # Check for R5 near-tie conflict and append verification action for runner-up
        is_r5_tie = any(c.get("rule") == "R5" for c in correlation_result.conflicts_resolved)
        if is_r5_tie and len(correlation_result.ranked_hypotheses) > 1:
            runner_up = correlation_result.ranked_hypotheses[1]
            actions.append(
                RecommendedAction(
                    priority=2,
                    action=f"Verify secondary hypothesis ({runner_up.cause_code.value}) on affected devices.",
                    rationale=f"Score margin between {root_cause_code.value} and {runner_up.cause_code.value} was within verification threshold.",
                    requires_human_review=True,
                )
            )

        actions.sort(key=lambda a: a.priority)
        return actions

    def _build_limitations(
        self,
        agent_status: Dict[str, str],
        data_quality_dict: Dict[str, Any],
        completeness: float,
        missing_fields: List[str],
        stale_fields: List[str],
        assumptions: List[str],
        correlation_result: CorrelationResult,
        status: str,
    ) -> List[str]:
        """Compile comprehensive operational limitations and risk factors."""
        limitations: List[str] = []

        if missing_fields:
            limitations.append(f"Missing telemetry metric(s): {', '.join(sorted(missing_fields))}.")
        if stale_fields:
            limitations.append(f"Stale telemetry field(s) detected: {', '.join(sorted(stale_fields))}.")
        if completeness < self.completeness_threshold:
            limitations.append(f"Reduced telemetry completeness ({completeness * 100:.1f}%), triggering low completeness confidence cap.")

        for a in assumptions:
            limitations.append(f"Diagnostic assumption: {a}")

        for ag, st in agent_status.items():
            if st.lower() in ["degraded", "timeout"]:
                limitations.append(f"Agent '{ag}' status was '{st}', potentially omitting key subsystem observations.")

        # Single agent support cap limitation
        if len(correlation_result.agent_support) <= 1 and correlation_result.confidence <= 0.60:
            limitations.append("Confidence constrained by single-agent support cap (0.60).")

        if status == "insufficient_evidence" or correlation_result.primary_cause_code == CauseCode.UNKNOWN:
            for miss in correlation_result.missing_evidence:
                limitations.append(f"Missing evidence: {miss}")

        limitations.append(self.disclaimer)
        return limitations

    def _build_remediation_preview(self, root_cause_code: CauseCode, status: str) -> str:
        """Generate safe, simulated execution preview where every line starts with 'SIMULATED:'."""
        lines: List[str] = []

        if status == "insufficient_evidence" or root_cause_code == CauseCode.UNKNOWN:
            return "SIMULATED: No remediation executed. Gathering missing telemetry evidence."

        cause_entry = self.recommendations_kb.get(root_cause_code.value, {})
        preview_items = cause_entry.get("preview", [])

        for item in preview_items:
            clean_item = str(item).strip()
            if not clean_item.startswith("SIMULATED:"):
                clean_item = f"SIMULATED: {clean_item}"
            lines.append(clean_item)

        if not lines:
            lines.append("SIMULATED: Review device configuration and monitor operating thresholds.")

        return "\n".join(lines)