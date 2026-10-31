from .base import BaseAgent, level, worst, join_words


class ConnectivityAgent(BaseAgent):
    name = "Connectivity Agent"

    IF_TH = {"error_count": (100, 1000), "flaps_last_hour": (3, 10)}
    IF_LABELS = {"link_down": "link down", "error_count": "interface errors",
                 "flaps_last_hour": "link flapping"}

    WIFI_TH = {  # metric: (warning, critical, lower_is_worse)
        "rssi_dbm": (-70, -80, True),
        "snr_db": (25, 15, True),
        "retry_pct": (15, 30, False),
        "channel_utilization_pct": (70, 90, False),
    }
    WIFI_LABELS = {"rssi_dbm": "weak signal strength", "snr_db": "low SNR",
                   "retry_pct": "high retransmissions",
                   "channel_utilization_pct": "busy channel"}

    def analyze(self, telemetry):
        interfaces = telemetry.get("interfaces", [])
        wifi = telemetry.get("wifi", [])
        issues = []

        for i in interfaces:
            name = f"{i['device']}:{i['name']}"
            errors = sum(i.get(k, 0) for k in ("crc_errors", "input_errors", "output_errors"))
            flags = {}
            for key, val in (("error_count", errors),
                             ("flaps_last_hour", i.get("flaps_last_hour", 0))):
                lv = level(val, *self.IF_TH[key])
                if lv:
                    flags[key] = lv
            down = i.get("admin_status", "UP") == "UP" and i.get("oper_status", "UP") == "DOWN"
            if down:
                flags["link_down"] = "CRITICAL"
            if not flags:
                continue

            causes = []
            if down:
                causes.append("LINK_DOWN")
            if "error_count" in flags or "flaps_last_hour" in flags:
                causes.append("INTERFACE_FAULT")
            words = [self.IF_LABELS[k] for k in flags]
            issues.append({
                "headline": f"{join_words(words).capitalize()} on {name}",
                "causes": causes,
                "severity": worst(flags.values()),
                "signals": len(flags),
                "components": [name],
                "devices": list(i.get("connected_devices", [])),
                "evidence": {"interface": name, "link_status": i.get("oper_status", "UP"),
                             "crc_errors": i.get("crc_errors", 0),
                             "input_errors": i.get("input_errors", 0),
                             "output_errors": i.get("output_errors", 0),
                             "flaps_last_hour": i.get("flaps_last_hour", 0)},
            })

        for w in wifi:
            vals = {k: w.get(k) for k in self.WIFI_TH}
            flags = {}
            for k, (warn, crit, low) in self.WIFI_TH.items():
                lv = level(vals[k], warn, crit, lower_is_worse=low)
                if lv:
                    flags[k] = lv
            if not flags:
                continue
            weak = "rssi_dbm" in flags or "snr_db" in flags
            causes = []
            if weak:
                causes.append("WEAK_WIFI_SIGNAL")
            if "retry_pct" in flags and not weak:
                causes.append("WIFI_INTERFERENCE")
            if "channel_utilization_pct" in flags:
                causes.append("WIFI_CHANNEL_CONGESTION")
            words = [self.WIFI_LABELS[k] for k in flags]
            issues.append({
                "headline": f"{join_words(words).capitalize()} on {w['ap']}",
                "causes": causes,
                "severity": worst(flags.values()),
                "signals": len(flags),
                "components": [w["ap"]],
                "devices": list(w.get("client_devices", [])),
                "evidence": {"ap": w["ap"],
                             **{k: v for k, v in vals.items() if v is not None},
                             "clients": w.get("clients", 0)},
            })

        healthy_evidence = {
            "interfaces_checked": len(interfaces),
            "interfaces_up": sum(1 for i in interfaces if i.get("oper_status", "UP") == "UP"),
            "total_errors": sum(i.get("crc_errors", 0) + i.get("input_errors", 0)
                                + i.get("output_errors", 0) for i in interfaces),
            "access_points_checked": len(wifi),
            "weakest_rssi_dbm": min([w.get("rssi_dbm", 0) for w in wifi], default=None),
        }
        return self._report(telemetry, issues,
                            "All interfaces up and error-free; Wi-Fi signal healthy",
                            healthy_evidence)