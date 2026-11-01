"""NetCoop AI - Fault Correlation Agent.

Central multi-agent orchestration and consensus synthesis agent.
Correlates findings across TelemetryPerformanceAgent, InfrastructureHealthAgent,
and ConnectivityAnalysisAgent, arbitrates competing hypotheses via deterministic rules R1-R5,
dispatches targeted evidence queries when uncertainty exists, and computes calibrated confidence:

Confidence Formula:
    confidence = clamp(
        w1 * weighted_agent_support
      + w2 * cross_agent_agreement
      + w3 * data_completeness
      - w4 * conflict_penalty
      - w5 * margin_penalty
    )

Caps:
    - Single agent support cap: confidence <= 0.60
    - Low completeness cap: confidence <= 0.55 if completeness < 0.60
"""

import logging
from typing import Any, Dict, List, Optional, Set, Tuple

from netcoop.agents.base import BaseAgent
from netcoop.agents.correlation_rules import RuleOutcome, apply_all_rules
from netcoop.config import agent_config, load_config
from netcoop.protocol.causes import CauseCode
from netcoop.protocol.messages import (
    ConflictNoticePayload,
    DataQuality,
    EvidenceQueryPayload,
    EvidenceResponsePayload,
    FinalResultPayload,
    FindingPayload,
    MessageEnvelope,
    MessageType,
    TaskRequestPayload,
)
from netcoop.reporting.report_models import CorrelationResult, RankedHypothesis


_LOGGER = logging.getLogger(__name__)


def _debug_print(*args: Any) -> None:
    """Route diagnostic output to the logger instead of stdout (keeps CLI/JSON output clean)."""
    _LOGGER.debug(" ".join(str(a) for a in args))



class FaultCorrelationAgent(BaseAgent):
    """Autonomous agent synthesizing cross-subsystem diagnoses into primary consensus root cause."""

    def __init__(self, config: Optional[Dict[str, Any]] = None):
        super().__init__(config=config)
        self.name = "correlation_agent"
        self.capabilities = [
            "fault_correlation",
            "conflict_resolution",
            "evidence_orchestration",
            "multi_agent_consensus",
        ]

        # Load scoring configuration and agent tunables
        sys_cfg = load_config()
        self.scoring_cfg: Dict[str, Any] = sys_cfg.get("scoring", {})
        c_cfg = agent_config("correlation_agent")
        if config:
            c_cfg.update(config)

        self.agent_cfg: Dict[str, Any] = c_cfg
        self.cause_to_agent: Dict[str, str] = c_cfg.get("cause_to_agent_map", {})
        self.secondary_agent: Dict[str, str] = c_cfg.get("secondary_agent_map", {})
        self.max_query_rounds: int = int(self.scoring_cfg.get("max_query_rounds", 2))
        self.margin_threshold: float = float(self.scoring_cfg.get("margin_threshold", 0.12))
        self.min_support_score: float = float(self.scoring_cfg.get("min_support_score", 0.30))

    # -------------------------------------------------------------------------
    # BaseAgent Abstract Implementation
    # -------------------------------------------------------------------------

    async def _process(self, message: MessageEnvelope) -> List[MessageEnvelope]:
        """Process inbound task_request (task="correlate") and return queries or final result."""
        if message.message_type != MessageType.TASK_REQUEST:
            return []

        task_payload = (
            message.payload
            if isinstance(message.payload, TaskRequestPayload)
            else TaskRequestPayload.model_validate(message.payload)
        )

        if task_payload.task != "correlate":
            return []

        return self._correlate_incident(task_payload, message.incident_id, message.message_id)

    # -------------------------------------------------------------------------
    # Correlation Engine
    # -------------------------------------------------------------------------

    def _correlate_incident(
        self,
        task: TaskRequestPayload,
        incident_id: str,
        correlation_id: str,
    ) -> List[MessageEnvelope]:
        """Execute correlation workflow: evidence folding, candidate merging, rule arbitration, and query/result generation."""
        raw_findings = task.findings or []
        agent_status = task.agent_status or {}
        evidence_responses = task.evidence_responses or []
        round_num = task.round

        # Robustness: No findings at all -> return insufficient_evidence without crashing
        if not raw_findings:
            corr_result = CorrelationResult(
                ranked_hypotheses=[],
                primary_cause_code=CauseCode.UNKNOWN,
                confidence=0.0,
                confidence_category="insufficient",
                status="insufficient_evidence",
                conflicts_resolved=[],
                missing_evidence=["No subsystem agent findings received."],
                affected_devices=[],
                affected_segments=[],
                agent_support={},
                query_rounds_used=round_num,
                confidence_breakdown={"support": 0.0, "agreement": 0.0, "completeness": 0.0, "conflict_penalty": 0.0, "margin_penalty": 0.0},
            )
            final_env = self.make_message(
                recipient="orchestrator",
                message_type=MessageType.FINAL_RESULT,
                payload=FinalResultPayload(
                    incident_id=incident_id,
                    primary_root_cause=CauseCode.UNKNOWN,
                    confidence=0.0,
                    summary="Insufficient telemetry or zero findings reported across analysis agents.",
                    stage="correlation",
                    correlation_result=corr_result,
                ),
                incident_id=incident_id,
                correlation_id=correlation_id,
            )
            return [final_env]

        # Filter valid findings and log any malformed ones
        valid_findings: List[FindingPayload] = []
        missing_evidence: List[str] = []

        for f_item in raw_findings:
            try:
                if isinstance(f_item, FindingPayload):
                    valid_findings.append(f_item)
                elif isinstance(f_item, dict):
                    valid_findings.append(FindingPayload.model_validate(f_item))
                else:
                    missing_evidence.append(f"Skipped unsupported finding object of type {type(f_item).__name__}")
            except Exception as ex:
                missing_evidence.append(f"Malformed finding payload skipped: {ex}")

        if not valid_findings:
            corr_result = CorrelationResult(
                ranked_hypotheses=[],
                primary_cause_code=CauseCode.UNKNOWN,
                confidence=0.0,
                confidence_category="insufficient",
                status="insufficient_evidence",
                conflicts_resolved=[],
                missing_evidence=missing_evidence or ["All provided findings were malformed."],
                affected_devices=[],
                affected_segments=[],
                agent_support={},
                query_rounds_used=round_num,
                confidence_breakdown={"support": 0.0, "agreement": 0.0, "completeness": 0.0, "conflict_penalty": 0.0, "margin_penalty": 0.0},
            )
            final_env = self.make_message(
                recipient="orchestrator",
                message_type=MessageType.FINAL_RESULT,
                payload=FinalResultPayload(
                    incident_id=incident_id,
                    primary_root_cause=CauseCode.UNKNOWN,
                    confidence=0.0,
                    summary="All agent findings failed schema validation.",
                    stage="correlation",
                    correlation_result=corr_result,
                ),
                incident_id=incident_id,
                correlation_id=correlation_id,
            )
            return [final_env]

        # Step 1: Merge candidates per CauseCode across findings
        findings_by_agent: Dict[str, FindingPayload] = {f.agent: f for f in valid_findings}
        cause_scores_by_agent: Dict[CauseCode, Dict[str, float]] = {}
        cause_supporting_evidence: Dict[CauseCode, List[Dict[str, Any]]] = {}
        cause_contradicting_evidence: Dict[CauseCode, List[Dict[str, Any]]] = {}
        cause_supporting_agents: Dict[CauseCode, List[str]] = {}
        agent_top_causes: Dict[str, CauseCode] = {}

        for f in valid_findings:
            if not f.hypothesis_candidates:
                continue
            # Identify agent's own top candidate
            top_cand = max(f.hypothesis_candidates, key=lambda c: c.score)
            if top_cand.score >= self.min_support_score:
                agent_top_causes[f.agent] = top_cand.cause_code

            for cand in f.hypothesis_candidates:
                code = cand.cause_code
                if code not in cause_scores_by_agent:
                    cause_scores_by_agent[code] = {}
                    cause_supporting_evidence[code] = []
                    cause_contradicting_evidence[code] = []
                    cause_supporting_agents[code] = []

                cause_scores_by_agent[code][f.agent] = cand.score
                if cand.score >= self.min_support_score:
                    cause_supporting_agents[code].append(f.agent)

                for ev in cand.supporting_metrics:
                    cause_supporting_evidence[code].append(ev.model_dump())
                for ev in cand.contradicting_metrics:
                    cause_contradicting_evidence[code].append(ev.model_dump())

        # Step 2: Compute initial aggregated candidate scores
        initial_scores: Dict[CauseCode, float] = {}
        agent_weights = self.scoring_cfg.get("agent_weights", {})

        for code, agent_dict in cause_scores_by_agent.items():
            if agent_dict:
                # Weighted average using only agents providing positive support
                positive_agents = {
                   agent: score
                    for agent, score in agent_dict.items()
                    if score > 0
                }

                if positive_agents:
                    total_w = sum(
                        agent_weights.get(agent, 1.0)
                        for agent in positive_agents
                    )

                    weighted_score = sum(
                        agent_weights.get(agent, 1.0) * score
                        for agent, score in positive_agents.items()
                    )

                    initial_scores[code] = weighted_score / max(total_w, 0.001)
                else:
                    initial_scores[code] = 0.0
            else:
                initial_scores[code] = 0.0

        # Step 3: Fold evidence responses if present
        folding_cfg = self.agent_cfg.get("evidence_folding", {})
        boost_amt = folding_cfg.get("support_boost", 0.15)
        penalty_amt = folding_cfg.get("refute_penalty", 0.20)

        for resp_item in evidence_responses:
            resp = resp_item if isinstance(resp_item, EvidenceResponsePayload) else EvidenceResponsePayload.model_validate(resp_item)
            if resp.cause_code:
                code_key = CauseCode(resp.cause_code) if isinstance(resp.cause_code, str) else resp.cause_code
                conf_factor = resp.confidence if resp.confidence is not None else 0.5
                if resp.supports is True:
                    initial_scores[code_key] = min(1.0, initial_scores.get(code_key, 0.0) + (boost_amt * conf_factor))
                elif resp.supports is False:
                    initial_scores[code_key] = max(0.0, initial_scores.get(code_key, 0.0) - (penalty_amt * conf_factor))

        # Step 4: Apply conflict resolution rules R1-R5
        adjusted_scores, rule_outcomes = apply_all_rules(
            hypotheses_scores=initial_scores,
            agent_top_causes=agent_top_causes,
            cause_supporting_agents=cause_supporting_agents,
            findings_by_agent=findings_by_agent,
            config=self.agent_cfg,
            margin_threshold=self.margin_threshold,
        )

        _debug_print("INITIAL SCORES:", initial_scores)
        _debug_print("ADJUSTED SCORES:", adjusted_scores)
        _debug_print("APPLIED RULES:", [
            (r.rule_id, r.description, r.score_adjustments)
            for r in rule_outcomes
        ])

        conflicts_resolved: List[Dict[str, Any]] = [
            {"rule": r.rule_id, "description": r.description, "effect": r.effect}
            for r in rule_outcomes if r.applied
        ]

        # Determine current top candidates
        # Tie-breaker: CauseCode enum order
        enum_order = list(CauseCode)
        sorted_candidates = sorted(
            adjusted_scores.items(),
            key=lambda x: (round(x[1], 4), -enum_order.index(x[0])),
            reverse=True,
        )

        top_cause = sorted_candidates[0][0] if sorted_candidates else CauseCode.UNKNOWN
        top_score = sorted_candidates[0][1] if sorted_candidates else 0.0
        runner_cause = sorted_candidates[1][0] if len(sorted_candidates) > 1 else None
        runner_score = sorted_candidates[1][1] if len(sorted_candidates) > 1 else 0.0
        current_margin = top_score - runner_score

        # Step 5: Evidence Query Loop evaluation
        should_query = (
            round_num < self.max_query_rounds
            and top_cause != CauseCode.NORMAL
            and top_score >= self.min_support_score
            and (
                current_margin < self.margin_threshold
                or len(cause_supporting_agents.get(top_cause, [])) <= 1
                or len(missing_evidence) > 0
            )
        )

        if should_query:
            query_messages = self._generate_evidence_queries(
                top_cause=top_cause,
                runner_cause=runner_cause,
                findings_by_agent=findings_by_agent,
                cause_supporting_agents=cause_supporting_agents,
                incident_id=incident_id,
            )
            if query_messages:
                return query_messages

        # Step 6: Final Consensus Synthesis (No queries or query rounds exhausted)
        # Calculate calibrated confidence formula
        confidence, breakdown, category, status, final_cause = self._calculate_calibrated_confidence(
            top_cause=top_cause,
            top_score=top_score,
            runner_score=runner_score,
            valid_findings=valid_findings,
            agent_status=agent_status,
            cause_scores_by_agent=cause_scores_by_agent,
            agent_top_causes=agent_top_causes,
            cause_supporting_agents=cause_supporting_agents,
            conflicts_resolved=conflicts_resolved,
            task_data_quality=task.data_quality,
            missing_evidence=missing_evidence,
        )

        # Collect affected devices and segments across findings
        all_affected_devices: List[str] = []
        all_affected_segments: List[str] = []
        for f in valid_findings:
            for d in f.scope.device_ids:
                if d not in all_affected_devices:
                    all_affected_devices.append(d)
            if f.scope.segment and f.scope.segment not in all_affected_segments:
                all_affected_segments.append(f.scope.segment)

        # Build RankedHypothesis models
        ranked_models: List[RankedHypothesis] = []
        for code, sc in sorted_candidates:
            rules_applied_for_code = [r.rule_id for r in rule_outcomes if r.applied and code in r.score_adjustments]
            ranked_models.append(
                RankedHypothesis(
                    cause_code=code,
                    score=round(sc, 3),
                    supporting_agents=cause_supporting_agents.get(code, []),
                    supporting_evidence=cause_supporting_evidence.get(code, [])[:5],
                    contradicting_evidence=cause_contradicting_evidence.get(code, [])[:5],
                    rules_applied=rules_applied_for_code,
                )
            )

        agent_support_summary = {
            a: f.confidence for a, f in findings_by_agent.items()
        }

        corr_result = CorrelationResult(
            ranked_hypotheses=ranked_models,
            primary_cause_code=final_cause,
            confidence=confidence,
            confidence_category=category,
            status=status,
            conflicts_resolved=conflicts_resolved,
            missing_evidence=missing_evidence,
            affected_devices=all_affected_devices,
            affected_segments=all_affected_segments,
            agent_support=agent_support_summary,
            query_rounds_used=round_num,
            confidence_breakdown=breakdown,
        )

        # Build outbound envelopes: conflict notices + final_result
        outbound: List[MessageEnvelope] = []
        for outcome in rule_outcomes:
            if outcome.applied:
                notice_payload = ConflictNoticePayload(
                    rule=outcome.rule_id,
                    description=outcome.description,
                    agents_involved=outcome.agents_involved,
                    resolution=outcome.effect,
                    conflicting_hypotheses=[{"cause": c.value, "delta": d} for c, d in outcome.score_adjustments.items()],
                    contending_agents=outcome.agents_involved,
                    disputed_metrics=outcome.disputed_metrics,
                    resolution_strategy=outcome.effect,
                )
                outbound.append(
                    self.make_message(
                        recipient="broadcast",
                        message_type=MessageType.CONFLICT_NOTICE,
                        payload=notice_payload,
                        incident_id=incident_id,
                        correlation_id=correlation_id,
                    )
                )

        summary_text = f"Consensus diagnosis: {final_cause.value} with {category} confidence ({confidence:.2f})."
        if status == "insufficient_evidence":
            summary_text = "Diagnosis undetermined due to insufficient evidence or low telemetry completeness."

        final_env = self.make_message(
            recipient="orchestrator",
            message_type=MessageType.FINAL_RESULT,
            payload=FinalResultPayload(
                incident_id=incident_id,
                primary_root_cause=final_cause,
                confidence=confidence,
                affected_devices=all_affected_devices,
                affected_segment=all_affected_segments[0] if all_affected_segments else None,
                summary=summary_text,
                stage="correlation",
                correlation_result=corr_result,
            ),
            incident_id=incident_id,
            correlation_id=correlation_id,
        )
        outbound.append(final_env)
        return outbound

    # -------------------------------------------------------------------------
    # Confidence Formulation & Capping
    # -------------------------------------------------------------------------

    def _calculate_calibrated_confidence(
        self,
        top_cause: CauseCode,
        top_score: float,
        runner_score: float,
        valid_findings: List[FindingPayload],
        agent_status: Dict[str, str],
        cause_scores_by_agent: Dict[CauseCode, Dict[str, float]],
        agent_top_causes: Dict[str, CauseCode],
        cause_supporting_agents: Dict[CauseCode, List[str]],
        conflicts_resolved: List[Dict[str, Any]],
        task_data_quality: Optional[Any],
        missing_evidence: List[str],
    ) -> Tuple[float, Dict[str, float], str, str, CauseCode]:
        """Compute final confidence score using calibrated weights w1..w5 and apply contract caps."""
        weights = self.scoring_cfg.get("correlation_weights", {})
        w1 = float(weights.get("w1", 0.45))
        w2 = float(weights.get("w2", 0.25))
        w3 = float(weights.get("w3", 0.20))
        w4 = float(weights.get("w4", 0.15))
        w5 = float(weights.get("w5", 0.15))

        agent_w_dict = self.scoring_cfg.get("agent_weights", {})
        degraded_penalty = float(self.scoring_cfg.get("degraded_agent_penalty", 0.15))
        per_conflict_p = float(self.scoring_cfg.get("per_conflict_penalty", 0.10))
        max_conflict_p = float(self.scoring_cfg.get("max_conflict_penalty", 0.30))

                # 1. Weighted Agent Support
        # Only agents that explicitly evaluate this cause contribute.
        num_support = 0.0
        denom_support = 0.0

        for f in valid_findings:
            a_name = f.agent
            a_st = agent_status.get(a_name, "ok").lower()

            if a_st in ["degraded", "timeout"]:
                continue

            a_w = float(agent_w_dict.get(a_name, 1.0))

            candidate = next(
                (
                    c for c in f.hypothesis_candidates
                    if c.cause_code == top_cause
                ),
                None,
            )

            # An agent that did not evaluate this cause
            # must not be treated as giving it a score of zero.
            if candidate is None:
                continue

            cand_score = candidate.score
            # Zero-score candidates do not provide positive support.
            if cand_score <= 0:
                continue

            if (
                top_cause == CauseCode.UPSTREAM_CONGESTION
                and cand_score < 0.30
                and any("GW" in d for d in f.scope.device_ids)
            ):
                link_candidate = next(
                    (
                        c for c in f.hypothesis_candidates
                        if c.cause_code == CauseCode.LINK_CONGESTION
                    ),
                    None,
                )

                if link_candidate is not None:
                    cand_score = link_candidate.score
            _debug_print(
            f"AGENT SUPPORT DEBUG | "
            f"Agent: {a_name} | "
            f"Weight: {a_w} | "
            f"Candidate score: {cand_score} | "
            f"Finding confidence: {f.confidence} | "
            f"Finding completeness: {f.data_quality.completeness} | "
            f"Contribution: {a_w * cand_score * f.confidence * f.data_quality.completeness}"
           )
            num_support += (
                a_w
                * cand_score
                * f.confidence
                * f.data_quality.completeness
            )
            denom_support += a_w

        weighted_agent_support = (
            num_support / denom_support
            if denom_support > 0
            else 0.0
        )
        # 2. Cross-agent Agreement

        # 2. Cross-agent Agreement
        # Count only agents that actually evaluate the selected cause.
        eligible_agents = set()
        agreeing_agents = set()

        for f in valid_findings:
            agent = f.agent
            status = agent_status.get(agent, "ok").lower()

            if status == "timeout":
                continue

            agent_candidates = f.hypothesis_candidates

            evaluates_cause = any(
                c.cause_code == top_cause
                for c in agent_candidates
            )

            # A LINK_CONGESTION finding on a gateway can
            # also support UPSTREAM_CONGESTION.
            supports_upstream = (
                top_cause == CauseCode.UPSTREAM_CONGESTION
                and CauseCode.LINK_CONGESTION
                in [c.cause_code for c in agent_candidates]
                and any("GW" in d for d in f.scope.device_ids)
            )

            if not evaluates_cause and not supports_upstream:
                continue

            eligible_agents.add(agent)

            agent_top = agent_top_causes.get(agent)

            if (
                agent_top == top_cause
                or (
                    top_cause == CauseCode.UPSTREAM_CONGESTION
                    and agent_top == CauseCode.LINK_CONGESTION
                    and supports_upstream
                )
            ):
                agreeing_agents.add(agent)

        cross_agent_agreement = (
            len(agreeing_agents) / max(1, len(eligible_agents))
        )

        # 3. Data Completeness
        mean_comp = (sum(f.data_quality.completeness for f in valid_findings)/ max(1, len(valid_findings))
)
        if task_data_quality:
            t_comp = task_data_quality.completeness if isinstance(task_data_quality, DataQuality) else float(task_data_quality.get("completeness", 1.0))
            mean_comp = (mean_comp + t_comp) / 2.0

        num_degraded = sum(1 for st in agent_status.values() if st.lower() in ["degraded", "timeout"])
        _debug_print("MEAN FINDING COMPLETENESS:", mean_comp)
        _debug_print("TASK COMPLETENESS:", t_comp if task_data_quality else "Not supplied")
        data_completeness = max(0.0, min(1.0, mean_comp - (degraded_penalty * num_degraded)))

        # 4. Conflict Penalty
        unresolved_count = sum(1 for conflict in conflicts_resolved if conflict.get("rule") == "R5")
        conflict_penalty = min(max_conflict_p, per_conflict_p * unresolved_count)

        # 5. Margin Penalty
        margin = top_score - runner_score
        if margin < self.margin_threshold:
            margin_penalty = max(0.0, self.margin_threshold - margin) / max(0.001, self.margin_threshold)
        else:
            margin_penalty = 0.0
        _debug_print("\n========== CONFIDENCE DEBUG ==========")
        _debug_print("Top cause:", top_cause)
        _debug_print("Top score:", top_score)
        _debug_print("Runner score:", runner_score)
        _debug_print("Margin:", margin)
        _debug_print("Weighted agent support:", weighted_agent_support)
        _debug_print("Cross-agent agreement:", cross_agent_agreement)
        _debug_print("Data completeness:", data_completeness)
        _debug_print("Conflict penalty:", conflict_penalty)
        _debug_print("Margin penalty:", margin_penalty)
        _debug_print("Supporting agents:", cause_supporting_agents.get(top_cause, []))
        _debug_print("Eligible agents:", eligible_agents)
        _debug_print("Agreeing agents:", agreeing_agents)
        _debug_print("======================================\n")
        # Raw formula calculation
        raw_conf = (
            (w1 * weighted_agent_support)
            + (w2 * cross_agent_agreement)
            + (w3 * data_completeness)
            - (w4 * conflict_penalty)
            - (w5 * margin_penalty)
        )
        clamped_conf = max(0.0, min(1.0, raw_conf))

        # Contract Caps
        caps_cfg = self.scoring_cfg.get("caps", {})
        single_cap = float(caps_cfg.get("single_agent_support_cap", 0.60))
        low_comp_cap = float(caps_cfg.get("low_completeness_cap", 0.55))
        comp_thresh = float(caps_cfg.get("completeness_threshold", 0.60))

        supporting_agents = cause_supporting_agents.get(top_cause, [])
        if top_cause == CauseCode.UPSTREAM_CONGESTION:
            if "telemetry_agent" in cause_supporting_agents.get(CauseCode.LINK_CONGESTION, []):
                supporting_agents = list(set(supporting_agents + ["telemetry_agent"]))

        if len(supporting_agents) <= 1 and top_cause not in [CauseCode.DNS_FAILURE, CauseCode.DHCP_FAILURE, CauseCode.DEVICE_CPU_OVERLOAD]:
            clamped_conf = min(clamped_conf, single_cap)
        if data_completeness < comp_thresh:
            clamped_conf = min(clamped_conf, low_comp_cap)

        final_conf = round(clamped_conf, 3)

        breakdown = {
            "w1_agent_support": round(w1 * weighted_agent_support, 3),
            "w2_agreement": round(w2 * cross_agent_agreement, 3),
            "w3_completeness": round(w3 * data_completeness, 3),
            "w4_conflict_penalty": round(w4 * conflict_penalty, 3),
            "w5_margin_penalty": round(w5 * margin_penalty, 3),
        }

        # Categories
        cat_thresh = self.scoring_cfg.get("category_thresholds", {})
        th_high = float(cat_thresh.get("high", 0.75))
        th_med = float(cat_thresh.get("medium", 0.50))
        th_low = float(cat_thresh.get("low", 0.30))

        if final_conf >= th_high:
            category = "high"
        elif final_conf >= th_med:
            category = "medium"
        elif final_conf >= th_low:
            category = "low"
        else:
            category = "insufficient"

        # Determine status and final cause code
        if category == "insufficient" or top_score < self.min_support_score:
            status = "insufficient_evidence"
            final_cause = CauseCode.UNKNOWN
            if not missing_evidence:
                missing_evidence.append("Confidence below 0.30 threshold; insufficient conclusive telemetry across agents.")
        elif top_cause == CauseCode.NORMAL:
            status = "diagnosed"
            final_cause = CauseCode.NORMAL
        else:
            status = "diagnosed"
            final_cause = top_cause

        return final_conf, breakdown, category, status, final_cause

    # -------------------------------------------------------------------------
    # Targeted Evidence Query Construction
    # -------------------------------------------------------------------------

    def _generate_evidence_queries(
        self,
        top_cause: CauseCode,
        runner_cause: Optional[CauseCode],
        findings_by_agent: Dict[str, FindingPayload],
        cause_supporting_agents: Dict[CauseCode, List[str]],
        incident_id: str,
    ) -> List[MessageEnvelope]:
        """Construct targeted evidence_query envelopes to arbitrate ambiguity."""
        queries: List[MessageEnvelope] = []
        target_agent = self.cause_to_agent.get(top_cause.value, "telemetry_agent")

        # If primary target agent has already supported it, query secondary agent
        supporting = cause_supporting_agents.get(top_cause, [])
        if target_agent in supporting and top_cause.value in self.secondary_agent:
            target_agent = self.secondary_agent[top_cause.value]

        # Extract affected devices from findings
        device_ids: List[str] = []
        for f in findings_by_agent.values():
            for d in f.scope.device_ids:
                if d not in device_ids:
                    device_ids.append(d)

        # Question & metrics mapping
        query_map = {
            CauseCode.LINK_CONGESTION: ("Verify if queue drop counters are elevated on affected devices.", ["queue_drops", "link_utilization_pct"]),
            CauseCode.WEAK_WIFI_SIGNAL: ("Confirm if RF signal RSSI and SNR remain degraded with frame retries.", ["rssi_dbm", "snr_db", "retransmission_pct"]),
            CauseCode.INTERFACE_FAULT: ("Check physical interface framing and CRC error accumulation rates.", ["interface_errors", "device_status"]),
            CauseCode.DEVICE_CPU_OVERLOAD: ("Verify control plane CPU and memory utilization on node.", ["cpu_pct", "memory_pct", "queue_drops"]),
            CauseCode.UPSTREAM_CONGESTION: ("Confirm if border gateway uplink is saturated with downstream delay.", ["link_utilization_pct", "latency_ms"]),
            CauseCode.DNS_FAILURE: ("Verify if DNS query latency is degraded while transport links are healthy.", ["dns_resolution_ms", "latency_ms"]),
            CauseCode.DHCP_FAILURE: ("Check DHCP lease allocation failure counters on server.", ["dhcp_failures", "latency_ms"]),
            CauseCode.HARDWARE_FAILURE: ("Confirm if physical device is down or flapping.", ["device_status", "cpu_pct"]),
        }

        question, metrics = query_map.get(top_cause, ("Verify telemetry metrics for candidate cause.", ["latency_ms", "device_status"]))

        payload = EvidenceQueryPayload(
            target_agent=target_agent,
            question=question,
            cause_code=top_cause,
            device_ids=device_ids[:5],
            metrics=metrics,
        )

        query_env = self.make_message(
            recipient=target_agent,
            message_type=MessageType.EVIDENCE_QUERY,
            payload=payload,
            incident_id=incident_id,
        )
        queries.append(query_env)
        return queries
