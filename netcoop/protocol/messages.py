"""NetCoop AI Protocol - Versioned Message Envelopes and Typed Payloads."""

from datetime import datetime, timezone
from enum import Enum
import json
from typing import Any, Dict, List, Optional, Union
import uuid

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from netcoop.protocol.causes import CauseCode


class MessageType(str, Enum):
    """Supported protocol message types."""

    TASK_REQUEST = "task_request"
    FINDING = "finding"
    EVIDENCE_QUERY = "evidence_query"
    EVIDENCE_RESPONSE = "evidence_response"
    CONFLICT_NOTICE = "conflict_notice"
    ERROR = "error"
    FINAL_RESULT = "final_result"


# -------------------------------------------------------------------------
# Sub-models for Payloads
# -------------------------------------------------------------------------


class MetricEvidence(BaseModel):
    """A supporting or contradicting metric observation."""

    model_config = ConfigDict(extra="ignore")

    metric: str
    value: Union[float, int, str]
    unit: str
    baseline: Optional[Union[float, int, str]] = None
    interpretation: str


class HypothesisCandidate(BaseModel):
    """A root cause hypothesis candidate evaluated by an agent."""

    model_config = ConfigDict(extra="ignore")

    cause_code: CauseCode
    score: float = Field(ge=0.0, le=1.0, description="Hypothesis probability/score (0.0 to 1.0)")
    supporting_metrics: List[MetricEvidence] = Field(default_factory=list)
    contradicting_metrics: List[MetricEvidence] = Field(default_factory=list)


class FindingScope(BaseModel):
    """Geographical/topological scope of a finding."""

    model_config = ConfigDict(extra="ignore")

    device_ids: List[str] = Field(default_factory=list)
    segment: Optional[str] = None


class DataQuality(BaseModel):
    """Data quality and completeness assessment for a finding."""

    model_config = ConfigDict(extra="ignore")

    completeness: float = Field(ge=0.0, le=1.0, description="Completeness score (0.0 to 1.0)")
    stale_fields: List[str] = Field(default_factory=list)
    missing_fields: List[str] = Field(default_factory=list)
    assumptions: List[str] = Field(default_factory=list)


# -------------------------------------------------------------------------
# Typed Payload Models
# -------------------------------------------------------------------------


class TaskRequestPayload(BaseModel):
    """Payload requesting an agent to execute an investigation task."""

    model_config = ConfigDict(extra="ignore")

    task_id: str
    target_device_ids: List[str] = Field(default_factory=list)
    target_segment: Optional[str] = None
    window_start: Optional[datetime] = None
    window_end: Optional[datetime] = None
    parameters: Dict[str, Any] = Field(default_factory=dict)


class FindingPayload(BaseModel):
    """Payload carrying an agent's diagnosis findings and hypotheses."""

    model_config = ConfigDict(extra="ignore")

    agent: str
    scope: FindingScope
    hypothesis_candidates: List[HypothesisCandidate] = Field(default_factory=list)
    data_quality: DataQuality
    confidence: float = Field(ge=0.0, le=1.0, description="Overall confidence (0.0 to 1.0)")


class EvidenceQueryPayload(BaseModel):
    """Payload querying raw telemetry or observations from peers."""

    model_config = ConfigDict(extra="ignore")

    query_id: str
    requested_by: str
    device_ids: List[str] = Field(default_factory=list)
    metrics: List[str] = Field(default_factory=list)
    start_time: Optional[datetime] = None
    end_time: Optional[datetime] = None
    filter_criteria: Dict[str, Any] = Field(default_factory=dict)


class EvidenceResponsePayload(BaseModel):
    """Payload delivering queried evidence/telemetry records."""

    model_config = ConfigDict(extra="ignore")

    query_id: str
    device_telemetry: List[Dict[str, Any]] = Field(default_factory=list)
    matched_records_count: int = 0
    data_truncated: bool = False


class ConflictNoticePayload(BaseModel):
    """Payload alerting peers/orchestrator of competing diagnoses."""

    model_config = ConfigDict(extra="ignore")

    conflict_id: str
    conflicting_hypotheses: List[Dict[str, Any]] = Field(default_factory=list)
    contending_agents: List[str] = Field(default_factory=list)
    disputed_metrics: List[str] = Field(default_factory=list)
    resolution_strategy: Optional[str] = None


class ErrorPayload(BaseModel):
    """Payload communicating execution or validation failures."""

    model_config = ConfigDict(extra="ignore")

    error_code: str
    error_message: str
    details: Dict[str, Any] = Field(default_factory=dict)
    retryable: bool = False


class FinalResultPayload(BaseModel):
    """Payload publishing the consensus root cause and remediation."""

    model_config = ConfigDict(extra="ignore")

    incident_id: str
    primary_root_cause: CauseCode
    confidence: float = Field(ge=0.0, le=1.0)
    affected_devices: List[str] = Field(default_factory=list)
    affected_segment: Optional[str] = None
    remediation_recommendations: List[str] = Field(default_factory=list)
    summary: str
    contributing_findings: List[FindingPayload] = Field(default_factory=list)


PAYLOAD_MAP: Dict[MessageType, type[BaseModel]] = {
    MessageType.TASK_REQUEST: TaskRequestPayload,
    MessageType.FINDING: FindingPayload,
    MessageType.EVIDENCE_QUERY: EvidenceQueryPayload,
    MessageType.EVIDENCE_RESPONSE: EvidenceResponsePayload,
    MessageType.CONFLICT_NOTICE: ConflictNoticePayload,
    MessageType.ERROR: ErrorPayload,
    MessageType.FINAL_RESULT: FinalResultPayload,
}


# -------------------------------------------------------------------------
# Versioned Message Envelope
# -------------------------------------------------------------------------


class MessageEnvelope(BaseModel):
    """Canonical versioned communication envelope for NetCoop AI."""

    model_config = ConfigDict(extra="ignore")

    message_id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    incident_id: str = Field(pattern=r"^INC-[A-Za-z0-9_-]+$")
    schema_version: str = "1.0"
    timestamp: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    sender: str
    recipient: str  # agent name | "orchestrator" | "broadcast"
    message_type: MessageType
    correlation_id: Optional[str] = None
    payload: Union[
        TaskRequestPayload,
        FindingPayload,
        EvidenceQueryPayload,
        EvidenceResponsePayload,
        ConflictNoticePayload,
        ErrorPayload,
        FinalResultPayload,
        Dict[str, Any],
    ]

    @field_validator("recipient")
    @classmethod
    def validate_recipient(cls, v: str) -> str:
        cleaned = v.strip()
        if not cleaned:
            raise ValueError("Recipient cannot be empty")
        return cleaned

    @field_validator("schema_version")
    @classmethod
    def validate_schema_version(cls, v: str) -> str:
        if v not in ["1.0", "0.9"]:
            raise ValueError(f"Unsupported schema version: {v}. Must be '1.0' or '0.9'")
        return v

    def to_json(self, indent: Optional[int] = None) -> str:
        """Serialize envelope to ISO8601 UTC JSON."""
        return self.model_dump_json(indent=indent)

    def to_dict(self) -> Dict[str, Any]:
        """Convert envelope to dictionary representation."""
        return self.model_dump(mode="json")


def parse_message(raw: Union[str, Dict[str, Any]]) -> MessageEnvelope:
    """Parse raw JSON string or dictionary into a typed MessageEnvelope.

    Polymorphically binds the typed payload according to message_type.
    """
    if isinstance(raw, str):
        data = json.loads(raw)
    elif isinstance(raw, dict):
        data = dict(raw)
    else:
        raise TypeError(f"Expected str or dict, got {type(raw).__name__}")

    msg_type_str = data.get("message_type")
    if not msg_type_str:
        raise ValueError("Missing message_type field in envelope")

    try:
        msg_type = MessageType(msg_type_str)
    except ValueError as e:
        raise ValueError(f"Unknown message_type '{msg_type_str}'") from e

    payload_data = data.get("payload", {})
    payload_cls = PAYLOAD_MAP.get(msg_type)
    if payload_cls and isinstance(payload_data, dict):
        data["payload"] = payload_cls.model_validate(payload_data)

    return MessageEnvelope.model_validate(data)
