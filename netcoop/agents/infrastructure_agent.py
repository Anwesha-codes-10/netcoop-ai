"""NetCoop AI - Infrastructure Health Agent.

Specialized agent analyzing device operational state and subsystem integrity:
- device_status (up/down/degraded), cpu_pct, memory_pct, interface_errors,
  queue_drops, rssi_dbm, snr_db, and retransmission_pct.
Evaluates status transitions/flapping, sustained resource exhaustion, interface error rates,
buffer drops vs control-plane CPU load, and wireless RF health.
Identifies DEVICE_CPU_OVERLOAD, INTERFACE_FAULT, HARDWARE_FAILURE, LINK_CONGESTION,
WEAK_WIFI_SIGNAL, and NORMAL baselines.
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


class InfrastructureHealthAgent(BaseAgent):
    """Autonomous agent diagnosing infrastructure device health and physical/system degradation."""

    def __init__(self, config: Optional[Dict[str, Any]] = None):
        super().__init__(config=config)
        self.name = "infrastructure_agent"
        self.capabilities = [
            "device_health",
            "cpu_memory_utilization",
            "interface_errors",
            "queue_drops",
            "wireless_rf_health",
            "hardware_lifecycle",
        ]

        sys_cfg = load_config()
        i_cfg = agent_config("infrastructure_agent")
        if config:
            i_cfg.update(config)

        self.thresholds_cfg: Dict[str, Any] = sys_cfg.get("thresholds", {})
        self.metric_thresholds: Dict[str, Any] = self.thresholds_cfg.get("metrics", {})
        self.monitored_metrics: List[str] = i_cfg.get(
            "monitored_metrics",
            [
                "device_status",
                "cpu_pct",
                "memory_pct",
                "interface_errors",
                "queue_drops",
                "rssi_dbm",
                "snr_db",
                "retransmission_pct",
            ],
        )
        self.detection_cfg: Dict[str, Any] = i_cfg.get("detection", {})
        self.weights_cfg: Dict[str, Any] = i_cfg.get("weights", {})
        self.conf_cfg: Dict[str, Any] = i_cfg.get("confidence", {})

    def detect_status_flapping(self, statuses: List[str]) -> Tuple[int, bool]:
        """Detect operational state flapping across time window and return (transition_count, is_flapping)."""
        if len(statuses) < 2:
            return 0, False

        transitions = 0
        for i in range(1, len(statuses)):
            if str(statuses[i]).strip().lower() != str(statuses[i - 1]).strip().lower():
                transitions += 1

        thresh = self.detection_cfg.get("flapping_transition_threshold", 2)
        return transitions, transitions >= thresh

    def calculate_downtime_fraction(self, statuses: List[str]) -> float:
        """Calculate fraction of telemetry window where device state is not 'up'."""
        if not statuses:
            return 0.0
        non_up = sum(1 for s in statuses if str(s).strip().lower() != "up")
        return round(non_up / len(statuses), 3)

    def check_sustained_condition(
        self,
        values: List[float],
        threshold: float,
        min_consecutive: int = 2,
        operator: str = ">=",
    ) -> bool:
        """Verify if a metric sustains a threshold boundary for at least N consecutive samples."""
        if not values or len(values) < min_consecutive:
            return False

        consecutive = 0
        for v in values:
            match = False
            if operator == ">=" and v >= threshold:
                match = True
            elif operator == "<=" and v <= threshold:
                match = True
            elif operator == ">" and v > threshold:
                match = True
            elif operator == "<" and v < threshold:
                match = True

            if match:
                consecutive += 1
                if consecutive >= min_consecutive:
                    return True
            else:
                consecutive = 0
        return False

    def calculate_counter_trend(self, timestamps: List[Any], values: List[float]) -> float:
        """Compute rate of increase (trend slope per hour) for cumulative counters."""
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

    def calculate_rate_of_change(self, timestamps: List[Any], values: List[float]) -> float:
        """Calculate rate of change per minute over telemetry window."""
        if len(values) < 2 or len(timestamps) < 2:
            return 0.0

        t_first = parse_iso_timestamp(timestamps[0]) if isinstance(timestamps[0], str) else timestamps[0]
        t_last = parse_iso_timestamp(timestamps[-1]) if isinstance(timestamps[-1], str) else timestamps[-1]

        if isinstance(t_first, datetime) and isinstance(t_last, datetime):
            span_sec = max(60.0, (t_last - t_first).total_seconds())
        else:
            span_sec = max(60.0, (len(values) - 1) * 60.0)

        delta_val = values[-1] - values[0]
        return (delta_val / span_sec) * 60.0

    def calculate_zscore(self, values: List[float], baseline: Optional[float] = None) -> float:
        """Calculate statistical z-score of values relative to baseline."""
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

    def is_wireless_device(self, device_id: str, topology: Optional[Dict[str, Any]] = None) -> bool:
        """Identify if device is a wireless Access Point via topology metadata or naming convention."""
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

    async def _process(self, message: MessageEnvelope) -> List[MessageEnvelope]:
        """Dispatch task requests and peer evidence queries."""
        if message.message_type == MessageType.TASK_REQUEST:
            task_payload = (
                message.payload
                if isinstance(message.payload, TaskRequestPayload)
                else TaskRequestPayload.model_validate(message.payload)
            )
            if task_payload.task == "analyze":
                finding = self._analyze_infrastructure(task_payload, message.incident_id, message.message_id)
                return [finding]
            return []

        if message.message_type == MessageType.EVIDENCE_QUERY:
            evidence_resp = self._handle_evidence_query(message)
            return [evidence_resp]

        return []

    def _analyze_infrastructure(
        self,
        task: TaskRequestPayload,
        incident_id: str,
        correlation_id: str,
    ) -> MessageEnvelope:
        """Analyze device health telemetry and construct FindingPayload."""
        telemetry = task.telemetry or {}

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

        device_summaries: Dict[str, Dict[str, Any]] = {}
        max_samples_seen = 0

        for dev_id, records in telemetry.items():
            if not records:
                continue
            max_samples_seen = max(max_samples_seen, len(records))

            timestamps = [r.get("timestamp") for r in records if "timestamp" in r]
            statuses = [str(r.get("device_status") or r.get("status") or "up") for r in records]

            cpu_vals = [float(r["cpu_pct"]) for r in records if "cpu_pct" in r and r["cpu_pct"] is not None]
            mem_vals = [float(r["memory_pct"]) for r in records if "memory_pct" in r and r["memory_pct"] is not None]
            err_vals = [float(r["interface_errors"]) for r in records if "interface_errors" in r and r["interface_errors"] is not None]
            drop_vals = [float(r["queue_drops"]) for r in records if "queue_drops" in r and r["queue_drops"] is not None]

            rssi_vals = [float(r["rssi_dbm"]) for r in records if "rssi_dbm" in r and r["rssi_dbm"] is not None]
            snr_vals = [float(r["snr_db"]) for r in records if "snr_db" in r and r["snr_db"] is not None]
            retrans_vals = [float(r["retransmission_pct"]) for r in records if "retransmission_pct" in r and r["retransmission_pct"] is not None]

            for m in ["cpu_pct", "memory_pct", "interface_errors", "queue_drops"]:
                if not any(m in r for r in records if isinstance(r, dict)):
                    missing_fields.add(m)

            is_wireless = self.is_wireless_device(dev_id, task.topology) or len(rssi_vals) > 0

            mean_cpu = sum(cpu_vals) / len(cpu_vals) if cpu_vals else 0.0
            max_cpu = max(cpu_vals) if cpu_vals else 0.0
            mean_mem = sum(mem_vals) / len(mem_vals) if mem_vals else 0.0
            max_mem = max(mem_vals) if mem_vals else 0.0
            mean_err = sum(err_vals) / len(err_vals) if err_vals else 0.0
            max_err = max(err_vals) if err_vals else 0.0
            mean_drop = sum(drop_vals) / len(drop_vals) if drop_vals else 0.0
            max_drop = max(drop_vals) if drop_vals else 0.0

            mean_rssi = sum(rssi_vals) / len(rssi_vals) if rssi_vals else None
            mean_snr = sum(snr_vals) / len(snr_vals) if snr_vals else None
            mean_retrans = sum(retrans_vals) / len(retrans_vals) if retrans_vals else 0.0

            min_sustained = self.detection_cfg.get("min_consecutive_sustained_samples", 2)
            sustained_high_cpu = self.check_sustained_condition(
                cpu_vals, self.detection_cfg.get("cpu_warn_pct", 75.0), min_consecutive=min_sustained
            )

            err_trend = self.calculate_counter_trend(timestamps, err_vals) if len(err_vals) >= 2 else 0.0
            drop_rate = self.calculate_rate_of_change(timestamps, drop_vals) if len(drop_vals) >= 2 else 0.0
            flapping_count, is_flapping = self.detect_status_flapping(statuses)
            downtime_frac = self.calculate_downtime_fraction(statuses)
            has_down_state = any(s.lower() == "down" for s in statuses)

            device_summaries[dev_id] = {
                "has_cpu": bool(cpu_vals),
                "has_mem": bool(mem_vals),
                "has_err": bool(err_vals),
                "has_drop": bool(drop_vals),
                "has_rssi": bool(rssi_vals),
                "has_snr": bool(snr_vals),
                "has_retrans": bool(retrans_vals),
                "has_status": any(
                    ("device_status" in r and r["device_status"] is not None)
                    or ("status" in r and r["status"] is not None)
                    for r in records
                    if isinstance(r, dict)
        ),
                "is_wireless": is_wireless,
                "statuses": statuses,
                "has_down_state": has_down_state,
                "flapping_count": flapping_count,
                "is_flapping": is_flapping,
                "downtime_frac": downtime_frac,
                "mean_cpu": mean_cpu,
                "max_cpu": max_cpu,
                "sustained_high_cpu": sustained_high_cpu,
                "mean_mem": mean_mem,
                "max_mem": max_mem,
                "mean_err": mean_err,
                "max_err": max_err,
                "err_trend": err_trend,
                "mean_drop": mean_drop,
                "max_drop": max_drop,
                "drop_rate": drop_rate,
                "mean_rssi": mean_rssi,
                "mean_snr": mean_snr,
                "mean_retrans": mean_retrans,
            }

        cpu_w = self.detection_cfg.get("cpu_warn_pct", 75.0)
        err_w = self.detection_cfg.get("interface_errors_warn", 5)
        drop_w = self.detection_cfg.get("queue_drops_warn", 10)
        rssi_w = self.detection_cfg.get("rssi_warn_dbm", -75.0)

        anomalous_devices: List[str] = []
        for dev_id, s in device_summaries.items():
            is_anom = False
            if s["downtime_frac"] > 0 or s["has_down_state"] or s["is_flapping"]:
                is_anom = True
            elif s["mean_cpu"] >= cpu_w or s["mean_err"] >= err_w or s["mean_drop"] >= drop_w:
                is_anom = True
            elif s["mean_rssi"] is not None and s["mean_rssi"] <= rssi_w:
                is_anom = True

            if is_anom:
                anomalous_devices.append(dev_id)

        candidates: List[HypothesisCandidate] = [
            self._evaluate_device_cpu_overload(device_summaries),
            self._evaluate_interface_fault(device_summaries),
            self._evaluate_hardware_failure(device_summaries),
            self._evaluate_link_congestion(device_summaries),
            self._evaluate_weak_wifi(device_summaries),
            self._evaluate_normal(device_summaries),
        ]

        candidates.sort(key=lambda c: c.score, reverse=True)

        top_score = candidates[0].score if candidates else 0.0
        second_score = candidates[1].score if len(candidates) > 1 else 0.0
        margin = top_score - second_score

        base_w = self.conf_cfg.get("base_weight", 0.35)
        comp_w = self.conf_cfg.get("completeness_weight", 0.35)
        samp_w = self.conf_cfg.get("sample_count_weight", 0.30)
        min_samp = self.conf_cfg.get("min_samples_full_confidence", 5)

        missing_penalty = len(missing_fields) * 0.08
        completeness = max(0.0, min(1.0, round(base_completeness - missing_penalty, 2)))

        sample_factor = min(1.0, max_samples_seen / float(min_samp))
        raw_conf = (base_w * top_score) + (comp_w * completeness) + (samp_w * sample_factor)

        if top_score < 0.50:
            final_conf = min(raw_conf, 0.45, top_score * 0.9)
        elif margin < 0.12:
            final_conf = raw_conf * 0.85
        else:
            final_conf = raw_conf

        if completeness < 0.60:
            final_conf = min(final_conf, completeness * 0.9)

        confidence = max(0.0, min(0.98, round(final_conf, 2)))

        scope_devs = anomalous_devices if anomalous_devices else list(device_summaries.keys())

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

    def _evaluate_device_cpu_overload(self, summaries: Dict[str, Dict[str, Any]]) -> HypothesisCandidate:
        """Evaluate DEVICE_CPU_OVERLOAD: sustained high CPU/memory, contradicted by low CPU or extreme queue drops."""
        w_cfg = self.weights_cfg.get("device_cpu_overload", {})
        crit_cpu_w = w_cfg.get("critical_cpu", 0.45)
        warn_cpu_w = w_cfg.get("warn_cpu", 0.25)
        high_mem_w = w_cfg.get("high_memory", 0.20)
        sustained_w = w_cfg.get("sustained_duration", 0.15)
        degraded_w = w_cfg.get("degraded_status", 0.10)
        low_cpu_penalty = w_cfg.get("contradiction_low_cpu_penalty", 0.60)
        high_drops_penalty = w_cfg.get("contradiction_high_queue_drops_penalty", 0.30)

        best_score = 0.0
        best_supporting: List[MetricEvidence] = []
        best_contradicting: List[MetricEvidence] = []

        for dev_id, s in summaries.items():
            supporting: List[MetricEvidence] = []
            contradicting: List[MetricEvidence] = []
            score = 0.0

            if s.get("has_cpu", True) and s["mean_cpu"] >= self.detection_cfg.get("cpu_critical_pct", 90.0):
                score += crit_cpu_w
                supporting.append(
                    MetricEvidence(
                        metric="cpu_pct",
                        value=round(s["mean_cpu"], 2),
                        unit="%",
                        baseline=25.0,
                        interpretation=f"{dev_id}: Processor utilization critically exhausted at {s['mean_cpu']:.1f}%",
                    )
                )
            elif s.get("has_cpu", True) and s["mean_cpu"] >= self.detection_cfg.get("cpu_warn_pct", 75.0):
                score += warn_cpu_w
                supporting.append(
                    MetricEvidence(
                        metric="cpu_pct",
                        value=round(s["mean_cpu"], 2),
                        unit="%",
                        baseline=25.0,
                        interpretation=f"{dev_id}: Processor utilization elevated at {s['mean_cpu']:.1f}%",
                    )
                )

            if s.get("has_mem", True) and s["mean_mem"] >= self.detection_cfg.get("memory_warn_pct", 80.0):
                score += high_mem_w
                supporting.append(
                    MetricEvidence(
                        metric="memory_pct",
                        value=round(s["mean_mem"], 2),
                        unit="%",
                        baseline=40.0,
                        interpretation=f"{dev_id}: High system memory usage ({s['mean_mem']:.1f}%)",
                    )
                )

            if s.get("has_cpu", True) and s["sustained_high_cpu"]:
                score += sustained_w
                supporting.append(
                    MetricEvidence(
                        metric="cpu_pct",
                        value=round(s["max_cpu"], 2),
                        unit="%",
                        baseline=25.0,
                        interpretation=f"{dev_id}: High CPU sustained over consecutive observation intervals",
                    )
                )

            if s["downtime_frac"] > 0:
                score += degraded_w

            if s.get("has_cpu", True) and s["mean_cpu"] < self.detection_cfg.get("cpu_low_threshold_pct", 50.0):
                score -= low_cpu_penalty
                contradicting.append(
                    MetricEvidence(
                        metric="cpu_pct",
                        value=round(s["mean_cpu"], 2),
                        unit="%",
                        baseline=25.0,
                        interpretation=f"{dev_id}: Normal processor utilization ({s['mean_cpu']:.1f}%) rules out CPU overload",
                    )
                )

            extreme_drops = self.detection_cfg.get("queue_drops_extreme", 2000)
            if s["mean_drop"] >= extreme_drops:
                score -= high_drops_penalty
                contradicting.append(
                    MetricEvidence(
                        metric="queue_drops",
                        value=round(s["mean_drop"], 0),
                        unit="packets",
                        baseline=0,
                        interpretation=f"{dev_id}: Massive egress queue drops ({s['mean_drop']:.0f} pkts) point to link bandwidth saturation rather than pure CPU overload",
                    )
                )
            elif s["mean_drop"] >= self.detection_cfg.get("queue_drops_warn", 10):
                contradicting.append(
                    MetricEvidence(
                        metric="queue_drops",
                        value=round(s["mean_drop"], 0),
                        unit="packets",
                        baseline=0,
                        interpretation=f"{dev_id}: Queue drops ({s['mean_drop']:.0f} pkts) present alongside CPU stress",
                    )
                )

            score = max(0.0, min(1.0, score))
            if score > best_score:
                best_score = score
                best_supporting = supporting
                best_contradicting = contradicting

        return HypothesisCandidate(
            cause_code=CauseCode.DEVICE_CPU_OVERLOAD,
            score=round(best_score, 2),
            supporting_metrics=best_supporting,
            contradicting_metrics=best_contradicting,
        )

    def _evaluate_interface_fault(self, summaries: Dict[str, Dict[str, Any]]) -> HypothesisCandidate:
        """Evaluate INTERFACE_FAULT: physical interface errors, rising error counters, status flapping."""
        w_cfg = self.weights_cfg.get("interface_fault", {})
        crit_err_w = w_cfg.get("critical_interface_errors", 0.50)
        warn_err_w = w_cfg.get("warn_interface_errors", 0.30)
        trend_w = w_cfg.get("rising_errors_trend", 0.20)
        status_w = w_cfg.get("degraded_or_flapping_status", 0.15)
        wired_w = w_cfg.get("wired_device", 0.15)
        zero_err_penalty = w_cfg.get("contradiction_zero_errors_penalty", 0.60)
        wireless_penalty = w_cfg.get("contradiction_wireless_penalty", 0.30)

        best_score = 0.0
        best_supporting: List[MetricEvidence] = []
        best_contradicting: List[MetricEvidence] = []

        for dev_id, s in summaries.items():
            if s["has_down_state"]:
                continue

            supporting: List[MetricEvidence] = []
            contradicting: List[MetricEvidence] = []
            score = 0.0

            if not s["is_wireless"]:
                score += wired_w
            else:
                score -= wireless_penalty

            if s["mean_err"] >= self.detection_cfg.get("interface_errors_critical", 50):
                score += crit_err_w
                supporting.append(
                    MetricEvidence(
                        metric="interface_errors",
                        value=round(s["mean_err"], 0),
                        unit="errors",
                        baseline=0,
                        interpretation=f"{dev_id}: High physical framing/CRC errors ({s['mean_err']:.0f}) detected",
                    )
                )
            elif s["mean_err"] >= self.detection_cfg.get("interface_errors_warn", 5):
                score += warn_err_w
                supporting.append(
                    MetricEvidence(
                        metric="interface_errors",
                        value=round(s["mean_err"], 0),
                        unit="errors",
                        baseline=0,
                        interpretation=f"{dev_id}: Elevated interface errors ({s['mean_err']:.0f}) detected",
                    )
                )

            if s["err_trend"] >= self.detection_cfg.get("interface_errors_slope_per_hour_warn", 10.0) or (s["mean_err"] > 0 and s["max_err"] > 0):
                score += trend_w
                supporting.append(
                    MetricEvidence(
                        metric="interface_errors",
                        value=round(s["max_err"], 0),
                        unit="errors",
                        baseline=0,
                        interpretation=f"{dev_id}: Active accumulation of interface error events",
                    )
                )

            if s["is_flapping"] or s["downtime_frac"] > 0:
                score += status_w
                supporting.append(
                    MetricEvidence(
                        metric="device_status",
                        value=s["statuses"][-1],
                        unit="enum",
                        baseline="up",
                        interpretation=f"{dev_id}: Link operational status degraded ({s['statuses'][-1]})",
                    )
                )

            if s["max_err"] == 0:
                score -= zero_err_penalty
                contradicting.append(
                    MetricEvidence(
                        metric="interface_errors",
                        value=0,
                        unit="errors",
                        baseline=0,
                        interpretation=f"{dev_id}: Zero interface errors observed",
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

    def _evaluate_hardware_failure(self, summaries: Dict[str, Dict[str, Any]]) -> HypothesisCandidate:
        """Evaluate HARDWARE_FAILURE: node down, persistent degradation, or severe flapping."""
        w_cfg = self.weights_cfg.get("hardware_failure", {})
        down_w = w_cfg.get("device_down", 0.65)
        flapping_w = w_cfg.get("status_flapping", 0.30)
        downtime_w = w_cfg.get("high_downtime_fraction", 0.25)
        healthy_penalty = w_cfg.get("contradiction_healthy_status_penalty", 0.70)

        best_score = 0.0
        best_supporting: List[MetricEvidence] = []
        best_contradicting: List[MetricEvidence] = []

        for dev_id, s in summaries.items():
            supporting: List[MetricEvidence] = []
            contradicting: List[MetricEvidence] = []
            score = 0.0

            if s["has_down_state"]:
                score += down_w + downtime_w + 0.10
                supporting.append(
                    MetricEvidence(
                        metric="device_status",
                        value="down",
                        unit="enum",
                        baseline="up",
                        interpretation=f"{dev_id}: Hardware device reported down state",
                    )
                )

            if s["is_flapping"]:
                score += flapping_w
                supporting.append(
                    MetricEvidence(
                        metric="device_status",
                        value=f"{s['flapping_count']} transitions",
                        unit="enum",
                        baseline="up",
                        interpretation=f"{dev_id}: Link/node status is flapping intermittently",
                    )
                )

            if not s["has_down_state"] and not s["is_flapping"] and s["downtime_frac"] == 0:
                score -= healthy_penalty
                contradicting.append(
                    MetricEvidence(
                        metric="device_status",
                        value="up",
                        unit="enum",
                        baseline="up",
                        interpretation=f"{dev_id}: Device status persistently up with no hardware crash",
                    )
                )

            score = max(0.0, min(1.0, score))
            if score > best_score:
                best_score = score
                best_supporting = supporting
                best_contradicting = contradicting

        return HypothesisCandidate(
            cause_code=CauseCode.HARDWARE_FAILURE,
            score=round(best_score, 2),
            supporting_metrics=best_supporting,
            contradicting_metrics=best_contradicting,
        )

    def _evaluate_link_congestion(self, summaries: Dict[str, Dict[str, Any]]) -> HypothesisCandidate:
        """Evaluate LINK_CONGESTION via queue_drops (buffer overflow) while CPU is normal."""
        w_cfg = self.weights_cfg.get("link_congestion", {})
        crit_drop_w = w_cfg.get("critical_queue_drops", 0.50)
        warn_drop_w = w_cfg.get("warn_queue_drops", 0.30)
        normal_cpu_w = w_cfg.get("normal_cpu", 0.20)
        status_w = w_cfg.get("degraded_status", 0.10)
        zero_drop_penalty = w_cfg.get("contradiction_zero_queue_drops_penalty", 0.60)
        crit_cpu_penalty = w_cfg.get("contradiction_critical_cpu_penalty", 0.35)

        best_score = 0.0
        best_supporting: List[MetricEvidence] = []
        best_contradicting: List[MetricEvidence] = []

        for dev_id, s in summaries.items():
            supporting: List[MetricEvidence] = []
            contradicting: List[MetricEvidence] = []
            score = 0.0

            if s["mean_drop"] >= self.detection_cfg.get("queue_drops_critical", 100):
                score += crit_drop_w
                supporting.append(
                    MetricEvidence(
                        metric="queue_drops",
                        value=round(s["mean_drop"], 0),
                        unit="packets",
                        baseline=0,
                        interpretation=f"{dev_id}: High buffer overflow packet discards ({s['mean_drop']:.0f} pkts)",
                    )
                )
            elif s["mean_drop"] >= self.detection_cfg.get("queue_drops_warn", 10):
                score += warn_drop_w
                supporting.append(
                    MetricEvidence(
                        metric="queue_drops",
                        value=round(s["mean_drop"], 0),
                        unit="packets",
                        baseline=0,
                        interpretation=f"{dev_id}: Elevated queue drops ({s['mean_drop']:.0f} pkts)",
                    )
                )

            if s["mean_cpu"] < self.detection_cfg.get("cpu_low_threshold_pct", 50.0):
                score += normal_cpu_w
                supporting.append(
                    MetricEvidence(
                        metric="cpu_pct",
                        value=round(s["mean_cpu"], 2),
                        unit="%",
                        baseline=25.0,
                        interpretation=f"{dev_id}: Normal processor utilization ({s['mean_cpu']:.1f}%) confirms data-plane saturation",
                    )
                )
            elif s["mean_cpu"] >= self.detection_cfg.get("cpu_critical_pct", 90.0):
                score -= crit_cpu_penalty
                contradicting.append(
                    MetricEvidence(
                        metric="cpu_pct",
                        value=round(s["mean_cpu"], 2),
                        unit="%",
                        baseline=25.0,
                        interpretation=f"{dev_id}: Critical CPU ({s['mean_cpu']:.1f}%) points to control-plane overload rather than pure link congestion",
                    )
                )

            if s["downtime_frac"] > 0:
                score += status_w

            if s["max_drop"] == 0:
                score -= zero_drop_penalty
                contradicting.append(
                    MetricEvidence(
                        metric="queue_drops",
                        value=0,
                        unit="packets",
                        baseline=0,
                        interpretation=f"{dev_id}: No buffer queue discards observed",
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
        """Evaluate WEAK_WIFI_SIGNAL: wireless AP with low RSSI, poor SNR, and high frame retransmissions."""
        w_cfg = self.weights_cfg.get("weak_wifi", {})
        wl_w = w_cfg.get("wireless_device", 0.25)
        rssi_w = w_cfg.get("critical_rssi", 0.30)
        snr_w = w_cfg.get("critical_snr", 0.25)
        retrans_w = w_cfg.get("critical_retrans", 0.20)
        wired_penalty = w_cfg.get("contradiction_wired_device_penalty", 0.60)
        healthy_rf_penalty = w_cfg.get("contradiction_healthy_rf_penalty", 0.50)

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

            if s["mean_rssi"] is not None:
                if s["mean_rssi"] <= self.detection_cfg.get("rssi_critical_dbm", -85.0):
                    score += rssi_w
                    supporting.append(
                        MetricEvidence(
                            metric="rssi_dbm",
                            value=round(s["mean_rssi"], 1),
                            unit="dBm",
                            baseline=-55.0,
                            interpretation=f"{dev_id}: Severely degraded signal strength ({s['mean_rssi']:.1f} dBm)",
                        )
                    )
                elif s["mean_rssi"] <= self.detection_cfg.get("rssi_warn_dbm", -75.0):
                    score += rssi_w * 0.70

            if s["mean_snr"] is not None:
                if s["mean_snr"] <= self.detection_cfg.get("snr_critical_db", 12.0):
                    score += snr_w
                    supporting.append(
                        MetricEvidence(
                            metric="snr_db",
                            value=round(s["mean_snr"], 1),
                            unit="dB",
                            baseline=35.0,
                            interpretation=f"{dev_id}: Poor Signal-to-Noise Ratio ({s['mean_snr']:.1f} dB)",
                        )
                    )
                elif s["mean_snr"] <= self.detection_cfg.get("snr_warn_db", 20.0):
                    score += snr_w * 0.70

            if s["mean_retrans"] >= self.detection_cfg.get("retrans_critical_pct", 20.0):
                score += retrans_w
                supporting.append(
                    MetricEvidence(
                        metric="retransmission_pct",
                        value=round(s["mean_retrans"], 2),
                        unit="%",
                        baseline=1.0,
                        interpretation=f"{dev_id}: Heavy 802.11 frame retry rate ({s['mean_retrans']:.1f}%)",
                    )
                )

            if s["mean_rssi"] is not None and s["mean_rssi"] > -70.0 and s["mean_retrans"] < 5.0:
                score -= healthy_rf_penalty

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

    def _evaluate_normal(self, summaries: Dict[str, Dict[str, Any]]) -> HypothesisCandidate:
        """Evaluate NORMAL baseline: all metrics within nominal ranges, status up."""
        w_cfg = self.weights_cfg.get("normal", {})
        base_score = w_cfg.get("all_within_thresholds", 1.0)
        crit_penalty = w_cfg.get("contradiction_any_critical_penalty", 0.85)

        cpu_crit = self.detection_cfg.get("cpu_critical_pct", 90.0)
        cpu_warn = self.detection_cfg.get("cpu_warn_pct", 75.0)
        err_crit = self.detection_cfg.get("interface_errors_critical", 50)
        err_warn = self.detection_cfg.get("interface_errors_warn", 5)
        drop_crit = self.detection_cfg.get("queue_drops_critical", 100)
        drop_warn = self.detection_cfg.get("queue_drops_warn", 10)
        rssi_crit = self.detection_cfg.get("rssi_critical_dbm", -85.0)
        rssi_warn = self.detection_cfg.get("rssi_warn_dbm", -75.0)

        has_critical = False
        has_warning = False
        has_unhealthy_status = False

        supporting: List[MetricEvidence] = []
        contradicting: List[MetricEvidence] = []
        all_required_observed = bool(summaries)

        for dev_id, s in summaries.items():
            required_observed = all(
                s.get(flag, True)
                for flag in (
                    "has_cpu",
                    "has_mem",
                    "has_err",
                    "has_drop",
                    "has_status",
                )
            )

            if not required_observed:
                all_required_observed = False
                continue

    
 
            if s["has_down_state"] or s["is_flapping"]:
                has_critical = True
            elif s["downtime_frac"] > 0:
                has_unhealthy_status = True

            if s["max_cpu"] >= cpu_crit or s["max_err"] >= err_crit or s["max_drop"] >= drop_crit:
                has_critical = True
            elif s["mean_cpu"] >= cpu_warn or s["mean_err"] >= err_warn or s["mean_drop"] >= drop_warn:
                has_warning = True

            if s["mean_rssi"] is not None:
                if s["mean_rssi"] <= rssi_crit:
                    has_critical = True
                elif s["mean_rssi"] <= rssi_warn:
                    has_warning = True

            if not has_critical and not has_warning:
                supporting.append(
                    MetricEvidence(
                        metric="cpu_pct",
                        value=round(s["mean_cpu"], 2),
                        unit="%",
                        baseline=25.0,
                        interpretation=f"{dev_id}: Hardware operating within nominal boundaries",
                    )
                )

        score = base_score if all_required_observed else 0.0
        if has_critical:
            score -= crit_penalty
        elif has_warning:
            score -= 0.55
        elif has_unhealthy_status:
            score -= 0.55

        return HypothesisCandidate(
            cause_code=CauseCode.NORMAL,
            score=round(max(0.0, min(1.0, score)), 2),
            supporting_metrics=supporting[:4],
            contradicting_metrics=contradicting[:4],
        )

    def _handle_evidence_query(self, message: MessageEnvelope) -> MessageEnvelope:
        """Handle incoming evidence_query from correlation agent using cached telemetry context."""
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
                if m == "device_status":
                    latest_status = str(records[-1].get("device_status") or records[-1].get("status") or "up")
                    answers.append(
                        EvidenceAnswer(
                            device_id=d,
                            metric="device_status",
                            value=latest_status,
                            unit="enum",
                            baseline="up",
                            interpretation=f"{d}: Operational status is {latest_status}",
                        )
                    )
                    continue

                vals = [float(r[m]) for r in records if m in r and r[m] is not None]
                if not vals:
                    continue
                mean_v = sum(vals) / len(vals)
                canon = CANONICAL_METRICS.get(m)
                unit = canon.unit if canon else ""
                base_val = 25.0 if m == "cpu_pct" else (40.0 if m == "memory_pct" else 0.0)

                interp = f"{d}: mean {m} is {mean_v:.2f}{unit}"
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

        supports: Optional[bool] = None
        conf = 0.5
        q_cause = str(query_payload.cause_code) if query_payload.cause_code else None

        if q_cause:
            dev_sub = {d: telemetry[d] for d in target_devs if d in telemetry}
            sub_task = TaskRequestPayload(task="analyze", telemetry=dev_sub)
            finding_env = self._analyze_infrastructure(sub_task, incident_id, message.message_id)
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