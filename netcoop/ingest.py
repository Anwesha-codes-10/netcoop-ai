"""NetCoop AI Ingestion Pipeline.

Validates and normalizes raw telemetry files or dictionaries, producing structured IngestResult.
"""

from dataclasses import asdict, dataclass, field, is_dataclass
from pathlib import Path
from typing import Any, Dict, List, Optional, Set, Union
import uuid

from netcoop.config import load_config
from netcoop.data.topology import CampusTopology
from netcoop.protocol.messages import DataQuality
from netcoop.protocol.normalizer import TelemetryNormalizer
from netcoop.protocol.schema_registry import is_version_supported
from netcoop.protocol.validators import (
    ErrorCode,
    TelemetryValidator,
    ValidationIssue,
    ValidationResult,
)


@dataclass
class IngestResult:
    """Result of telemetry ingestion and normalization."""

    ok: bool
    partial: bool
    validation: Optional[ValidationResult]
    normalized_telemetry: Dict[str, List[Dict[str, Any]]]
    normalization_log: List[Dict[str, Any]]
    data_quality: DataQuality
    schema_version: str
    incident_id: str
    errors: List[str] = field(default_factory=list)


def ingest(
    path_or_dict: Union[str, Path, Dict[str, Any], List[Any]],
    topology: Optional[CampusTopology] = None,
    config: Optional[Dict[str, Any]] = None,
) -> IngestResult:
    """Ingest, validate, and normalize network telemetry.

    Args:
        path_or_dict: File path, JSON string, or Python dict/list.
        topology: Optional campus topology instance for device validation.
        config: Optional configuration dictionary.

    Returns:
        IngestResult with normalized telemetry indexed by device_id.
    """
    if config is None:
        config = load_config()

    incident_id = f"INC-{uuid.uuid4().hex[:8].upper()}"
    allowed_devices: Set[str] = set(topology.get_device_ids()) if topology else set()
    validator = TelemetryValidator(allowed_topology_devices=allowed_devices)
    normalizer = TelemetryNormalizer()

    # 1. Parse input source
    raw_data: Any = None
    if isinstance(path_or_dict, (str, Path)):
        p = Path(path_or_dict)
        raw_text: str = ""
        is_likely_path = False
        try:
            if "\n" not in str(path_or_dict) and not str(path_or_dict).strip().startswith(("{", "[")):
                is_likely_path = True
        except Exception:
            pass

        if is_likely_path:
            if not p.exists() or not p.is_file():
                err_issue = ValidationIssue(
                    code=ErrorCode.ERR_EMPTY_INPUT,
                    message=f"Telemetry file not found: {path_or_dict}",
                )
                return IngestResult(
                    ok=False,
                    partial=False,
                    validation=ValidationResult(ok=False, errors=[err_issue], completeness=0.0),
                    normalized_telemetry={},
                    normalization_log=[],
                    data_quality=DataQuality(completeness=0.0, missing_fields=[], stale_fields=[], assumptions=[]),
                    schema_version="unknown",
                    incident_id=incident_id,
                    errors=[f"File not found: {path_or_dict}"],
                )
            try:
                raw_text = p.read_text(encoding="utf-8")
            except Exception as e:
                err_issue = ValidationIssue(
                    code=ErrorCode.ERR_CORRUPTED_JSON,
                    message=f"Failed to read file: {e}",
                )
                return IngestResult(
                    ok=False,
                    partial=False,
                    validation=ValidationResult(ok=False, errors=[err_issue], completeness=0.0),
                    normalized_telemetry={},
                    normalization_log=[],
                    data_quality=DataQuality(completeness=0.0, missing_fields=[], stale_fields=[], assumptions=[]),
                    schema_version="unknown",
                    incident_id=incident_id,
                    errors=[str(e)],
                )
        else:
            raw_text = str(path_or_dict)

        parsed, json_res = validator.validate_json_string(raw_text)
        if not json_res.ok:
            return IngestResult(
                ok=False,
                partial=False,
                validation=json_res,
                normalized_telemetry={},
                normalization_log=[],
                data_quality=DataQuality(completeness=0.0, missing_fields=[], stale_fields=[], assumptions=[]),
                schema_version="unknown",
                incident_id=incident_id,
                errors=[e.message for e in json_res.errors],
            )
        raw_data = parsed
    elif isinstance(path_or_dict, (list, dict)):
        raw_data = path_or_dict
    else:
        err_issue = ValidationIssue(
            code=ErrorCode.ERR_WRONG_TYPE,
            message=f"Unsupported input type: {type(path_or_dict).__name__}",
        )
        return IngestResult(
            ok=False,
            partial=False,
            validation=ValidationResult(ok=False, errors=[err_issue], completeness=0.0),
            normalized_telemetry={},
            normalization_log=[],
            data_quality=DataQuality(completeness=0.0, missing_fields=[], stale_fields=[], assumptions=[]),
            schema_version="unknown",
            incident_id=incident_id,
            errors=[f"Unsupported input type: {type(path_or_dict).__name__}"],
        )

    # 2. Extract records list (handles flat lists, envelopes, and device_id -> records mappings)
    records: List[Dict[str, Any]] = []
    if isinstance(raw_data, list):
        records = [r for r in raw_data if isinstance(r, dict)]
    elif isinstance(raw_data, dict):
        for key in ["records", "telemetry", "device_telemetry", "data"]:
            if isinstance(raw_data.get(key), list):
                records = [r for r in raw_data[key] if isinstance(r, dict)]
                break
        if not records:
            is_device_map = any(isinstance(v, list) for v in raw_data.values())
            if is_device_map:
                for dev_k, v_list in raw_data.items():
                    if isinstance(v_list, list):
                        for item in v_list:
                            if isinstance(item, dict):
                                item_copy = dict(item)
                                if "device_id" not in item_copy and "dev" not in item_copy:
                                    item_copy["device_id"] = dev_k
                                records.append(item_copy)
                    elif isinstance(v_list, dict):
                        item_copy = dict(v_list)
                        if "device_id" not in item_copy and "dev" not in item_copy:
                            item_copy["device_id"] = dev_k
                        records.append(item_copy)
            else:
                records = [raw_data]

    if not records:
        err_issue = ValidationIssue(
            code=ErrorCode.ERR_EMPTY_INPUT,
            message="No telemetry records found in input",
        )
        return IngestResult(
            ok=False,
            partial=False,
            validation=ValidationResult(ok=False, errors=[err_issue], completeness=0.0),
            normalized_telemetry={},
            normalization_log=[],
            data_quality=DataQuality(completeness=0.0, missing_fields=[], stale_fields=[], assumptions=[]),
            schema_version="unknown",
            incident_id=incident_id,
            errors=["No telemetry records found in input"],
        )

    # 3. Detect & check schema version
    detected_schema = "1.0"
    for r in records:
        ver = r.get("schema_version")
        if ver is not None:
            detected_schema = str(ver).strip()
            if not is_version_supported(detected_schema):
                err_issue = ValidationIssue(
                    code=ErrorCode.ERR_UNKNOWN_SCHEMA_VERSION,
                    message=f"Unsupported schema version: '{detected_schema}'",
                    field="schema_version",
                )
                return IngestResult(
                    ok=False,
                    partial=False,
                    validation=ValidationResult(ok=False, errors=[err_issue], completeness=0.0),
                    normalized_telemetry={},
                    normalization_log=[],
                    data_quality=DataQuality(completeness=0.0, missing_fields=[], stale_fields=[], assumptions=[]),
                    schema_version=detected_schema,
                    incident_id=incident_id,
                    errors=[f"Unsupported schema version: '{detected_schema}'"],
                )
            break

    # 4. Normalize records
    normalized_by_device: Dict[str, List[Dict[str, Any]]] = {}
    normalization_log: List[Dict[str, Any]] = []
    total_completeness = 0.0
    missing_fields_set: Set[str] = set()
    stale_fields_set: Set[str] = set()
    has_missing_required = False

    for rec in records:
        dev = rec.get("device_id") or rec.get("dev") or rec.get("device")
        ts = rec.get("timestamp") or rec.get("time")

        if not dev:
            missing_fields_set.add("device_id")
            has_missing_required = True
        if not ts:
            missing_fields_set.add("timestamp")
            has_missing_required = True

        norm_res = normalizer.normalize_record(rec)
        for entry in norm_res.log:
            if is_dataclass(entry):
                normalization_log.append(asdict(entry))
            else:
                normalization_log.append(dict(entry.__dict__))

        norm_rec = norm_res.normalized_data
        dev_id = norm_rec.get("device_id") or (str(dev) if dev else None)
        if dev_id:
            norm_rec["device_id"] = str(dev_id).strip()
            d_id = norm_rec["device_id"]
            if d_id not in normalized_by_device:
                normalized_by_device[d_id] = []
            normalized_by_device[d_id].append(norm_rec)

        total_completeness += norm_res.completeness
        missing_fields_set.update(norm_res.missing_fields)
        stale_fields_set.update(norm_res.stale_fields)

    # 5. Assess completeness and partial status
    avg_completeness = round(total_completeness / len(records), 3) if records else 0.0
    if has_missing_required:
        avg_completeness = min(avg_completeness, 0.5)

    completeness_threshold = config.get("scoring", {}).get("caps", {}).get("completeness_threshold", 0.6)
    partial = False
    if avg_completeness < completeness_threshold or has_missing_required:
        partial = True

    all_normalized: List[Dict[str, Any]] = []
    for rec_list in normalized_by_device.values():
        all_normalized.extend(rec_list)

    batch_val = validator.validate_telemetry_batch(all_normalized) if all_normalized else None
    ok = len(normalized_by_device) > 0

    dq = DataQuality(
        completeness=avg_completeness,
        missing_fields=sorted(list(missing_fields_set)),
        stale_fields=sorted(list(stale_fields_set)),
        assumptions=[],
    )

    errors_list: List[str] = []
    if batch_val and not batch_val.ok:
        errors_list.extend([e.message for e in batch_val.errors])

    return IngestResult(
        ok=ok,
        partial=partial,
        validation=batch_val,
        normalized_telemetry=normalized_by_device,
        normalization_log=normalization_log,
        data_quality=dq,
        schema_version=detected_schema,
        incident_id=incident_id,
        errors=errors_list,
    )