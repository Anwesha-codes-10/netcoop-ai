"""NetCoop AI Protocol - Telemetry Normalizer.

Maps aliases to canonical names, converts units (s->ms, bps/kbps/Gbps->Mbps, fraction->pct),
records every conversion in an audit log, and penalizes completeness on ambiguous/unconvertible data.
"""

from dataclasses import dataclass, field
import re
from typing import Any, Dict, List, Optional, Set, Tuple

from netcoop.protocol.causes import CANONICAL_METRICS, is_canonical_metric
from netcoop.protocol.schema_registry import LEGACY_0_9_ALIAS_MAP

# Comprehensive alias mapping to canonical names
ALIAS_MAP: Dict[str, str] = {
    # Schema 0.9 aliases
    **LEGACY_0_9_ALIAS_MAP,
    # Common telemetry variants
    "cpu_utilization_pct": "cpu_pct",
    "cpu_usage": "cpu_pct",
    "cpu_util": "cpu_pct",
    "link_util": "link_utilization_pct",
    "utilization": "link_utilization_pct",
    "link_util_pct": "link_utilization_pct",
    "loss_pct": "packet_loss_pct",
    "loss_rate": "packet_loss_pct",
    "packet_loss": "packet_loss_pct",
    "latency": "latency_ms",
    "rtt_ms": "latency_ms",
    "delay_ms": "latency_ms",
    "jitter": "jitter_ms",
    "bandwidth": "bandwidth_mbps",
    "throughput": "throughput_mbps",
    "memory": "memory_pct",
    "mem_pct": "memory_pct",
    "memory_utilization_pct": "memory_pct",
    "rssi": "rssi_dbm",
    "snr": "snr_db",
    "retransmissions": "retransmission_pct",
    "retrans_pct": "retransmission_pct",
    "dns_latency": "dns_resolution_ms",
    "dns_ms": "dns_resolution_ms",
    "dhcp_errors": "dhcp_failures",
    "dhcp_drops": "dhcp_failures",
}

# String unit matching patterns
UNIT_STRING_PATTERN = re.compile(
    r"^\s*([+-]?\d+(?:\.\d+)?(?:[eE][+-]?\d+)?)\s*([a-zA-Z%]+)?\s*$"
)


@dataclass
class ConversionLogEntry:
    """Audit log entry capturing a field normalization or unit conversion."""

    field_original: str
    canonical_field: str
    original_value: Any
    original_unit: Optional[str]
    canonical_value: Any
    canonical_unit: str
    rule: str


@dataclass
class NormalizationResult:
    """Result of normalizing a raw telemetry payload or record."""

    normalized_data: Dict[str, Any]
    log: List[ConversionLogEntry] = field(default_factory=list)
    completeness: float = 1.0
    ambiguities: List[str] = field(default_factory=list)
    missing_fields: List[str] = field(default_factory=list)
    stale_fields: List[str] = field(default_factory=list)


class TelemetryNormalizer:
    """Normalizes network telemetry metrics to canonical NetCoop AI v1.0 schema."""

    def __init__(
        self,
        unconvertible_penalty: float = 0.10,
        ambiguous_unit_penalty: float = 0.08,
        missing_metric_penalty: float = 0.05,
    ):
        self.unconvertible_penalty = unconvertible_penalty
        self.ambiguous_unit_penalty = ambiguous_unit_penalty
        self.missing_metric_penalty = missing_metric_penalty

    def normalize_record(
        self,
        record: Dict[str, Any],
        expected_metrics: Optional[Set[str]] = None,
    ) -> NormalizationResult:
        """Normalize a single telemetry record or flattened metrics dictionary.

        Args:
            record: Raw input dictionary containing metrics, device_id, timestamp, etc.
            expected_metrics: Optional set of canonical metric names expected.

        Returns:
            NormalizationResult with normalized dictionary, audit log, and completeness score.
        """
        log: List[ConversionLogEntry] = []
        ambiguities: List[str] = []
        missing_fields: List[str] = []
        normalized: Dict[str, Any] = {}

        # Extract explicit units block if present
        explicit_units: Dict[str, str] = {}
        if isinstance(record.get("units"), dict):
            explicit_units = {k.lower(): str(v).lower() for k, v in record["units"].items()}

        # Retain top-level non-metric envelope identifiers if present
        for top_key in ["device_id", "timestamp", "status", "schema_version", "device_type"]:
            if top_key in record:
                normalized[top_key] = record[top_key]

        # Check if record has nested "metrics" subdict or is flat
        raw_metrics: Dict[str, Any] = {}
        if isinstance(record.get("metrics"), dict):
            raw_metrics = record["metrics"]
            # Check for units inside metrics block too
            if isinstance(raw_metrics.get("units"), dict):
                explicit_units.update({k.lower(): str(v).lower() for k, v in raw_metrics["units"].items()})
        else:
            raw_metrics = record

        # Process each key in raw_metrics
        for raw_key, raw_val in raw_metrics.items():
            if raw_key in ["units", "metrics"]:
                continue

            # Determine canonical name and candidate unit from key suffix
            canonical_name, suffix_unit = self._resolve_field_name_and_unit(raw_key)

            # Determine unit declared in explicit units block
            declared_unit = (
                explicit_units.get(raw_key.lower())
                or explicit_units.get(canonical_name.lower())
                or suffix_unit
            )

            # Convert value and unit to canonical
            conv_val, conv_unit, rule, error = self._convert_value_to_canonical(
                canonical_name=canonical_name,
                raw_value=raw_val,
                declared_unit=declared_unit,
            )

            if error:
                ambiguities.append(f"Field '{raw_key}': {error}")
                # Keep raw value under canonical name if plausible or drop
                normalized[canonical_name] = raw_val
                log.append(
                    ConversionLogEntry(
                        field_original=raw_key,
                        canonical_field=canonical_name,
                        original_value=raw_val,
                        original_unit=declared_unit,
                        canonical_value=raw_val,
                        canonical_unit="unconverted",
                        rule=f"FAILED: {error}",
                    )
                )
            else:
                normalized[canonical_name] = conv_val
                if raw_key != canonical_name or declared_unit is not None or rule != "identity":
                    canon_def = CANONICAL_METRICS.get(canonical_name)
                    target_unit = canon_def.unit if canon_def else ""
                    log.append(
                        ConversionLogEntry(
                            field_original=raw_key,
                            canonical_field=canonical_name,
                            original_value=raw_val,
                            original_unit=declared_unit or target_unit,
                            canonical_value=conv_val,
                            canonical_unit=target_unit,
                            rule=rule,
                        )
                    )

        # Standardize device status if present
        if "device_status" in normalized:
            status_val = str(normalized["device_status"]).lower()
            if status_val in ["healthy", "ok", "up", "normal"]:
                normalized["device_status"] = "up"
            elif status_val in ["warning", "degraded", "degrade"]:
                normalized["device_status"] = "degraded"
            elif status_val in ["critical", "down", "faulty", "fail", "failed"]:
                normalized["device_status"] = "down"

        # Check for missing expected metrics
        if expected_metrics:
            for exp in expected_metrics:
                if exp not in normalized:
                    missing_fields.append(exp)

        # Calculate completeness score
        completeness = self._calculate_completeness(
            ambiguities_count=len(ambiguities),
            missing_count=len(missing_fields),
        )

        return NormalizationResult(
            normalized_data=normalized,
            log=log,
            completeness=completeness,
            ambiguities=ambiguities,
            missing_fields=missing_fields,
        )

    def _resolve_field_name_and_unit(self, raw_key: str) -> Tuple[str, Optional[str]]:
        """Resolve a raw key to its canonical name and any unit implied by its suffix."""
        cleaned = raw_key.strip().lower()

        # Check direct alias
        if cleaned in ALIAS_MAP:
            return ALIAS_MAP[cleaned], None

        # Check suffixes for units
        unit_suffixes = [
            ("_seconds", "s"),
            ("_sec", "s"),
            ("_s", "s"),
            ("_ms", "ms"),
            ("_gbps", "Gbps"),
            ("_mbps", "Mbps"),
            ("_kbps", "kbps"),
            ("_bps", "bps"),
            ("_pct", "%"),
            ("_percent", "%"),
            ("_ratio", "fraction"),
            ("_fraction", "fraction"),
            ("_dbm", "dBm"),
            ("_db", "dB"),
        ]

        for sfx, unit in unit_suffixes:
            if cleaned.endswith(sfx):
                base_name = cleaned[: -len(sfx)]
                canonical_candidate = ALIAS_MAP.get(base_name, base_name)
                # If appending standard suffix matches canonical
                if is_canonical_metric(canonical_candidate):
                    return canonical_candidate, unit
                # Check metric map for base + unit
                for canon in CANONICAL_METRICS:
                    if canon.startswith(base_name) or base_name in canon:
                        return canon, unit
                return canonical_candidate, unit

        # Check if it is already canonical
        if is_canonical_metric(cleaned):
            return cleaned, None

        return cleaned, None

    def _convert_value_to_canonical(
        self,
        canonical_name: str,
        raw_value: Any,
        declared_unit: Optional[str],
    ) -> Tuple[Any, Optional[str], str, Optional[str]]:
        """Convert a raw value and declared unit into canonical unit and representation."""
        if raw_value is None:
            return None, declared_unit, "none_value", "Value is None"

        canon_def = CANONICAL_METRICS.get(canonical_name)

        # Handle string metrics / status
        if canonical_name == "device_status" or (canon_def and canon_def.data_type == "enum"):
            return str(raw_value).lower(), "enum", "enum_normalization", None

        # Try to parse string with embedded unit (e.g., "150ms", "1.5s", "10Gbps")
        num_val: Optional[float] = None
        extracted_unit: Optional[str] = declared_unit

        if isinstance(raw_value, str):
            match = UNIT_STRING_PATTERN.match(raw_value)
            if match:
                num_val = float(match.group(1))
                if match.group(2):
                    extracted_unit = match.group(2).strip()
            else:
                return raw_value, declared_unit, "unparseable_string", f"Could not parse numeric value from '{raw_value}'"
        elif isinstance(raw_value, (int, float)):
            num_val = float(raw_value)
        else:
            return raw_value, declared_unit, "invalid_type", f"Unsupported value type {type(raw_value).__name__}"

        target_unit = canon_def.unit if canon_def else ""
        norm_unit = (extracted_unit or "").strip().lower()

        # 1. Latency / Jitter / DNS time conversions (Canonical target: ms)
        if target_unit == "ms":
            if norm_unit in ["s", "sec", "second", "seconds"]:
                converted = num_val * 1000.0
                return converted, "ms", "unit_convert_s_to_ms", None
            if norm_unit in ["ms", "msec", ""]:
                return num_val, "ms", "identity", None
            if norm_unit in ["us", "µs"]:
                return num_val / 1000.0, "ms", "unit_convert_us_to_ms", None
            return num_val, norm_unit, "ambiguous_time_unit", f"Unrecognized time unit '{extracted_unit}'"

        # 2. Throughput / Bandwidth conversions (Canonical target: Mbps)
        if target_unit == "Mbps":
            if norm_unit in ["bps", "bits/s", "b/s"]:
                return num_val / 1_000_000.0, "Mbps", "unit_convert_bps_to_mbps", None
            if norm_unit in ["kbps", "kbit/s", "kbits/s", "kb/s"]:
                return num_val / 1_000.0, "Mbps", "unit_convert_kbps_to_mbps", None
            if norm_unit in ["mbps", "mbit/s", "mb/s", ""]:
                return num_val, "Mbps", "identity", None
            if norm_unit in ["gbps", "gbit/s", "gb/s"]:
                return num_val * 1_000.0, "Mbps", "unit_convert_gbps_to_mbps", None
            return num_val, norm_unit, "ambiguous_bandwidth_unit", f"Unrecognized throughput unit '{extracted_unit}'"

        # 3. Percentages (Canonical target: %)
        if target_unit == "%":
            if norm_unit in ["fraction", "ratio"] or (norm_unit == "" and 0.0 <= num_val <= 1.0 and "fraction" in canonical_name):
                return num_val * 100.0, "%", "unit_convert_fraction_to_percent", None
            if norm_unit in ["%", "pct", "percent", ""]:
                # If explicit fraction unit was provided:
                if norm_unit in ["fraction", "ratio"]:
                    return num_val * 100.0, "%", "unit_convert_fraction_to_percent", None
                return num_val, "%", "identity", None
            return num_val, norm_unit, "ambiguous_percent_unit", f"Unrecognized percentage unit '{extracted_unit}'"

        # 4. Integer Counts (queue_drops, interface_errors, dhcp_failures)
        if canon_def and canon_def.data_type == "int":
            return int(round(num_val)), canon_def.unit, "cast_int", None

        # 5. Signal units (dBm, dB)
        if target_unit in ["dBm", "dB"]:
            return num_val, target_unit, "identity", None

        return num_val, extracted_unit or target_unit, "identity", None

    def _calculate_completeness(self, ambiguities_count: int, missing_count: int) -> float:
        """Compute penalized completeness score between 0.0 and 1.0."""
        score = 1.0 - (ambiguities_count * self.unconvertible_penalty) - (missing_count * self.missing_metric_penalty)
        return max(0.0, min(1.0, round(score, 3)))
