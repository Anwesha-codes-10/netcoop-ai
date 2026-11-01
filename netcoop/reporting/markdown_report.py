"""NetCoop AI Markdown Report Renderer.

Renders a FinalReport as plain Markdown (no emojis). Uses only fields that exist
on FinalReport, tolerates empty/None sections, and refuses to present a fake
diagnosis for insufficient_evidence, partial (no cause) and invalid_input reports.
"""

from typing import Any, Dict, Iterable, List, Optional

from netcoop.reporting.report_models import FinalReport

_STATUS_LABELS = {
    "diagnosed": "Diagnosed",
    "insufficient_evidence": "Insufficient evidence",
    "partial": "Partial",
    "invalid_input": "Invalid input",
}


def _cell(value: Any) -> str:
    """Format a value for a Markdown table cell (escape pipes, flatten newlines)."""
    if value is None:
        return "-"
    text = str(value).replace("\r", " ").replace("\n", " ").strip()
    if not text:
        return "-"
    return text.replace("|", "\\|")


def _inline(value: Any) -> str:
    """Format a value for inline prose (flatten newlines)."""
    if value is None:
        return ""
    return str(value).replace("\r", " ").replace("\n", " ").strip()


def _fmt_value(value: Any) -> str:
    if isinstance(value, float):
        return f"{value:g}"
    return _cell(value)


def _table(headers: List[str], rows: Iterable[List[str]]) -> List[str]:
    lines = [
        "| " + " | ".join(headers) + " |",
        "| " + " | ".join("---" for _ in headers) + " |",
    ]
    for row in rows:
        lines.append("| " + " | ".join(row) + " |")
    return lines


def _bullets(items: Iterable[Any]) -> List[str]:
    return [f"- {_inline(i)}" for i in items if _inline(i)]


def _section(title: str) -> List[str]:
    return ["", f"## {title}", ""]


def _has_cause(report: FinalReport) -> bool:
    """True only when the report genuinely asserts a root cause."""
    return report.status == "diagnosed"


def _summary_section(report: FinalReport) -> List[str]:
    lines: List[str] = []
    conf = f"{report.confidence:.2f} ({report.confidence_category})"
    if report.status == "invalid_input":
        lines += _section("Suspected Cause")
        lines.append(
            "The telemetry input was rejected during validation. "
            "No diagnosis was produced and no root cause is asserted."
        )
    elif report.status == "insufficient_evidence":
        lines += _section("Suspected Cause")
        lines.append(
            "The available telemetry is insufficient to determine a root cause. "
            "No diagnosis is asserted."
        )
        lines.append("")
        lines.append(f"- **Confidence:** {conf}")
    elif report.status == "partial":
        lines += _section("Suspected Cause")
        lines.append(
            "Only part of the input could be processed. "
            "The evidence does not support a firm root cause, so none is asserted."
        )
        lines.append("")
        lines.append(f"- **Confidence:** {conf}")
    else:
        lines += _section("Suspected Cause")
        lines.append(f"**{_inline(report.suspected_root_cause)}**")
        lines.append("")
        lines.append(f"- **Cause code:** {report.root_cause_code.value}")
        lines.append(f"- **Confidence:** {conf}")
    return lines


def _affected_section(report: FinalReport) -> List[str]:
    lines = _section("Affected Devices and Segments")
    devices = [d for d in (report.affected_devices or []) if d]
    segments = [s for s in (report.affected_segments or []) if s]
    if not devices and not segments:
        lines.append("None identified.")
        return lines
    lines.append("**Devices:** " + (", ".join(f"`{d}`" for d in devices) if devices else "none identified"))
    lines.append("")
    lines.append("**Segments:** " + (", ".join(f"`{s}`" for s in segments) if segments else "none identified"))
    return lines


def _evidence_section(report: FinalReport) -> List[str]:
    lines = _section("Supporting Evidence")
    evidence = report.supporting_evidence or []
    if not evidence:
        lines.append("No supporting evidence recorded.")
        return lines
    rows = []
    for ev in evidence:
        if not isinstance(ev, dict):
            rows.append(["-", "-", "-", "-", "-", _cell(ev)])
            continue
        rows.append(
            [
                _cell(ev.get("metric")),
                _fmt_value(ev.get("value")),
                _cell(ev.get("unit")),
                _cell(ev.get("device_id")),
                _cell(ev.get("source_agent")),
                _cell(ev.get("interpretation")),
            ]
        )
    lines += _table(["Metric", "Value", "Unit", "Device", "Source agent", "Interpretation"], rows)
    return lines


def _alternatives_section(report: FinalReport) -> List[str]:
    title = "Alternative Causes" if _has_cause(report) else "Hypotheses Considered (not conclusions)"
    lines = _section(title)
    alts = report.alternative_causes or []
    if not alts:
        lines.append("No alternative causes recorded.")
        return lines
    for alt in alts:
        if not isinstance(alt, dict):
            lines.append(f"- {_inline(alt)}")
            continue
        cause = alt.get("cause") or alt.get("cause_code") or "UNKNOWN"
        cause = getattr(cause, "value", cause)
        score = alt.get("score")
        score_txt = f" (score {score:.2f})" if isinstance(score, (int, float)) else ""
        why = _inline(alt.get("why_less_likely"))
        lines.append(f"- **{_inline(cause)}**{score_txt}" + (f": {why}" if why else ""))
    return lines


def _actions_section(report: FinalReport) -> List[str]:
    lines = _section("Recommended Actions")
    actions = sorted(report.recommended_actions or [], key=lambda a: a.priority)
    if not actions:
        lines.append("No actions recommended.")
        return lines
    for idx, act in enumerate(actions, start=1):
        review = " *(requires human review)*" if act.requires_human_review else ""
        lines.append(f"{idx}. **[P{act.priority}]** {_inline(act.action)}{review}")
        if _inline(act.rationale):
            lines.append(f"   - Rationale: {_inline(act.rationale)}")
    return lines


def _preview_section(report: FinalReport) -> List[str]:
    lines = _section("Simulated Remediation Preview")
    preview = (report.simulated_remediation_preview or "").strip()
    if not preview:
        lines.append("No remediation preview available.")
        return lines
    lines.append("Simulation only. Nothing was executed on any device.")
    lines.append("")
    lines.append("```text")
    lines.extend(preview.splitlines())
    lines.append("```")
    return lines


def _conflicts_section(report: FinalReport) -> List[str]:
    lines = _section("Conflicts Resolved")
    conflicts = report.conflicts_resolved or []
    if not conflicts:
        lines.append("No conflicts between agents were detected.")
        return lines
    for c in conflicts:
        if not isinstance(c, dict):
            lines.append(f"- {_inline(c)}")
            continue
        rule = _inline(c.get("rule")) or "Rule"
        desc = _inline(c.get("description"))
        effect = _inline(c.get("effect"))
        text = f"- **{rule}**"
        if desc:
            text += f": {desc}"
        if effect:
            text += f" Effect: {effect}"
        lines.append(text)
    return lines


def _limitations_section(report: FinalReport) -> List[str]:
    lines = _section("Limitations")
    items = _bullets(report.limitations or [])
    lines += items if items else ["None recorded."]
    return lines


def _data_quality_section(report: FinalReport) -> List[str]:
    lines = _section("Data Quality")
    dq: Dict[str, Any] = report.data_quality or {}
    if not dq:
        lines.append("No data quality information recorded.")
        return lines
    comp = dq.get("completeness")
    if isinstance(comp, (int, float)):
        lines.append(f"- **Completeness:** {comp * 100:.1f}%")
    for key, label in (
        ("missing_fields", "Missing fields"),
        ("stale_fields", "Stale fields"),
        ("assumptions", "Assumptions"),
    ):
        vals = dq.get(key) or []
        if vals:
            lines.append(f"- **{label}:** " + "; ".join(_inline(v) for v in vals))
        else:
            lines.append(f"- **{label}:** none")
    known = {"completeness", "missing_fields", "stale_fields", "assumptions"}
    for key in sorted(k for k in dq if k not in known):
        lines.append(f"- **{_inline(key)}:** {_inline(dq[key])}")
    return lines


def _normalization_section(report: FinalReport) -> List[str]:
    lines = _section("Normalization Log")
    log = report.normalization_log or []
    if not log:
        lines.append("No normalization performed.")
        return lines
    changed = [e for e in log if isinstance(e, dict) and e.get("rule") != "identity"]
    unchanged = len(log) - len(changed)
    if changed:
        rows = []
        for e in changed:
            orig = f"{_fmt_value(e.get('original_value'))} {_inline(e.get('original_unit'))}".strip()
            canon = f"{_fmt_value(e.get('canonical_value'))} {_inline(e.get('canonical_unit'))}".strip()
            rows.append(
                [
                    _cell(e.get("field_original")),
                    _cell(e.get("canonical_field")),
                    _cell(orig),
                    _cell(canon),
                    _cell(e.get("rule")),
                ]
            )
        lines += _table(["Original field", "Canonical field", "Original value", "Canonical value", "Rule"], rows)
        lines.append("")
    lines.append(f"{unchanged} field value(s) were already canonical and passed through unchanged.")
    return lines


def _agent_status_section(report: FinalReport) -> List[str]:
    lines = _section("Agent Status")
    status = report.agent_status or {}
    if not status:
        lines.append("No agents ran for this incident.")
        return lines
    lines += _table(["Agent", "Status"], [[_cell(k), _cell(v)] for k, v in status.items()])
    return lines


def _trace_section(report: FinalReport) -> List[str]:
    lines = _section("Trace Reference")
    ref = report.message_trace_ref
    lines.append(f"`{ref}`" if ref else "No trace reference recorded.")
    if report.evidence_sources:
        lines.append("")
        lines.append("**Evidence sources:** " + ", ".join(f"`{s}`" for s in report.evidence_sources))
    return lines


def render_markdown(report: FinalReport) -> str:
    """Render a FinalReport as a plain Markdown document."""
    status_label = _STATUS_LABELS.get(report.status, _inline(report.status) or "Unknown")
    lines: List[str] = [f"# Incident {report.incident_id} - {status_label}"]
    lines.append("")
    lines.append(f"**Status:** {report.status}")

    lines += _summary_section(report)
    if report.status == "invalid_input":
        # No devices/evidence exist for rejected input; skip those sections entirely.
        lines += _limitations_section(report)
        lines += _actions_section(report)
        lines += _preview_section(report)
        lines += _data_quality_section(report)
        lines += _agent_status_section(report)
        lines += _trace_section(report)
        return "\n".join(lines).rstrip() + "\n"

    lines += _affected_section(report)
    lines += _evidence_section(report)
    lines += _alternatives_section(report)
    lines += _actions_section(report)
    lines += _preview_section(report)
    lines += _conflicts_section(report)
    lines += _limitations_section(report)
    lines += _data_quality_section(report)
    lines += _normalization_section(report)
    lines += _agent_status_section(report)
    lines += _trace_section(report)
    return "\n".join(lines).rstrip() + "\n"
