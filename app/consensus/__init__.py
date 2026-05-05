"""
Consensus module for Byzantine Fault-Tolerant Multi-Agent System.

This module implements Practical Byzantine Fault Tolerance (PBFT) for achieving
consensus among multiple AI agents on code repair decisions.

Key Innovation: First application of BFT to automated program repair.
"""

from app.consensus.pbft import PBFTConsensus, ConsensusResult
from app.consensus.message_types import (
    ConsensusMessage,
    PrePrepareMessage,
    PrepareMessage,
    CommitMessage,
    ViewChangeMessage,
)

__all__ = [
    "PBFTConsensus",
    "ConsensusResult",
    "ConsensusMessage",
    "PrePrepareMessage",
    "PrepareMessage",
    "CommitMessage",
    "ViewChangeMessage",
]
