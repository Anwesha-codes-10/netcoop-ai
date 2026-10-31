"""Evidence Verification Agent (Member 2) - refuses diagnoses the evidence does not support."""


class _Evidence:
    """Read-only view over the evidence dictionaries of all agents that found an issue."""

    def __init__(self, findings):
        self.items = [f.get("evidence", {}) for f in findings if f.get("status") == "ISSUE_DETECTED"]

    def nums(self, key):
        return [e[key] for e in self.items
                if isinstance(e.get(key), (int, float)) and not isinstance(e.get(key), bool)]

    def mx(self, key):
        v = self.nums(key)
        return max(v) if v else None

    def mn(self, key):
        v = self.nums(key)
        return min(v) if v else None

    def texts(self, key):
        return [str(e[key]) for e in self.items if key in e]


def _show(key, val):
    return f"{key}={val}" if val is not None else f"{key}: no data"


def at_least(key, thr):
    def fn(e):
        v = e.mx(key)
        return (v is not None and v >= thr), _show(key, v)
    return fn


def at_most(key, thr):
    def fn(e):
        v = e.mn(key)
        return (v is not None and v <= thr), _show(key, v)
    return fn


def any_of(*fns):
    def fn(e):
        res = [f(e) for f in fns]
        return any(r[0] for r in res), "; ".join(r[1] for r in res)
    return fn


def interface_errors(e):
    parts = [e.mx(k) for k in ("crc_errors", "input_errors", "output_errors")]
    if all(p is None for p in parts):
        return False, "interface errors: no data"
    total = sum(p for p in parts if p)
    return total >= 100, f"total_errors={total}"


def not_healthy(e):
    vals = e.texts("health")
    return any(v != "OK" for v in vals), f"health={','.join(vals) if vals else 'no data'}"


def link_is_down(e):
    vals = e.texts("link_status")
    return any(v == "DOWN" for v in vals), f"link_status={','.join(vals) if vals else 'no data'}"


# diagnosis -> (minimum optional checks that must pass, [(label, check_fn, required)])
SPECS = {
    "LINK_CONGESTION": (2, [
        ("High link utilization (>=80%)", at_least("link_utilization_pct", 80), True),
        ("High latency (>=100 ms)", at_least("latency_ms", 100), False),
        ("Packet loss (>=2%)", at_least("packet_loss_pct", 2), False),
        ("Jitter (>=30 ms)", at_least("jitter_ms", 30), False),
        ("Queue drops (>=1000)", at_least("queue_drops", 1000), False),
    ]),
    "DEVICE_OVERLOAD": (1, [
        ("High CPU (>=80%) or memory (>=85%)",
         any_of(at_least("cpu_pct", 80), at_least("memory_pct", 85)), True),
        ("High temperature (>=70 C)", at_least("temperature_c", 70), False),
        ("Queue drops (>=1000)", at_least("queue_drops", 1000), False),
        ("Device health not OK", not_healthy, False),
        ("Packet loss (>=2%) on connected links", at_least("packet_loss_pct", 2), False),
    ]),
    "INTERFACE_FAULT": (1, [
        ("Interface errors (>=100) or flapping (>=3/hour)",
         any_of(interface_errors, at_least("flaps_last_hour", 3)), True),
        ("Packet loss (>=2%)", at_least("packet_loss_pct", 2), False),
        ("Jitter (>=30 ms)", at_least("jitter_ms", 30), False),
    ]),
    "WEAK_WIFI": (1, [
        ("Poor Wi-Fi quality (RSSI<=-70, SNR<=25, retries>=15% or channel>=70%)",
         any_of(at_most("rssi_dbm", -70), at_most("snr_db", 25),
                at_least("retry_pct", 15), at_least("channel_utilization_pct", 70)), True),
        ("High latency (>=100 ms)", at_least("latency_ms", 100), False),
        ("Packet loss (>=2%)", at_least("packet_loss_pct", 2), False),
        ("Jitter (>=30 ms)", at_least("jitter_ms", 30), False),
    ]),
    "LINK_DOWN": (0, [("Interface operational status is DOWN", link_is_down, True)]),
}


class VerificationAgent:
    name = "Evidence Verification Agent"

    def verify(self, diagnosis, findings):
        if diagnosis == "NO_FAULT":
            ok = all(f["status"] == "HEALTHY" for f in findings)
            return self._result(diagnosis, "VERIFIED" if ok else "INSUFFICIENT_EVIDENCE",
                                [{"check": "All agents report HEALTHY", "passed": ok,
                                  "required": True, "evidence": f"{len(findings)} agents checked"}])
        if diagnosis not in SPECS:
            return self._result(diagnosis, "INSUFFICIENT_EVIDENCE",
                                [{"check": "Known diagnosis with a verification rule", "passed": False,
                                  "required": True, "evidence": "no rule defined"}])
        min_optional, checks = SPECS[diagnosis]
        ev = _Evidence(findings)
        results = []
        for label, fn, required in checks:
            passed, shown = fn(ev)
            results.append({"check": label, "passed": bool(passed),
                            "required": required, "evidence": shown})
        required_ok = all(r["passed"] for r in results if r["required"])
        optional_ok = sum(1 for r in results if not r["required"] and r["passed"]) >= min_optional
        status = "VERIFIED" if (required_ok and optional_ok) else "INSUFFICIENT_EVIDENCE"
        return self._result(diagnosis, status, results)

    def _result(self, diagnosis, status, checks):
        passed = sum(1 for c in checks if c["passed"])
        return {"agent": self.name, "diagnosis": diagnosis, "status": status,
                "checks_passed": passed, "checks_total": len(checks), "checks": checks}