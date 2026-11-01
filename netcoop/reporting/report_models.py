"""NetCoop AI Reporting Models.

Pydantic v2 schemas for ranked hypotheses, correlation results,
recommended actions, and executive incident reports.
"""

from typing import Any, Dict, List, Optional
from pydantic import BaseModel, ConfigDict, Field

from netcoop.protocol.causes import CauseCode


class RankedHypothesis(BaseModel):
    """Ranked root cause hypothesis evaluated during correlation."""

    model_config = ConfigDict(extra="ignore")

    cause_code: CauseCode
    score: float = Field(ge=0.0, le=1.0, description="Hypothesis probability/belief score (0.0 to 1.0)")
    supporting_agents: List[str] = Field(default_factory=list)
    supporting_evidence: List[Dict[str, Any]] = Field(default_factory=list)
    contradicting_evidence: List[Dict[str, Any]] = Field(default_factory=list)
    rules_applied: List[str] = Field(default_factory=list)


class CorrelationResult(BaseModel):
    """Aggregate multi-agent fault correlation outcome produced by FaultCorrelationAgent."""

    model_config = ConfigDict(extra="ignore")

    ranked_hypotheses: List[RankedHypothesis] = Field(default_factory=list)
    primary_cause_code: CauseCode
    confidence: float = Field(ge=0.0, le=1.0)
    confidence_category: str  # "high" | "medium" | "low" | "insufficient"
    status: str  # "diagnosed" | "insufficient_evidence"
    conflicts_resolved: List[Dict[str, Any]] = Field(default_factory=list)  # [{rule, description, effect}]
    missing_evidence: List[str] = Field(default_factory=list)
    affected_devices: List[str] = Field(default_factory=list)
    affected_segments: List[str] = Field(default_factory=list)
    agent_support: Dict[str, Any] = Field(default_factory=dict)
    query_rounds_used: int = 0
    confidence_breakdown: Dict[str, float] = Field(default_factory=dict)


class RecommendedAction(BaseModel):
    """Structured remediation action item for campus network engineering."""

    model_config = ConfigDict(extra="ignore")

    priority: int = 1
    action: str
    rationale: str
    requires_human_review: bool = True


class FinalReport(BaseModel):
    """Comprehensive executive and technical diagnosis report produced by RecommendationReportingAgent."""

    model_config = ConfigDict(extra="ignore")

    incident_id: str
    status: str  # "diagnosed" | "insufficient_evidence" | "partial" | "invalid_input"
    suspected_root_cause: str
    root_cause_code: CauseCode
    confidence: float = Field(ge=0.0, le=1.0)
    confidence_category: str  # "high" | "medium" | "low" | "insufficient"
    affected_devices: List[str] = Field(default_factory=list)
    affected_segments: List[str] = Field(default_factory=list)
    supporting_evidence: List[Dict[str, Any]] = Field(default_factory=list)
    alternative_causes: List[Dict[str, Any]] = Field(default_factory=list)
    recommended_actions: List[RecommendedAction] = Field(default_factory=list)
    evidence_sources: List[str] = Field(default_factory=list)
    limitations: List[str] = Field(default_factory=list)
    conflicts_resolved: List[Dict[str, Any]] = Field(default_factory=list)
    data_quality: Dict[str, Any] = Field(default_factory=dict)
    normalization_log: List[Dict[str, Any]] = Field(default_factory=list)
    agent_status: Dict[str, str] = Field(default_factory=dict)
    simulated_remediation_preview: Optional[str] = None
    message_trace_ref: Optional[str] = None

    def to_json(self, indent: Optional[int] = 2) -> str:
        """Serialize report to formatted JSON string."""
        return self.model_dump_json(indent=indent)

    @classmethod
    def from_json(cls, json_str: str) -> "FinalReport":
        """Deserialize JSON string into typed FinalReport instance."""
        return cls.model_validate_json(json_str)