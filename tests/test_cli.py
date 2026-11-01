"""Tests for netcoop.cli using typer's CliRunner (every command)."""

import json
import re
from pathlib import Path

import pytest
from typer.testing import CliRunner

from netcoop import cli
from netcoop.cli import app

SAMPLES = Path(__file__).resolve().parent.parent / "data" / "samples"
runner = CliRunner()


@pytest.fixture(autouse=True)
def isolated_cwd(tmp_path, monkeypatch):
    """Each test runs in an empty temp dir so logs/ and outputs never touch the repo."""
    monkeypatch.chdir(tmp_path)
    return tmp_path


def _incident_id(output: str) -> str:
    m = re.search(r"Incident:\s+(INC-[A-Za-z0-9_-]+)", output)
    assert m, output
    return m.group(1)


def test_version_flag():
    result = runner.invoke(app, ["--version"])
    assert result.exit_code == 0
    assert "netcoop 0.1.0" in result.output


def test_generate_single_scenario(tmp_path):
    out_dir = tmp_path / "samples"
    result = runner.invoke(app, ["generate", "--scenario", "link_congestion", "--out", str(out_dir)])
    assert result.exit_code == 0, result.output
    generated = json.loads((out_dir / "link_congestion.json").read_text(encoding="utf-8"))
    shipped = json.loads((SAMPLES / "link_congestion.json").read_text(encoding="utf-8"))
    assert generated == shipped


def test_generate_corrupted_scenario_writes_raw_text(tmp_path):
    out_dir = tmp_path / "samples"
    result = runner.invoke(app, ["generate", "--scenario", "corrupted_json", "--out", str(out_dir)])
    assert result.exit_code == 0, result.output
    generated = (out_dir / "corrupted_json.json").read_text(encoding="utf-8")
    shipped = (SAMPLES / "corrupted_json.json").read_bytes().decode("utf-8")
    # shipped samples may carry Windows CRLF endings; compare content, not line endings
    assert generated.replace("\r\n", "\n").strip() == shipped.replace("\r\n", "\n").strip()


def test_generate_all(tmp_path):
    out_dir = tmp_path / "all"
    result = runner.invoke(app, ["generate", "--scenario", "all", "--out", str(out_dir)])
    assert result.exit_code == 0, result.output
    assert len(list(out_dir.glob("*.json"))) == 14


def test_generate_unknown_scenario_is_friendly():
    result = runner.invoke(app, ["generate", "--scenario", "nope"])
    assert result.exit_code == 1
    assert "Unknown scenario 'nope'" in result.output
    assert "Traceback" not in result.output


def test_diagnose_prints_summary_and_writes_files(tmp_path):
    out_json = tmp_path / "out" / "report.json"
    out_md = tmp_path / "out" / "report.md"
    result = runner.invoke(
        app, ["diagnose", str(SAMPLES / "link_congestion.json"), "--out", str(out_json), "--md", str(out_md)]
    )
    assert result.exit_code == 0, result.output
    assert "LINK_CONGESTION" in result.output
    assert "DIST_SW_HOSTEL" in result.output
    data = json.loads(out_json.read_text(encoding="utf-8"))
    assert data["root_cause_code"] == "LINK_CONGESTION"
    md = out_md.read_text(encoding="utf-8")
    assert md.startswith("# Incident INC-")
    assert "## Recommended Actions" in md


def test_diagnose_output_has_no_agent_debug_noise():
    result = runner.invoke(app, ["diagnose", str(SAMPLES / "link_congestion.json")])
    assert result.exit_code == 0
    assert "CONFIDENCE DEBUG" not in result.output
    assert "INITIAL SCORES" not in result.output


def test_diagnose_verbose_trace_lines():
    result = runner.invoke(app, ["diagnose", str(SAMPLES / "link_congestion.json"), "--verbose-trace"])
    assert result.exit_code == 0, result.output
    lines = [ln for ln in result.output.splitlines() if re.match(r"^\d\d:\d\d:\d\d\.\d{3}  ", ln)]
    assert len(lines) >= 8
    assert any("orchestrator -> telemetry_agent  task_request  task=analyze" in ln for ln in lines)
    assert any("telemetry_agent -> correlation_agent  finding  LINK_CONGESTION" in ln for ln in lines)
    assert any("reporting_agent -> orchestrator  final_result" in ln for ln in lines)


def test_agent_colours_are_distinct_and_cover_real_agents():
    agents = ["telemetry_agent", "infrastructure_agent", "connectivity_agent", "correlation_agent", "reporting_agent"]
    colours = [cli.AGENT_COLOURS[a] for a in agents]
    assert len(set(colours)) == len(colours)
    assert "orchestrator" in cli.AGENT_COLOURS and "orchestrator_bus" in cli.AGENT_COLOURS


def test_diagnose_missing_file():
    result = runner.invoke(app, ["diagnose", "does_not_exist.json"])
    assert result.exit_code == 1
    assert "Input file not found" in result.output
    assert "Traceback" not in result.output


def test_diagnose_directory_input(tmp_path):
    result = runner.invoke(app, ["diagnose", str(tmp_path)])
    assert result.exit_code == 1
    assert "not a file" in result.output


def test_diagnose_corrupted_json_reports_line_column_and_exit_2(tmp_path):
    out_json = tmp_path / "r.json"
    result = runner.invoke(app, ["diagnose", str(SAMPLES / "corrupted_json.json"), "--out", str(out_json)])
    assert result.exit_code == 2
    assert "CORRUPTED_JSON" in result.output
    assert "line 9, column 3" in result.output
    assert "Traceback" not in result.output
    assert json.loads(out_json.read_text(encoding="utf-8"))["status"] == "invalid_input"


def test_diagnose_unknown_schema_version_exit_2():
    result = runner.invoke(app, ["diagnose", str(SAMPLES / "unknown_schema_version.json")])
    assert result.exit_code == 2
    assert "UNKNOWN_SCHEMA_VERSION" in result.output


def test_diagnose_insufficient_evidence_is_not_an_error():
    result = runner.invoke(app, ["diagnose", str(SAMPLES / "ambiguous_insufficient.json")])
    assert result.exit_code == 0
    assert "insufficient_evidence" in result.output
    assert "not determined" in result.output


def test_diagnose_with_topology_file(tmp_path):
    topo_file = tmp_path / "topo.json"
    cli.load_topology().save_to_json(topo_file)
    result = runner.invoke(app, ["diagnose", str(SAMPLES / "weak_wifi.json"), "--topology", str(topo_file)])
    assert result.exit_code == 0, result.output
    assert "WEAK_WIFI_SIGNAL" in result.output


def test_diagnose_bad_topology_path():
    result = runner.invoke(app, ["diagnose", str(SAMPLES / "weak_wifi.json"), "--topology", "missing_topo.json"])
    assert result.exit_code == 1
    assert "Topology file not found" in result.output


def test_unexpected_exception_becomes_one_line(monkeypatch):
    def boom(*_args, **_kwargs):
        raise RuntimeError("kaboom\nsecond line")

    monkeypatch.setattr(cli, "_run", boom)
    result = runner.invoke(app, ["diagnose", str(SAMPLES / "normal.json")])
    assert result.exit_code == 1
    assert "Error: kaboom second line" in result.output
    assert "Traceback" not in result.output


def test_demo_runs_four_scenarios_with_enter():
    result = runner.invoke(app, ["demo"], input="\n\n\n")
    assert result.exit_code == 0, result.output
    for i, name in enumerate(cli.DEMO_SEQUENCE, start=1):
        assert f"Demo {i}/4: {name}" in result.output
    assert result.output.count("Press Enter for the next scenario") == 3
    assert "Message trace" in result.output
    assert "Demo complete." in result.output


def test_demo_survives_closed_stdin():
    result = runner.invoke(app, ["demo"], input="")
    assert result.exit_code == 0, result.output
    assert "Demo complete." in result.output


def test_benchmark_all_pass_and_saves_json(tmp_path):
    out = tmp_path / "bench.json"
    result = runner.invoke(app, ["benchmark", "--out", str(out)])
    assert result.exit_code == 0, result.output
    assert "Accuracy: 14/14 = 100.0%" in result.output
    assert result.output.count("PASS") == 14
    assert not re.search(r"\bFAIL\b", result.output)
    data = json.loads(out.read_text(encoding="utf-8"))
    assert data["total"] == 14 and data["passed"] == 14 and data["accuracy"] == 1.0
    names = {r["scenario"] for r in data["results"]}
    assert {"normal", "link_congestion", "corrupted_json"} <= names


def test_benchmark_default_output_file(tmp_path):
    result = runner.invoke(app, ["benchmark"])
    assert result.exit_code == 0, result.output
    assert (tmp_path / "benchmark_results.json").exists()


def test_benchmark_failure_exits_nonzero(monkeypatch):
    async def fake_benchmark(*_a, **_k):
        return {"accuracy": 0.0, "total": 1, "passed": 0, "results": [
            {"scenario": "x", "description": "", "expected": "A", "predicted": "B", "status": "diagnosed",
             "confidence": 0.5, "confidence_category": "medium", "passed": False, "incident_id": "INC-X"}]}

    monkeypatch.setattr(cli, "run_benchmark", fake_benchmark)
    result = runner.invoke(app, ["benchmark"])
    assert result.exit_code == 1
    assert re.search(r"\bFAIL\b", result.output)


def test_resume_shows_saved_report():
    first = runner.invoke(app, ["diagnose", str(SAMPLES / "dns_failure.json")])
    incident = _incident_id(first.output)
    result = runner.invoke(app, ["resume", incident])
    assert result.exit_code == 0, result.output
    assert incident in result.output
    assert "DNS_FAILURE" in result.output


def test_resume_invalid_input_incident_shows_rejection():
    first = runner.invoke(app, ["diagnose", str(SAMPLES / "corrupted_json.json")])
    incident = _incident_id(first.output)
    result = runner.invoke(app, ["resume", incident])
    assert result.exit_code == 0, result.output
    assert "invalid_input" in result.output


def test_resume_unknown_incident():
    result = runner.invoke(app, ["resume", "INC-DOESNOTEXIST"])
    assert result.exit_code == 1
    assert "No saved state for incident INC-DOESNOTEXIST" in result.output


def test_resume_bad_id_format():
    result = runner.invoke(app, ["resume", "../etc/passwd"])
    assert result.exit_code == 1
    assert "not a valid incident id" in result.output


def test_resume_incomplete_incident(tmp_path):
    logs = tmp_path / "logs"
    logs.mkdir()
    (logs / "state_INC-HALFWAY1.json").write_text(
        json.dumps({"incident_id": "INC-HALFWAY1", "last_stage": "analysed", "analysed": {}}), encoding="utf-8"
    )
    result = runner.invoke(app, ["resume", "INC-HALFWAY1"])
    assert result.exit_code == 1
    assert "stopped at stage 'analysed'" in result.output


def test_serve_starts_uvicorn_with_port(monkeypatch):
    import uvicorn

    captured = {}

    def fake_run(application, host, port, log_level):
        captured.update(application=application, host=host, port=port)

    monkeypatch.setattr(uvicorn, "run", fake_run)
    result = runner.invoke(app, ["serve", "--port", "8123"])
    assert result.exit_code == 0, result.output
    assert captured["port"] == 8123
    assert captured["host"] == "127.0.0.1"
    assert hasattr(captured["application"], "routes")
    assert "http://127.0.0.1:8123" in result.output


def test_serve_port_in_use_is_friendly(monkeypatch):
    import uvicorn

    def fake_run(*_a, **_k):
        raise OSError("address already in use")

    monkeypatch.setattr(uvicorn, "run", fake_run)
    result = runner.invoke(app, ["serve"])
    assert result.exit_code == 1
    assert "Could not start server" in result.output


def test_serve_rejects_bad_port():
    result = runner.invoke(app, ["serve", "--port", "99999"])
    assert result.exit_code != 0
    assert "Traceback" not in result.output
