"""
Unit Tests for PBFT Consensus Engine.

These tests validate the core research contribution:
Byzantine Fault-Tolerant consensus for automated program repair.

Author: Millicent Mufambi (H240624A)
"""

import pytest
import asyncio
from datetime import datetime

from app.consensus.pbft import PBFTConsensus, ConsensusResult, AgentInfo
from app.consensus.message_types import (
    FixProposal,
    ConsensusPhase,
    PrePrepareMessage,
    PrepareMessage,
    CommitMessage,
)
from app.consensus.crypto import CryptoProvider, key_manager


class TestPBFTInitialization:
    """Test PBFT consensus initialization."""

    def test_default_initialization(self):
        """Test default PBFT initialization with f=1."""
        consensus = PBFTConsensus(f=1)

        assert consensus.f == 1
        assert consensus.n_required == 4  # 3f+1 = 4
        assert consensus.quorum == 3  # 2f+1 = 3
        assert consensus.view == 0
        assert consensus.sequence == 0

    def test_custom_fault_tolerance(self):
        """Test PBFT with different fault tolerance levels."""
        # f=2 should require 7 agents
        consensus = PBFTConsensus(f=2)
        assert consensus.n_required == 7
        assert consensus.quorum == 5

        # f=3 should require 10 agents
        consensus = PBFTConsensus(f=3)
        assert consensus.n_required == 10
        assert consensus.quorum == 7

    def test_agent_registration(self):
        """Test agent registration."""
        consensus = PBFTConsensus(f=1)

        agent = AgentInfo(
            agent_id="analyzer-01",
            agent_type="analyzer",
            llm_provider="claude"
        )

        result = consensus.register_agent(agent)
        assert result is True
        assert "analyzer-01" in consensus.agents
        assert consensus.agents["analyzer-01"].llm_provider == "claude"

    def test_is_ready_with_insufficient_agents(self):
        """Test that system reports not ready with insufficient agents."""
        consensus = PBFTConsensus(f=1)

        # Only register 3 agents (need 4)
        for i in range(3):
            consensus.register_agent(AgentInfo(
                agent_id=f"agent-{i}",
                agent_type="validator",
                llm_provider="ollama"
            ))

        assert consensus.is_ready() is False

    def test_is_ready_with_sufficient_agents(self):
        """Test that system reports ready with sufficient agents."""
        consensus = PBFTConsensus(f=1)

        # Register 4 agents (minimum for f=1)
        for i in range(4):
            consensus.register_agent(AgentInfo(
                agent_id=f"agent-{i}",
                agent_type="validator",
                llm_provider="ollama"
            ))

        assert consensus.is_ready() is True


class TestFixProposal:
    """Test FixProposal message creation and hashing."""

    def test_fix_proposal_creation(self):
        """Test creating a fix proposal."""
        fix = FixProposal(
            bug_id="bug-123",
            original_code="x = None\nprint(x.value)",
            fixed_code="x = None\nif x:\n    print(x.value)",
            explanation="Added null check",
            proposing_agent_id="healer-01",
            confidence_score=0.85,
            language="python",
            file_path="test.py",
            line_number=2
        )

        assert fix.bug_id == "bug-123"
        assert fix.confidence_score == 0.85

    def test_fix_proposal_digest(self):
        """Test that digest is deterministic."""
        fix1 = FixProposal(
            bug_id="bug-123",
            original_code="code",
            fixed_code="fixed",
            explanation="fix",
            proposing_agent_id="agent-01",
            confidence_score=0.9,
            language="python",
            file_path="test.py",
            line_number=1
        )

        fix2 = FixProposal(
            bug_id="bug-123",
            original_code="code",
            fixed_code="fixed",
            explanation="fix",
            proposing_agent_id="agent-01",
            confidence_score=0.9,
            language="python",
            file_path="test.py",
            line_number=1
        )

        # Same content should produce same digest
        assert fix1.compute_digest() == fix2.compute_digest()

    def test_different_fixes_different_digests(self):
        """Test that different fixes produce different digests."""
        fix1 = FixProposal(
            bug_id="bug-123",
            original_code="code",
            fixed_code="fixed1",
            explanation="fix",
            proposing_agent_id="agent-01",
            confidence_score=0.9,
            language="python",
            file_path="test.py",
            line_number=1
        )

        fix2 = FixProposal(
            bug_id="bug-123",
            original_code="code",
            fixed_code="fixed2",  # Different fix
            explanation="fix",
            proposing_agent_id="agent-01",
            confidence_score=0.9,
            language="python",
            file_path="test.py",
            line_number=1
        )

        assert fix1.compute_digest() != fix2.compute_digest()


class TestCryptography:
    """Test cryptographic signing and verification."""

    def test_sign_and_verify(self):
        """Test message signing and verification."""
        crypto = CryptoProvider("agent-01")

        message = {
            "type": "prepare",
            "view": 0,
            "sequence": 1,
            "digest": "abc123"
        }

        signature = crypto.sign_message(message)
        assert signature is not None
        assert len(signature) > 0

        # Verify the signature
        is_valid = crypto.verify_signature(message, signature, "agent-01")
        assert is_valid is True

    def test_invalid_signature_rejected(self):
        """Test that invalid signatures are rejected."""
        crypto = CryptoProvider("agent-01")

        message = {
            "type": "prepare",
            "view": 0,
            "sequence": 1
        }

        # Create valid signature
        signature = crypto.sign_message(message)

        # Modify message
        message["sequence"] = 2

        # Verification should fail
        is_valid = crypto.verify_signature(message, signature, "agent-01")
        assert is_valid is False

    def test_different_agents_different_signatures(self):
        """Test that different agents produce different signatures."""
        crypto1 = CryptoProvider("agent-01")
        crypto2 = CryptoProvider("agent-02")

        message = {"data": "test"}

        sig1 = crypto1.sign_message(message)
        sig2 = crypto2.sign_message(message)

        assert sig1 != sig2


class TestConsensusMessages:
    """Test consensus message creation."""

    def test_pre_prepare_message(self):
        """Test PrePrepare message creation."""
        fix = FixProposal(
            bug_id="bug-123",
            original_code="code",
            fixed_code="fixed",
            explanation="fix",
            proposing_agent_id="agent-01",
            confidence_score=0.9,
            language="python",
            file_path="test.py",
            line_number=1
        )

        msg = PrePrepareMessage(
            view=0,
            sequence=1,
            sender_id="primary-01",
            fix_proposal=fix
        )

        assert msg.view == 0
        assert msg.sequence == 1
        assert msg.digest == fix.compute_digest()

    def test_prepare_message(self):
        """Test Prepare message creation."""
        msg = PrepareMessage(
            view=0,
            sequence=1,
            sender_id="agent-01",
            digest="abc123",
            validation_result=True,
            validation_confidence=0.85,
            validation_reason="Fix looks correct"
        )

        assert msg.validation_result is True
        assert msg.validation_confidence == 0.85

    def test_commit_message(self):
        """Test Commit message creation."""
        msg = CommitMessage(
            view=0,
            sequence=1,
            sender_id="agent-01",
            digest="abc123"
        )

        assert msg.digest == "abc123"


class TestConsensusProtocol:
    """Test the full PBFT consensus protocol."""

    @pytest.fixture
    def setup_consensus(self):
        """Set up consensus with 4 agents."""
        consensus = PBFTConsensus(f=1, timeout_ms=1000)

        # Register 4 agents (3f+1 for f=1)
        agents = [
            AgentInfo("analyzer-01", "analyzer", "claude"),
            AgentInfo("healer-01", "healer", "gpt4"),
            AgentInfo("validator-01", "validator", "ollama"),
            AgentInfo("validator-02", "validator", "ollama"),
        ]

        for agent in agents:
            consensus.register_agent(agent)

        return consensus

    @pytest.mark.asyncio
    async def test_successful_consensus(self, setup_consensus):
        """Test successful consensus with all agents agreeing."""
        consensus = setup_consensus

        fix = FixProposal(
            bug_id="bug-test",
            original_code="x = None\nprint(x.value)",
            fixed_code="x = None\nif x:\n    print(x.value)",
            explanation="Added null check",
            proposing_agent_id="healer-01",
            confidence_score=0.9,
            language="python",
            file_path="test.py",
            line_number=2
        )

        # All agents validate positively
        async def validate_positive(fix, agent_id):
            return True, 0.9, "Looks good"

        result = await consensus.propose_fix(fix, validate_fn=validate_positive)

        assert result.success is True
        assert result.prepare_votes >= consensus.quorum
        assert result.commit_votes >= consensus.quorum

    @pytest.mark.asyncio
    async def test_consensus_fails_with_rejections(self, setup_consensus):
        """Test that consensus fails when too many agents reject."""
        consensus = setup_consensus

        fix = FixProposal(
            bug_id="bug-test",
            original_code="code",
            fixed_code="bad fix",
            explanation="Incorrect fix",
            proposing_agent_id="healer-01",
            confidence_score=0.3,
            language="python",
            file_path="test.py",
            line_number=1
        )

        # Most agents reject
        call_count = [0]
        async def validate_mostly_reject(fix, agent_id):
            call_count[0] += 1
            # Only 1 agent accepts, 3 reject (need 3 for quorum)
            return call_count[0] == 1, 0.2, "Fix is incorrect"

        result = await consensus.propose_fix(fix, validate_fn=validate_mostly_reject)

        assert result.success is False
        assert "Not enough" in result.decision_reason

    @pytest.mark.asyncio
    async def test_consensus_with_byzantine_agent(self, setup_consensus):
        """Test that consensus succeeds despite one faulty agent."""
        consensus = setup_consensus

        fix = FixProposal(
            bug_id="bug-test",
            original_code="code",
            fixed_code="fixed",
            explanation="Good fix",
            proposing_agent_id="healer-01",
            confidence_score=0.9,
            language="python",
            file_path="test.py",
            line_number=1
        )

        # One agent is Byzantine (always rejects), others accept
        async def validate_one_byzantine(fix, agent_id):
            if agent_id == "validator-02":
                # Byzantine agent always rejects
                return False, 0.0, "Malicious rejection"
            return True, 0.9, "Valid fix"

        result = await consensus.propose_fix(fix, validate_fn=validate_one_byzantine)

        # Should still succeed with 3/4 agents (quorum = 3)
        assert result.success is True

    @pytest.mark.asyncio
    async def test_insufficient_agents_fails(self):
        """Test that consensus fails with insufficient agents."""
        consensus = PBFTConsensus(f=1)

        # Only register 2 agents (need 4)
        consensus.register_agent(AgentInfo("agent-01", "analyzer", "claude"))
        consensus.register_agent(AgentInfo("agent-02", "healer", "gpt4"))

        fix = FixProposal(
            bug_id="bug-test",
            original_code="code",
            fixed_code="fixed",
            explanation="fix",
            proposing_agent_id="agent-02",
            confidence_score=0.9,
            language="python",
            file_path="test.py",
            line_number=1
        )

        result = await consensus.propose_fix(fix)

        assert result.success is False
        assert "Not enough agents" in result.decision_reason


class TestConsensusMetrics:
    """Test consensus metrics and statistics."""

    @pytest.mark.asyncio
    async def test_stats_tracking(self):
        """Test that consensus tracks statistics."""
        consensus = PBFTConsensus(f=1)

        # Register agents
        for i in range(4):
            consensus.register_agent(AgentInfo(f"agent-{i}", "validator", "ollama"))

        fix = FixProposal(
            bug_id="bug-test",
            original_code="code",
            fixed_code="fixed",
            explanation="fix",
            proposing_agent_id="agent-0",
            confidence_score=0.9,
            language="python",
            file_path="test.py",
            line_number=1
        )

        # Run consensus
        async def accept_all(fix, agent_id):
            return True, 0.9, "OK"

        await consensus.propose_fix(fix, validate_fn=accept_all)

        stats = consensus.get_stats()

        assert stats["total_rounds"] == 1
        assert stats["registered_agents"] == 4
        assert stats["online_agents"] == 4
        assert stats["is_ready"] is True


class TestViewChange:
    """Test view change protocol."""

    @pytest.mark.asyncio
    async def test_view_change_increments_view(self):
        """Test that view change increments the view number."""
        consensus = PBFTConsensus(f=1)

        for i in range(4):
            consensus.register_agent(AgentInfo(f"agent-{i}", "validator", "ollama"))

        initial_view = consensus.view

        await consensus.initiate_view_change(reason="timeout")

        assert consensus.view == initial_view + 1

    def test_primary_rotation(self):
        """Test that primary rotates with view change."""
        consensus = PBFTConsensus(f=1)

        for i in range(4):
            consensus.register_agent(AgentInfo(f"agent-{i}", "validator", "ollama"))

        primary_v0 = consensus.get_primary_id()
        consensus.view = 1
        primary_v1 = consensus.get_primary_id()

        # Primary should change with view
        assert primary_v0 != primary_v1 or len(consensus.agents) == 1


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
