"""NetCoop AI Agents - Abstract Base Agent.

Provides non-crashing message handling, structured logging, inbound/outbound
Pydantic validation, incident task caching, and standardized helper constructors.
"""

import logging
from typing import Any, Dict, List, Optional, Union
import uuid

from netcoop.protocol.causes import CauseCode
from netcoop.protocol.messages import (
    DataQuality,
    ErrorPayload,
    FindingPayload,
    FindingScope,
    HypothesisCandidate,
    MessageEnvelope,
    MessageType,
    parse_message,
)
from netcoop.protocol.validators import ErrorCode


class BaseAgent:
    """Abstract base class for all NetCoop AI autonomous agents."""

    def __init__(self, config: Optional[Dict[str, Any]] = None):
        self.name: str = getattr(self, "name", self.__class__.__name__)
        self.capabilities: List[str] = getattr(self, "capabilities", [])
        self.config: Dict[str, Any] = config or {}
        self._incident_contexts: Dict[str, MessageEnvelope] = {}
        self.logger: logging.Logger = logging.getLogger(f"netcoop.agents.{self.name}")

    def context_for(self, incident_id: str) -> Optional[MessageEnvelope]:
        """Retrieve the cached inbound task request envelope for an incident."""
        return self._incident_contexts.get(incident_id)

    def make_message(
        self,
        recipient: str,
        message_type: Union[MessageType, str],
        payload: Any,
        incident_id: Optional[str] = None,
        correlation_id: Optional[str] = None,
    ) -> MessageEnvelope:
        """Helper to create a properly formatted outbound MessageEnvelope."""
        m_type = MessageType(message_type) if isinstance(message_type, str) else message_type
        inc_id = incident_id or "INC-0000"
        return MessageEnvelope(
            message_id=str(uuid.uuid4()),
            incident_id=inc_id,
            schema_version="1.0",
            sender=self.name,
            recipient=recipient,
            message_type=m_type,
            correlation_id=correlation_id,
            payload=payload,
        )

    def make_finding(
        self,
        incident_id: str,
        hypothesis_candidates: List[HypothesisCandidate],
        scope: FindingScope,
        confidence: float,
        data_quality: Optional[DataQuality] = None,
        correlation_id: Optional[str] = None,
        recipient: str = "correlation_agent",
    ) -> MessageEnvelope:
        """Construct a standardized Finding message."""
        payload = FindingPayload(
            agent=self.name,
            scope=scope,
            hypothesis_candidates=hypothesis_candidates,
            data_quality=data_quality or DataQuality(completeness=1.0),
            confidence=max(0.0, min(1.0, confidence)),
        )
        return self.make_message(
            recipient=recipient,
            message_type=MessageType.FINDING,
            payload=payload,
            incident_id=incident_id,
            correlation_id=correlation_id,
        )

    def make_error(
        self,
        error_code: Union[ErrorCode, str],
        error_message: str,
        incident_id: Optional[str] = None,
        recipient: str = "orchestrator",
        correlation_id: Optional[str] = None,
        details: Optional[Dict[str, Any]] = None,
        retryable: bool = False,
    ) -> MessageEnvelope:
        """Construct a structured Error message."""
        code_str = error_code.value if isinstance(error_code, ErrorCode) else str(error_code)
        payload = ErrorPayload(
            error_code=code_str,
            error_message=error_message,
            details=details or {},
            retryable=retryable,
        )
        return self.make_message(
            recipient=recipient,
            message_type=MessageType.ERROR,
            payload=payload,
            incident_id=incident_id or "INC-UNKNOWN",
            correlation_id=correlation_id,
        )

    async def handle(
        self,
        message: Union[MessageEnvelope, Dict[str, Any], str],
    ) -> List[MessageEnvelope]:
        """Public entry point to handle an incoming message without raising exceptions.

        Validates envelope and recipient, caches latest task request per incident,
        executes `_process()`, validates outbound envelopes, and logs progress.
        """
        # 1. Parse and validate inbound message envelope
        msg: MessageEnvelope
        try:
            if isinstance(message, (str, dict)):
                msg = parse_message(message)
            elif isinstance(message, MessageEnvelope):
                msg = message
            else:
                err_msg = f"Inbound message must be str, dict, or MessageEnvelope, got {type(message).__name__}"
                self.logger.error("Agent %s validation failure: %s", self.name, err_msg)
                return [self.make_error(ErrorCode.CORRUPTED_JSON, err_msg)]
        except Exception as ex:
            err_msg = f"Failed to parse inbound message: {str(ex)}"
            self.logger.error("Agent %s inbound parse error: %s", self.name, err_msg)
            return [self.make_error(ErrorCode.CORRUPTED_JSON, err_msg)]

        # 2. Check recipient routing
        if msg.recipient != self.name and msg.recipient != "broadcast":
            routing_err = f"Message recipient '{msg.recipient}' does not match agent '{self.name}'"
            self.logger.warning("Agent %s recipient mismatch: %s", self.name, routing_err)
            return [
                self.make_error(
                    error_code="ERR_WRONG_RECIPIENT",
                    error_message=routing_err,
                    incident_id=msg.incident_id,
                    recipient=msg.sender,
                    correlation_id=msg.message_id,
                )
            ]

        # 3. Cache latest task_request per incident
        if msg.message_type == MessageType.TASK_REQUEST:
            self._incident_contexts[msg.incident_id] = msg

        # 4. Delegate to subclass _process implementation
        outbound: List[MessageEnvelope] = []
        try:
            outbound = await self._process(msg)
        except Exception as ex:
            self.logger.error(
                "Agent %s unhandled exception in _process for message %s: %s",
                self.name,
                msg.message_id,
                str(ex),
                exc_info=True,
            )
            return [
                self.make_error(
                    error_code="ERR_AGENT_PROCESSING_FAILED",
                    error_message=f"Agent '{self.name}' internal processing exception: {str(ex)}",
                    incident_id=msg.incident_id,
                    recipient=msg.sender,
                    correlation_id=msg.message_id,
                )
            ]

        # 5. Validate outbound messages
        validated_outbound: List[MessageEnvelope] = []
        for out in outbound:
            if isinstance(out, MessageEnvelope):
                validated_outbound.append(out)
            elif isinstance(out, dict):
                try:
                    validated_outbound.append(parse_message(out))
                except Exception as ex:
                    self.logger.error("Agent %s produced invalid outbound message dict: %s", self.name, ex)
            else:
                self.logger.error("Agent %s produced unsupported outbound type: %s", self.name, type(out).__name__)

        # 6. Structured logging: one line per handled message
        self.logger.info(
            "Agent %s successfully handled message %s [type=%s, incident=%s] -> produced %d outbound message(s)",
            self.name,
            msg.message_id,
            msg.message_type.value,
            msg.incident_id,
            len(validated_outbound),
        )

        return validated_outbound

    async def _process(self, message: MessageEnvelope) -> List[MessageEnvelope]:
        """Subclass implementation hook. Must be implemented by specialized agents."""
        raise NotImplementedError(f"Agent '{self.name}' has not implemented _process()")