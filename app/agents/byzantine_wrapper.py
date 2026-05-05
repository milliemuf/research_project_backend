"""
Byzantine wrapper — make an agent deliberately misbehave for fault-injection
experiments. Wraps any BaseAgent subclass and overrides its `process(...)`
method with one of several Byzantine behaviours.

Used by the benchmark harness via `--inject-fault {behaviour}` and
`--inject-fault-count N` to demonstrate the safety guarantees of the
H-BFT pipeline under up to f Byzantine validators (review §VI metric 5,
§VIII-E item 5).

Author: Millicent Mufambi (H240624A)
"""
from __future__ import annotations

import asyncio
import random
from datetime import datetime
from enum import Enum
from typing import Any

import structlog

from app.agents.base_agent import AgentOutput

logger = structlog.get_logger(__name__)


class ByzantineBehaviour(str, Enum):
    NONE = "none"
    ALWAYS_REJECT = "always_reject"        # Vote NO no matter what (denial-of-service)
    ALWAYS_APPROVE = "always_approve"      # Vote YES no matter what (most dangerous: lets bad fixes pass)
    RANDOM = "random"                      # Flip a coin
    TIMEOUT = "timeout"                    # Sleep past the round timeout (simulates crash)
    GARBAGE = "garbage"                    # Return a malformed result


class ByzantineWrapper:
    """
    Wraps an agent and makes it misbehave according to `behaviour`.

    The wrapper exposes the same surface as the wrapped agent (agent_id,
    agent_type, llm_provider, set_llm_client, update_reputation, accuracy,
    average_latency_ms, get_stats, process) so the rest of the system
    cannot tell it apart from a real agent.
    """

    def __init__(self, real_agent: Any, behaviour: ByzantineBehaviour):
        self.real = real_agent
        self.behaviour = ByzantineBehaviour(behaviour)
        # Mirror the surface of the real agent
        self.agent_id = real_agent.agent_id
        self.agent_type = real_agent.agent_type
        self.llm_provider = real_agent.llm_provider
        self.config = real_agent.config

        logger.warning(
            "Byzantine wrapper installed",
            agent_id=self.agent_id,
            behaviour=self.behaviour.value,
        )

    # --- pass-throughs for things the rest of the system uses --------------
    @property
    def reputation_score(self):
        return self.real.reputation_score

    @reputation_score.setter
    def reputation_score(self, v):
        self.real.reputation_score = v

    @property
    def total_tasks(self):
        return self.real.total_tasks

    @property
    def successful_tasks(self):
        return self.real.successful_tasks

    @property
    def accuracy(self):
        return self.real.accuracy

    @property
    def average_latency_ms(self):
        return self.real.average_latency_ms

    def set_llm_client(self, client):
        return self.real.set_llm_client(client)

    def update_reputation(self, success):
        return self.real.update_reputation(success)

    def get_stats(self):
        s = self.real.get_stats()
        s["byzantine_behaviour"] = self.behaviour.value
        return s

    # --- the misbehaving entry point --------------------------------------
    async def process(self, input_data: Any) -> AgentOutput:
        start = datetime.utcnow()

        if self.behaviour == ByzantineBehaviour.TIMEOUT:
            try:
                await asyncio.sleep(120)
            except asyncio.CancelledError:
                pass
            return self._fake_output(False, 0.0, start, "byzantine timeout")

        if self.behaviour == ByzantineBehaviour.GARBAGE:
            return self._fake_output(False, 0.0, start, "garbage output")

        if self.behaviour == ByzantineBehaviour.ALWAYS_REJECT:
            return self._fake_output(False, 0.95, start, "byzantine always-reject")

        if self.behaviour == ByzantineBehaviour.ALWAYS_APPROVE:
            return self._fake_output(True, 0.95, start, "byzantine always-approve")

        if self.behaviour == ByzantineBehaviour.RANDOM:
            decision = random.choice([True, False])
            return self._fake_output(decision, 0.5, start, "byzantine random")

        # ByzantineBehaviour.NONE — just defer to the real agent
        return await self.real.process(input_data)

    def _fake_output(self, is_valid: bool, confidence: float,
                     start: datetime, reason: str) -> AgentOutput:
        from app.agents.validator_agent import ValidationResult
        latency = (datetime.utcnow() - start).total_seconds() * 1000
        return AgentOutput(
            agent_id=self.agent_id,
            agent_type=self.agent_type,
            success=True,
            result=ValidationResult(
                is_valid=is_valid,
                confidence=confidence,
                syntax_valid=True,
                safety_score=0.5,
                issues=[reason] if not is_valid else [],
                recommendations=[],
            ),
            confidence=confidence,
            reasoning=reason,
            latency_ms=latency,
            metadata={"byzantine": True, "behaviour": self.behaviour.value},
        )
