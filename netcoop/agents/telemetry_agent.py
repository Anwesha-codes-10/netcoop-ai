"""NetCoop AI - Telemetry Performance Analysis Agent.

Specialized agent analyzing network transport performance metrics:
- latency_ms, jitter_ms, packet_loss_pct, throughput_mbps, bandwidth_mbps, link_utilization_pct.
Evaluates baselines, z-scores, rolling spike counts, linear regression trend slopes,
and throughput saturation to identify LINK_CONGESTION, WEAK_WIFI_SIGNAL, INTERFACE_FAULT,
and NORMAL operating baselines.
"""

from datetime import datetime
import math
from typing import Any, Dict, List, Optional, Set, Tuple

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
from netcoop.protocol.validators import parse_iso_timestamp


class TelemetryPerformanceAgent(BaseAgent):
    """Autonomous agent analyzing link and transport-layer performance telemetry."""

    def __init__(self, config: Optional[Dict[str, Any]] = None):
        super().__init__(config=config)
        self.name = "telemetry_agent"
        self.capabilities = [
            "performance_telemetry",
            "link_utilization",
            "latency_jitter_loss",
            "throughput_saturation",
        ]

        # Load agent-specific tunables merged with global thresholds
        sys_cfg = load_config()
        t_cfg = agent_config("telemetry_agent")
        if config:
            t_cfg.update(config)

        self.thresholds_cfg: Dict[str, Any] = sys_cfg.get("thresholds", {})
        self.metric_thresholds: Dict[str, Any] = self.thresholds_cfg.get("metrics", {})
        self.monitored_metrics: List[str] = t_cfg.get(
            "monitored_metrics",
            [
                "latency_ms",
                "jitter_ms",
                "packet_loss_pct",
                "throughput_mbps",
                "bandwidth_mbps",
                "link_utilization_pct",
            ],
        )
        self.detection_cfg: Dict[str, Any] = t_cfg.get("detection", {})
        self.weights_cfg: Dict[str, Any] = t_cfg.get("weights", {})
        self.conf_cfg: Dict[str, Any] = t_cfg.get("confidence", {})

    # -------------------------------------------------------------------------
    # Helper Statistical & Anomaly Detection Functions
    # -------------------------------------------------------------------------

    def calculate_zscore(self, values: List[float], baseline: Optional[float] = None) -> float:
        """Calculate z-score of values against reference baseline or sample mean."""
        if not values:
            return 0.0
        n = len(values)
        mean_val = sum(values) / n
        ref_baseline = baseline if baseline is not None else mean_val
        if n < 2:
            denom = max(abs(ref_baseline) * 0.1, 1.0)
            return (mean_val - ref_baseline) / denom
        variance = sum((x - mean_val) ** 2 for x in values) / (n - 1)
        std_dev = math.sqrt(variance)
        if std_dev < 1e-6:
            denom = max(abs(ref_baseline) * 0.05, 1.0)
            return (mean_val - ref_baseline) / denom
        return (mean_val - ref_baseline) / std_dev

    def calculate_trend_slope(self, timestamps: List[Any], values: List[float]) -> float:
        """Calculate linear regression slope over time window, normalized per hour."""
        if len(values) < 2 or len(timestamps) < 2:
            return 0.0

        t_secs: List[float] = []
        start_t: Optional[datetime] = None
        for ts in timestamps:
            dt: Optional[datetime] = None
            if isinstance(ts, datetime):
                dt = ts
            elif isinstance(ts, str):
                dt = parse_iso_timestamp(ts)
            if dt is None:
                t_secs.append(len(t_secs) * 60.0)
            else:
                if start_t is None:
                    start_t = dt
                t_secs.append((dt - start_t).total_seconds())

        dt_span = t_secs[-1] - t_secs[0]
        if dt_span <= 0:
            return 0.0

        n = len(values)
        mean_t = sum(t_secs) / n
        mean_y = sum(values) / n
        num = sum((t_secs[i] - mean_t) * (values[i] - mean_y) for i in range(n))
        den = sum((t_secs[i] - mean_t) ** 2 for i in range(n))
        if den == 0:
            return 0.0

        slope_per_sec = num / den
        return slope_per_sec * 3600.0

    def count_spikes(self, values: List[float], threshold: Optional[float] = None) -> Tuple[int, float]:
        """Count values exceeding spike threshold and return (count, max_spike_size)."""
        if not values:
            return 0, 0.0

        if threshold is not None:
            thresh = threshold
        else:
            sorted_v = sorted(values)
            median = sorted_v[len(sorted_v) // 2]
            mult = self.detection_cfg.get("spike_threshold_multiplier", 1.5)
            thresh = median * mult

        count = 0
        max_spike = 0.0
        for v in values:
            if v > thresh:
                count += 1
                spike_size = v - thresh
                if spike_size > max_spike:
                    max_spike = spike_size
        return count, max_spike

    def detect_throughput_saturation(self, throughput: float, bandwidth: float, utilization: float) -> bool:
        """Determine if interface throughput is saturated near bandwidth with high utilization."""
        sat_util = self.detection_cfg.get("saturation_utilization_pct", 85.0)
        sat_ratio = self.detection_cfg.get("saturation_throughput_ratio", 0.85)

        is_util_high = utilization >= sat_util
        if bandwidth > 0:
            is_tput_high = (throughput / bandwidth) >= sat_ratio
        else:
            is_tput_high = is_util_high
        return is_util_high and is_tput_high

    def is_wireless_device(self, device_id: str, topology: Optional[Dict[str, Any]] = None) -> bool:
        """Classify device as wireless (AP) or wired using topology metadata or naming conventions."""
        if topology and isinstance(topology, dict):
            nodes = topology.get("nodes", [])
            for node in nodes:
                nid = node.get("id") or node.get("device_id")
                if nid == device_id:
                    dtype = node.get("device_type", "").lower()
                    if dtype == "access_point" or "wifi" in dtype or "wireless" in dtype:
                        return True
                    if dtype in ["access_switch", "distribution_switch", "core_router", "uplink", "server"]:
                        return False

        d_upper = device_id.upper()
        if d_upper.startswith("AP_") or "_AP_" in d_upper or "WIFI" in d_upper:
            return True
        return False

    # -------------------------------------------------------------------------
    # Core BaseAgent Message Processing
    # -------------------------------------------------------------------------

    async def _process(self, message: MessageEnvelope) -> List[MessageEnvelope]:
        """Dispatch task requests and peer evidence queries."""
        if message.message_type == MessageType.TASK_REQUEST:
            task_payload = (
                message.payload
                if isinstance(message.payload, TaskRequestPayload)
                else TaskRequestPayload.model_validate(message.payload)
            )
            if task_payload.task == "analyze":
                finding = self._analyze_telemetry(task_payload, message.incident_id, message.message_id)
                return [finding]
            return []

        if message.message_type == MessageType.EVIDENCE_QUERY:
            evidence_resp = self._handle_evidence_query(message)
            return [evidence_resp]

        return []

    # -------------------------------------------------------------------------
    # Task Analysis Implementation
    # -------------------------------------------------------------------------

    def _analyze_telemetry(
        self,
        task: TaskRequestPayload,
        incident_id: str,
        correlation_id: str,
    ) -> MessageEnvelope:
        """Analyze performance telemetry and return a structured FindingPayload."""
        telemetry = task.telemetry or {}

        # Handle empty telemetry payload
        if not telemetry or all(len(recs) == 0 for recs in telemetry.values()):
            dq_empty = DataQuality(
                completeness=0.0,
                missing_fields=list(self.monitored_metrics),
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

        # Track missing metrics and assess data completeness
        missing_fields: Set[str] = set()
        stale_fields: Set[str] = set()
        assumptions: List[str] = []

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
        else:
            base_completeness = 1.0
        preexisting_missing_fields = set(missing_fields)

        # Extract per-device summary metrics
        device_summaries: Dict[str, Dict[str, Any]] = {}
        max_samples_seen = 0

        for dev_id, records in telemetry.items():
            if not records:
                continue
            max_samples_seen = max(max_samples_seen, len(records))

            # Verify presence of monitored metrics
            for m in self.monitored_metrics:
                if not any(m in r for r in records if isinstance(r, dict)):
                    missing_fields.add(m)

            timestamps = [r.get("timestamp") for r in records if "timestamp" in r]
            lat_vals = [float(r["latency_ms"]) for r in records if "latency_ms" in r and r["latency_ms"] is not None]
            jit_vals = [float(r["jitter_ms"]) for r in records if "jitter_ms" in r and r["jitter_ms"] is not None]
            loss_vals = [float(r["packet_loss_pct"]) for r in records if "packet_loss_pct" in r and r["packet_loss_pct"] is not None]
            util_vals = [float(r["link_utilization_pct"]) for r in records if "link_utilization_pct" in r and r["link_utilization_pct"] is not None]
            tput_vals = [float(r["throughput_mbps"]) for r in records if "throughput_mbps" in r and r["throughput_mbps"] is not None]
            bw_vals = [float(r["bandwidth_mbps"]) for r in records if "bandwidth_mbps" in r and r["bandwidth_mbps"] is not None]

            mean_lat = sum(lat_vals) / len(lat_vals) if lat_vals else 0.0
            max_lat = max(lat_vals) if lat_vals else 0.0
            mean_jit = sum(jit_vals) / len(jit_vals) if jit_vals else 0.0
            max_jit = max(jit_vals) if jit_vals else 0.0
            mean_loss = sum(loss_vals) / len(loss_vals) if loss_vals else 0.0
            max_loss = max(loss_vals) if loss_vals else 0.0
            mean_util = sum(util_vals) / len(util_vals) if util_vals else 0.0
            max_util = max(util_vals) if util_vals else 0.0
            mean_tput = sum(tput_vals) / len(tput_vals) if tput_vals else 0.0
            max_bw = max(bw_vals) if bw_vals else 1000.0

            lat_slope = self.calculate_trend_slope(timestamps, lat_vals) if len(lat_vals) >= 2 else 0.0
            loss_spikes, max_loss_spike = self.count_spikes(loss_vals, threshold=self.detection_cfg.get("high_packet_loss_min_pct", 4.0))
            is_saturated = self.detect_throughput_saturation(mean_tput, max_bw, mean_util)
            is_wireless = self.is_wireless_device(dev_id, task.topology)

            device_summaries[dev_id] = {
                "is_wireless": is_wireless,
                "mean_lat": mean_lat,
                "max_lat": max_lat,
                "lat_slope": lat_slope,
                "mean_jit": mean_jit,
                "max_jit": max_jit,
                "mean_loss": mean_loss,
                "max_loss": max_loss,
                "loss_spikes": loss_spikes,
                "max_loss_spike": max_loss_spike,
                "mean_util": mean_util,
                "max_util": max_util,
                "mean_tput": mean_tput,
                "max_bw": max_bw,
                "is_saturated": is_saturated,
            }

        # Identify anomalous devices
        warn_lat = self.detection_cfg.get("warning_latency_ms", 80.0)
        warn_jit = self.detection_cfg.get("warning_jitter_ms", 20.0)
        warn_loss = self.detection_cfg.get("normal_loss_max_pct", 1.0)
        warn_util = self.detection_cfg.get("high_utilization_threshold_pct", 80.0)

        anomalous_devices: List[str] = []
        for dev_id, s in device_summaries.items():
            if s["mean_util"] >= warn_util or s["mean_lat"] >= warn_lat or s["mean_loss"] >= warn_loss or s["mean_jit"] >= warn_jit:
                anomalous_devices.append(dev_id)

        # Evaluate candidate root causes across devices
        candidates: List[HypothesisCandidate] = [
            self._evaluate_link_congestion(device_summaries),
            self._evaluate_weak_wifi(device_summaries),
            self._evaluate_interface_fault(device_summaries),
            self._evaluate_normal(device_summaries),
        ]

        candidates.sort(key=lambda c: c.score, reverse=True)

        # Compute aggregate confidence
        top_score = candidates[0].score if candidates else 0.0
        second_score = candidates[1].score if len(candidates) > 1 else 0.0
        margin = top_score - second_score

        base_w = self.conf_cfg.get("base_weight", 0.35)
        comp_w = self.conf_cfg.get("completeness_weight", 0.35)
        samp_w = self.conf_cfg.get("sample_count_weight", 0.30)
        min_samp = self.conf_cfg.get("min_samples_full_confidence", 5)

        # Factor in missing metrics into completeness penalty
        newly_missing_fields = missing_fields - preexisting_missing_fields
        missing_penalty = len(newly_missing_fields) * 0.08
        completeness = max(0.0, min(1.0, round(base_completeness - missing_penalty, 2)))

        sample_factor = min(1.0, max_samples_seen / float(min_samp))
        raw_conf = (base_w * top_score) + (comp_w * completeness) + (samp_w * sample_factor)

        # Lower confidence when data is borderline or completeness is low
        if top_score < 0.50:
            final_conf = min(raw_conf, 0.45, top_score * 0.9)
        elif margin < 0.12:
            final_conf = raw_conf * 0.85
        else:
            final_conf = raw_conf

        if completeness < 0.60:
            final_conf = min(final_conf, completeness * 0.9)

        confidence = max(0.0, min(0.98, round(final_conf, 2)))

        # Determine scope
        evaluated_devs = list(device_summaries.keys())
        scope_devs = anomalous_devices if anomalous_devices else evaluated_devs

        shared_segment = task.target_segment
        if not shared_segment and task.topology and isinstance(task.topology, dict):
            nodes = task.topology.get("nodes", [])
            segments_seen = set()
            for dev in scope_devs:
                for node in nodes:
                    nid = node.get("id") or node.get("device_id")
                    if nid == dev and node.get("segment"):
                        segments_seen.add(node["segment"])
            if len(segments_seen) == 1:
                shared_segment = list(segments_seen)[0]

        scope = FindingScope(device_ids=scope_devs, segment=shared_segment)
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

    # -------------------------------------------------------------------------
    # Candidate Evaluators
    # -------------------------------------------------------------------------

    def _evaluate_link_congestion(self, summaries: Dict[str, Dict[str, Any]]) -> HypothesisCandidate:
        """Evaluate LINK_CONGESTION indicators: high utilization, saturation, rising latency."""
        w_cfg = self.weights_cfg.get("link_congestion", {})
        high_util_w = w_cfg.get("high_utilization", 0.35)
        sat_w = w_cfg.get("throughput_saturation", 0.25)
        lat_w = w_cfg.get("elevated_latency", 0.20)
        jit_w = w_cfg.get("elevated_jitter", 0.10)
        loss_w = w_cfg.get("moderate_loss", 0.10)
        low_util_penalty = w_cfg.get("contradiction_low_utilization_penalty", 0.50)

        best_score = 0.0
        best_supporting: List[MetricEvidence] = []
        best_contradicting: List[MetricEvidence] = []

        for dev_id, s in summaries.items():
            supporting: List[MetricEvidence] = []
            contradicting: List[MetricEvidence] = []
            score = 0.0

            # 1. Utilization indicator
            if s["mean_util"] >= self.detection_cfg.get("critical_utilization_pct", 92.0):
                score += high_util_w
                supporting.append(
                    MetricEvidence(
                        metric="link_utilization_pct",
                        value=round(s["mean_util"], 2),
                        unit="%",
                        baseline=35.0,
                        interpretation=f"{dev_id}: Link utilization critically saturated at {s['mean_util']:.1f}%",
                    )
                )
            elif s["mean_util"] >= self.detection_cfg.get("high_utilization_threshold_pct", 80.0):
                score += high_util_w * 0.70
                supporting.append(
                    MetricEvidence(
                        metric="link_utilization_pct",
                        value=round(s["mean_util"], 2),
                        unit="%",
                        baseline=35.0,
                        interpretation=f"{dev_id}: Link utilization elevated at {s['mean_util']:.1f}%",
                    )
                )
            elif s["mean_util"] >= 75.0:
                score += high_util_w * 0.30

            # 2. Throughput saturation indicator
            if s["is_saturated"]:
                score += sat_w
                supporting.append(
                    MetricEvidence(
                        metric="throughput_mbps",
                        value=round(s["mean_tput"], 2),
                        unit="Mbps",
                        baseline=450.0,
                        interpretation=f"{dev_id}: Throughput ({s['mean_tput']:.1f} Mbps) saturated near link capacity ({s['max_bw']:.0f} Mbps)",
                    )
                )
            elif s["mean_util"] >= 85.0:
                score += sat_w * 0.70

            # 3. Elevated latency
            crit_lat = self.detection_cfg.get("critical_latency_ms", 200.0)
            warn_lat = self.detection_cfg.get("warning_latency_ms", 80.0)
            if s["mean_lat"] >= crit_lat or s["max_lat"] >= 250.0:
                score += lat_w
                supporting.append(
                    MetricEvidence(
                        metric="latency_ms",
                        value=round(s["mean_lat"], 2),
                        unit="ms",
                        baseline=12.0,
                        interpretation=f"{dev_id}: High latency ({s['mean_lat']:.1f} ms) due to buffer queue backlog",
                    )
                )
            elif s["mean_lat"] >= warn_lat or s["lat_slope"] > 50.0:
                score += lat_w * 0.70
                supporting.append(
                    MetricEvidence(
                        metric="latency_ms",
                        value=round(s["mean_lat"], 2),
                        unit="ms",
                        baseline=12.0,
                        interpretation=f"{dev_id}: Elevated latency ({s['mean_lat']:.1f} ms)",
                    )
                )

            # 4. Elevated jitter
            if s["mean_jit"] >= self.detection_cfg.get("critical_jitter_ms", 60.0):
                score += jit_w
                supporting.append(
                    MetricEvidence(
                        metric="jitter_ms",
                        value=round(s["mean_jit"], 2),
                        unit="ms",
                        baseline=2.5,
                        interpretation=f"{dev_id}: Critical queue variance/jitter ({s['mean_jit']:.1f} ms)",
                    )
                )
            elif s["mean_jit"] >= self.detection_cfg.get("warning_jitter_ms", 20.0):
                score += jit_w * 0.70

            # 5. Moderate packet loss
            if 0.5 <= s["mean_loss"] <= self.detection_cfg.get("moderate_packet_loss_max_pct", 6.0):
                score += loss_w
                supporting.append(
                    MetricEvidence(
                        metric="packet_loss_pct",
                        value=round(s["mean_loss"], 2),
                        unit="%",
                        baseline=0.0,
                        interpretation=f"{dev_id}: Moderate tail drops/loss ({s['mean_loss']:.1f}%) consistent with buffer saturation",
                    )
                )

            # Contradiction: Low utilization
            low_util_thresh = self.detection_cfg.get("low_utilization_threshold_pct", 50.0)
            if s["max_util"] < low_util_thresh:
                score -= low_util_penalty
                contradicting.append(
                    MetricEvidence(
                        metric="link_utilization_pct",
                        value=round(s["max_util"], 2),
                        unit="%",
                        baseline=35.0,
                        interpretation=f"{dev_id}: Low link utilization ({s['max_util']:.1f}%) contradicts link congestion",
                    )
                )

            score = max(0.0, min(1.0, score))
            if score > best_score:
                best_score = score
                best_supporting = supporting
                best_contradicting = contradicting

        return HypothesisCandidate(
            cause_code=CauseCode.LINK_CONGESTION,
            score=round(best_score, 2),
            supporting_metrics=best_supporting,
            contradicting_metrics=best_contradicting,
        )

    def _evaluate_weak_wifi(self, summaries: Dict[str, Dict[str, Any]]) -> HypothesisCandidate:
        """Evaluate WEAK_WIFI_SIGNAL: wireless AP with elevated latency/loss/jitter and low utilization."""
        w_cfg = self.weights_cfg.get("weak_wifi", {})
        wl_w = w_cfg.get("wireless_device", 0.25)
        low_util_w = w_cfg.get("low_utilization", 0.20)
        loss_w = w_cfg.get("elevated_loss", 0.25)
        lat_jit_w = w_cfg.get("elevated_latency_or_jitter", 0.30)
        wired_penalty = w_cfg.get("contradiction_wired_device_penalty", 0.60)
        high_util_penalty = w_cfg.get("contradiction_high_utilization_penalty", 0.35)

        best_score = 0.0
        best_supporting: List[MetricEvidence] = []
        best_contradicting: List[MetricEvidence] = []

        for dev_id, s in summaries.items():
            supporting: List[MetricEvidence] = []
            contradicting: List[MetricEvidence] = []
            score = 0.0

            if s["is_wireless"]:
                score += wl_w
            else:
                score -= wired_penalty
                contradicting.append(
                    MetricEvidence(
                        metric="link_utilization_pct",
                        value=round(s["mean_util"], 2),
                        unit="%",
                        baseline=35.0,
                        interpretation=f"{dev_id} is a wired infrastructure device, not an RF wireless node",
                    )
                )

            if s["max_util"] <= 60.0:
                score += low_util_w
                supporting.append(
                    MetricEvidence(
                        metric="link_utilization_pct",
                        value=round(s["mean_util"], 2),
                        unit="%",
                        baseline=35.0,
                        interpretation=f"{dev_id}: Link backhaul utilization is normal/unstressed ({s['mean_util']:.1f}%)",
                    )
                )
            elif s["mean_util"] >= 80.0:
                score -= high_util_penalty

            # Elevated packet loss
            if s["mean_loss"] >= self.detection_cfg.get("high_packet_loss_min_pct", 4.0):
                score += loss_w
                supporting.append(
                    MetricEvidence(
                        metric="packet_loss_pct",
                        value=round(s["mean_loss"], 2),
                        unit="%",
                        baseline=0.0,
                        interpretation=f"{dev_id}: High frame/packet loss ({s['mean_loss']:.1f}%) typical of weak RF coverage",
                    )
                )

            # Elevated latency or jitter
            if s["mean_lat"] >= self.detection_cfg.get("warning_latency_ms", 80.0) or s["mean_jit"] >= self.detection_cfg.get("warning_jitter_ms", 20.0):
                score += lat_jit_w
                supporting.append(
                    MetricEvidence(
                        metric="latency_ms",
                        value=round(s["mean_lat"], 2),
                        unit="ms",
                        baseline=12.0,
                        interpretation=f"{dev_id}: High delay ({s['mean_lat']:.1f} ms) caused by Wi-Fi retransmission timeouts",
                    )
                )

            score = max(0.0, min(1.0, score))
            if score > best_score:
                best_score = score
                best_supporting = supporting
                best_contradicting = contradicting

        return HypothesisCandidate(
            cause_code=CauseCode.WEAK_WIFI_SIGNAL,
            score=round(best_score, 2),
            supporting_metrics=best_supporting,
            contradicting_metrics=best_contradicting,
        )

    def _evaluate_interface_fault(self, summaries: Dict[str, Dict[str, Any]]) -> HypothesisCandidate:
        """Evaluate INTERFACE_FAULT: wired port with high/spiky loss while utilization is low."""
        w_cfg = self.weights_cfg.get("interface_fault", {})
        wired_w = w_cfg.get("wired_device", 0.25)
        loss_w = w_cfg.get("high_packet_loss", 0.35)
        low_util_w = w_cfg.get("low_or_normal_utilization", 0.25)
        spiky_w = w_cfg.get("spiky_or_intermittent_loss", 0.15)
        wireless_penalty = w_cfg.get("contradiction_wireless_penalty", 0.60)
        high_util_penalty = w_cfg.get("contradiction_high_utilization_penalty", 0.35)
        crit_lat_penalty = w_cfg.get("contradiction_critical_latency_penalty", 0.40)

        best_score = 0.0
        best_supporting: List[MetricEvidence] = []
        best_contradicting: List[MetricEvidence] = []

        for dev_id, s in summaries.items():
            supporting: List[MetricEvidence] = []
            contradicting: List[MetricEvidence] = []
            score = 0.0

            if not s["is_wireless"]:
                score += wired_w
            else:
                score -= wireless_penalty
                contradicting.append(
                    MetricEvidence(
                        metric="packet_loss_pct",
                        value=round(s["mean_loss"], 2),
                        unit="%",
                        baseline=0.0,
                        interpretation=f"{dev_id} is a wireless AP; packet drops are RF-related rather than PHY framing",
                    )
                )

            # High packet loss
            if s["mean_loss"] >= self.detection_cfg.get("high_packet_loss_min_pct", 4.0):
                score += loss_w
                supporting.append(
                    MetricEvidence(
                        metric="packet_loss_pct",
                        value=round(s["mean_loss"], 2),
                        unit="%",
                        baseline=0.0,
                        interpretation=f"{dev_id}: Elevated frame drop rate ({s['mean_loss']:.1f}%) on interface",
                    )
                )

            # Low/normal utilization
            if s["max_util"] <= 60.0:
                score += low_util_w
                supporting.append(
                    MetricEvidence(
                        metric="link_utilization_pct",
                        value=round(s["mean_util"], 2),
                        unit="%",
                        baseline=35.0,
                        interpretation=f"{dev_id}: Interface operates at unstressed capacity ({s['mean_util']:.1f}%)",
                    )
                )
            elif s["mean_util"] >= 80.0:
                score -= high_util_penalty

            # Spiky or intermittent loss
            if s["loss_spikes"] > 0 or s["max_loss_spike"] > 0:
                score += spiky_w
                supporting.append(
                    MetricEvidence(
                        metric="packet_loss_pct",
                        value=round(s["max_loss"], 2),
                        unit="%",
                        baseline=0.0,
                        interpretation=f"{dev_id}: Observed intermittent packet loss spikes up to {s['max_loss']:.1f}%",
                    )
                )

            # Contradiction: Extreme queuing delay (> 200 ms) contradicts purely physical FCS errors
            if s["mean_lat"] >= self.detection_cfg.get("critical_latency_ms", 200.0):
                score -= crit_lat_penalty
                contradicting.append(
                    MetricEvidence(
                        metric="latency_ms",
                        value=round(s["mean_lat"], 2),
                        unit="ms",
                        baseline=12.0,
                        interpretation=f"{dev_id}: Extreme queuing latency ({s['mean_lat']:.1f} ms) indicates device/queue overload rather than simple interface fault",
                    )
                )

            score = max(0.0, min(1.0, score))
            if score > best_score:
                best_score = score
                best_supporting = supporting
                best_contradicting = contradicting

        return HypothesisCandidate(
            cause_code=CauseCode.INTERFACE_FAULT,
            score=round(best_score, 2),
            supporting_metrics=best_supporting,
            contradicting_metrics=best_contradicting,
        )

    def _evaluate_normal(self, summaries: Dict[str, Dict[str, Any]]) -> HypothesisCandidate:
        """Evaluate NORMAL baseline: all metrics operating within nominal baseline parameters."""
        w_cfg = self.weights_cfg.get("normal", {})
        base_normal_score = w_cfg.get("all_within_thresholds", 1.0)
        crit_penalty = w_cfg.get("contradiction_any_critical_penalty", 0.85)
        warn_penalty = w_cfg.get("contradiction_any_warning_penalty", 0.45)

        warn_lat = self.detection_cfg.get("warning_latency_ms", 80.0)
        crit_lat = self.detection_cfg.get("critical_latency_ms", 200.0)
        warn_jit = self.detection_cfg.get("warning_jitter_ms", 20.0)
        crit_jit = self.detection_cfg.get("critical_jitter_ms", 60.0)
        warn_loss = self.detection_cfg.get("normal_loss_max_pct", 1.0)
        crit_loss = self.detection_cfg.get("high_packet_loss_min_pct", 4.0)
        warn_util = self.detection_cfg.get("high_utilization_threshold_pct", 80.0)
        crit_util = self.detection_cfg.get("critical_utilization_pct", 92.0)

        has_critical = False
        has_warning = False
        supporting: List[MetricEvidence] = []
        contradicting: List[MetricEvidence] = []

        for dev_id, s in summaries.items():
            if s["max_lat"] >= crit_lat or s["max_jit"] >= crit_jit or s["max_loss"] >= crit_loss or s["max_util"] >= crit_util:
                has_critical = True
                contradicting.append(
                    MetricEvidence(
                        metric="link_utilization_pct",
                        value=round(s["max_util"], 2),
                        unit="%",
                        baseline=35.0,
                        interpretation=f"{dev_id}: Metric exceeds critical boundary threshold",
                    )
                )
            elif s["mean_lat"] >= warn_lat or s["mean_jit"] >= warn_jit or s["mean_loss"] >= warn_loss or s["mean_util"] >= warn_util:
                has_warning = True
                contradicting.append(
                    MetricEvidence(
                        metric="latency_ms",
                        value=round(s["mean_lat"], 2),
                        unit="ms",
                        baseline=12.0,
                        interpretation=f"{dev_id}: Metric operates at elevated warning threshold",
                    )
                )
            else:
                supporting.append(
                    MetricEvidence(
                        metric="latency_ms",
                        value=round(s["mean_lat"], 2),
                        unit="ms",
                        baseline=12.0,
                        interpretation=f"{dev_id}: Round-trip delay ({s['mean_lat']:.1f} ms) well within nominal operating range",
                    )
                )

        score = base_normal_score
        if has_critical:
            score -= crit_penalty
        elif has_warning:
            score -= 0.55

        return HypothesisCandidate(
            cause_code=CauseCode.NORMAL,
            score=round(max(0.0, min(1.0, score)), 2),
            supporting_metrics=supporting[:4],
            contradicting_metrics=contradicting[:4],
        )

    # -------------------------------------------------------------------------
    # Peer Evidence Query Handler
    # -------------------------------------------------------------------------

    def _handle_evidence_query(self, message: MessageEnvelope) -> MessageEnvelope:
        """Handle incoming evidence_query from correlation agent using cached telemetry."""
        query_payload = (
            message.payload
            if isinstance(message.payload, EvidenceQueryPayload)
            else EvidenceQueryPayload.model_validate(message.payload)
        )
        incident_id = message.incident_id
        cached_task = self.context_for(incident_id)

        # Context absent: return unknown supports and zero confidence
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
        target_devs = query_payload.device_ids if query_payload.device_ids else list(telemetry.keys())
        target_metrics = query_payload.metrics if query_payload.metrics else self.monitored_metrics

        matched_telemetry: List[Dict[str, Any]] = []
        answers: List[EvidenceAnswer] = []

        for d in target_devs:
            records = telemetry.get(d, [])
            matched_telemetry.extend(records)
            if not records:
                continue

            for m in target_metrics:
                vals = [float(r[m]) for r in records if m in r and r[m] is not None]
                if not vals:
                    continue
                mean_v = sum(vals) / len(vals)
                canon = CANONICAL_METRICS.get(m)
                unit = canon.unit if canon else ""
                base_val = 12.0 if m == "latency_ms" else (35.0 if m == "link_utilization_pct" else 0.0)

                interp = f"{d}: mean {m} is {mean_v:.2f}{unit}"
                if m == "link_utilization_pct" and mean_v >= 80.0:
                    interp += " (high bandwidth saturation)"
                elif m == "latency_ms" and mean_v >= 80.0:
                    interp += " (elevated latency)"
                elif m == "packet_loss_pct" and mean_v >= 3.0:
                    interp += " (elevated drop rate)"

                answers.append(
                    EvidenceAnswer(
                        device_id=d,
                        metric=m,
                        value=round(mean_v, 2),
                        unit=unit,
                        baseline=base_val,
                        interpretation=interp,
                    )
                )

        # Evaluate if queried evidence supports the requested hypothesis
        supports: Optional[bool] = None
        conf = 0.5
        q_cause = str(query_payload.cause_code) if query_payload.cause_code else None

        if q_cause:
            # Re-evaluate candidate score over queried devices
            dev_sub = {d: telemetry[d] for d in target_devs if d in telemetry}
            sub_task = TaskRequestPayload(task="analyze", telemetry=dev_sub)
            finding_env = self._analyze_telemetry(sub_task, incident_id, message.message_id)
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

        notes_str = f"Evaluated {len(target_devs)} device(s) and {len(target_metrics)} metric(s) for query {query_payload.query_id}."
        resp_payload = EvidenceResponsePayload(
            query_id=query_payload.query_id,
            cause_code=query_payload.cause_code,
            supports=supports,
            confidence=conf,
            answers=answers,
            notes=notes_str,
            device_telemetry=matched_telemetry[:50],
            matched_records_count=len(matched_telemetry),
            data_truncated=len(matched_telemetry) > 50,
        )
        return self.make_message(
            recipient=message.sender,
            message_type=MessageType.EVIDENCE_RESPONSE,
            payload=resp_payload,
            incident_id=incident_id,
            correlation_id=message.message_id,
        )