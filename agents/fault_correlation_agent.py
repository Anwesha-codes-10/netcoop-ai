"""Fault Correlation Agent (Member 2) - combines the three agents' findings into one diagnosis."""
from utils.message_protocol import canonical, validate_finding


class FaultCorrelationAgent:
    name = "Fault Correlation Agent"
    CONFLICT_RATIO = 0.4    # runner-up >= 40% of winner's score => conflict reported
    SEGMENT_BONUS = 0.03    # agents point at the same device/link
    MAX_CONF = 0.97

    def correlate(self, findings, telemetry=None):
        for f in findings:
            validate_finding(f)
        issues = [f for f in findings if f["status"] == "ISSUE_DETECTED"]

        if not issues:
            return self._result("NO_FAULT", 0.95, [], [], [], False, [],
                                ["All agents report HEALTHY - no fault to correlate"])

        # 1. every agent votes for diagnoses, best-ranked cause weighs most
        votes = {}
        for f in issues:
            seen = {}
            for rank, cause in enumerate(f["possible_causes"]):
                seen.setdefault(canonical(cause), f["confidence"] / (1 + rank))
            for diag, w in seen.items():
                votes.setdefault(diag, {})[f["agent"]] = round(w, 3)
        if not votes:
            return self._result("UNKNOWN", 0.3, [], [], [], False, [],
                                ["Agents detected issues but suggested no cause"])

        # 2. score + confidence for every candidate diagnosis
        scores = {d: round(sum(v.values()), 3) for d, v in votes.items()}
        total = sum(scores.values())
        candidates = []
        for diag, score in sorted(scores.items(), key=lambda x: -x[1]):
            others = max([s for d, s in scores.items() if d != diag], default=0)
            margin = max(0.0, (score - others) / score) if others else 1.0
            p = 1.0
            for w in votes[diag].values():          # independent agents reinforce each other
                p *= 1 - min(w, 0.99)
            shared = self._shared_components(votes[diag], issues, telemetry)
            conf = (1 - p) * (0.75 + 0.25 * margin) + (self.SEGMENT_BONUS if shared else 0)
            candidates.append({
                "diagnosis": diag, "score": score,
                "share_pct": round(100 * score / total),
                "confidence": round(min(conf, self.MAX_CONF), 2),
                "supporting_agents": list(votes[diag]),
                "shared_components": shared,
            })

        top = candidates[0]
        conflict = len(candidates) > 1 and candidates[1]["score"] >= self.CONFLICT_RATIO * top["score"]

        # 3. human-readable reasoning trail
        by_agent = {f["agent"]: f for f in issues}
        reasoning = [f"{a}: {by_agent[a]['finding']} (confidence {by_agent[a]['confidence']:.0%})"
                     for a in top["supporting_agents"]]
        if top["shared_components"]:
            reasoning.append("Agents point at the same segment: " + ", ".join(top["shared_components"]))
        if len(candidates) > 1:
            runner = candidates[1]
            ratio = top["score"] / runner["score"]
            if conflict:
                reasoning.append(
                    f"Conflict: {top['diagnosis']} (score {top['score']}) vs "
                    f"{runner['diagnosis']} (score {runner['score']}). Resolved in favour of "
                    f"{top['diagnosis']}: backed by {len(top['supporting_agents'])} agent(s), "
                    f"evidence weight {ratio:.1f}x higher")
            else:
                reasoning.append(f"Alternative considered: {runner['diagnosis']} "
                                 f"(score {runner['score']}), much weaker")
        return self._result(top["diagnosis"], top["confidence"], top["supporting_agents"],
                            top["shared_components"], candidates, conflict, candidates[1:], reasoning)

    # ------------------------------------------------------------------
    def _shared_components(self, supporters, issues, telemetry):
        """Devices/links that at least two supporting agents both point at."""
        seen = {}
        for f in issues:
            if f["agent"] not in supporters:
                continue
            ents = set()
            for comp in f.get("affected_components", []):
                ents |= self._entities(comp, telemetry)
            for e in ents:
                seen.setdefault(e, set()).add(f["agent"])
        return sorted(e for e, agents in seen.items() if len(agents) >= 2)

    @staticmethod
    def _entities(component, telemetry):
        ents = {component}
        if ":" in component:
            ents.add(component.split(":")[0])
        for link in (telemetry or {}).get("links", []):
            if link["id"] == component:
                ents.update([link["src"], link["dst"]])
        return ents

    def _result(self, diagnosis, confidence, supporting, shared, candidates,
                conflict, alternatives, reasoning):
        return {"agent": self.name, "diagnosis": diagnosis, "confidence": confidence,
                "supporting_agents": supporting, "shared_components": shared,
                "conflict_detected": conflict, "alternative_causes": alternatives,
                "candidates": candidates, "reasoning": reasoning}