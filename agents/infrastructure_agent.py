from .base import BaseAgent, level, worst, join_words


class InfrastructureAgent(BaseAgent):
    name = "Infrastructure Agent"

    THRESHOLDS = {
        "cpu_pct": (80, 90),
        "memory_pct": (85, 95),
        "temperature_c": (70, 80),
        "queue_drops": (1000, 10000),
    }
    LABELS = {
        "cpu_pct": "CPU",
        "memory_pct": "memory",
        "temperature_c": "temperature",
        "queue_drops": "queue drops",
        "health": "device health",
    }

    def analyze(self, telemetry):
        devices = telemetry.get("devices", [])
        issues = []
        for d in devices:
            vals = {k: d.get(k) for k in self.THRESHOLDS}
            flags = {k: level(v, *self.THRESHOLDS[k]) for k, v in vals.items()}
            flags = {k: v for k, v in flags.items() if v}
            health = d.get("health", "OK")
            if health == "DEGRADED":
                flags["health"] = "WARNING"
            elif health == "FAILED":
                flags["health"] = "CRITICAL"
            if not flags:
                continue

            overloaded = "cpu_pct" in flags or "memory_pct" in flags
            causes = []
            if overloaded:
                causes.append("DEVICE_OVERLOAD")
            if "temperature_c" in flags or "health" in flags:
                causes.append("HARDWARE_DEGRADATION")
            if "queue_drops" in flags and not overloaded:
                causes.append("LINK_CONGESTION")

            words = [self.LABELS[k] for k in flags]
            issues.append({
                "headline": f"Abnormal {join_words(words)} on {d['id']}",
                "causes": causes,
                "severity": worst(flags.values()),
                "signals": len(flags),
                "components": [d["id"]],
                "devices": [d["id"]],
                "evidence": {"device": d["id"],
                             **{k: v for k, v in vals.items() if v is not None},
                             "health": health},
            })

        def mx(key):
            return max([d.get(key, 0) for d in devices], default=0)

        healthy_evidence = {
            "devices_checked": len(devices),
            "max_cpu_pct": mx("cpu_pct"),
            "max_memory_pct": mx("memory_pct"),
            "max_temperature_c": mx("temperature_c"),
            "total_queue_drops": sum(d.get("queue_drops", 0) for d in devices),
        }
        return self._report(telemetry, issues,
                            "All devices healthy: CPU, memory, temperature and queues normal",
                            healthy_evidence)