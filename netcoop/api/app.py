"""NetCoop AI HTTP API (FastAPI).

Same-origin API under /api. If a frontend/ folder exists it is served at "/" (mounted
after the API routes so it never shadows them); if not, the API starts fine on its own.

Every error is JSON {"error": code, "detail": text}; no endpoint returns a traceback.
"""

import json
import logging
import tempfile
from pathlib import Path
from typing import Any, Dict, List, Optional, Union

from fastapi import FastAPI, Request
from fastapi import Path as PathParam
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse, PlainTextResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, ConfigDict, Field, ValidationError, model_validator
from starlette.exceptions import HTTPException as StarletteHTTPException

from netcoop import __version__
from netcoop.cli import (
    INCIDENT_ID_PATTERN,
    describe_invalid_input,
    find_data_file,
    get_scenario,
    get_scenarios,
    list_incident_summaries,
    load_incident_state,
    load_topology,
    log_dir,
    report_from_state,
    run_benchmark,
    scenario_kind,
    trace_entries,
)
from netcoop.data.topology import CampusTopology
from netcoop.orchestrator import run_diagnosis
from netcoop.reporting.markdown_report import render_markdown
from netcoop.reporting.report_models import FinalReport

logger = logging.getLogger(__name__)

MAX_UPLOAD_BYTES = 5 * 1024 * 1024  # 5 MB

_STATUS_CODES = {
    400: "bad_request",
    404: "not_found",
    405: "method_not_allowed",
    413: "payload_too_large",
    422: "validation_error",
}


# ---------------------------------------------------------------------------
# Models
# ---------------------------------------------------------------------------


class ApiError(Exception):
    """Raised by handlers/helpers to produce a JSON error with a specific code."""

    def __init__(self, status_code: int, error: str, detail: str):
        super().__init__(detail)
        self.status_code = status_code
        self.error = error
        self.detail = detail


class HealthResponse(BaseModel):
    status: str
    version: str


class ScenarioInfo(BaseModel):
    name: str
    description: str
    expected_cause: Optional[str] = None
    kind: str


class ScenarioTelemetry(BaseModel):
    scenario: str
    valid_json: bool
    records: Optional[List[Any]] = None
    raw: Optional[str] = None


class TraceEntry(BaseModel):
    index: int
    timestamp: Optional[str] = None
    sender: str
    recipient: str
    message_type: str
    summary: str
    payload: Any = None


class ErrorInfo(BaseModel):
    code: str
    detail: str
    line: Optional[int] = None
    column: Optional[int] = None


class DiagnoseRequest(BaseModel):
    """Body of POST /api/diagnose: exactly one of `scenario` or `telemetry`."""

    model_config = ConfigDict(extra="forbid")

    scenario: Optional[str] = Field(default=None, description="Name of a built-in scenario.")
    telemetry: Optional[Union[Dict[str, Any], List[Any], str]] = Field(
        default=None, description="Telemetry as a JSON object/array, or as raw JSON text."
    )
    topology: Optional[Dict[str, Any]] = Field(default=None, description="Optional node-link topology.")

    @model_validator(mode="after")
    def _exactly_one_source(self) -> "DiagnoseRequest":
        if (self.scenario is None) == (self.telemetry is None):
            raise ValueError("provide exactly one of 'scenario' or 'telemetry'")
        return self


class DiagnoseResponse(BaseModel):
    report: FinalReport
    trace: List[TraceEntry]
    markdown: str
    error: Optional[ErrorInfo] = None


class IncidentSummary(BaseModel):
    incident_id: str
    status: str
    suspected_root_cause: Optional[str] = None
    root_cause_code: Optional[str] = None
    confidence: Optional[float] = None
    confidence_category: Optional[str] = None
    last_stage: Optional[str] = None
    updated_at: Optional[str] = None


class BenchmarkRow(BaseModel):
    scenario: str
    description: str
    expected: str
    predicted: str
    status: str
    confidence: float
    confidence_category: str
    passed: bool
    incident_id: str


class BenchmarkResponse(BaseModel):
    accuracy: float
    total: int
    passed: int
    results: List[BenchmarkRow]


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

_DIAGNOSE_BODY_SCHEMA = DiagnoseRequest.model_json_schema()


async def _read_limited_body(request: Request) -> bytes:
    """Read the request body, enforcing MAX_UPLOAD_BYTES on the bytes actually received."""
    declared = request.headers.get("content-length")
    if declared and declared.isdigit() and int(declared) > MAX_UPLOAD_BYTES:
        raise ApiError(413, "payload_too_large", f"Request body exceeds the {MAX_UPLOAD_BYTES // (1024 * 1024)} MB limit.")
    chunks: List[bytes] = []
    size = 0
    async for chunk in request.stream():
        size += len(chunk)
        if size > MAX_UPLOAD_BYTES:
            raise ApiError(413, "payload_too_large", f"Request body exceeds the {MAX_UPLOAD_BYTES // (1024 * 1024)} MB limit.")
        chunks.append(chunk)
    return b"".join(chunks)


async def _parse_diagnose_request(request: Request) -> DiagnoseRequest:
    raw = await _read_limited_body(request)
    if not raw.strip():
        raise ApiError(400, "empty_body", "Request body is empty; send JSON with 'scenario' or 'telemetry'.")
    try:
        data = json.loads(raw.decode("utf-8"))
    except UnicodeDecodeError:
        raise ApiError(400, "invalid_encoding", "Request body must be UTF-8 encoded JSON.")
    except json.JSONDecodeError as ex:
        raise ApiError(400, "invalid_json", f"Request body is not valid JSON: {ex.msg} at line {ex.lineno} column {ex.colno}.")
    try:
        return DiagnoseRequest.model_validate(data)
    except ValidationError as ex:
        raise ApiError(422, "validation_error", _format_pydantic_errors(ex.errors()))


def _format_pydantic_errors(errors: List[Dict[str, Any]]) -> str:
    parts = []
    for e in errors:
        loc = ".".join(str(p) for p in e.get("loc", ()) if p != "body")
        msg = str(e.get("msg", "invalid value")).removeprefix("Value error, ")
        parts.append(f"{loc}: {msg}" if loc else msg)
    return "; ".join(parts) or "Invalid request."


def _topology_from_dict(data: Dict[str, Any]) -> CampusTopology:
    nodes, edges = data.get("nodes"), data.get("edges", [])
    if not isinstance(nodes, list) or not nodes or not isinstance(edges, list):
        raise ApiError(422, "invalid_topology", "Topology must contain a non-empty 'nodes' list and an 'edges' list.")
    try:
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "topology.json"
            path.write_text(json.dumps(data), encoding="utf-8")
            return CampusTopology.load_from_json(path)
    except Exception as ex:
        raise ApiError(422, "invalid_topology", f"Could not build topology: {ex}")


def _as_pipeline_source(value: Any) -> Any:
    """Make raw text safe for the pipeline.

    ingest() treats a string that has no newline and does not start with '{' or '[' as a
    FILE PATH. Uploaded text must never be interpreted as a server path, so in exactly that
    case a newline is appended: the text is then parsed as JSON text instead. Everything
    else is passed through untouched, so line/column numbers in syntax errors stay exact.
    """
    if isinstance(value, str) and "\n" not in value and not value.strip().startswith(("{", "[")):
        return value + "\n"
    return value


def _topology_document() -> Dict[str, Any]:
    for rel in (("data", "topology.json"), ("data", "samples", "topology.json")):
        found = find_data_file(*rel)
        if found:
            try:
                return json.loads(found.read_text(encoding="utf-8"))
            except Exception:
                logger.warning("Could not read topology file %s", found)
    return load_topology().to_dict()


def _require_report(incident_id: str) -> FinalReport:
    state = load_incident_state(incident_id)
    if not state:
        raise ApiError(404, "incident_not_found", f"No incident '{incident_id}' was found.")
    report = report_from_state(state)
    if report is None:
        raise ApiError(
            404, "report_not_available",
            f"Incident '{incident_id}' stopped at stage '{state.get('last_stage')}' and has no final report.",
        )
    return report


# ---------------------------------------------------------------------------
# Application factory
# ---------------------------------------------------------------------------


def create_app(frontend_dir: Optional[Union[str, Path]] = None) -> FastAPI:
    api = FastAPI(
        title="NetCoop AI API",
        version=__version__,
        description="Multi-agent campus network fault diagnosis. Same-origin JSON API.",
    )

    # ----- error handlers: always JSON {"error", "detail"} -----

    def _err(status: int, error: str, detail: str) -> JSONResponse:
        return JSONResponse(status_code=status, content={"error": error, "detail": detail})

    @api.exception_handler(ApiError)
    async def _api_error(_request: Request, exc: ApiError) -> JSONResponse:
        return _err(exc.status_code, exc.error, exc.detail)

    @api.exception_handler(RequestValidationError)
    async def _validation_error(_request: Request, exc: RequestValidationError) -> JSONResponse:
        return _err(422, "validation_error", _format_pydantic_errors(exc.errors()))

    @api.exception_handler(StarletteHTTPException)
    async def _http_error(_request: Request, exc: StarletteHTTPException) -> JSONResponse:
        code = _STATUS_CODES.get(exc.status_code, f"http_{exc.status_code}")
        return _err(exc.status_code, code, str(exc.detail))

    @api.exception_handler(Exception)
    async def _unexpected(_request: Request, exc: Exception) -> JSONResponse:
        logger.exception("Unhandled error in API request", exc_info=exc)
        return _err(500, "internal_error", "Unexpected server error. See server log for details.")

    # ----- endpoints -----

    @api.get("/api/health", response_model=HealthResponse)
    async def health() -> HealthResponse:
        return HealthResponse(status="ok", version=__version__)

    @api.get("/api/scenarios", response_model=List[ScenarioInfo])
    async def scenarios() -> List[ScenarioInfo]:
        return [
            ScenarioInfo(
                name=s.name,
                description=s.description,
                expected_cause=s.expected_root_cause.value if s.expected_root_cause else None,
                kind=scenario_kind(s.name),
            )
            for s in get_scenarios()
        ]

    @api.get("/api/scenarios/{name}/telemetry", response_model=ScenarioTelemetry)
    async def scenario_telemetry(name: str) -> ScenarioTelemetry:
        sc = get_scenario(name)
        if sc is None:
            raise ApiError(404, "scenario_not_found", f"Unknown scenario '{name}'.")
        if isinstance(sc.records, str):
            return ScenarioTelemetry(scenario=sc.name, valid_json=False, records=None, raw=sc.records)
        records = sc.records if isinstance(sc.records, list) else [sc.records]
        return ScenarioTelemetry(scenario=sc.name, valid_json=True, records=records, raw=None)

    @api.get("/api/topology")
    async def topology() -> Dict[str, Any]:
        return _topology_document()

    @api.post(
        "/api/diagnose",
        response_model=DiagnoseResponse,
        openapi_extra={
            "requestBody": {"required": True, "content": {"application/json": {"schema": _DIAGNOSE_BODY_SCHEMA}}}
        },
    )
    async def diagnose(request: Request) -> DiagnoseResponse:
        body = await _parse_diagnose_request(request)
        topo = _topology_from_dict(body.topology) if body.topology else load_topology()

        if body.scenario is not None:
            sc = get_scenario(body.scenario)
            if sc is None:
                raise ApiError(404, "scenario_not_found", f"Unknown scenario '{body.scenario}'.")
            source: Any = _as_pipeline_source(sc.records)
        else:
            source = _as_pipeline_source(body.telemetry)

        report = await run_diagnosis(source, topology=topo)
        return DiagnoseResponse(
            report=report,
            trace=[TraceEntry(**e) for e in trace_entries(report.incident_id)],
            markdown=render_markdown(report),
            error=describe_invalid_input(report, source, topo),
        )

    @api.get("/api/incidents", response_model=List[IncidentSummary])
    async def incidents() -> List[IncidentSummary]:
        return [IncidentSummary(**s) for s in list_incident_summaries()]

    @api.get("/api/incidents/{incident_id}/trace", response_model=List[TraceEntry])
    async def incident_trace(incident_id: str = PathParam(..., pattern=INCIDENT_ID_PATTERN)) -> List[TraceEntry]:
        if load_incident_state(incident_id) is None and not (log_dir() / f"messages_{incident_id}.jsonl").exists():
            raise ApiError(404, "incident_not_found", f"No incident '{incident_id}' was found.")
        return [TraceEntry(**e) for e in trace_entries(incident_id)]

    @api.get("/api/incidents/{incident_id}/report.json", response_model=FinalReport)
    async def incident_report_json(incident_id: str = PathParam(..., pattern=INCIDENT_ID_PATTERN)) -> FinalReport:
        return _require_report(incident_id)

    @api.get("/api/incidents/{incident_id}/report.md", response_class=PlainTextResponse)
    async def incident_report_md(incident_id: str = PathParam(..., pattern=INCIDENT_ID_PATTERN)) -> PlainTextResponse:
        return PlainTextResponse(render_markdown(_require_report(incident_id)), media_type="text/markdown; charset=utf-8")

    @api.post("/api/benchmark", response_model=BenchmarkResponse)
    async def benchmark() -> BenchmarkResponse:
        return BenchmarkResponse(**(await run_benchmark()))

    # ----- frontend: mounted LAST so it never shadows /api or /docs -----

    front = Path(frontend_dir) if frontend_dir else find_data_file("frontend")
    if front is not None and Path(front).is_dir():
        api.mount("/", StaticFiles(directory=str(front), html=True), name="frontend")

    return api


app = create_app()
