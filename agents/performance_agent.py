from .base import BaseAgent, level, worst, join_words


class PerformanceAgent(BaseAgent):
    name = "Performance Agent"

    THRESHOLDS = {
        "latency_ms": (100, 200),
        "packet_loss_pct": (2, 5),
        "jitter_ms": (30, 60),
        "link_utilization_pct": (80, 90),
    }
    LABELS = {
        "latency_ms": "high latency",
        "packet_loss_pct": "packet loss",
        "jitter_ms": "jitter",
        "link_utilization_pct": "high utilization",
    }

    def analyze(self, telemetry):
        links = telemetry.get("links", [])
        issues = []
        for link in links:
            vals = {
                "latency_ms": link.get("latency_ms"),
                "packet_loss_pct": link.get("packet_loss_pct"),
                "jitter_ms": link.get("jitter_ms"),
                "link_utilization_pct": link.get("utilization_pct"),
            }
            flags = {k: level(v, *self.THRESHOLDS[k]) for k, v in vals.items()}
            flags = {k: v for k, v in flags.items() if v}
            if not flags:
                continue

            quality = [k for k in flags if k != "link_utilization_pct"]
            saturated = "link_utilization_pct" in flags
            if quality and saturated:
                causes = ["LINK_CONGESTION"]
            elif quality and link.get("type") == "wireless":
                causes = ["WIFI_DEGRADATION"]
            elif quality:
                causes = ["PHYSICAL_LAYER_FAULT", "DEVICE_OVERLOAD"]
            else:
                causes = ["LINK_CONGESTION"]

            words = [self.LABELS[k] for k in flags]
            issues.append({
                "headline": f"{join_words(words).capitalize()} on {link['id']}",
                "causes": causes,
                "severity": worst(flags.values()),
                "signals": len(flags),
                "components": [link["id"]],
                "devices": [],
                "evidence": {"link": link["id"],
                             **{k: v for k, v in vals.items() if v is not None}},
            })

        def mx(key):
            return max([l.get(key, 0) for l in links], default=0)

        healthy_evidence = {
            "links_checked": len(links),
            "max_latency_ms": mx("latency_ms"),
            "max_packet_loss_pct": mx("packet_loss_pct"),
            "max_jitter_ms": mx("jitter_ms"),
            "max_link_utilization_pct": mx("utilization_pct"),
        }
        return self._report(telemetry, issues,
                            "Latency, loss, jitter and utilization within limits",
                            healthy_evidence)