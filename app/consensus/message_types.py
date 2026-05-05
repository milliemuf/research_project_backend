"""
PBFT Message Types for Consensus Protocol.

Defines the message structures used in the three-phase PBFT protocol:
1. Pre-prepare: Leader proposes a fix
2. Prepare: Agents validate and vote
3. Commit: Agreement is reached and fix is applied

Author: Millicent Mufambi (H240624A)
"""

from dataclasses import dataclass, field
from typing import Optional, Any
from datetime import datetime
from enum import Enum
import hashlib
import json


class MessageType(str, Enum):
    """Types of consensus messages."""
    PRE_PREPARE = "pre_prepare"
    PREPARE = "prepare"
    COMMIT = "commit"
    VIEW_CHANGE = "view_change"
    NEW_VIEW = "new_view"


class ConsensusPhase(str, Enum):
    """Current phase of consensus for a fix proposal."""
    IDLE = "idle"
    PRE_PREPARE = "pre_prepare"
    PREPARE = "prepare"
    COMMIT = "commit"
    DECIDED = "decided"
    FAILED = "failed"


@dataclass
class FixProposal:
    """
    A proposed fix for a detected bug.

    This is the payload that goes through consensus.
    """
    bug_id: str
    original_code: str
    fixed_code: str
    explanation: str
    proposing_agent_id: str
    confidence_score: float
    language: str
    file_path: str
    line_number: int
    created_at: datetime = field(default_factory=datetime.utcnow)

    def compute_digest(self) -> str:
        """Compute a unique digest of the fix proposal."""
        content = json.dumps({
            "bug_id": self.bug_id,
            "original_code": self.original_code,
            "fixed_code": self.fixed_code,
            "proposing_agent_id": self.proposing_agent_id,
        }, sort_keys=True)
        return hashlib.sha256(content.encode()).hexdigest()


@dataclass
class ConsensusMessage:
    """Base class for all consensus messages."""
    message_type: MessageType
    view: int  # Current view number (changes on leader failure)
    sequence: int  # Sequence number for ordering
    sender_id: str  # Agent ID of the sender
    timestamp: datetime = field(default_factory=datetime.utcnow)
    signature: Optional[str] = None  # Cryptographic signature

    def to_dict(self) -> dict:
        """Convert message to dictionary for serialization."""
        return {
            "message_type": self.message_type.value,
            "view": self.view,
            "sequence": self.sequence,
            "sender_id": self.sender_id,
            "timestamp": self.timestamp.isoformat(),
            "signature": self.signature,
        }


@dataclass
class PrePrepareMessage(ConsensusMessage):
    """
    Pre-prepare message sent by the primary (leader) agent.

    In PBFT, the primary receives a fix proposal and broadcasts it
    to all replicas with a sequence number.
    """
    fix_proposal: Optional[FixProposal] = None
    digest: str = ""  # Hash of the fix proposal

    def __post_init__(self):
        self.message_type = MessageType.PRE_PREPARE
        if self.fix_proposal:
            self.digest = self.fix_proposal.compute_digest()

    def to_dict(self) -> dict:
        base = super().to_dict()
        base["fix_proposal"] = {
            "bug_id": self.fix_proposal.bug_id,
            "original_code": self.fix_proposal.original_code,
            "fixed_code": self.fix_proposal.fixed_code,
            "explanation": self.fix_proposal.explanation,
            "proposing_agent_id": self.fix_proposal.proposing_agent_id,
            "confidence_score": self.fix_proposal.confidence_score,
        } if self.fix_proposal else None
        base["digest"] = self.digest
        return base


@dataclass
class PrepareMessage(ConsensusMessage):
    """
    Prepare message sent by backup agents.

    After receiving a valid pre-prepare, each backup broadcasts a prepare
    message to indicate it accepts the proposal.
    """
    digest: str = ""  # Must match the pre-prepare digest
    validation_result: bool = True  # Agent's validation of the fix
    validation_confidence: float = 0.0  # Confidence in validation
    validation_reason: Optional[str] = None  # Explanation

    def __post_init__(self):
        self.message_type = MessageType.PREPARE


@dataclass
class CommitMessage(ConsensusMessage):
    """
    Commit message sent after receiving 2f prepare messages.

    Once an agent receives 2f+1 matching prepares (including its own),
    it broadcasts a commit message.
    """
    digest: str = ""

    def __post_init__(self):
        self.message_type = MessageType.COMMIT


@dataclass
class ViewChangeMessage(ConsensusMessage):
    """
    View change message for leader failure recovery.

    If the primary fails or is suspected of being faulty, agents
    initiate a view change to elect a new primary.
    """
    new_view: int = 0  # Proposed new view number
    reason: str = ""  # Reason for view change (timeout, failure, etc.)

    def __post_init__(self):
        self.message_type = MessageType.VIEW_CHANGE


@dataclass
class ConsensusRound:
    """
    Tracks the state of a single consensus round.

    Each fix proposal goes through one consensus round.
    """
    sequence: int
    view: int
    fix_proposal: FixProposal
    phase: ConsensusPhase = ConsensusPhase.IDLE
    pre_prepare: Optional[PrePrepareMessage] = None
    prepares: dict = field(default_factory=dict)  # agent_id -> PrepareMessage
    commits: dict = field(default_factory=dict)  # agent_id -> CommitMessage
    started_at: datetime = field(default_factory=datetime.utcnow)
    decided_at: Optional[datetime] = None
    decision: Optional[bool] = None  # True = approved, False = rejected

    def prepare_count(self) -> int:
        """Count of valid prepare messages received."""
        return len([p for p in self.prepares.values() if p.validation_result])

    def commit_count(self) -> int:
        """Count of commit messages received."""
        return len(self.commits)

    def duration_ms(self) -> float:
        """Duration of consensus round in milliseconds."""
        end = self.decided_at or datetime.utcnow()
        return (end - self.started_at).total_seconds() * 1000
