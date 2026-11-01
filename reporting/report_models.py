class RankedHypothesis(BaseModel):
    cause_code: CauseCode
    score: float  # ge=0.0, le=1.0
    supporting_agents: List[str] = []
    supporting_evidence: List[Dict[str, Any]] = []
    contradicting_evidence: List[Dict[str, Any]] = []
    rules_applied: List[str] = []

class CorrelationResult(BaseModel):
    ranked_hypotheses: List[RankedHypothesis] = []
    primary_cause_code: CauseCode
    confidence: float  # ge=0.0, le=1.0
    confidence_category: str  # "high" | "medium" | "low" | "insufficient"
    status: str  # "diagnosed" | "insufficient_evidence"
    conflicts_resolved: List[Dict[str, Any]] = []  # [{rule, description, effect}]
    missing_evidence: List[str] = []
    affected_devices: List[str] = []
    affected_segments: List[str] = []
    agent_support: Dict[str, Any] = {}
    query_rounds_used: int = 0
    confidence_breakdown: Dict[str, float] = {}

class RecommendedAction(BaseModel):
    priority: int = 1
    action: str
    rationale: str
    requires_human_review: bool = True

class FinalReport(BaseModel):
    incident_id: str
    status: str  # "diagnosed" | "insufficient_evidence" | "partial" | "invalid_input"
    suspected_root_cause: str
    root_cause_code: CauseCode
    confidence: float  # ge=0.0, le=1.0
    confidence_category: str  # "high" | "medium" | "low" | "insufficient"
    affected_devices: List[str] = []
    affected_segments: List[str] = []
    supporting_evidence: List[Dict[str, Any]] = []
    alternative_causes: List[Dict[str, Any]] = []
    recommended_actions: List[RecommendedAction] = []
    evidence_sources: List[str] = []
    limitations: List[str] = []
    conflicts_resolved: List[Dict[str, Any]] = []
    data_quality: Dict[str, Any] = {}
    normalization_log: List[Dict[str, Any]] = []
    agent_status: Dict[str, str] = {}
    simulated_remediation_preview: Optional[str] = None
    message_trace_ref: Optional[str] = None

    def to_json(self, indent: Optional[int] = 2) -> str: ...
    @classmethod from_json(cls, json_str: str) -> "FinalReport": ...