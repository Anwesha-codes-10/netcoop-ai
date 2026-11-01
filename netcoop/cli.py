"""NetCoop AI command line interface (typer + rich).

Commands: generate, diagnose, demo, benchmark, resume, serve.

This module also hosts the small set of shared helpers (trace reading, benchmark
evaluation, incident lookup) that the HTTP API reuses, so the CLI and the API can
never disagree about how a trace is summarised or how a benchmark is scored.
"""

import asyncio
import functools
import json
import re
import shutil
from datetime import datetime
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional, Union

import typer
from rich import box
from rich.console import Console
from rich.markup import escape
from rich.panel import Panel
from rich.table import Table

from netcoop import __version__
from netcoop.config import agent_config
from netcoop.data.scenarios import Scenario, ScenarioBuilder
from netcoop.data.topology import CampusTopology
from netcoop.ingest import ingest
from netcoop.orchestrator import MessageLog, StateStore, run_diagnosis
from netcoop.protocol.causes import CauseCode
from netcoop.protocol.messages import parse_message
from netcoop.reporting.markdown_report import render_markdown
from netcoop.reporting.report_models import FinalReport

PROJECT_ROOT = Path(__file__).resolve().parent.parent
INCIDENT_ID_PATTERN = r"^INC-[A-Za-z0-9_-]+$"
DEMO_SEQUENCE = ["normal", "link_congestion", "legacy_schema_0_9", "ambiguous_insufficient"]

# One distinct colour per real agent name (see netcoop/agents/*.py and message_bus.py).
AGENT_COLOURS: Dict[str, str] = {
    "orchestrator": "white",
    "orchestrator_bus": "red",
    "telemetry_agent": "cyan",
    "infrastructure_agent": "green",
    "connectivity_agent": "yellow",
    "correlation_agent": "magenta",
    "reporting_agent": "blue",
    "broadcast": "bright_black",
}

app = typer.Typer(
    name="netcoop",
    help="NetCoop AI - multi-agent campus network fault diagnosis.",
    add_completion=False,
    no_args_is_help=True,
    pretty_exceptions_enable=False,
)


class CliError(Exception):
    """A user-facing error: printed as one friendly line, exit code non-zero."""

    def __init__(self, message: str, code: int = 1):
        super().__init__(message)
        self.message = message
        self.code = code


# ---------------------------------------------------------------------------
# Shared helpers (also imported by netcoop.api.app)
# ---------------------------------------------------------------------------


def log_dir() -> Path:
    """Directory used by the orchestrator for message logs and state checkpoints."""
    return Path(agent_config("orchestrator").get("log_dir", "logs"))


def find_data_file(*parts: str) -> Optional[Path]:
    """Locate a data path in the working directory first, then in the project root."""
    for base in (Path.cwd(), PROJECT_ROOT):
        candidate = base.joinpath(*parts)
        if candidate.exists():
            return candidate
    return None


def load_topology(path: Optional[Union[str, Path]] = None) -> CampusTopology:
    """Load a topology JSON file, or build the default IIT Bhubaneswar topology."""
    if path is None:
        return CampusTopology.build_iit_bhubaneswar_topology()
    p = Path(path)
    if not p.is_file():
        raise CliError(f"Topology file not found: {p}")
    try:
        return CampusTopology.load_from_json(p)
    except Exception as ex:
        raise CliError(f"Could not read topology file {p}: {ex}")


def scenario_kind(name: str) -> str:
    """Group scenarios the way netcoop/data/scenarios.py documents them."""
    interop = {"legacy_schema_0_9", "mixed_units", "missing_fields", "unknown_schema_version", "corrupted_json"}
    return "interoperability" if name in interop else "root_cause"


def get_scenarios() -> List[Scenario]:
    return ScenarioBuilder().build_all()


def get_scenario(name: str) -> Optional[Scenario]:
    return next((s for s in get_scenarios() if s.name == name), None)


def trace_entries(incident_id: str) -> List[Dict[str, Any]]:
    """Return the recorded message trace for an incident in a stable, JSON-ready shape."""
    log = MessageLog(log_dir=log_dir())
    entries: List[Dict[str, Any]] = []
    for idx, rec in enumerate(log.read_trace(incident_id)):
        try:
            summary = log.summarize(parse_message(rec))
        except Exception:
            summary = f"{rec.get('sender')} -> {rec.get('recipient')} | {rec.get('message_type')} | (unparsed)"
        entries.append(
            {
                "index": idx,
                "timestamp": rec.get("timestamp"),
                "sender": rec.get("sender"),
                "recipient": rec.get("recipient"),
                "message_type": rec.get("message_type"),
                "summary": summary,
                "payload": rec.get("payload"),
            }
        )
    return entries


def report_from_state(state: Optional[Dict[str, Any]]) -> Optional[FinalReport]:
    """Extract the final (or ingestion-failure) report from a state checkpoint."""
    if not state:
        return None
    raw = (state.get("reported") or {}).get("final_report") or (state.get("ingested") or {}).get("report")
    if not raw:
        return None
    try:
        return FinalReport.model_validate(raw)
    except Exception:
        return None


def load_incident_state(incident_id: str) -> Optional[Dict[str, Any]]:
    return StateStore(log_dir=log_dir()).load(incident_id)


def list_incident_summaries() -> List[Dict[str, Any]]:
    """Summaries of every incident that has a state checkpoint, newest first."""
    d = log_dir()
    if not d.is_dir():
        return []
    files = sorted(d.glob("state_INC-*.json"), key=lambda p: p.stat().st_mtime, reverse=True)
    store = StateStore(log_dir=d)
    out: List[Dict[str, Any]] = []
    for f in files:
        incident_id = f.stem[len("state_"):]
        state = store.load(incident_id)
        if not state:
            continue
        report = report_from_state(state)
        out.append(
            {
                "incident_id": incident_id,
                "status": report.status if report else "incomplete",
                "suspected_root_cause": report.suspected_root_cause if report else None,
                "root_cause_code": report.root_cause_code.value if report else None,
                "confidence": report.confidence if report else None,
                "confidence_category": report.confidence_category if report else None,
                "last_stage": state.get("last_stage"),
                "updated_at": state.get("updated_at"),
            }
        )
    return out


_CODE_BY_TEXT = (
    ("corrupted json", "CORRUPTED_JSON"),
    ("schema version", "UNKNOWN_SCHEMA_VERSION"),
    ("not found", "EMPTY_INPUT"),
    ("empty", "EMPTY_INPUT"),
)
_LINE_COL = re.compile(r"line (\d+),? column (\d+)")


def describe_invalid_input(report: FinalReport, source: Any = None, topology: Optional[CampusTopology] = None) -> Optional[Dict[str, Any]]:
    """Return {code, detail, line, column} for an invalid_input report, else None.

    The exact validator error code is recovered by re-running the (cheap, agent-free)
    ingestion step on `source`; if that is not possible the code is inferred from the
    validation message that the report already carries.
    """
    if report.status != "invalid_input":
        return None
    detail = ""
    for lim in report.limitations or []:
        if lim.startswith("Validation error:"):
            detail = lim[len("Validation error:"):].strip()
            break
    code: Optional[str] = None
    if source is not None:
        try:
            res = ingest(source, topology=topology)
            if res.validation and res.validation.errors:
                first = res.validation.errors[0]
                code = getattr(first.code, "value", str(first.code))
                detail = detail or first.message
        except Exception:
            code = None
    if code is None:
        low = detail.lower()
        code = next((c for needle, c in _CODE_BY_TEXT if needle in low), "INVALID_INPUT")
    line = column = None
    m = _LINE_COL.search(detail)
    if m:
        line, column = int(m.group(1)), int(m.group(2))
    return {"code": code, "detail": detail or "Input failed validation.", "line": line, "column": column}


def evaluate_scenario(scenario: Scenario, report: FinalReport) -> Dict[str, Any]:
    """Score one report against the scenario ground truth and return a benchmark row."""
    expected = scenario.expected_root_cause
    if expected is None:
        expected_label = "INVALID_OR_PARTIAL"
        passed = report.status in ("invalid_input", "partial")
    elif expected == CauseCode.UNKNOWN:
        expected_label = CauseCode.UNKNOWN.value
        passed = report.root_cause_code == CauseCode.UNKNOWN and report.status == "insufficient_evidence"
    else:
        expected_label = expected.value
        passed = report.root_cause_code == expected and report.status == "diagnosed"
    predicted = report.status.upper() if report.status in ("invalid_input", "partial") else report.root_cause_code.value
    return {
        "scenario": scenario.name,
        "description": scenario.description,
        "expected": expected_label,
        "predicted": predicted,
        "status": report.status,
        "confidence": report.confidence,
        "confidence_category": report.confidence_category,
        "passed": bool(passed),
        "incident_id": report.incident_id,
    }


async def run_benchmark(topology: Optional[CampusTopology] = None) -> Dict[str, Any]:
    """Run every scenario through the full pipeline and score it."""
    topo = topology or load_topology()
    rows: List[Dict[str, Any]] = []
    for sc in get_scenarios():
        report = await run_diagnosis(sc.records, topology=topo)
        rows.append(evaluate_scenario(sc, report))
    passed = sum(1 for r in rows if r["passed"])
    total = len(rows)
    return {
        "accuracy": round(passed / total, 4) if total else 0.0,
        "total": total,
        "passed": passed,
        "results": rows,
    }


# ---------------------------------------------------------------------------
# Console helpers
# ---------------------------------------------------------------------------


def _console() -> Console:
    width = max(shutil.get_terminal_size((130, 24)).columns, 120)
    return Console(width=width, highlight=False, emoji=False)


def _fail(message: str, code: int = 1) -> None:
    typer.echo(f"Error: {message}", err=True)
    raise typer.Exit(code)


def _friendly(func: Callable[..., Any]) -> Callable[..., Any]:
    """Turn every failure into a one-line message plus a non-zero exit code."""

    @functools.wraps(func)
    def wrapper(*args: Any, **kwargs: Any) -> Any:
        try:
            return func(*args, **kwargs)
        except typer.Exit:
            raise
        except CliError as ex:
            _fail(ex.message, ex.code)
        except KeyboardInterrupt:
            _fail("Interrupted.", 130)
        except Exception as ex:  # never show a traceback to the operator
            text = " ".join(str(ex).split()) or type(ex).__name__
            _fail(f"{text[:200]}")

    return wrapper


def _write_text(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")


def _colour(name: Any) -> str:
    return AGENT_COLOURS.get(str(name), "white")


def print_trace(console: Console, entries: List[Dict[str, Any]]) -> None:
    """One line per message: time, sender -> recipient, message type, summary details."""
    if not entries:
        console.print("[dim]No agent messages recorded (input was rejected before analysis).[/dim]")
        return
    for e in entries:
        ts = str(e.get("timestamp") or "")
        try:
            t = datetime.fromisoformat(ts.replace("Z", "+00:00")).strftime("%H:%M:%S.%f")[:-3]
        except ValueError:
            t = ts[:12]
        sender, recipient = e["sender"], e["recipient"]
        details = e["summary"].split(" | ", 2)[-1]
        console.print(
            f"[dim]{escape(t)}[/dim]  "
            f"[{_colour(sender)}]{escape(str(sender))}[/{_colour(sender)}] -> "
            f"[{_colour(recipient)}]{escape(str(recipient))}[/{_colour(recipient)}]  "
            f"[bold]{escape(str(e['message_type']))}[/bold]  {escape(details)}"
        )


def print_report_summary(console: Console, report: FinalReport) -> None:
    status_colour = {"diagnosed": "green", "insufficient_evidence": "yellow", "partial": "yellow"}.get(report.status, "red")
    lines = [
        f"[bold]Incident:[/bold] {escape(report.incident_id)}",
        f"[bold]Status:[/bold] [{status_colour}]{escape(report.status)}[/{status_colour}]",
    ]
    if report.status == "invalid_input":
        lines.append("[bold]Result:[/bold] input rejected, no diagnosis produced")
    elif report.status == "diagnosed":
        lines.append(f"[bold]Root cause:[/bold] {escape(report.suspected_root_cause)} ({report.root_cause_code.value})")
        lines.append(f"[bold]Confidence:[/bold] {report.confidence:.2f} ({report.confidence_category})")
    else:
        lines.append("[bold]Root cause:[/bold] not determined")
        lines.append(f"[bold]Confidence:[/bold] {report.confidence:.2f} ({report.confidence_category})")
    if report.affected_devices:
        lines.append("[bold]Affected devices:[/bold] " + escape(", ".join(report.affected_devices)))
    if report.affected_segments:
        lines.append("[bold]Affected segments:[/bold] " + escape(", ".join(report.affected_segments)))
    for act in sorted(report.recommended_actions, key=lambda a: a.priority):
        lines.append(f"[bold]Action P{act.priority}:[/bold] {escape(act.action)}")
    for lim in report.limitations:
        if lim.startswith("Validation error:"):
            lines.append(f"[bold]Problem:[/bold] {escape(lim)}")
    console.print(Panel("\n".join(lines), title="Diagnosis", expand=False))


def _run(source: Any, topology: Optional[CampusTopology]) -> FinalReport:
    return asyncio.run(run_diagnosis(source, topology=topology))


# ---------------------------------------------------------------------------
# Commands
# ---------------------------------------------------------------------------


def _version_callback(value: bool) -> None:
    if value:
        typer.echo(f"netcoop {__version__}")
        raise typer.Exit()


@app.callback()
def _main(
    version: bool = typer.Option(
        False, "--version", help="Show version and exit.", callback=_version_callback, is_eager=True
    ),
) -> None:
    """NetCoop AI command line."""


@app.command()
@_friendly
def generate(
    scenario: str = typer.Option(..., "--scenario", "-s", help="Scenario name, or 'all'."),
    out: Path = typer.Option(Path("data/samples"), "--out", "-o", help="Output directory."),
) -> None:
    """Generate sample telemetry file(s) for a scenario."""
    console = _console()
    names = [s.name for s in get_scenarios()]
    builder = ScenarioBuilder()
    if scenario == "all":
        paths = builder.save_all(out)
        for p in paths:
            console.print(f"Wrote {escape(str(p))}")
        return
    if scenario not in names:
        raise CliError(f"Unknown scenario '{scenario}'. Choose one of: {', '.join(names)}, all")
    sc = next(s for s in builder.build_all() if s.name == scenario)
    out.mkdir(parents=True, exist_ok=True)
    target = out / f"{sc.name}.json"
    if isinstance(sc.records, str):
        _write_text(target, sc.records)
    else:
        _write_text(target, json.dumps(sc.records, indent=2))
    console.print(f"Wrote {escape(str(target))}")


@app.command()
@_friendly
def diagnose(
    input_path: Path = typer.Argument(..., metavar="INPUT", help="Telemetry JSON file."),
    topology: Optional[Path] = typer.Option(None, "--topology", help="Topology JSON file."),
    out: Optional[Path] = typer.Option(None, "--out", help="Write the report as JSON."),
    md: Optional[Path] = typer.Option(None, "--md", help="Write the report as Markdown."),
    verbose_trace: bool = typer.Option(False, "--verbose-trace", help="Print every agent message."),
) -> None:
    """Diagnose a telemetry file with the multi-agent pipeline."""
    console = _console()
    if not input_path.exists():
        raise CliError(f"Input file not found: {input_path}")
    if not input_path.is_file():
        raise CliError(f"Input is not a file: {input_path}")
    topo = load_topology(topology)
    report = _run(str(input_path), topo)

    if verbose_trace:
        console.print("[bold]Message trace[/bold]")
        print_trace(console, trace_entries(report.incident_id))
        console.print()
    print_report_summary(console, report)

    if out:
        _write_text(out, report.to_json())
        console.print(f"Wrote {escape(str(out))}")
    if md:
        _write_text(md, render_markdown(report))
        console.print(f"Wrote {escape(str(md))}")

    if report.status == "invalid_input":
        info = describe_invalid_input(report, str(input_path), topo)
        where = f" (line {info['line']}, column {info['column']})" if info and info["line"] else ""
        raise CliError(f"Input rejected [{info['code'] if info else 'INVALID_INPUT'}]{where}: {info['detail'] if info else ''}", 2)


@app.command()
@_friendly
def demo() -> None:
    """Walk through four scenarios, pausing for Enter between them."""
    console = _console()
    by_name = {s.name: s for s in get_scenarios()}
    topo = load_topology()
    for i, name in enumerate(DEMO_SEQUENCE):
        sc = by_name[name]
        console.rule(f"[bold]Demo {i + 1}/{len(DEMO_SEQUENCE)}: {escape(name)}[/bold]")
        console.print(escape(sc.description))
        console.print()
        report = _run(sc.records, topo)
        console.print("[bold]Message trace[/bold]")
        print_trace(console, trace_entries(report.incident_id))
        console.print()
        print_report_summary(console, report)
        if i < len(DEMO_SEQUENCE) - 1:
            console.print("\nPress Enter for the next scenario...")
            try:
                input()
            except EOFError:
                pass
    console.print("\nDemo complete.")


@app.command()
@_friendly
def benchmark(
    out: Path = typer.Option(Path("benchmark_results.json"), "--out", help="Where to save the results JSON."),
) -> None:
    """Run every sample scenario and compare expected vs predicted causes."""
    console = _console()
    result = asyncio.run(run_benchmark())
    table = Table(title="NetCoop AI benchmark", box=box.SIMPLE_HEAVY)
    for col in ("Scenario", "Expected", "Predicted", "Status", "Confidence", "Result"):
        table.add_column(col, no_wrap=True, overflow="fold")
    for r in result["results"]:
        res = "[green]PASS[/green]" if r["passed"] else "[red]FAIL[/red]"
        table.add_row(
            r["scenario"], r["expected"], r["predicted"], r["status"],
            f"{r['confidence']:.2f} ({r['confidence_category']})", res,
        )
    console.print(table)
    console.print(f"Accuracy: {result['passed']}/{result['total']} = {result['accuracy'] * 100:.1f}%")
    _write_text(out, json.dumps(result, indent=2))
    console.print(f"Saved {escape(str(out))}")
    if result["passed"] != result["total"]:
        raise CliError("Some scenarios failed.", 1)


@app.command()
@_friendly
def resume(
    incident_id: str = typer.Argument(..., metavar="INCIDENT_ID", help="Incident id, e.g. INC-1A2B3C4D."),
) -> None:
    """Show the saved report of a previously diagnosed incident."""
    console = _console()
    if not re.match(INCIDENT_ID_PATTERN, incident_id):
        raise CliError(f"'{incident_id}' is not a valid incident id (expected INC-XXXXXXXX).")
    state = load_incident_state(incident_id)
    if not state:
        raise CliError(f"No saved state for incident {incident_id} in '{log_dir()}'.")
    report = report_from_state(state)
    if report is None:
        raise CliError(
            f"Incident {incident_id} stopped at stage '{state.get('last_stage')}' and has no final report; "
            "run 'netcoop diagnose' again with the original input."
        )
    console.print(f"Resumed incident {escape(incident_id)} from its saved final report.")
    print_report_summary(console, report)


@app.command()
@_friendly
def serve(
    port: int = typer.Option(8000, "--port", min=1, max=65535, help="Port to listen on."),
    host: str = typer.Option("127.0.0.1", "--host", help="Interface to bind."),
) -> None:
    """Start the HTTP API (and the frontend, if a frontend/ folder exists)."""
    import uvicorn

    from netcoop.api.app import create_app

    api = create_app()
    console = _console()
    console.print(f"Serving NetCoop AI on http://{escape(host)}:{port}  (API docs at /docs). Press Ctrl+C to stop.")
    try:
        uvicorn.run(api, host=host, port=port, log_level="info")
    except OSError as ex:
        raise CliError(f"Could not start server on {host}:{port}: {ex}")


def main() -> None:
    app()


if __name__ == "__main__":
    main()
