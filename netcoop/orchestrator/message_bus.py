"""NetCoop AI Orchestrator - Message Bus and Structured Audit Logging.

Provides:
- MessageBus abstract interface
- InProcessBus with per-agent asyncio timeout protection and concurrent delivery
- MessageLog for recording JSONL message/finding traces and human-readable one-line summaries
"""

from abc import ABC, abstractmethod
import asyncio
from datetime import datetime, timezone
import json
from pathlib import Path
from typing import Any, Dict, List, Optional, Union

from netcoop.agents.base import BaseAgent
from netcoop.protocol.messages import (
    ErrorPayload,
    FindingPayload,
    MessageEnvelope,
    MessageType,
)


class MessageBus(ABC):
    """Abstract communication bus interface for multi-agent message routing."""

    @abstractmethod
    def register(self, agent: BaseAgent) -> None:
        """Register an agent instance on the bus."""
        raise NotImplementedError

    @abstractmethod
    async def send(self, message: MessageEnvelope) -> List[MessageEnvelope]:
        """Deliver a message to its designated recipient and return outbound responses."""
        raise NotImplementedError


class MessageLog:
    """Audit logger appending JSONL traces and formatting human-readable summaries."""

    def __init__(self, log_dir: Union[str, Path] = "logs"):
        self.log_dir = Path(log_dir)
        self.log_dir.mkdir(parents=True, exist_ok=True)

    def log_message(self, message: MessageEnvelope) -> None:
        """Append envelope to messages_<incident_id>.jsonl and findings_<incident_id>.jsonl."""
        inc_id = message.incident_id or "INC-UNKNOWN"
        msg_file = self.log_dir / f"messages_{inc_id}.jsonl"
        with open(msg_file, "a", encoding="utf-8") as f:
            f.write(message.to_json() + "\n")

        if message.message_type == MessageType.FINDING:
            finding_file = self.log_dir / f"findings_{inc_id}.jsonl"
            with open(finding_file, "a", encoding="utf-8") as f:
                f.write(message.to_json() + "\n")

    def summarize(self, message: MessageEnvelope) -> str:
        """Generate a standardized one-line human summary for terminal/CLI tracing."""
        sender = message.sender
        recipient = message.recipient
        mtype = message.message_type.value
        payload = message.payload

        details = ""
        if message.message_type == MessageType.FINDING and isinstance(payload, FindingPayload):
            top_cand = payload.hypothesis_candidates[0] if payload.hypothesis_candidates else None
            dev_count = len(payload.scope.device_ids)
            cause = top_cand.cause_code.value if top_cand else "NONE"
            score = top_cand.score if top_cand else 0.0
            details = f"{cause} {score:.2f} on {dev_count} device(s)"
        elif message.message_type == MessageType.TASK_REQUEST:
            task_name = getattr(payload, "task", "unknown")
            details = f"task={task_name}"
        elif message.message_type == MessageType.FINAL_RESULT:
            stage = getattr(payload, "stage", "final")
            cause = getattr(payload, "primary_root_cause", "UNKNOWN")
            cause_str = cause.value if hasattr(cause, "value") else str(cause)
            details = f"stage={stage} cause={cause_str}"
        elif message.message_type == MessageType.CONFLICT_NOTICE:
            rule = getattr(payload, "rule", "R?")
            desc = getattr(payload, "description", "")
            details = f"{rule}: {desc[:40]}..."
        elif message.message_type == MessageType.EVIDENCE_QUERY:
            q_cause = getattr(payload, "cause_code", "evidence")
            devs = len(getattr(payload, "device_ids", []))
            details = f"query {q_cause} on {devs} device(s)"
        elif message.message_type == MessageType.EVIDENCE_RESPONSE:
            supp = getattr(payload, "supports", None)
            details = f"supports={supp}"
        elif message.message_type == MessageType.ERROR:
            err_code = getattr(payload, "error_code", "ERROR")
            err_msg = getattr(payload, "error_message", "")
            details = f"{err_code}: {err_msg[:40]}"
        else:
            details = type(payload).__name__

        return f"{sender} -> {recipient} | {mtype} | {details}"

    def read_trace(self, incident_id: str) -> List[Dict[str, Any]]:
        """Read and return all recorded messages for an incident from disk."""
        msg_file = self.log_dir / f"messages_{incident_id}.jsonl"
        if not msg_file.exists():
            return []
        records: List[Dict[str, Any]] = []
        with open(msg_file, "r", encoding="utf-8") as f:
            for line in f:
                line_str = line.strip()
                if line_str:
                    records.append(json.loads(line_str))
        return records


class InProcessBus(MessageBus):
    """Direct in-process asyncio bus with per-agent timeout protection."""

    def __init__(
        self,
        timeout_s: float = 5.0,
        message_log: Optional[MessageLog] = None,
    ):
        self.timeout_s = timeout_s
        self.message_log = message_log or MessageLog()
        self._agents: Dict[str, BaseAgent] = {}

    def register(self, agent: BaseAgent) -> None:
        """Register an agent by its unique name."""
        self._agents[agent.name] = agent

    async def send(self, message: MessageEnvelope) -> List[MessageEnvelope]:
        """Route message to recipient with timeout protection and structured error handling."""
        self.message_log.log_message(message)

        # Handle broadcast routing
        if message.recipient == "broadcast":
            tasks = []
            for name, agent in self._agents.items():
                if name != message.sender:
                    tasks.append(self._deliver(agent, message))
            nested = await asyncio.gather(*tasks)
            responses: List[MessageEnvelope] = [resp for sub in nested for resp in sub]
            return responses

        # Handle direct peer routing
        agent = self._agents.get(message.recipient)
        if not agent:
            err_env = MessageEnvelope(
                incident_id=message.incident_id,
                sender="orchestrator_bus",
                recipient=message.sender,
                message_type=MessageType.ERROR,
                correlation_id=message.message_id,
                payload=ErrorPayload(
                    error_code="ERR_AGENT_NOT_FOUND",
                    error_message=f"Recipient agent '{message.recipient}' is not registered on the bus.",
                ),
            )
            self.message_log.log_message(err_env)
            return [err_env]

        return await self._deliver(agent, message)

    async def _deliver(self, agent: BaseAgent, message: MessageEnvelope) -> List[MessageEnvelope]:
        """Deliver envelope with asyncio.wait_for timeout protection."""
        try:
            outbound = await asyncio.wait_for(agent.handle(message), timeout=self.timeout_s)
        except asyncio.TimeoutError:
            err_env = MessageEnvelope(
                incident_id=message.incident_id,
                sender=agent.name,
                recipient=message.sender,
                message_type=MessageType.ERROR,
                correlation_id=message.message_id,
                payload=ErrorPayload(
                    error_code="TIMEOUT",
                    error_message=f"Agent '{agent.name}' timed out after {self.timeout_s:.1f}s.",
                    retryable=False,
                ),
            )
            self.message_log.log_message(err_env)
            return [err_env]
        except Exception as ex:
            err_env = MessageEnvelope(
                incident_id=message.incident_id,
                sender=agent.name,
                recipient=message.sender,
                message_type=MessageType.ERROR,
                correlation_id=message.message_id,
                payload=ErrorPayload(
                    error_code="ERR_AGENT_EXCEPTION",
                    error_message=f"Agent '{agent.name}' unhandled exception: {ex}",
                ),
            )
            self.message_log.log_message(err_env)
            return [err_env]

        for resp in outbound:
            self.message_log.log_message(resp)

        return outbound