"""Recommendation Agent (Member 2) - corrective actions for a verified diagnosis."""

PLAYBOOK = {
    "LINK_CONGESTION": [
        "Inspect traffic distribution on {target} to find the top talkers",
        "Reroute traffic or enable load balancing across an alternate path",
        "Apply QoS / rate limiting to non-critical traffic",
        "Check queue-drop counters on the upstream router",
        "Plan a bandwidth upgrade if utilization stays above 80%",
    ],
    "DEVICE_OVERLOAD": [
        "Reduce load on {target}: shift traffic or disable non-essential services",
        "Check running processes and control-plane activity for CPU/memory spikes",
        "Inspect cooling and airflow - temperature may be elevated",
        "Schedule a maintenance window to restart the device if memory is leaking",
        "Consider adding a redundant or higher-capacity device",
    ],
    "INTERFACE_FAULT": [
        "Inspect interface {target}: cable, connector and SFP module",
        "Switch traffic to a backup link or spare port while repairing",
        "Replace the cable/SFP if CRC errors continue",
        "Verify speed/duplex settings match on both ends",
        "Monitor error counters after the fix to confirm recovery",
    ],
    "WEAK_WIFI": [
        "Check access point coverage and placement around {target}",
        "Move or add an access point, or raise transmit power",
        "Switch to a cleaner channel and check for interference",
        "Check client load and enable band steering",
        "Verify roaming thresholds so clients leave weak APs",
    ],
    "LINK_DOWN": [
        "Check physical connection and power at {target}",
        "Fail over to the backup link immediately",
        "Inspect the remote end of the link",
        "Escalate to the carrier or cabling team if the link stays down",
    ],
    "NO_FAULT": ["No action required - continue routine monitoring"],
}

INSUFFICIENT = [
    "Do not act on the suspected cause yet - evidence is incomplete",
    "Collect more telemetry for {target} (interface counters, utilization, device stats)",
    "Re-run the diagnosis in a few minutes to confirm the trend",
    "Escalate to a network engineer if symptoms persist",
]

TARGET_KEY = {"LINK_CONGESTION": "link", "DEVICE_OVERLOAD": "device",
              "INTERFACE_FAULT": "interface", "WEAK_WIFI": "ap", "LINK_DOWN": "interface"}


class RecommendationAgent:
    name = "Recommendation Agent"

    def recommend(self, diagnosis, verification_status, findings, supporting_agents):
        target = self._target(diagnosis, findings, supporting_agents)
        if verification_status != "VERIFIED":
            steps = INSUFFICIENT
        else:
            steps = PLAYBOOK.get(diagnosis, INSUFFICIENT)
        actions = [s.format(target=target) for s in steps]
        plan = [{"step": i + 1,
                 "priority": "IMMEDIATE" if i < 2 and diagnosis != "NO_FAULT" else "FOLLOW_UP",
                 "action": a} for i, a in enumerate(actions)]
        return {"agent": self.name, "target": target,
                "recommended_actions": actions, "action_plan": plan}

    @staticmethod
    def _target(diagnosis, findings, supporting_agents):
        key = TARGET_KEY.get(diagnosis)
        for f in findings:
            if f["agent"] in supporting_agents and key in f.get("evidence", {}):
                return str(f["evidence"][key])
        return "the affected component"