"""NetCoop AI Protocol - Structured Telemetry & Envelope Validators.

Validates schemas, records, envelopes, and time series without raising raw tracebacks.
Returns structured ValidationResult {ok, errors[], warnings[], completeness}.
"""

from datetime import datetime, timezone
from enum import Enum
import json
import math
import re
from typing import Any, Dict, List, Optional, Set, Tuple, Union

from pydantic import BaseModel, ConfigDict, Field

from netcoop.protocol.causes import CANONICAL_METRICS, is_canonical_metric
from netcoop.protocol.schema_registry import is_version_supported


class ErrorCode(str, Enum):
    """Structured validator error codes."""

    # Canonical error codes
    CORRUPTED_JSON = "CORRUPTED_JSON"
    EMPTY_INPUT = "EMPTY_INPUT"
    MISSING_REQUIRED_FIELD = "MISSING_REQUIRED_FIELD"
    WRONG_TYPE = "WRONG_TYPE"
    OUT_OF_RANGE = "OUT_OF_RANGE"
    NAN_OR_NULL = "NAN_OR_NULL"
    TIMESTAMP_DUPLICATE = "TIMESTAMP_DUPLICATE"
    TIMESTAMP_OUT_OF_ORDER = "TIMESTAMP_OUT_OF_ORDER"
    STALE_DATA = "STALE_DATA"
    UNKNOWN_DEVICE_ID = "UNKNOWN_DEVICE_ID"
    UNKNOWN_SCHEMA_VERSION = "UNKNOWN_SCHEMA_VERSION"
    MIXED_UNITS = "MIXED_UNITS"

    # Aliases with ERR_ prefix for backward compatibility
    ERR_CORRUPTED_JSON = "CORRUPTED_JSON"
    ERR_EMPTY_INPUT = "EMPTY_INPUT"
    ERR_MISSING_REQUIRED_FIELD = "MISSING_REQUIRED_FIELD"
    ERR_WRONG_TYPE = "WRONG_TYPE"
    ERR_OUT_OF_RANGE = "OUT_OF_RANGE"
    ERR_NAN_OR_NULL = "NAN_OR_NULL"
    ERR_TIMESTAMP_DUPLICATE = "TIMESTAMP_DUPLICATE"
    ERR_TIMESTAMP_OUT_OF_ORDER = "TIMESTAMP_OUT_OF_ORDER"
    ERR_STALE_DATA = "STALE_DATA"
    ERR_UNKNOWN_DEVICE_ID = "UNKNOWN_DEVICE_ID"
    ERR_UNKNOWN_SCHEMA_VERSION = "UNKNOWN_SCHEMA_VERSION"
    ERR_MIXED_UNITS = "MIXED_UNITS"

    @classmethod
    def _missing_(cls, value: object):
        if isinstance(value, str):
            clean = value.replace("ERR_", "")
            for member in cls:
                if member.value == clean:
                    return member
        return None

    def __eq__(self, other: Any) -> bool:
        if super().__eq__(other):
            return True
        if isinstance(other, str):
            return self.value.replace("ERR_", "") == str(other).replace("ERR_", "")
        return False


class ValidationIssue(BaseModel):
    """Represents a single validation error or warning."""

    model_config = ConfigDict(extra="ignore")

    code: ErrorCode
    message: str
    field: Optional[str] = None
    device_id: Optional[str] = None
    timestamp: Optional[str] = None
    severity: str = "ERROR"  # "ERROR" or "WARNING"


class ValidationResult(BaseModel):
    """Encapsulates the complete result of a validation check."""

    model_config = ConfigDict(extra="ignore")

    ok: bool
    errors: List[ValidationIssue] = Field(default_factory=list)
    warnings: List[ValidationIssue] = Field(default_factory=list)
    completeness: float = 1.0
    device_count: int = 0
    record_count: int = 0


def parse_iso_timestamp(ts_str: Any) -> Optional[datetime]:
    """Safely parse ISO8601 timestamp string into timezone-aware datetime."""
    if not ts_str or not isinstance(ts_str, str):
        return None
    try:
        clean_ts = ts_str.replace("Z", "+00:00")
        dt = datetime.fromisoformat(clean_ts)
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        return dt
    except Exception:
        return None


class TelemetryValidator:
    """Structured non-crashing validator for NetCoop AI telemetry and envelopes."""

    def __init__(
        self,
        stale_window_seconds: int = 300,
        allowed_topology_devices: Optional[Set[str]] = None,
    ):
        self.stale_window_seconds = stale_window_seconds
        self.allowed_topology_devices = allowed_topology_devices or set()

    def validate_json_string(self, raw_json: str) -> Tuple[Optional[Any], ValidationResult]:
        """Safely parse a JSON string using strict stdlib json.loads only.

        Returns:
            Tuple[Optional[Any], ValidationResult]:
                - (parsed_obj, ValidationResult(ok=True, ...)) if valid with >= 1 record and >= 1 device.
                - (None, ValidationResult(ok=False, errors=[CORRUPTED_JSON], completeness=0.0)) on syntax error.
                - (parsed_or_None, ValidationResult(ok=False, errors=[EMPTY_INPUT], completeness=0.0)) if empty, whitespace, null, or zero records/devices.
        """
        # 1. Empty or whitespace check
        if raw_json is None or not isinstance(raw_json, str) or not raw_json.strip():
            issue = ValidationIssue(
                code=ErrorCode.EMPTY_INPUT,
                message="Input JSON string is empty or whitespace-only",
                severity="ERROR",
            )
            return None, ValidationResult(
                ok=False,
                errors=[issue],
                completeness=0.0,
                device_count=0,
                record_count=0,
            )

        # 2. Strict parse with standard library json.loads only
        try:
            parsed = json.loads(raw_json)
        except json.JSONDecodeError as err:
            issue = ValidationIssue(
                code=ErrorCode.CORRUPTED_JSON,
                message=f"Corrupted JSON syntax: {err.msg} at line {err.lineno} column {err.colno}",
                severity="ERROR",
            )
            return None, ValidationResult(
                ok=False,
                errors=[issue],
                completeness=0.0,
                device_count=0,
                record_count=0,
            )
        except Exception as ex:
            issue = ValidationIssue(
                code=ErrorCode.CORRUPTED_JSON,
                message=f"Failed to parse JSON: {str(ex)}",
                severity="ERROR",
            )
            return None, ValidationResult(
                ok=False,
                errors=[issue],
                completeness=0.0,
                device_count=0,
                record_count=0,
            )

        # 3. Check for zero records or zero devices on successful parse
        if parsed is None:
            issue = ValidationIssue(
                code=ErrorCode.EMPTY_INPUT,
                message="Parsed JSON is null (contains zero records or devices)",
                severity="ERROR",
            )
            return None, ValidationResult(
                ok=False,
                errors=[issue],
                completeness=0.0,
                device_count=0,
                record_count=0,
            )

        if isinstance(parsed, list):
            if len(parsed) == 0:
                issue = ValidationIssue(
                    code=ErrorCode.EMPTY_INPUT,
                    message="Parsed JSON array contains zero records",
                    severity="ERROR",
                )
                return parsed, ValidationResult(
                    ok=False,
                    errors=[issue],
                    completeness=0.0,
                    device_count=0,
                    record_count=0,
                )

            # Collect devices across list of records
            devices: Set[str] = set()
            for item in parsed:
                if isinstance(item, dict):
                    dev = item.get("device_id") or item.get("dev") or item.get("device")
                    if dev:
                        devices.add(str(dev).strip())

            device_count = len(devices)
            record_count = len(parsed)

            if record_count == 0 or device_count == 0:
                issue = ValidationIssue(
                    code=ErrorCode.EMPTY_INPUT,
                    message=f"Parsed JSON array contains {record_count} records but zero recognized devices",
                    severity="ERROR",
                )
                return parsed, ValidationResult(
                    ok=False,
                    errors=[issue],
                    completeness=0.0,
                    device_count=device_count,
                    record_count=record_count,
                )

            return parsed, ValidationResult(
                ok=True,
                completeness=1.0,
                device_count=device_count,
                record_count=record_count,
            )

        if isinstance(parsed, dict):
            if len(parsed) == 0:
                issue = ValidationIssue(
                    code=ErrorCode.EMPTY_INPUT,
                    message="Parsed JSON object is empty (contains zero records or devices)",
                    severity="ERROR",
                )
                return parsed, ValidationResult(
                    ok=False,
                    errors=[issue],
                    completeness=0.0,
                    device_count=0,
                    record_count=0,
                )

            # Collect devices from top-level or payload/nested lists
            devices = set()
            dev = parsed.get("device_id") or parsed.get("dev") or parsed.get("device")
            if dev:
                devices.add(str(dev).strip())

            for target_key in ["target_device_ids", "device_ids", "affected_devices"]:
                target_val = parsed.get(target_key)
                if isinstance(target_val, (list, set, tuple)):
                    for d in target_val:
                        if d:
                            devices.add(str(d).strip())

            if isinstance(parsed.get("payload"), dict):
                p = parsed["payload"]
                if p.get("device_id"):
                    devices.add(str(p["device_id"]).strip())
                for target_key in ["target_device_ids", "device_ids", "affected_devices"]:
                    target_val = p.get(target_key)
                    if isinstance(target_val, (list, set, tuple)):
                        for d in target_val:
                            if d:
                                devices.add(str(d).strip())
                if isinstance(p.get("scope"), dict) and isinstance(p["scope"].get("device_ids"), (list, set, tuple)):
                    for d in p["scope"]["device_ids"]:
                        if d:
                            devices.add(str(d).strip())

            # Check if dict wraps nested records
            nested_records = None
            for key in ["records", "telemetry", "device_telemetry", "data"]:
                if isinstance(parsed.get(key), list):
                    nested_records = parsed[key]
                    break

            if nested_records is not None:
                record_count = len(nested_records)
                for item in nested_records:
                    if isinstance(item, dict):
                        d = item.get("device_id") or item.get("dev") or item.get("device")
                        if d:
                            devices.add(str(d).strip())
            else:
                record_count = 1

            device_count = len(devices)

            if record_count == 0 or device_count == 0:
                issue = ValidationIssue(
                    code=ErrorCode.EMPTY_INPUT,
                    message=f"Parsed JSON object contains {record_count} records but zero recognized devices",
                    severity="ERROR",
                )
                return parsed, ValidationResult(
                    ok=False,
                    errors=[issue],
                    completeness=0.0,
                    device_count=device_count,
                    record_count=record_count,
                )

            return parsed, ValidationResult(
                ok=True,
                completeness=1.0,
                device_count=device_count,
                record_count=record_count,
            )

        # Other types (e.g. integer, boolean, string)
        issue = ValidationIssue(
            code=ErrorCode.EMPTY_INPUT,
            message=f"Parsed JSON primitive {type(parsed).__name__} contains zero records or devices",
            severity="ERROR",
        )
        return parsed, ValidationResult(
            ok=False,
            errors=[issue],
            completeness=0.0,
            device_count=0,
            record_count=0,
        )

    def validate_envelope(self, data: Dict[str, Any]) -> ValidationResult:
        """Validate protocol MessageEnvelope structure without crashing."""
        errors: List[ValidationIssue] = []
        warnings: List[ValidationIssue] = []

        if not isinstance(data, dict):
            errors.append(
                ValidationIssue(
                    code=ErrorCode.ERR_WRONG_TYPE,
                    message=f"Envelope must be a dict/object, got {type(data).__name__}",
                )
            )
            return ValidationResult(ok=False, errors=errors, completeness=0.0)

        # Check required fields
        required_fields = ["message_id", "incident_id", "schema_version", "timestamp", "sender", "recipient", "message_type", "payload"]
        for req in required_fields:
            if req not in data or data[req] is None:
                errors.append(
                    ValidationIssue(
                        code=ErrorCode.ERR_MISSING_REQUIRED_FIELD,
                        message=f"Missing required envelope field '{req}'",
                        field=req,
                    )
                )

        # Check schema version
        ver = data.get("schema_version")
        if ver is not None and not is_version_supported(ver):
            errors.append(
                ValidationIssue(
                    code=ErrorCode.ERR_UNKNOWN_SCHEMA_VERSION,
                    message=f"Unsupported schema version: '{ver}'",
                    field="schema_version",
                )
            )

        # Check incident_id pattern
        inc_id = data.get("incident_id")
        if inc_id and not re.match(r"^INC-[A-Za-z0-9_-]+$", str(inc_id)):
            errors.append(
                ValidationIssue(
                    code=ErrorCode.ERR_WRONG_TYPE,
                    message=f"incident_id must match format 'INC-xxxx', got '{inc_id}'",
                    field="incident_id",
                )
            )

        # Check timestamp
        ts = data.get("timestamp")
        if ts is not None and parse_iso_timestamp(ts) is None:
            errors.append(
                ValidationIssue(
                    code=ErrorCode.ERR_WRONG_TYPE,
                    message=f"Invalid ISO8601 timestamp in envelope: '{ts}'",
                    field="timestamp",
                )
            )

        ok = len(errors) == 0
        completeness = max(0.0, 1.0 - (len(errors) * 0.15))
        return ValidationResult(ok=ok, errors=errors, warnings=warnings, completeness=completeness)

    def validate_telemetry_batch(
        self,
        records: List[Dict[str, Any]],
        reference_time: Optional[datetime] = None,
    ) -> ValidationResult:
        """Validate a list of telemetry records for consistency, metrics, and timestamps."""
        errors: List[ValidationIssue] = []
        warnings: List[ValidationIssue] = []

        if not records:
            errors.append(
                ValidationIssue(
                    code=ErrorCode.ERR_EMPTY_INPUT,
                    message="Telemetry records list is empty",
                )
            )
            return ValidationResult(ok=False, errors=errors, completeness=0.0)

        devices_seen: Set[str] = set()
        timestamps_by_device: Dict[str, List[datetime]] = {}
        units_seen: Dict[str, Set[str]] = {}

        for idx, rec in enumerate(records):
            if not isinstance(rec, dict):
                errors.append(
                    ValidationIssue(
                        code=ErrorCode.ERR_WRONG_TYPE,
                        message=f"Record at index {idx} must be a dictionary, got {type(rec).__name__}",
                    )
                )
                continue

            # Validate schema version if declared
            schema_ver = rec.get("schema_version")
            if schema_ver is not None and not is_version_supported(schema_ver):
                errors.append(
                    ValidationIssue(
                        code=ErrorCode.ERR_UNKNOWN_SCHEMA_VERSION,
                        message=f"Record {idx} has unknown schema_version: '{schema_ver}'",
                        field="schema_version",
                    )
                )

            # Check required fields
            dev_id = rec.get("device_id")
            if not dev_id:
                errors.append(
                    ValidationIssue(
                        code=ErrorCode.ERR_MISSING_REQUIRED_FIELD,
                        message=f"Record at index {idx} missing required 'device_id'",
                        field="device_id",
                    )
                )
            else:
                dev_id_str = str(dev_id).strip()
                devices_seen.add(dev_id_str)
                # Check topology validity
                if self.allowed_topology_devices and dev_id_str not in self.allowed_topology_devices:
                    errors.append(
                        ValidationIssue(
                            code=ErrorCode.ERR_UNKNOWN_DEVICE_ID,
                            message=f"Device ID '{dev_id_str}' not found in campus topology",
                            field="device_id",
                            device_id=dev_id_str,
                        )
                    )

            # Check timestamp
            raw_ts = rec.get("timestamp")
            dt_ts: Optional[datetime] = None
            if not raw_ts:
                errors.append(
                    ValidationIssue(
                        code=ErrorCode.ERR_MISSING_REQUIRED_FIELD,
                        message=f"Record at index {idx} missing required 'timestamp'",
                        field="timestamp",
                        device_id=str(dev_id) if dev_id else None,
                    )
                )
            else:
                dt_ts = parse_iso_timestamp(raw_ts)
                if dt_ts is None:
                    errors.append(
                        ValidationIssue(
                            code=ErrorCode.ERR_WRONG_TYPE,
                            message=f"Record at index {idx} has unparseable ISO8601 timestamp: '{raw_ts}'",
                            field="timestamp",
                            device_id=str(dev_id) if dev_id else None,
                        )
                    )
                else:
                    # Check staleness against reference time
                    if reference_time:
                        ref_utc = reference_time if reference_time.tzinfo else reference_time.replace(tzinfo=timezone.utc)
                        delta_sec = (ref_utc - dt_ts).total_seconds()
                        if delta_sec > self.stale_window_seconds:
                            errors.append(
                                ValidationIssue(
                                    code=ErrorCode.ERR_STALE_DATA,
                                    message=f"Record timestamp {raw_ts} is stale by {int(delta_sec)}s (threshold: {self.stale_window_seconds}s)",
                                    field="timestamp",
                                    device_id=str(dev_id) if dev_id else None,
                                    timestamp=str(raw_ts),
                                )
                            )

                    # Track for order and duplicate checks
                    if dev_id:
                        dev_key = str(dev_id)
                        if dev_key not in timestamps_by_device:
                            timestamps_by_device[dev_key] = []
                        timestamps_by_device[dev_key].append(dt_ts)

            # Check unit declarations across records for mixed units
            rec_units = rec.get("units")
            if isinstance(rec_units, dict):
                for metric_k, unit_v in rec_units.items():
                    if metric_k not in units_seen:
                        units_seen[metric_k] = set()
                    units_seen[metric_k].add(str(unit_v).lower())

            # Validate metrics inside record
            metrics_dict = rec.get("metrics") if isinstance(rec.get("metrics"), dict) else rec
            for m_key, m_val in metrics_dict.items():
                if m_key in ["device_id", "timestamp", "status", "schema_version", "units", "metrics", "device_type"]:
                    continue

                # Check NaN / Null
                if m_val is None or (isinstance(m_val, float) and (math.isnan(m_val) or math.isinf(m_val))):
                    errors.append(
                        ValidationIssue(
                            code=ErrorCode.ERR_NAN_OR_NULL,
                            message=f"Metric '{m_key}' has NaN or null value",
                            field=m_key,
                            device_id=str(dev_id) if dev_id else None,
                            timestamp=str(raw_ts) if raw_ts else None,
                        )
                    )
                    continue

                # Check canonical bounds
                canon_def = CANONICAL_METRICS.get(m_key)
                if canon_def:
                    if canon_def.data_type in ["float", "int"]:
                        try:
                            f_val = float(m_val)
                            if canon_def.min_val is not None and f_val < canon_def.min_val:
                                errors.append(
                                    ValidationIssue(
                                        code=ErrorCode.ERR_OUT_OF_RANGE,
                                        message=f"Metric '{m_key}' value {f_val} below minimum {canon_def.min_val}",
                                        field=m_key,
                                        device_id=str(dev_id) if dev_id else None,
                                        timestamp=str(raw_ts) if raw_ts else None,
                                    )
                                )
                            elif canon_def.max_val is not None and f_val > canon_def.max_val:
                                errors.append(
                                    ValidationIssue(
                                        code=ErrorCode.ERR_OUT_OF_RANGE,
                                        message=f"Metric '{m_key}' value {f_val} exceeds maximum {canon_def.max_val}",
                                        field=m_key,
                                        device_id=str(dev_id) if dev_id else None,
                                        timestamp=str(raw_ts) if raw_ts else None,
                                    )
                                )
                        except (ValueError, TypeError):
                            errors.append(
                                ValidationIssue(
                                    code=ErrorCode.ERR_WRONG_TYPE,
                                    message=f"Metric '{m_key}' expects numeric value, got '{m_val}'",
                                    field=m_key,
                                    device_id=str(dev_id) if dev_id else None,
                                )
                            )
                    elif canon_def.data_type == "enum" and canon_def.allowed_values:
                        if str(m_val).lower() not in [v.lower() for v in canon_def.allowed_values]:
                            errors.append(
                                ValidationIssue(
                                    code=ErrorCode.ERR_OUT_OF_RANGE,
                                    message=f"Metric '{m_key}' value '{m_val}' not in allowed values: {canon_def.allowed_values}",
                                    field=m_key,
                                    device_id=str(dev_id) if dev_id else None,
                                )
                            )

        # Check duplicate and out-of-order timestamps per device
        for dev_name, ts_list in timestamps_by_device.items():
            seen_ts: Set[datetime] = set()
            for i, ts_val in enumerate(ts_list):
                if ts_val in seen_ts:
                    errors.append(
                        ValidationIssue(
                            code=ErrorCode.ERR_TIMESTAMP_DUPLICATE,
                            message=f"Duplicate timestamp {ts_val.isoformat()} for device '{dev_name}'",
                            field="timestamp",
                            device_id=dev_name,
                            timestamp=ts_val.isoformat(),
                        )
                    )
                seen_ts.add(ts_val)

                if i > 0 and ts_val < ts_list[i - 1]:
                    errors.append(
                        ValidationIssue(
                            code=ErrorCode.ERR_TIMESTAMP_OUT_OF_ORDER,
                            message=f"Out-of-order timestamp for device '{dev_name}': {ts_val.isoformat()} preceded by {ts_list[i-1].isoformat()}",
                            field="timestamp",
                            device_id=dev_name,
                            timestamp=ts_val.isoformat(),
                        )
                    )

        # Check for mixed units across the batch
        for metric_k, units in units_seen.items():
            if len(units) > 1:
                errors.append(
                    ValidationIssue(
                        code=ErrorCode.ERR_MIXED_UNITS,
                        message=f"Conflicting mixed units declared for metric '{metric_k}': {sorted(list(units))}",
                        field=metric_k,
                    )
                )

        ok = len(errors) == 0
        penalty_per_error = 0.08
        completeness = max(0.0, 1.0 - (len(errors) * penalty_per_error))
        return ValidationResult(
            ok=ok,
            errors=errors,
            warnings=warnings,
            completeness=round(completeness, 3),
            device_count=len(devices_seen),
            record_count=len(records),
        )