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


class EvidenceAnswer(BaseModel):
    """Detailed query answer observation returned by an analysis agent."""

    model_config = ConfigDict(extra="ignore")

    device_id: str
    metric: str
    value: Union[float, int, str]
    unit: str
    baseline: Optional[Union[float, int, str]] = None
    interpretation: Optional[str] = None


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

    completeness: float = Field(default=1.0, ge=0.0, le=1.0, description="Completeness score (0.0 to 1.0)")
    stale_fields: List[str] = Field(default_factory=list)
    missing_fields: List[str] = Field(default_factory=list)
    assumptions: List[str] = Field(default_factory=list)


# -------------------------------------------------------------------------
# Typed Payload Models
# -------------------------------------------------------------------------


class TaskRequestPayload(BaseModel):
    """Payload requesting an agent to execute an investigation task."""

    model_config = ConfigDict(extra="ignore")

    task_id: Optional[str] = Field(default_factory=lambda: str(uuid.uuid4()))
    task: str = "analyze"  # "analyze" | "correlate" | "report"
    target_device_ids: List[str] = Field(default_factory=list)
    target_segment: Optional[str] = None
    window_start: Optional[datetime] = None
    window_end: Optional[datetime] = None
    parameters: Dict[str, Any] = Field(default_factory=dict)

    # Round 2 additions
    telemetry: Optional[Dict[str, List[Dict[str, Any]]]] = None
    topology: Optional[Dict[str, Any]] = None
    data_quality: Optional[Union[DataQuality, Dict[str, Any]]] = None
    findings: Optional[List[Union[Dict[str, Any], Any]]] = None
    agent_status: Optional[Dict[str, str]] = None
    evidence_responses: Optional[List[Union[Dict[str, Any], Any]]] = None
    round: int = 0
    correlation_result: Optional[Union[Dict[str, Any], Any]] = None
    normalization_log: Optional[List[Dict[str, Any]]] = None
    message_trace_ref: Optional[str] = None


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

    query_id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    requested_by: Optional[str] = None
    target_agent: Optional[str] = None
    question: Optional[str] = None
    cause_code: Optional[Union[CauseCode, str]] = None
    device_ids: List[str] = Field(default_factory=list)
    metrics: List[str] = Field(default_factory=list)
    start_time: Optional[datetime] = None
    end_time: Optional[datetime] = None
    filter_criteria: Dict[str, Any] = Field(default_factory=dict)


class EvidenceResponsePayload(BaseModel):
    """Payload delivering queried evidence/telemetry records."""

    model_config = ConfigDict(extra="ignore")

    query_id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    cause_code: Optional[Union[CauseCode, str]] = None
    supports: Optional[bool] = None
    confidence: Optional[float] = None
    answers: List[Union[EvidenceAnswer, Dict[str, Any]]] = Field(default_factory=list)
    notes: Optional[str] = None
    device_telemetry: List[Dict[str, Any]] = Field(default_factory=list)
    matched_records_count: int = 0
    data_truncated: bool = False


class ConflictNoticePayload(BaseModel):
    """Payload alerting peers/orchestrator of competing diagnoses."""

    model_config = ConfigDict(extra="ignore")

    conflict_id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    rule: Optional[str] = None
    description: Optional[str] = None
    agents_involved: List[str] = Field(default_factory=list)
    resolution: Optional[str] = None
    conflicting_hypotheses: List[Dict[str, Any]] = Field(default_factory=list)
    contending_agents: List[str] = Field(default_factory=list)
    disputed_metrics: List[str] = Field(default_factory=list)
    resolution_strategy: Optional[str] = None

    @model_validator(mode="after")
    def sync_conflict_fields(self):
        """Keep Round 1 and Round 2 naming conventions synchronized."""
        if not self.agents_involved and self.contending_agents:
            self.agents_involved = list(self.contending_agents)
        elif not self.contending_agents and self.agents_involved:
            self.contending_agents = list(self.agents_involved)
        if self.resolution and not self.resolution_strategy:
            self.resolution_strategy = self.resolution
        elif self.resolution_strategy and not self.resolution:
            self.resolution = self.resolution_strategy
        return self


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

    incident_id: Optional[str] = None
    primary_root_cause: Optional[CauseCode] = None
    confidence: float = Field(default=0.0, ge=0.0, le=1.0)
    affected_devices: List[str] = Field(default_factory=list)
    affected_segment: Optional[str] = None
    remediation_recommendations: List[str] = Field(default_factory=list)
    summary: Optional[str] = None
    contributing_findings: List[FindingPayload] = Field(default_factory=list)

    # Round 2 additions
    stage: Optional[str] = None  # "correlation" | "report"
    correlation_result: Optional[Union[Dict[str, Any], Any]] = None
    report: Optional[Union[Dict[str, Any], Any]] = None


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


Message = MessageEnvelope


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