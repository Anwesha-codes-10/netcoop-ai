"""Tests for netcoop.api.app using FastAPI's TestClient (sync tests only)."""

import json
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

import netcoop.api.app as api_module
from netcoop.api.app import MAX_UPLOAD_BYTES, create_app

SAMPLES = Path(__file__).resolve().parent.parent / "data" / "samples"
EXPECTED_PATHS = {
    "/api/health",
    "/api/scenarios",
    "/api/scenarios/{name}/telemetry",
    "/api/topology",
    "/api/diagnose",
    "/api/incidents",
    "/api/incidents/{incident_id}/trace",
    "/api/incidents/{incident_id}/report.json",
    "/api/incidents/{incident_id}/report.md",
    "/api/benchmark",
}


@pytest.fixture
def client(tmp_path, monkeypatch):
    """Isolated cwd (so logs/ is per-test) and an app without a frontend mount."""
    monkeypatch.chdir(tmp_path)
    return TestClient(create_app(frontend_dir=tmp_path / "no_frontend"))


def _sample_text(name: str) -> str:
    return (SAMPLES / f"{name}.json").read_bytes().decode("utf-8")


def _assert_error(resp, status: int, code: str):
    assert resp.status_code == status, resp.text
    body = resp.json()
    assert set(body.keys()) == {"error", "detail"}
    assert body["error"] == code
    assert isinstance(body["detail"], str) and body["detail"]
    assert "Traceback" not in resp.text
    return body


# ----- basic endpoints -----


def test_health(client):
    resp = client.get("/api/health")
    assert resp.status_code == 200
    assert resp.json() == {"status": "ok", "version": "0.1.0"}


def test_openapi_lists_every_endpoint(client):
    paths = set(client.get("/openapi.json").json()["paths"].keys())
    assert EXPECTED_PATHS <= paths
    assert client.get("/docs").status_code == 200


def test_scenarios_list(client):
    resp = client.get("/api/scenarios")
    assert resp.status_code == 200
    items = resp.json()
    assert len(items) == 14
    assert all(set(i.keys()) == {"name", "description", "expected_cause", "kind"} for i in items)
    by_name = {i["name"]: i for i in items}
    assert by_name["link_congestion"]["expected_cause"] == "LINK_CONGESTION"
    assert by_name["link_congestion"]["kind"] == "root_cause"
    assert by_name["legacy_schema_0_9"]["kind"] == "interoperability"
    assert by_name["corrupted_json"]["expected_cause"] is None


def test_scenario_telemetry(client):
    resp = client.get("/api/scenarios/link_congestion/telemetry")
    assert resp.status_code == 200
    body = resp.json()
    assert body["scenario"] == "link_congestion"
    assert body["valid_json"] is True and body["raw"] is None
    assert len(body["records"]) == 15
    assert {"device_id", "timestamp", "metrics"} <= set(body["records"][0].keys())


def test_scenario_telemetry_matches_shipped_sample_file(client):
    body = client.get("/api/scenarios/weak_wifi/telemetry").json()
    assert body["records"] == json.loads(_sample_text("weak_wifi"))


def test_scenario_telemetry_corrupted_returns_raw_text(client):
    body = client.get("/api/scenarios/corrupted_json/telemetry").json()
    assert body["valid_json"] is False
    assert body["records"] is None
    assert "MALFORMED_JSON_SYNTAX_ERROR" in body["raw"]


def test_scenario_telemetry_unknown_name(client):
    _assert_error(client.get("/api/scenarios/nope/telemetry"), 404, "scenario_not_found")


def test_topology(client):
    body = client.get("/api/topology").json()
    ids = {n["id"] for n in body["nodes"]}
    assert "DIST_SW_HOSTEL" in ids and "CORE_RTR_01" in ids
    assert body["edges"] and {"source", "target"} <= set(body["edges"][0].keys())


# ----- diagnose -----


def test_diagnose_scenario_shape(client):
    resp = client.post("/api/diagnose", json={"scenario": "link_congestion"})
    assert resp.status_code == 200
    body = resp.json()
    assert set(body.keys()) == {"report", "trace", "markdown", "error"}
    assert body["error"] is None
    assert body["report"]["status"] == "diagnosed"
    assert body["report"]["root_cause_code"] == "LINK_CONGESTION"
    assert body["markdown"].startswith(f"# Incident {body['report']['incident_id']} - Diagnosed")
    trace = body["trace"]
    assert len(trace) >= 8
    assert [t["index"] for t in trace] == list(range(len(trace)))
    assert set(trace[0].keys()) == {"index", "timestamp", "sender", "recipient", "message_type", "summary", "payload"}
    assert trace[0]["sender"] == "orchestrator" and trace[0]["recipient"] == "telemetry_agent"
    assert trace[0]["message_type"] == "task_request"
    assert trace[0]["summary"] == "orchestrator -> telemetry_agent | task_request | task=analyze"
    assert trace[-1]["sender"] == "reporting_agent"


def test_diagnose_telemetry_object(client):
    records = json.loads(_sample_text("dns_failure"))
    body = client.post("/api/diagnose", json={"telemetry": records}).json()
    assert body["report"]["root_cause_code"] == "DNS_FAILURE"


def test_diagnose_telemetry_as_text(client):
    body = client.post("/api/diagnose", json={"telemetry": _sample_text("weak_wifi")}).json()
    assert body["report"]["root_cause_code"] == "WEAK_WIFI_SIGNAL"
    assert body["error"] is None


def test_diagnose_with_topology_roundtrip(client):
    topo = client.get("/api/topology").json()
    body = client.post("/api/diagnose", json={"scenario": "interface_fault", "topology": topo}).json()
    assert body["report"]["root_cause_code"] == "INTERFACE_FAULT"


def test_diagnose_bad_topology(client):
    resp = client.post("/api/diagnose", json={"scenario": "normal", "topology": {"nodes": []}})
    _assert_error(resp, 422, "invalid_topology")


def test_diagnose_insufficient_evidence_is_a_normal_response(client):
    body = client.post("/api/diagnose", json={"scenario": "ambiguous_insufficient"}).json()
    assert body["report"]["status"] == "insufficient_evidence"
    assert body["error"] is None
    assert "No diagnosis is asserted." in body["markdown"]


def test_diagnose_corrupted_scenario_returns_invalid_input_report(client):
    resp = client.post("/api/diagnose", json={"scenario": "corrupted_json"})
    assert resp.status_code == 200
    body = resp.json()
    assert body["report"]["status"] == "invalid_input"
    assert body["error"]["code"] == "CORRUPTED_JSON"
    assert (body["error"]["line"], body["error"]["column"]) == (9, 3)
    assert body["trace"] == []
    assert "No diagnosis was produced" in body["markdown"]


def test_diagnose_corrupted_upload_text_reports_line_and_column(client):
    text = '{\n  "schema_version": "1.0",\n  "device_id": "DIST_SW_HOSTEL",\n  "metrics": {\n'
    resp = client.post("/api/diagnose", json={"telemetry": text})
    assert resp.status_code == 200
    body = resp.json()
    assert body["report"]["status"] == "invalid_input"
    assert body["error"]["code"] == "CORRUPTED_JSON"
    assert body["error"]["line"] == 5 and body["error"]["column"] is not None


def test_diagnose_unknown_schema_version(client):
    body = client.post("/api/diagnose", json={"scenario": "unknown_schema_version"}).json()
    assert body["report"]["status"] == "invalid_input"
    assert body["error"]["code"] == "UNKNOWN_SCHEMA_VERSION"
    assert body["error"]["line"] is None


def test_diagnose_never_treats_upload_text_as_a_server_path(client, tmp_path):
    (tmp_path / "secret.json").write_text(_sample_text("normal"), encoding="utf-8")
    resp = client.post("/api/diagnose", json={"telemetry": "secret.json"})
    assert resp.status_code == 200
    assert resp.json()["report"]["status"] == "invalid_input"


def test_diagnose_blank_text_is_invalid_input(client):
    body = client.post("/api/diagnose", json={"telemetry": "   "}).json()
    assert body["report"]["status"] == "invalid_input"
    assert body["error"]["code"] == "EMPTY_INPUT"


def test_diagnose_unknown_scenario(client):
    _assert_error(client.post("/api/diagnose", json={"scenario": "nope"}), 404, "scenario_not_found")


@pytest.mark.parametrize(
    "payload",
    [
        {},
        {"scenario": "normal", "telemetry": []},
        {"scenario": "normal", "unexpected": 1},
        {"scenario": 5},
        [1, 2, 3],
    ],
)
def test_diagnose_invalid_bodies_are_422(client, payload):
    _assert_error(client.post("/api/diagnose", json=payload), 422, "validation_error")


def test_diagnose_non_json_body_is_400(client):
    resp = client.post("/api/diagnose", content=b"this is not json", headers={"content-type": "application/json"})
    body = _assert_error(resp, 400, "invalid_json")
    assert "line 1 column 1" in body["detail"]


def test_diagnose_empty_body_is_400(client):
    _assert_error(client.post("/api/diagnose", content=b""), 400, "empty_body")


def test_diagnose_oversized_upload_is_413(client):
    big = b"x" * (MAX_UPLOAD_BYTES + 1)
    _assert_error(client.post("/api/diagnose", content=big), 413, "payload_too_large")


def test_diagnose_oversized_chunked_upload_without_content_length_is_413(client):
    def chunks():
        for _ in range(6):
            yield b"y" * (1024 * 1024)

    resp = client.post("/api/diagnose", content=chunks())
    _assert_error(resp, 413, "payload_too_large")


def test_diagnose_upload_under_limit_is_accepted(client):
    text = "{" + ("a" * (MAX_UPLOAD_BYTES - 1024 * 1024))
    resp = client.post("/api/diagnose", json={"telemetry": text})
    assert resp.status_code == 200
    assert resp.json()["report"]["status"] == "invalid_input"


# ----- incidents -----


def test_incidents_empty_then_listed(client):
    assert client.get("/api/incidents").json() == []
    inc = client.post("/api/diagnose", json={"scenario": "dhcp_failure"}).json()["report"]["incident_id"]
    items = client.get("/api/incidents").json()
    assert [i["incident_id"] for i in items] == [inc]
    assert items[0]["status"] == "diagnosed" and items[0]["root_cause_code"] == "DHCP_FAILURE"
    assert set(items[0].keys()) == {
        "incident_id", "status", "suspected_root_cause", "root_cause_code",
        "confidence", "confidence_category", "last_stage", "updated_at",
    }


def test_incident_trace_report_json_and_markdown(client):
    first = client.post("/api/diagnose", json={"scenario": "upstream_congestion"}).json()
    inc = first["report"]["incident_id"]

    trace = client.get(f"/api/incidents/{inc}/trace")
    assert trace.status_code == 200
    assert trace.json() == first["trace"]

    rep = client.get(f"/api/incidents/{inc}/report.json")
    assert rep.status_code == 200
    assert rep.json() == first["report"]

    md = client.get(f"/api/incidents/{inc}/report.md")
    assert md.status_code == 200
    assert md.headers["content-type"].startswith("text/markdown")
    assert md.text == first["markdown"]


def test_invalid_input_incident_is_retrievable(client):
    first = client.post("/api/diagnose", json={"scenario": "corrupted_json"}).json()
    inc = first["report"]["incident_id"]
    assert client.get(f"/api/incidents/{inc}/report.json").json()["status"] == "invalid_input"
    assert client.get(f"/api/incidents/{inc}/trace").json() == []
    assert "Invalid input" in client.get(f"/api/incidents/{inc}/report.md").text


def test_incident_not_found(client):
    for suffix in ("trace", "report.json", "report.md"):
        _assert_error(client.get(f"/api/incidents/INC-MISSING1/{suffix}"), 404, "incident_not_found")


def test_incident_id_format_is_validated(client):
    resp = client.get("/api/incidents/not-an-id/report.json")
    _assert_error(resp, 422, "validation_error")


def test_incident_without_final_report_is_404(client, tmp_path):
    logs = tmp_path / "logs"
    logs.mkdir()
    (logs / "state_INC-HALFWAY1.json").write_text(
        json.dumps({"incident_id": "INC-HALFWAY1", "last_stage": "analysed", "analysed": {}}), encoding="utf-8"
    )
    body = _assert_error(client.get("/api/incidents/INC-HALFWAY1/report.json"), 404, "report_not_available")
    assert "analysed" in body["detail"]


# ----- benchmark -----


def test_benchmark(client):
    resp = client.post("/api/benchmark")
    assert resp.status_code == 200
    body = resp.json()
    assert (body["total"], body["passed"], body["accuracy"]) == (14, 14, 1.0)
    assert len(body["results"]) == 14
    assert set(body["results"][0].keys()) == {
        "scenario", "description", "expected", "predicted", "status",
        "confidence", "confidence_category", "passed", "incident_id",
    }
    assert all(r["passed"] for r in body["results"])


# ----- errors and frontend -----


def test_unknown_route_and_wrong_method_are_json(client):
    _assert_error(client.get("/api/does-not-exist"), 404, "not_found")
    _assert_error(client.get("/api/diagnose"), 405, "method_not_allowed")
    _assert_error(client.post("/api/health"), 405, "method_not_allowed")


def test_unexpected_exception_returns_json_500(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)

    async def boom(*_a, **_k):
        raise RuntimeError("secret internal detail")

    monkeypatch.setattr(api_module, "run_diagnosis", boom)
    local = TestClient(create_app(frontend_dir=tmp_path / "none"), raise_server_exceptions=False)
    resp = local.post("/api/diagnose", json={"scenario": "normal"})
    _assert_error(resp, 500, "internal_error")
    assert "secret internal detail" not in resp.text


def test_no_cors_headers(client):
    resp = client.get("/api/health", headers={"Origin": "http://example.com"})
    assert "access-control-allow-origin" not in {k.lower() for k in resp.headers}


def test_frontend_is_served_without_shadowing_api(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    front = tmp_path / "frontend"
    front.mkdir()
    (front / "index.html").write_text("<html><body>NetCoop UI</body></html>", encoding="utf-8")
    c = TestClient(create_app(frontend_dir=front))
    assert "NetCoop UI" in c.get("/").text
    assert c.get("/api/health").json()["status"] == "ok"
    assert c.get("/docs").status_code == 200
    _assert_error(c.get("/api/does-not-exist"), 404, "not_found")


def test_api_starts_without_frontend(client):
    assert client.get("/").status_code == 404
    assert client.get("/api/health").status_code == 200
