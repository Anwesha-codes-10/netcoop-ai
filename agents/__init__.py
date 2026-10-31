import json

from .performance_agent import PerformanceAgent
from .infrastructure_agent import InfrastructureAgent
from .connectivity_agent import ConnectivityAgent

ALL_AGENTS = [PerformanceAgent, InfrastructureAgent, ConnectivityAgent]


def load_telemetry(path):
    with open(path, "r", encoding="utf-8") as f:
        return json.load(f)


def run_all(telemetry):
    """Telemetry in -> list of structured findings (one per agent) out."""
    return [agent().analyze(telemetry) for agent in ALL_AGENTS]


def preliminary_verdict(results):
    """Quick cause ranking by confidence-weighted votes."""
    scores = {}
    for r in results:
        if r["status"] != "ISSUE_DETECTED":
            continue
        for rank, cause in enumerate(r["possible_causes"]):
            scores[cause] = scores.get(cause, 0.0) + r["confidence"] / (1 + rank)
    return sorted(((c, round(s, 2)) for c, s in scores.items()), key=lambda x: -x[1])