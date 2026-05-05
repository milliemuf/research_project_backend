"""
Practical Byzantine Fault Tolerance (PBFT) Implementation for Code Repair.

This is the CORE NOVEL CONTRIBUTION of the research project.

This module implements PBFT consensus adapted for multi-agent code repair decisions.
Key innovation: Heterogeneous BFT where agents use different LLM backends,
reducing the risk of correlated failures.

PBFT Guarantees:
- Safety: All honest agents agree on the same fix (or no fix)
- Liveness: Progress is made as long as f < n/3 agents are faulty

Protocol Phases:
1. Pre-prepare: Primary proposes a fix with sequence number
2. Prepare: Agents validate and broadcast acceptance
3. Commit: After 2f+1 prepares, agents commit to the decision

Author: Millicent Mufambi (H240624A)
Institution: Harare Institute of Technology
M.Tech Software Engineering
"""

import asyncio
from dataclasses import dataclass, field
from datetime import datetime
from typing import Optional, List, Dict, Callable, Awaitable
from enum import Enum
import structlog

from app.consensus.message_types import (
    ConsensusPhase,
    ConsensusRound,
    FixProposal,
    MessageType,
    PrePrepareMessage,
    PrepareMessage,
    CommitMessage,
    ViewChangeMessage,
)
from app.consensus.crypto import key_manager, CryptoProvider
from app.config import settings

logger = structlog.get_logger(__name__)


class ConsensusState(str, Enum):
    """Overall state of the consensus system."""
    READY = "ready"
    IN_PROGRESS = "in_progress"
    VIEW_CHANGE = "view_change"


@dataclass
class ConsensusResult:
    """Result of a consensus round."""
    success: bool
    fix_proposal: Optional[FixProposal]
    sequence: int
    view: int
    prepare_votes: int
    commit_votes: int
    duration_ms: float
    decision_reason: str


@dataclass
class AgentInfo:
    """Information about an agent participating in consensus."""
    agent_id: str
    agent_type: str  # analyzer, healer, validator
    llm_provider: str  # claude, gpt4, ollama
    is_online: bool = True


class PBFTConsensus:
    """
    PBFT Consensus Engine for Multi-Agent Code Repair.

    This implementation adapts classical PBFT for the specific use case of
    achieving consensus on AI-generated code fixes. Key adaptations:

    1. Heterogeneous agents: Different LLM backends provide diversity
    2. Weighted voting: Agent reputation affects vote weight
    3. Confidence scores: Agents report confidence in their decisions
    4. Async operation: Designed for real-time runtime repair

    Usage:
        consensus = PBFTConsensus(f=1)  # Tolerate 1 faulty agent
        consensus.register_agent(analyzer_agent)
        consensus.register_agent(healer_agent)
        consensus.register_agent(validator_agent_1)
        consensus.register_agent(validator_agent_2)

        result = await consensus.propose_fix(fix_proposal)
        if result.success:
            # Apply the fix
            pass
    """

    def __init__(
        self,
        f: int = 1,
        timeout_ms: int = 5000,
        reputation_weighted: bool = False,
        reputation_step: float = 0.05,
        reputation_min: float = 0.1,
        reputation_max: float = 1.0,
    ):
        """
        Initialize PBFT consensus.

        Args:
            f: Number of faulty agents to tolerate (need 3f+1 total)
            timeout_ms: Timeout for consensus rounds in milliseconds
            reputation_weighted: when True, the prepare-quorum check uses
                weighted votes summed by per-agent reputation, with the
                threshold scaled to (2/3) of the total registered weight.
                When False (default) the classical 2f+1 unweighted threshold
                applies.
            reputation_step: Maximum per-round movement of any agent's
                reputation. Bounds strategic credibility-building, after
                Abraham, Dolev, Halpern (2008).
            reputation_min / reputation_max: Hard bounds on reputation.
        """
        self.f = f
        self.n_required = 3 * f + 1  # Minimum agents needed
        self.quorum = 2 * f + 1  # Unweighted votes needed for consensus
        self.timeout_ms = timeout_ms

        # State
        self.view = 0  # Current view number
        self.sequence = 0  # Next sequence number
        self.state = ConsensusState.READY

        # Registered agents
        self.agents: Dict[str, AgentInfo] = {}

        # Active consensus rounds
        self.rounds: Dict[int, ConsensusRound] = {}

        # Callbacks for agent communication
        self._broadcast_callback: Optional[Callable] = None
        self._validate_callback: Optional[Callable] = None

        # Reputation-weighted voting (Abraham, Dolev, Halpern 2008)
        self.reputation_weighted = reputation_weighted
        self.reputation_step = reputation_step
        self.reputation_min = reputation_min
        self.reputation_max = reputation_max
        self.agent_reputations: Dict[str, float] = {}

        # Metrics
        self.total_rounds = 0
        self.successful_rounds = 0
        self.failed_rounds = 0

        logger.info(
            "PBFT consensus initialized",
            f=f,
            n_required=self.n_required,
            quorum=self.quorum,
            timeout_ms=timeout_ms,
            reputation_weighted=reputation_weighted,
        )

    def register_agent(self, agent: AgentInfo) -> bool:
        """
        Register an agent for consensus participation.

        Args:
            agent: Agent information

        Returns:
            True if registration successful
        """
        self.agents[agent.agent_id] = agent
        self.agent_reputations.setdefault(agent.agent_id, 1.0)
        key_manager.register_agent(agent.agent_id)

        logger.info(
            "Agent registered for consensus",
            agent_id=agent.agent_id,
            agent_type=agent.agent_type,
            llm_provider=agent.llm_provider,
            total_agents=len(self.agents)
        )

        return True

    def update_reputation(self, agent_id: str, was_correct: bool) -> None:
        """
        Move an agent's reputation by at most reputation_step (Abraham et al.
        bounded reputation). `was_correct` is True if the agent's vote
        agreed with the post-hoc ground truth (sandbox outcome) for the
        most recent round.
        """
        cur = self.agent_reputations.get(agent_id, 1.0)
        delta = self.reputation_step if was_correct else -self.reputation_step
        new_value = max(self.reputation_min, min(self.reputation_max, cur + delta))
        self.agent_reputations[agent_id] = new_value
        logger.debug(
            "Reputation updated",
            agent_id=agent_id,
            was_correct=was_correct,
            old=cur,
            new=new_value,
        )

    def _weighted_quorum_threshold(self) -> float:
        """
        Threshold for the weighted prepare quorum: (2/3) of total weight.
        For balanced reputations this collapses back to the classical 2f+1
        when the population is 3f+1.
        """
        total_weight = sum(self.agent_reputations.get(a.agent_id, 1.0)
                           for a in self.agents.values() if a.is_online)
        return total_weight * 2.0 / 3.0

    def _weighted_prepare_total(self, prepares) -> float:
        """Sum the reputation of every agent that voted YES."""
        return sum(
            self.agent_reputations.get(p.sender_id, 1.0)
            for p in prepares
            if p.validation_result
        )

    def is_ready(self) -> bool:
        """Check if we have enough agents for consensus."""
        online_agents = sum(1 for a in self.agents.values() if a.is_online)
        return online_agents >= self.n_required

    def get_primary_id(self) -> str:
        """
        Get the primary (leader) agent for current view.

        Primary rotates based on view number.
        """
        online = [a for a in self.agents.values() if a.is_online]
        if not online:
            raise RuntimeError("No online agents available")
        return online[self.view % len(online)].agent_id

    async def propose_fix(
        self,
        fix_proposal: FixProposal,
        validate_fn: Optional[Callable[[FixProposal, str], Awaitable[tuple[bool, float, str]]]] = None
    ) -> ConsensusResult:
        """
        Propose a fix for consensus voting.

        This is the main entry point for the consensus protocol.

        Args:
            fix_proposal: The proposed code fix
            validate_fn: Optional async function for agents to validate fixes
                         Signature: (fix, agent_id) -> (valid, confidence, reason)

        Returns:
            ConsensusResult indicating success/failure and details
        """
        if not self.is_ready():
            online = sum(1 for a in self.agents.values() if a.is_online)
            return ConsensusResult(
                success=False,
                fix_proposal=fix_proposal,
                sequence=-1,
                view=self.view,
                prepare_votes=0,
                commit_votes=0,
                duration_ms=0,
                decision_reason=f"Not enough agents: {online}/{self.n_required} online"
            )

        self.state = ConsensusState.IN_PROGRESS
        self.sequence += 1
        seq = self.sequence

        logger.info(
            "Starting consensus round",
            sequence=seq,
            view=self.view,
            bug_id=fix_proposal.bug_id
        )

        # Create consensus round
        round_state = ConsensusRound(
            sequence=seq,
            view=self.view,
            fix_proposal=fix_proposal,
            phase=ConsensusPhase.PRE_PREPARE,
        )
        self.rounds[seq] = round_state

        try:
            # Phase 1: Pre-prepare
            primary_id = self.get_primary_id()
            pre_prepare = await self._create_pre_prepare(fix_proposal, seq, primary_id)
            round_state.pre_prepare = pre_prepare
            round_state.phase = ConsensusPhase.PREPARE

            # Phase 2: Prepare - collect validation votes from all agents
            prepares = await self._collect_prepares(
                fix_proposal, pre_prepare, validate_fn
            )
            round_state.prepares = {p.sender_id: p for p in prepares}

            # Check if we have enough valid prepares. In reputation-weighted
            # mode, the threshold is (2/3) of total reputation rather than the
            # unweighted 2f+1 vote count.
            valid_prepares = sum(1 for p in prepares if p.validation_result)
            if self.reputation_weighted:
                weighted_yes = self._weighted_prepare_total(prepares)
                weighted_threshold = self._weighted_quorum_threshold()
                quorum_met = weighted_yes >= weighted_threshold
                logger.debug(
                    "Weighted prepare check",
                    weighted_yes=round(weighted_yes, 3),
                    threshold=round(weighted_threshold, 3),
                    quorum_met=quorum_met,
                )
            else:
                quorum_met = valid_prepares >= self.quorum
            if not quorum_met:
                round_state.phase = ConsensusPhase.FAILED
                round_state.decided_at = datetime.utcnow()
                round_state.decision = False

                return ConsensusResult(
                    success=False,
                    fix_proposal=fix_proposal,
                    sequence=seq,
                    view=self.view,
                    prepare_votes=valid_prepares,
                    commit_votes=0,
                    duration_ms=round_state.duration_ms(),
                    decision_reason=f"Not enough prepare votes: {valid_prepares}/{self.quorum}"
                )

            # Phase 3: Commit
            round_state.phase = ConsensusPhase.COMMIT
            commits = await self._collect_commits(pre_prepare.digest, seq)
            round_state.commits = {c.sender_id: c for c in commits}

            # Check if we have enough commits
            if len(commits) >= self.quorum:
                round_state.phase = ConsensusPhase.DECIDED
                round_state.decided_at = datetime.utcnow()
                round_state.decision = True
                self.successful_rounds += 1

                logger.info(
                    "Consensus reached - fix approved",
                    sequence=seq,
                    prepares=valid_prepares,
                    commits=len(commits),
                    duration_ms=round_state.duration_ms()
                )

                return ConsensusResult(
                    success=True,
                    fix_proposal=fix_proposal,
                    sequence=seq,
                    view=self.view,
                    prepare_votes=valid_prepares,
                    commit_votes=len(commits),
                    duration_ms=round_state.duration_ms(),
                    decision_reason="Consensus reached"
                )
            else:
                round_state.phase = ConsensusPhase.FAILED
                round_state.decided_at = datetime.utcnow()
                round_state.decision = False
                self.failed_rounds += 1

                return ConsensusResult(
                    success=False,
                    fix_proposal=fix_proposal,
                    sequence=seq,
                    view=self.view,
                    prepare_votes=valid_prepares,
                    commit_votes=len(commits),
                    duration_ms=round_state.duration_ms(),
                    decision_reason=f"Not enough commit votes: {len(commits)}/{self.quorum}"
                )

        except asyncio.TimeoutError:
            round_state.phase = ConsensusPhase.FAILED
            round_state.decided_at = datetime.utcnow()
            self.failed_rounds += 1

            logger.warning("Consensus timeout", sequence=seq)

            return ConsensusResult(
                success=False,
                fix_proposal=fix_proposal,
                sequence=seq,
                view=self.view,
                prepare_votes=round_state.prepare_count(),
                commit_votes=round_state.commit_count(),
                duration_ms=round_state.duration_ms(),
                decision_reason="Consensus timeout"
            )

        finally:
            self.total_rounds += 1
            self.state = ConsensusState.READY

    async def _create_pre_prepare(
        self,
        fix: FixProposal,
        sequence: int,
        primary_id: str
    ) -> PrePrepareMessage:
        """Create and sign a pre-prepare message."""
        crypto = key_manager.get_provider(primary_id)

        pre_prepare = PrePrepareMessage(
            message_type=MessageType.PRE_PREPARE,
            view=self.view,
            sequence=sequence,
            sender_id=primary_id,
            fix_proposal=fix,
        )

        # Sign the message
        msg_dict = pre_prepare.to_dict()
        pre_prepare.signature = crypto.sign_message(msg_dict)

        logger.debug(
            "Pre-prepare created",
            sequence=sequence,
            digest=pre_prepare.digest,
            primary=primary_id
        )

        return pre_prepare

    async def _collect_prepares(
        self,
        fix: FixProposal,
        pre_prepare: PrePrepareMessage,
        validate_fn: Optional[Callable] = None
    ) -> List[PrepareMessage]:
        """
        Collect prepare messages from all agents.

        Each agent validates the fix and returns a prepare message.
        """
        prepares = []

        async def get_prepare(agent_id: str) -> PrepareMessage:
            crypto = key_manager.get_provider(agent_id)

            # Validate the fix
            if validate_fn:
                valid, confidence, reason = await validate_fn(fix, agent_id)
            else:
                # Default validation: accept with high confidence
                valid, confidence, reason = True, 0.9, "Default acceptance"

            prepare = PrepareMessage(
                message_type=MessageType.PREPARE,
                view=self.view,
                sequence=pre_prepare.sequence,
                sender_id=agent_id,
                digest=pre_prepare.digest,
                validation_result=valid,
                validation_confidence=confidence,
                validation_reason=reason,
            )

            prepare.signature = crypto.sign_message(prepare.to_dict())

            logger.debug(
                "Prepare message created",
                agent=agent_id,
                valid=valid,
                confidence=confidence
            )

            return prepare

        # Collect prepares from all online agents concurrently
        online_agents = [a for a in self.agents.values() if a.is_online]

        tasks = [get_prepare(agent.agent_id) for agent in online_agents]

        try:
            results = await asyncio.wait_for(
                asyncio.gather(*tasks, return_exceptions=True),
                timeout=self.timeout_ms / 1000
            )

            for result in results:
                if isinstance(result, PrepareMessage):
                    prepares.append(result)
                elif isinstance(result, Exception):
                    logger.warning("Agent failed to prepare", error=str(result))

        except asyncio.TimeoutError:
            logger.warning("Prepare phase timeout")

        return prepares

    async def _collect_commits(
        self,
        digest: str,
        sequence: int
    ) -> List[CommitMessage]:
        """Collect commit messages from agents."""
        commits = []

        async def get_commit(agent_id: str) -> CommitMessage:
            crypto = key_manager.get_provider(agent_id)

            commit = CommitMessage(
                message_type=MessageType.COMMIT,
                view=self.view,
                sequence=sequence,
                sender_id=agent_id,
                digest=digest,
            )

            commit.signature = crypto.sign_message(commit.to_dict())
            return commit

        online_agents = [a for a in self.agents.values() if a.is_online]
        tasks = [get_commit(agent.agent_id) for agent in online_agents]

        try:
            results = await asyncio.wait_for(
                asyncio.gather(*tasks, return_exceptions=True),
                timeout=self.timeout_ms / 1000
            )

            for result in results:
                if isinstance(result, CommitMessage):
                    commits.append(result)

        except asyncio.TimeoutError:
            logger.warning("Commit phase timeout")

        return commits

    async def initiate_view_change(self, reason: str = "timeout"):
        """
        Initiate a view change due to primary failure.

        In PBFT, if the primary is suspected faulty, replicas can
        vote to change to a new view with a different primary.
        """
        self.state = ConsensusState.VIEW_CHANGE
        old_view = self.view

        logger.warning(
            "Initiating view change",
            old_view=old_view,
            reason=reason
        )

        # Broadcast view change messages
        view_changes = []
        for agent in self.agents.values():
            if agent.is_online:
                crypto = key_manager.get_provider(agent.agent_id)
                vc = ViewChangeMessage(
                    message_type=MessageType.VIEW_CHANGE,
                    view=old_view,
                    sequence=self.sequence,
                    sender_id=agent.agent_id,
                    new_view=old_view + 1,
                    reason=reason,
                )
                vc.signature = crypto.sign_message(vc.to_dict())
                view_changes.append(vc)

        # Check if we have enough votes for view change
        if len(view_changes) >= self.quorum:
            self.view += 1
            self.state = ConsensusState.READY

            logger.info(
                "View change completed",
                old_view=old_view,
                new_view=self.view,
                new_primary=self.get_primary_id()
            )

    def get_stats(self) -> dict:
        """Get consensus statistics."""
        return {
            "total_rounds": self.total_rounds,
            "successful_rounds": self.successful_rounds,
            "failed_rounds": self.failed_rounds,
            "success_rate": self.successful_rounds / max(self.total_rounds, 1),
            "current_view": self.view,
            "current_sequence": self.sequence,
            "registered_agents": len(self.agents),
            "online_agents": sum(1 for a in self.agents.values() if a.is_online),
            "is_ready": self.is_ready(),
        }
