from __future__ import annotations

SEV_RANK = {"NONE": 0, "WARNING": 1, "CRITICAL": 2}


def level(value, warn, crit, lower_is_worse=False):
    if value is None:
        return None
    if lower_is_worse:
        if value <= crit:
            return "CRITICAL"
        if value <= warn:
            return "WARNING"
    else:
        if value >= crit:
            return "CRITICAL"
        if value >= warn:
            return "WARNING"
    return None


def worst(levels):
    levels = list(levels)
    return max(levels, key=SEV_RANK.get) if levels else "NONE"


def confidence(signals, severity):
    c = 0.50 + 0.12 * (signals - 1) + (0.05 if severity == "CRITICAL" else 0.0)
    return round(min(c, 0.95), 2)


def join_words(words):
    words = list(words)
    if len(words) <= 1:
        return "".join(words)
    return ", ".join(words[:-1]) + " and " + words[-1]


def _unique(seq):
    out = []
    for x in seq:
        if x not in out:
            out.append(x)
    return out


class BaseAgent:
    name = "Base Agent"

    def analyze(self, telemetry):
        raise NotImplementedError

    def _report(self, telemetry, issues, healthy_finding, healthy_evidence):
        ts = telemetry.get("timestamp")
        if not issues:
            return {
                "agent": self.name,
                "status": "HEALTHY",
                "severity": "NONE",
                "finding": healthy_finding,
                "possible_causes": [],
                "evidence": healthy_evidence,
                "affected_components": [],
                "affected_devices": [],
                "confidence": 0.95,
                "timestamp": ts,
            }

        issues = sorted(
            issues, key=lambda i: (SEV_RANK[i["severity"]], i["signals"]), reverse=True
        )
        top = issues[0]
        finding = top["headline"]
        if len(issues) > 1:
            n = len(issues) - 1
            finding += f" (+{n} more issue{'s' if n > 1 else ''})"
        return {
            "agent": self.name,
            "status": "ISSUE_DETECTED",
            "severity": top["severity"],
            "finding": finding,
            "possible_causes": _unique(c for i in issues for c in i["causes"]),
            "evidence": top["evidence"],
            "affected_components": _unique(c for i in issues for c in i["components"]),
            "affected_devices": _unique(d for i in issues for d in i["devices"]),
            "confidence": confidence(top["signals"], top["severity"]),
            "timestamp": ts,
        }