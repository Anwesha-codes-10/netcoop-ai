"""NetCoop AI - Conflict Resolution Rules.

Pure functions implementing deterministic arbitration rules R1-R5:
- R1: Multi-agent agreement preference (excluding NORMAL from overriding active domain faults)
- R2: CPU overload vs buffer link congestion arbitration
- R3: Upstream failure vs local downstream symptom promotion
- R4: Service daemon (DNS/DHCP) failure vs transport link degradation
- R5: Near-tie margin threshold ambiguity flagging
"""

from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Set, Tuple

from netcoop.protocol.causes import CauseCode
from netcoop.protocol.messages import FindingPayload


@dataclass
class RuleOutcome:
    """Outcome produced by evaluating a conflict arbitration rule."""

    rule_id: str
    applied: bool
    description: str
    effect: str
    score_adjustments: Dict[CauseCode, float] = field(default_factory=dict)
    agents_involved: List[str] = field(default_factory=list)
    disputed_metrics: List[str] = field(default_factory=list)


def rule_multi_agent_disagreement(
    hypotheses_scores: Dict[CauseCode, float],
    agent_top_causes: Dict[str, CauseCode],
    cause_supporting_agents: Dict[CauseCode, List[str]],
    findings_by_agent: Dict[str, FindingPayload],
    config: Optional[Dict[str, Any]] = None,
) -> RuleOutcome:
    """R1: If agents disagree on top cause, prefer the active hypothesis with multi-agent support."""
    rule_cfg = (config or {}).get("rules", {})
    boost = rule_cfg.get("r1_multi_agent_boost", 0.10)
    penalty = rule_cfg.get("r1_single_agent_penalty", 0.10)

    unique_top_causes = set(agent_top_causes.values())
    if len(unique_top_causes) <= 1:
        return RuleOutcome(
            rule_id="R1",
            applied=False,
            description="Agents agree on top candidate; no disagreement detected.",
            effect="No adjustment.",
        )

    # Exclude NORMAL from multi-agent boost when an active fault is detected by a domain agent
    active_faults = [c for c in unique_top_causes if c != CauseCode.NORMAL]
    multi_supported = [c for c, ags in cause_supporting_agents.items() if len(ags) >= 2 and c != CauseCode.NORMAL]
    single_supported = [c for c, ags in cause_supporting_agents.items() if len(ags) == 1 and c != CauseCode.NORMAL]

    if multi_supported and single_supported:
        adjustments: Dict[CauseCode, float] = {}
        top_multi = max(multi_supported, key=lambda c: hypotheses_scores.get(c, 0.0))
        adjustments[top_multi] = boost

        for s in single_supported:
            adjustments[s] = -penalty

        agents_inv = sorted(list(set(
            cause_supporting_agents.get(top_multi, [])
            + [a for s in single_supported for a in cause_supporting_agents.get(s, [])]
        )))

        return RuleOutcome(
            rule_id="R1",
            applied=True,
            description=f"Agents disagreed on top root cause; preferred hypothesis {top_multi.value} with multi-agent support.",
            effect=f"Boosted {top_multi.value} (+{boost:.2f}) over single-agent candidate(s) (-{penalty:.2f}).",
            score_adjustments=adjustments,
            agents_involved=agents_inv,
            disputed_metrics=["latency_ms", "link_utilization_pct"],
        )

    return RuleOutcome(
        rule_id="R1",
        applied=False,
        description="No clear active multi-agent vs single-agent split.",
        effect="No adjustment.",
    )


def rule_cpu_vs_congestion(
    hypotheses_scores: Dict[CauseCode, float],
    findings_by_agent: Dict[str, FindingPayload],
    config: Optional[Dict[str, Any]] = None,
) -> RuleOutcome:
    """R2: If telemetry says congestion but infrastructure shows high CPU without queue drops, rank CPU overload higher."""
    rule_cfg = (config or {}).get("rules", {})
    boost = rule_cfg.get("r2_cpu_overload_boost", 0.15)
    penalty = rule_cfg.get("r2_congestion_penalty", 0.20)

    infra_f = findings_by_agent.get("infrastructure_agent")
    telem_f = findings_by_agent.get("telemetry_agent")

    if not infra_f or not telem_f:
        return RuleOutcome(rule_id="R2", applied=False, description="Missing telemetry or infrastructure finding.", effect="No adjustment.")

    telem_congestion = any(c.cause_code == CauseCode.LINK_CONGESTION and c.score >= 0.50 for c in telem_f.hypothesis_candidates)
    infra_cpu_cand = next((c for c in infra_f.hypothesis_candidates if c.cause_code == CauseCode.DEVICE_CPU_OVERLOAD), None)

    if telem_congestion and infra_cpu_cand and infra_cpu_cand.score >= 0.60:
        zero_or_low_drops = True
        for m in infra_cpu_cand.contradicting_metrics:
            if m.metric == "queue_drops" and "massive" in m.interpretation.lower():
                zero_or_low_drops = False

        if zero_or_low_drops:
            adjustments = {
                CauseCode.DEVICE_CPU_OVERLOAD: boost,
                CauseCode.LINK_CONGESTION: -penalty,
            }
            return RuleOutcome(
                rule_id="R2",
                applied=True,
                description="Telemetry indicates congestion but infrastructure exhibits severe CPU exhaustion without buffer overflow; prioritized DEVICE_CPU_OVERLOAD.",
                effect=f"Promoted DEVICE_CPU_OVERLOAD (+{boost:.2f}) above LINK_CONGESTION (-{penalty:.2f}).",
                score_adjustments=adjustments,
                agents_involved=["telemetry_agent", "infrastructure_agent"],
                disputed_metrics=["cpu_pct", "queue_drops", "link_utilization_pct"],
            )

    return RuleOutcome(rule_id="R2", applied=False, description="Condition R2 (CPU vs congestion) not met.", effect="No adjustment.")


def rule_upstream_vs_local(
    hypotheses_scores: Dict[CauseCode, float],
    findings_by_agent: Dict[str, FindingPayload],
    config: Optional[Dict[str, Any]] = None,
) -> RuleOutcome:
    """R3: If connectivity analysis shows a shared upstream failure, promote UPSTREAM_CONGESTION or HARDWARE_FAILURE above local causes."""
    rule_cfg = (config or {}).get("rules", {})
    boost = rule_cfg.get("r3_upstream_boost", 0.25)
    penalty = rule_cfg.get("r3_local_penalty", 0.25)

    conn_f = findings_by_agent.get("connectivity_agent")
    if not conn_f:
        return RuleOutcome(rule_id="R3", applied=False, description="Missing connectivity finding.", effect="No adjustment.")

    upstream_cand = next((c for c in conn_f.hypothesis_candidates if c.cause_code in [CauseCode.UPSTREAM_CONGESTION, CauseCode.HARDWARE_FAILURE] and c.score >= 0.60), None)

    if upstream_cand:
        target_upstream = upstream_cand.cause_code
        local_causes = [CauseCode.LINK_CONGESTION, CauseCode.WEAK_WIFI_SIGNAL, CauseCode.INTERFACE_FAULT, CauseCode.DEVICE_CPU_OVERLOAD]

        adjustments = {target_upstream: boost}
        for lc in local_causes:
            if lc in hypotheses_scores:
                adjustments[lc] = -penalty

        agents_inv = sorted(list(set(["connectivity_agent"] + [a for a, f in findings_by_agent.items() if a != "connectivity_agent"])))
        return RuleOutcome(
            rule_id="R3",
            applied=True,
            description=f"Connectivity agent identified shared upstream infrastructure failure ({target_upstream.value}); promoted upstream cause above downstream leaf symptoms.",
            effect=f"Promoted {target_upstream.value} (+{boost:.2f}) over local symptoms (-{penalty:.2f}).",
            score_adjustments=adjustments,
            agents_involved=agents_inv,
            disputed_metrics=["latency_ms", "link_utilization_pct"],
        )

    return RuleOutcome(rule_id="R3", applied=False, description="Condition R3 (upstream vs local) not met.", effect="No adjustment.")


def rule_service_vs_congestion(
    hypotheses_scores: Dict[CauseCode, float],
    findings_by_agent: Dict[str, FindingPayload],
    config: Optional[Dict[str, Any]] = None,
) -> RuleOutcome:
    """R4: DNS or DHCP service failure with healthy links -> prefer service cause over congestion or normal."""
    rule_cfg = (config or {}).get("rules", {})
    boost = rule_cfg.get("r4_service_boost", 0.25)
    penalty = rule_cfg.get("r4_congestion_penalty", 0.25)

    service_cause: Optional[CauseCode] = None
    for f in findings_by_agent.values():
        for c in f.hypothesis_candidates:
            if c.cause_code in [CauseCode.DNS_FAILURE, CauseCode.DHCP_FAILURE] and c.score >= 0.60:
                service_cause = c.cause_code
                break
        if service_cause:
            break

    if service_cause:
        adjustments = {
            service_cause: boost,
            CauseCode.NORMAL: -0.40,
            CauseCode.LINK_CONGESTION: -penalty,
        }
        return RuleOutcome(
            rule_id="R4",
            applied=True,
            description=f"Service daemon degradation ({service_cause.value}) detected while network links are operational; prioritized application service fault.",
            effect=f"Promoted {service_cause.value} (+{boost:.2f}) over NORMAL (-0.40) and LINK_CONGESTION (-{penalty:.2f}).",
            score_adjustments=adjustments,
            agents_involved=["connectivity_agent", "telemetry_agent"],
            disputed_metrics=["dns_resolution_ms", "dhcp_failures", "latency_ms"],
        )

    return RuleOutcome(rule_id="R4", applied=False, description="Condition R4 (service vs congestion) not met.", effect="No adjustment.")
def rule_near_tie_margin(
    hypotheses_scores: Dict[CauseCode, float],
    cause_supporting_agents: Dict[CauseCode, List[str]],
    margin_threshold: float = 0.12,
) -> RuleOutcome:
    sorted_causes = sorted(hypotheses_scores.items(), key=lambda x: x[1], reverse=True)
    if len(sorted_causes) < 2:
        return RuleOutcome(rule_id="R5", applied=False, description="Fewer than 2 candidates; no margin tie.", effect="No adjustment.")

    top_cause, top_score = sorted_causes[0]
    runner_cause, runner_score = sorted_causes[1]
    margin = top_score - runner_score

    if top_score > 0.30 and margin < margin_threshold:
        agents_inv = sorted(list(set(cause_supporting_agents.get(top_cause, []) + cause_supporting_agents.get(runner_cause, []))))
        return RuleOutcome(
            rule_id="R5",
            applied=True,
            description=f"Near-tie detected: top two hypotheses ({top_cause.value}: {top_score:.2f} vs {runner_cause.value}: {runner_score:.2f}) are within margin threshold ({margin:.3f} < {margin_threshold:.3f}).",
            effect=f"Flagged near-tie between {top_cause.value} and {runner_cause.value} for verification / evidence query.",
            score_adjustments={},
            agents_involved=agents_inv,
            disputed_metrics=["latency_ms", "packet_loss_pct", "link_utilization_pct"],
        )

    return RuleOutcome(rule_id="R5", applied=False, description="Margin between top two candidates exceeds threshold.", effect="No adjustment.")


    

def apply_all_rules(
    hypotheses_scores: Dict[CauseCode, float],
    agent_top_causes: Dict[str, CauseCode],
    cause_supporting_agents: Dict[CauseCode, List[str]],
    findings_by_agent: Dict[str, FindingPayload],
    config: Optional[Dict[str, Any]] = None,
    margin_threshold: float = 0.12,
) -> Tuple[Dict[CauseCode, float], List[RuleOutcome]]:
    """Execute all arbitration rules in strict deterministic order R1 -> R2 -> R3 -> R4 -> R5."""
    adjusted_scores = dict(hypotheses_scores)
    outcomes: List[RuleOutcome] = []

    # R1: Multi-agent disagreement
    r1 = rule_multi_agent_disagreement(adjusted_scores, agent_top_causes, cause_supporting_agents, findings_by_agent, config)
    if r1.applied:
        for c, delta in r1.score_adjustments.items():
            adjusted_scores[c] = max(0.0, min(1.0, adjusted_scores.get(c, 0.0) + delta))
        outcomes.append(r1)

    # R2: CPU overload vs buffer link congestion
    r2 = rule_cpu_vs_congestion(adjusted_scores, findings_by_agent, config)
    if r2.applied:
        for c, delta in r2.score_adjustments.items():
            adjusted_scores[c] = max(0.0, min(1.0, adjusted_scores.get(c, 0.0) + delta))
        outcomes.append(r2)

    # R3: Upstream failure vs local downstream symptom
    r3 = rule_upstream_vs_local(adjusted_scores, findings_by_agent, config)
    if r3.applied:
        for c, delta in r3.score_adjustments.items():
            adjusted_scores[c] = max(0.0, min(1.0, adjusted_scores.get(c, 0.0) + delta))
        outcomes.append(r3)

    # R4: Service daemon vs congestion/normal
    r4 = rule_service_vs_congestion(adjusted_scores, findings_by_agent, config)
    if r4.applied:
        for c, delta in r4.score_adjustments.items():
            adjusted_scores[c] = max(0.0, min(1.0, adjusted_scores.get(c, 0.0) + delta))
        outcomes.append(r4)

    # R5: Near-tie margin check (applied on post-R1..R4 adjusted scores)
    r5 = rule_near_tie_margin(adjusted_scores, cause_supporting_agents, margin_threshold)
    if r5.applied:
        outcomes.append(r5)

    return adjusted_scores, outcomes