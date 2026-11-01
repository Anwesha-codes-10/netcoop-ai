"""NetCoop AI - Connectivity Analysis Agent.

Specialized agent analyzing campus topology graph connectivity, path dependencies,
shared upstream bottlenecks, and service-specific isolation (DNS/DHCP).
Identifies UPSTREAM_CONGESTION, HARDWARE_FAILURE, DNS_FAILURE, DHCP_FAILURE,
and NORMAL baselines, and categorizes incident scope as isolated, segment-wide, or widespread.
"""

from typing import Any, Dict, List, Optional, Set, Tuple

import networkx as nx

from netcoop.agents.base import BaseAgent
from netcoop.config import agent_config, load_config
from netcoop.protocol.causes import CANONICAL_METRICS, CauseCode
from netcoop.protocol.messages import (
    DataQuality,
    EvidenceAnswer,
    EvidenceQueryPayload,
    EvidenceResponsePayload,
    FindingPayload,
    FindingScope,
    HypothesisCandidate,
    MessageEnvelope,
    MessageType,
    MetricEvidence,
    TaskRequestPayload,
)


class ConnectivityAnalysisAgent(BaseAgent):
    """Autonomous agent diagnosing topological reachability and upstream bottlenecks."""

    def __init__(self, config: Optional[Dict[str, Any]] = None):
        super().__init__(config=config)
        self.name = "connectivity_agent"
        self.capabilities = [
            "topology_analysis",
            "path_tracing",
            "spof_detection",
            "upstream_bottlenecks",
            "service_isolation",
        ]

        sys_cfg = load_config()
        c_cfg = agent_config("connectivity_agent")
        if config:
            c_cfg.update(config)

        self.thresholds_cfg: Dict[str, Any] = c_cfg.get("thresholds", {})
        self.graph_cfg: Dict[str, Any] = c_cfg.get("graph", {})
        self.weights_cfg: Dict[str, Any] = c_cfg.get("weights", {})
        self.conf_cfg: Dict[str, Any] = c_cfg.get("confidence", {})
        self.uplink_id: str = self.graph_cfg.get("default_uplink_id", "GW_NKN_ISP")

    def build_graph_from_topology(self, topology_dict: Optional[Dict[str, Any]]) -> nx.Graph:
        """Reconstruct a NetworkX undirected graph from node-link dictionary."""
        g = nx.Graph()
        if not topology_dict or not isinstance(topology_dict, dict):
            return g

        for node in topology_dict.get("nodes", []):
            nid = node.get("id") or node.get("device_id")
            if nid:
                g.add_node(str(nid).strip(), **node)

        for edge in topology_dict.get("edges", []):
            src = edge.get("source") or edge.get("u")
            dst = edge.get("target") or edge.get("v")
            if src and dst:
                g.add_edge(str(src).strip(), str(dst).strip(), **edge)

        return g

    def find_lowest_common_ancestor(
        self,
        graph: nx.Graph,
        affected_nodes: List[str],
        uplink_id: Optional[str] = None,
    ) -> Tuple[Optional[str], Dict[str, List[str]]]:
        """Find lowest common ancestor (LCA) node toward the uplink for affected devices."""
        root = uplink_id or self.uplink_id
        if not graph or root not in graph:
            root_candidates = [
                n for n, d in graph.nodes(data=True)
                if d.get("device_type") == "uplink" or "GW" in n
            ]
            root = root_candidates[0] if root_candidates else (list(graph.nodes())[0] if graph.nodes else "")

        if not root or root not in graph:
            return None, {}

        valid_nodes = [n for n in affected_nodes if n in graph]
        if not valid_nodes:
            return None, {}

        paths: Dict[str, List[str]] = {}
        for n in valid_nodes:
            try:
                p = nx.shortest_path(graph, source=n, target=root)
                paths[n] = p
            except (nx.NetworkXNoPath, nx.NodeNotFound):
                paths[n] = []

        valid_paths = [p for p in paths.values() if p]
        if not valid_paths:
            return None, paths

        common_nodes = set(valid_paths[0]).intersection(*[set(p) for p in valid_paths])
        if not common_nodes:
            return None, paths

        lca = max(common_nodes, key=lambda c: nx.shortest_path_length(graph, source=c, target=root))
        return lca, paths

    def get_downstream_nodes(
        self,
        graph: nx.Graph,
        upstream_node: str,
        uplink_id: Optional[str] = None,
    ) -> List[str]:
        """Return all nodes whose shortest path to uplink passes through upstream_node."""
        root = uplink_id or self.uplink_id
        if not graph or upstream_node not in graph or root not in graph:
            return []

        downstream: List[str] = []
        for n in graph.nodes():
            if n == root or n == upstream_node:
                continue
            try:
                p = nx.shortest_path(graph, source=n, target=root)
                if upstream_node in p:
                    downstream.append(n)
            except (nx.NetworkXNoPath, nx.NodeNotFound):
                pass
        return downstream

    def calculate_downstream_affected_fraction(
        self,
        graph: nx.Graph,
        upstream_node: str,
        affected_nodes: List[str],
        uplink_id: Optional[str] = None,
    ) -> float:
        """Calculate fraction of upstream_node's downstream devices that are affected."""
        downstream = self.get_downstream_nodes(graph, upstream_node, uplink_id)
        if not downstream:
            return 1.0 if upstream_node in affected_nodes else 0.0

        aff_downstream = [n for n in downstream if n in affected_nodes]
        return round(len(aff_downstream) / len(downstream), 3)

    def is_single_point_of_failure(
        self,
        graph: nx.Graph,
        upstream_node: str,
        downstream_nodes: List[str],
        uplink_id: Optional[str] = None,
    ) -> bool:
        """Determine if removing upstream_node disconnects any downstream node from the uplink."""
        root = uplink_id or self.uplink_id
        if not graph or upstream_node not in graph or not downstream_nodes or root not in graph:
            return False

        h = graph.copy()
        h.remove_node(upstream_node)

        for d in downstream_nodes:
            if d not in h:
                continue
            try:
                if not nx.has_path(h, source=d, target=root):
                    return True
            except (nx.NetworkXNoPath, nx.NodeNotFound):
                return True
        return False

    def classify_scope(
        self,
        affected_nodes: List[str],
        shared_upstream: Optional[str],
        graph: Optional[nx.Graph],
    ) -> Tuple[str, Optional[str]]:
        """Classify scope into isolated, segment-wide, or widespread, returning (scope_class, segment)."""
        if not affected_nodes:
            return "isolated", None

        segments: Set[str] = set()
        if graph:
            for n in affected_nodes:
                if n in graph.nodes:
                    seg = graph.nodes[n].get("segment")
                    if seg:
                        segments.add(seg)

        shared_seg = list(segments)[0] if len(segments) == 1 else None

        # A single affected leaf/device is strictly isolated
        if len(affected_nodes) <= self.graph_cfg.get("isolated_device_count_max", 1):
            return "isolated", shared_seg

        core_ids = set(self.graph_cfg.get("core_router_ids", ["CORE_RTR_01", "CORE_RTR_02"]))
        core_ids.add(self.uplink_id)

        if shared_upstream in core_ids or any(n in core_ids for n in affected_nodes) or len(segments) > 1:
            return "widespread", shared_seg or "campus_core"

        return "segment-wide", shared_seg

    async def _process(self, message: MessageEnvelope) -> List[MessageEnvelope]:
        """Handle inbound task requests and peer evidence queries."""
        if message.message_type == MessageType.TASK_REQUEST:
            task_payload = (
                message.payload
                if isinstance(message.payload, TaskRequestPayload)
                else TaskRequestPayload.model_validate(message.payload)
            )
            if task_payload.task == "analyze":
                finding = self._analyze_connectivity(task_payload, message.incident_id, message.message_id)
                return [finding]
            return []

        if message.message_type == MessageType.EVIDENCE_QUERY:
            evidence_resp = self._handle_evidence_query(message)
            return [evidence_resp]

        return []

    def _analyze_connectivity(
        self,
        task: TaskRequestPayload,
        incident_id: str,
        correlation_id: str,
    ) -> MessageEnvelope:
        """Analyze topology reachability and produce a structured FindingPayload."""
        telemetry = task.telemetry or {}

        if not telemetry or all(len(recs) == 0 for recs in telemetry.values()):
            dq_empty = DataQuality(
                completeness=0.0,
                missing_fields=[],
                stale_fields=[],
                assumptions=["No telemetry records provided in task request"],
            )
            scope_empty = FindingScope(device_ids=[], segment=None)
            return self.make_finding(
                incident_id=incident_id,
                hypothesis_candidates=[],
                scope=scope_empty,
                confidence=0.0,
                data_quality=dq_empty,
                correlation_id=correlation_id,
                recipient="correlation_agent",
            )

        graph = self.build_graph_from_topology(task.topology)
        has_topology = graph.number_of_nodes() > 0

        missing_fields: Set[str] = set()
        stale_fields: Set[str] = set()
        assumptions: List[str] = []

        base_completeness = 1.0
        if task.data_quality:
            if isinstance(task.data_quality, DataQuality):
                missing_fields.update(task.data_quality.missing_fields)
                stale_fields.update(task.data_quality.stale_fields)
                assumptions.extend(task.data_quality.assumptions)
                base_completeness = task.data_quality.completeness
            elif isinstance(task.data_quality, dict):
                missing_fields.update(task.data_quality.get("missing_fields", []))
                stale_fields.update(task.data_quality.get("stale_fields", []))
                assumptions.extend(task.data_quality.get("assumptions", []))
                base_completeness = float(task.data_quality.get("completeness", 1.0))

        if not has_topology:
            base_completeness -= self.conf_cfg.get("missing_topology_penalty", 0.30)
            assumptions.append("No topology graph provided; falling back to device naming and heuristics.")

        device_summaries: Dict[str, Dict[str, Any]] = {}
        affected_devices: List[str] = []
        unknown_devices: List[str] = []

        lat_w = self.thresholds_cfg.get("latency_warn_ms", 80.0)
        loss_w = self.thresholds_cfg.get("packet_loss_warn_pct", 1.5)
        util_w = self.thresholds_cfg.get("utilization_warn_pct", 80.0)
        dns_w = self.thresholds_cfg.get("dns_warn_ms", 150.0)
        dhcp_w = self.thresholds_cfg.get("dhcp_warn_failures", 5)

        for dev_id, records in telemetry.items():
            if not records:
                continue

            if has_topology and dev_id not in graph:
                unknown_devices.append(dev_id)
                missing_fields.add(dev_id)
                assumptions.append(f"Device '{dev_id}' not found in campus topology graph; excluded from path analysis.")
                continue

            lat_vals = [float(r["latency_ms"]) for r in records if "latency_ms" in r and r["latency_ms"] is not None]
            loss_vals = [float(r["packet_loss_pct"]) for r in records if "packet_loss_pct" in r and r["packet_loss_pct"] is not None]
            util_vals = [float(r["link_utilization_pct"]) for r in records if "link_utilization_pct" in r and r["link_utilization_pct"] is not None]
            dns_vals = [float(r["dns_resolution_ms"]) for r in records if "dns_resolution_ms" in r and r["dns_resolution_ms"] is not None]
            dhcp_vals = [float(r["dhcp_failures"]) for r in records if "dhcp_failures" in r and r["dhcp_failures"] is not None]
            status_vals = [str(r.get("device_status") or r.get("status") or "up") for r in records]

            mean_lat = sum(lat_vals) / len(lat_vals) if lat_vals else 0.0
            mean_loss = sum(loss_vals) / len(loss_vals) if loss_vals else 0.0
            mean_util = sum(util_vals) / len(util_vals) if util_vals else 0.0
            mean_dns = sum(dns_vals) / len(dns_vals) if dns_vals else 0.0
            mean_dhcp = sum(dhcp_vals) / len(dhcp_vals) if dhcp_vals else 0.0

            is_down = any(s.lower() == "down" for s in status_vals)
            is_degraded = any(s.lower() == "degraded" for s in status_vals)

            is_affected = (
                mean_lat >= lat_w
                or mean_loss >= loss_w
                or mean_util >= util_w
                or mean_dns >= dns_w
                or mean_dhcp >= dhcp_w
                or is_down
                or is_degraded
            )

            if is_affected:
                affected_devices.append(dev_id)

            device_summaries[dev_id] = {
                "is_affected": is_affected,
                "mean_lat": mean_lat,
                "mean_loss": mean_loss,
                "mean_util": mean_util,
                "mean_dns": mean_dns,
                "mean_dhcp": mean_dhcp,
                "is_down": is_down,
                "is_degraded": is_degraded,
            }

        shared_upstream: Optional[str] = None
        paths_to_root: Dict[str, List[str]] = {}
        downstream_fraction = 0.0

        if has_topology and affected_devices:
            shared_upstream, paths_to_root = self.find_lowest_common_ancestor(graph, affected_devices)
            if shared_upstream:
                downstream_fraction = self.calculate_downstream_affected_fraction(graph, shared_upstream, affected_devices)

        scope_class, shared_seg = self.classify_scope(affected_devices, shared_upstream, graph if has_topology else None)
        assumptions.append(f"Topology scope classified as '{scope_class}' (isolated={scope_class == 'isolated'}) with shared upstream node '{shared_upstream}'.")

        candidates: List[HypothesisCandidate] = [
            self._evaluate_upstream_congestion(shared_upstream, device_summaries, scope_class, downstream_fraction, graph),
            self._evaluate_dns_failure(device_summaries, graph),
            self._evaluate_dhcp_failure(device_summaries, graph),
            self._evaluate_hardware_failure(shared_upstream, device_summaries, graph),
            self._evaluate_normal(affected_devices),
        ]

        candidates.sort(key=lambda c: c.score, reverse=True)

        top_score = candidates[0].score if candidates else 0.0
        second_score = candidates[1].score if len(candidates) > 1 else 0.0
        margin = top_score - second_score

        base_w = self.conf_cfg.get("base_weight", 0.35)
        topo_w = self.conf_cfg.get("topology_coverage_weight", 0.35)
        comp_w = self.conf_cfg.get("completeness_weight", 0.30)

        completeness = max(0.0, min(1.0, round(base_completeness - (len(missing_fields) * 0.08), 2)))
        topo_coverage = 1.0 if has_topology else 0.40

        raw_conf = (base_w * top_score) + (topo_w * topo_coverage) + (comp_w * completeness)
        if top_score < 0.50:
            final_conf = min(raw_conf, 0.45, top_score * 0.9)
        elif margin < 0.12:
            final_conf = raw_conf * 0.85
        else:
            final_conf = raw_conf

        if completeness < 0.60:
            final_conf = min(final_conf, completeness * 0.9)

        confidence = max(0.0, min(0.98, round(final_conf, 2)))

        scope = FindingScope(
            device_ids=affected_devices if affected_devices else list(telemetry.keys()),
            segment=shared_seg,
        )
        data_qual = DataQuality(
            completeness=completeness,
            missing_fields=sorted(list(missing_fields)),
            stale_fields=sorted(list(stale_fields)),
            assumptions=assumptions,
        )

        return self.make_finding(
            incident_id=incident_id,
            hypothesis_candidates=candidates,
            scope=scope,
            confidence=confidence,
            data_quality=data_qual,
            correlation_id=correlation_id,
            recipient="correlation_agent",
        )

    def _evaluate_upstream_congestion(
        self,
        shared_upstream: Optional[str],
        summaries: Dict[str, Dict[str, Any]],
        scope_class: str,
        downstream_fraction: float,
        graph: Optional[nx.Graph],
    ) -> HypothesisCandidate:
        """Evaluate UPSTREAM_CONGESTION: shared border gateway/core saturated with widespread delay."""
        w_cfg = self.weights_cfg.get("upstream_congestion", {})
        high_util_w = w_cfg.get("upstream_high_utilization", 0.40)
        high_lat_w = w_cfg.get("upstream_high_latency", 0.30)
        scope_w = w_cfg.get("widespread_or_segment_affected", 0.20)
        not_down_w = w_cfg.get("upstream_not_down", 0.10)
        down_penalty = w_cfg.get("contradiction_upstream_down_penalty", 0.60)
        low_util_penalty = w_cfg.get("contradiction_low_utilization_penalty", 0.50)

        supporting: List[MetricEvidence] = []
        contradicting: List[MetricEvidence] = []
        score = 0.0

        if not shared_upstream or shared_upstream not in summaries:
            if self.uplink_id in summaries:
                shared_upstream = self.uplink_id
            else:
                return HypothesisCandidate(
                    cause_code=CauseCode.UPSTREAM_CONGESTION,
                    score=0.0,
                    supporting_metrics=[],
                    contradicting_metrics=[],
                )

        up_s = summaries[shared_upstream]
        is_uplink_node = (
            shared_upstream == self.uplink_id
            or (graph and graph.nodes.get(shared_upstream, {}).get("device_type") == "uplink")
            or "NKN" in shared_upstream
            or "ISP" in shared_upstream
        )

        # Local distribution or access switches are NOT border gateway UPSTREAM_CONGESTION
        if not is_uplink_node or scope_class == "isolated":
            return HypothesisCandidate(
                cause_code=CauseCode.UPSTREAM_CONGESTION,
                score=0.0,
                supporting_metrics=[],
                contradicting_metrics=[
                    MetricEvidence(
                        metric="link_utilization_pct",
                        value=round(up_s["mean_util"], 2),
                        unit="%",
                        baseline=35.0,
                        interpretation=f"{shared_upstream} is an internal campus switch, not an upstream border gateway; local link congestion applies.",
                    )
                ],
            )

        if up_s["mean_util"] >= self.thresholds_cfg.get("utilization_critical_pct", 90.0):
            score += high_util_w
            supporting.append(
                MetricEvidence(
                    metric="link_utilization_pct",
                    value=round(up_s["mean_util"], 2),
                    unit="%",
                    baseline=35.0,
                    interpretation=f"Upstream gateway {shared_upstream} link critically saturated at {up_s['mean_util']:.1f}%",
                )
            )
        elif up_s["mean_util"] >= self.thresholds_cfg.get("utilization_warn_pct", 80.0):
            score += high_util_w * 0.70
        elif up_s["mean_util"] < 50.0:
            score -= low_util_penalty

        if up_s["mean_lat"] >= self.thresholds_cfg.get("latency_critical_ms", 200.0):
            score += high_lat_w
            supporting.append(
                MetricEvidence(
                    metric="latency_ms",
                    value=round(up_s["mean_lat"], 2),
                    unit="ms",
                    baseline=12.0,
                    interpretation=f"Upstream transit delay ({up_s['mean_lat']:.1f} ms) severely elevated",
                )
            )
        elif up_s["mean_lat"] >= self.thresholds_cfg.get("latency_warn_ms", 80.0):
            score += high_lat_w * 0.70

        if scope_class in ["widespread", "segment-wide"] or downstream_fraction > 0.40:
            score += scope_w

        if not up_s["is_down"]:
            score += not_down_w
        else:
            score -= down_penalty

        return HypothesisCandidate(
            cause_code=CauseCode.UPSTREAM_CONGESTION,
            score=round(max(0.0, min(1.0, score)), 2),
            supporting_metrics=supporting,
            contradicting_metrics=contradicting,
        )

    def _evaluate_dns_failure(
        self,
        summaries: Dict[str, Dict[str, Any]],
        graph: Optional[nx.Graph],
    ) -> HypothesisCandidate:
        """Evaluate DNS_FAILURE: DNS query latency/timeouts while link transport is healthy."""
        w_cfg = self.weights_cfg.get("dns_failure", {})
        crit_w = w_cfg.get("critical_dns_latency", 0.60)
        warn_w = w_cfg.get("warn_dns_latency", 0.30)
        healthy_w = w_cfg.get("transport_links_healthy", 0.30)
        unhealthy_penalty = w_cfg.get("contradiction_transport_unhealthy_penalty", 0.40)
        healthy_dns_penalty = w_cfg.get("contradiction_dns_healthy_penalty", 0.70)

        supporting: List[MetricEvidence] = []
        contradicting: List[MetricEvidence] = []
        best_score = 0.0

        for dev_id, s in summaries.items():
            is_dns = "DNS" in dev_id or (graph and "dns" in str(graph.nodes.get(dev_id, {}).get("model", "")).lower())
            if s["mean_dns"] <= 0 and not is_dns:
                continue

            score = 0.0
            crit_dns = self.thresholds_cfg.get("dns_critical_ms", 1000.0)
            warn_dns = self.thresholds_cfg.get("dns_warn_ms", 150.0)

            if s["mean_dns"] >= crit_dns:
                score += crit_w
                supporting.append(
                    MetricEvidence(
                        metric="dns_resolution_ms",
                        value=round(s["mean_dns"], 2),
                        unit="ms",
                        baseline=15.0,
                        interpretation=f"{dev_id}: DNS resolution latency ({s['mean_dns']:.1f} ms) exceeds critical {crit_dns:.0f} ms threshold",
                    )
                )
            elif s["mean_dns"] >= warn_dns:
                score += warn_w
            else:
                score -= healthy_dns_penalty

            if s["mean_lat"] < self.thresholds_cfg.get("latency_warn_ms", 80.0) and s["mean_loss"] < 1.0:
                score += healthy_w
                supporting.append(
                    MetricEvidence(
                        metric="latency_ms",
                        value=round(s["mean_lat"], 2),
                        unit="ms",
                        baseline=12.0,
                        interpretation=f"{dev_id}: Underlying IP transport delay ({s['mean_lat']:.1f} ms) is healthy, isolating failure to DNS daemon",
                    )
                )
            elif s["mean_lat"] >= 150.0 or s["mean_loss"] >= 5.0:
                score -= unhealthy_penalty

            score = max(0.0, min(1.0, score))
            if score > best_score:
                best_score = score

        return HypothesisCandidate(
            cause_code=CauseCode.DNS_FAILURE,
            score=round(best_score, 2),
            supporting_metrics=supporting,
            contradicting_metrics=contradicting,
        )

    def _evaluate_dhcp_failure(
        self,
        summaries: Dict[str, Dict[str, Any]],
        graph: Optional[nx.Graph],
    ) -> HypothesisCandidate:
        """Evaluate DHCP_FAILURE: DHCP lease exhaustion/failures while link transport is healthy."""
        w_cfg = self.weights_cfg.get("dhcp_failure", {})
        crit_w = w_cfg.get("critical_dhcp_failures", 0.60)
        warn_w = w_cfg.get("warn_dhcp_failures", 0.30)
        healthy_w = w_cfg.get("transport_links_healthy", 0.30)
        unhealthy_penalty = w_cfg.get("contradiction_transport_unhealthy_penalty", 0.40)
        healthy_dhcp_penalty = w_cfg.get("contradiction_dhcp_healthy_penalty", 0.70)

        supporting: List[MetricEvidence] = []
        contradicting: List[MetricEvidence] = []
        best_score = 0.0

        for dev_id, s in summaries.items():
            is_dhcp = "DHCP" in dev_id or (graph and "dhcp" in str(graph.nodes.get(dev_id, {}).get("model", "")).lower())
            if s["mean_dhcp"] <= 0 and not is_dhcp:
                continue

            score = 0.0
            crit_dhcp = self.thresholds_cfg.get("dhcp_critical_failures", 25)
            warn_dhcp = self.thresholds_cfg.get("dhcp_warn_failures", 5)

            if s["mean_dhcp"] >= crit_dhcp:
                score += crit_w
                supporting.append(
                    MetricEvidence(
                        metric="dhcp_failures",
                        value=round(s["mean_dhcp"], 0),
                        unit="events",
                        baseline=0,
                        interpretation=f"{dev_id}: Severe DHCP lease allocation failure rate ({s['mean_dhcp']:.0f} events)",
                    )
                )
            elif s["mean_dhcp"] >= warn_dhcp:
                score += warn_w
            else:
                score -= healthy_dhcp_penalty

            if s["mean_lat"] < self.thresholds_cfg.get("latency_warn_ms", 80.0) and s["mean_loss"] < 1.0:
                score += healthy_w
                supporting.append(
                    MetricEvidence(
                        metric="latency_ms",
                        value=round(s["mean_lat"], 2),
                        unit="ms",
                        baseline=12.0,
                        interpretation=f"{dev_id}: Physical IP link healthy, isolating fault to DHCP server pool exhaustion",
                    )
                )
            elif s["mean_lat"] >= 150.0 or s["mean_loss"] >= 5.0:
                score -= unhealthy_penalty

            score = max(0.0, min(1.0, score))
            if score > best_score:
                best_score = score

        return HypothesisCandidate(
            cause_code=CauseCode.DHCP_FAILURE,
            score=round(best_score, 2),
            supporting_metrics=supporting,
            contradicting_metrics=contradicting,
        )

    def _evaluate_hardware_failure(
        self,
        shared_upstream: Optional[str],
        summaries: Dict[str, Dict[str, Any]],
        graph: Optional[nx.Graph],
    ) -> HypothesisCandidate:
        """Evaluate HARDWARE_FAILURE: upstream node down or all downstream nodes disconnected."""
        w_cfg = self.weights_cfg.get("hardware_failure", {})
        down_w = w_cfg.get("upstream_node_down", 0.65)
        downstream_unreachable_w = w_cfg.get("high_downstream_unreachable", 0.25)
        degraded_crit_w = w_cfg.get("upstream_degraded_critical", 0.20)
        healthy_penalty = w_cfg.get("contradiction_healthy_status_penalty", 0.70)

        supporting: List[MetricEvidence] = []
        contradicting: List[MetricEvidence] = []
        score = 0.0

        target_node = shared_upstream if (shared_upstream and shared_upstream in summaries) else None
        if not target_node:
            down_nodes = [d for d, s in summaries.items() if s["is_down"]]
            if down_nodes:
                target_node = down_nodes[0]

        if target_node:
            s = summaries[target_node]
            if s["is_down"]:
                score += down_w
                supporting.append(
                    MetricEvidence(
                        metric="device_status",
                        value="down",
                        unit="enum",
                        baseline="up",
                        interpretation=f"Hardware node {target_node} is down / unreachable",
                    )
                )
                if graph:
                    downstream = self.get_downstream_nodes(graph, target_node)
                    if downstream:
                        score += downstream_unreachable_w
            elif s["is_degraded"] and s["mean_loss"] >= 20.0:
                score += degraded_crit_w
            else:
                score -= healthy_penalty
        else:
            score -= healthy_penalty

        return HypothesisCandidate(
            cause_code=CauseCode.HARDWARE_FAILURE,
            score=round(max(0.0, min(1.0, score)), 2),
            supporting_metrics=supporting,
            contradicting_metrics=contradicting,
        )

    def _evaluate_normal(self, affected_devices: List[str]) -> HypothesisCandidate:
        """Evaluate NORMAL baseline: no affected devices detected in topology."""
        w_cfg = self.weights_cfg.get("normal", {})
        base_score = w_cfg.get("no_affected_devices", 1.0)
        penalty = w_cfg.get("contradiction_affected_devices_penalty", 0.85)

        if not affected_devices:
            return HypothesisCandidate(
                cause_code=CauseCode.NORMAL,
                score=round(base_score, 2),
                supporting_metrics=[
                    MetricEvidence(
                        metric="device_status",
                        value="up",
                        unit="enum",
                        baseline="up",
                        interpretation="All campus nodes and links operating within nominal boundaries",
                    )
                ],
                contradicting_metrics=[],
            )

        score = max(0.0, base_score - penalty)
        return HypothesisCandidate(
            cause_code=CauseCode.NORMAL,
            score=round(score, 2),
            supporting_metrics=[],
            contradicting_metrics=[
                MetricEvidence(
                    metric="device_status",
                    value=f"{len(affected_devices)} affected",
                    unit="enum",
                    baseline="up",
                    interpretation=f"{len(affected_devices)} device(s) exhibit performance degradation",
                )
            ],
        )

    def _handle_evidence_query(self, message: MessageEnvelope) -> MessageEnvelope:
        """Answer peer correlation queries regarding downstream impact or service state."""
        query_payload = (
            message.payload
            if isinstance(message.payload, EvidenceQueryPayload)
            else EvidenceQueryPayload.model_validate(message.payload)
        )
        incident_id = message.incident_id
        cached_task = self.context_for(incident_id)

        if not cached_task or not cached_task.payload or not getattr(cached_task.payload, "telemetry", None):
            resp_payload = EvidenceResponsePayload(
                query_id=query_payload.query_id,
                cause_code=query_payload.cause_code,
                supports=None,
                confidence=0.0,
                answers=[],
                notes="No cached telemetry context found for incident.",
                device_telemetry=[],
                matched_records_count=0,
                data_truncated=False,
            )
            return self.make_message(
                recipient=message.sender,
                message_type=MessageType.EVIDENCE_RESPONSE,
                payload=resp_payload,
                incident_id=incident_id,
                correlation_id=message.message_id,
            )

        telemetry: Dict[str, List[Dict[str, Any]]] = getattr(cached_task.payload, "telemetry", {})
        topology_dict: Optional[Dict[str, Any]] = getattr(cached_task.payload, "topology", None)
        graph = self.build_graph_from_topology(topology_dict)

        answers: List[EvidenceAnswer] = []
        target_devs = query_payload.device_ids if query_payload.device_ids else list(telemetry.keys())

        for d in target_devs:
            records = telemetry.get(d, [])
            downstream = self.get_downstream_nodes(graph, d) if graph else []

            interp = f"{d}: {len(downstream)} downstream node(s) in topology"
            if records:
                mean_lat = sum(float(r["latency_ms"]) for r in records if "latency_ms" in r) / len(records)
                interp += f", mean latency {mean_lat:.1f}ms"

            answers.append(
                EvidenceAnswer(
                    device_id=d,
                    metric="device_status",
                    value=f"{len(downstream)} downstream",
                    unit="nodes",
                    baseline=0,
                    interpretation=interp,
                )
            )

        supports: Optional[bool] = None
        conf = 0.5
        q_cause = str(query_payload.cause_code) if query_payload.cause_code else None

        if q_cause:
            sub_task = TaskRequestPayload(task="analyze", telemetry=telemetry, topology=topology_dict)
            finding_env = self._analyze_connectivity(sub_task, incident_id, message.message_id)
            f_payload: FindingPayload = finding_env.payload  # type: ignore

            matched_cand = next((c for c in f_payload.hypothesis_candidates if str(c.cause_code) == q_cause), None)
            if matched_cand:
                if matched_cand.score >= 0.60:
                    supports = True
                    conf = matched_cand.score
                elif matched_cand.score <= 0.30:
                    supports = False
                    conf = round(1.0 - matched_cand.score, 2)
                else:
                    supports = None
                    conf = 0.50

        notes_str = f"Evaluated topological connectivity and downstream reach for {len(target_devs)} device(s)."
        resp_payload = EvidenceResponsePayload(
            query_id=query_payload.query_id,
            cause_code=query_payload.cause_code,
            supports=supports,
            confidence=conf,
            answers=answers,
            notes=notes_str,
            device_telemetry=[],
            matched_records_count=len(answers),
            data_truncated=False,
        )
        return self.make_message(
            recipient=message.sender,
            message_type=MessageType.EVIDENCE_RESPONSE,
            payload=resp_payload,
            incident_id=incident_id,
            correlation_id=message.message_id,
        )