"""
Agent Manager - Orchestrates the Multi-Agent System.

Coordinates the three agents (Analyzer, Healer, Validator) and
integrates with the PBFT consensus engine.

Author: Millicent Mufambi (H240624A)
"""

import asyncio
from typing import Optional, Dict, List, Any
from datetime import datetime
import structlog

from app.agents.base_agent import BaseAgent, AgentConfig, AgentType, LLMProvider
from app.agents.analyzer_agent import AnalyzerAgent, BugAnalysisInput
from app.agents.healer_agent import HealerAgent, FixGenerationInput
from app.agents.validator_agent import ValidatorAgent, ValidationInput
from app.consensus.pbft import PBFTConsensus, ConsensusResult, AgentInfo
from app.consensus.message_types import FixProposal

logger = structlog.get_logger(__name__)


class AgentManager:
    """
    Manages the multi-agent repair pipeline.

    Orchestrates:
    1. Bug analysis (Analyzer Agent)
    2. Fix generation (Healer Agent)
    3. Fix validation (Validator Agents)
    4. Consensus voting (PBFT)
    5. Fix application

    The heterogeneous multi-LLM architecture provides:
    - Diverse perspectives on bugs and fixes
    - Reduced correlated failures
    - Improved reliability through consensus
    """

    def __init__(
        self,
        f: int = 1,
        reputation_weighted: bool = False,
        inject_fault: str = "none",
        inject_fault_count: int = 0,
    ):
        """
        Initialize the agent manager.

        Args:
            f: Byzantine fault tolerance level (tolerates f faulty agents)
            reputation_weighted: forwarded to PBFTConsensus
            inject_fault: behaviour for Byzantine validator wrappers
                          (none | always_reject | always_approve | random | timeout | garbage)
            inject_fault_count: how many validators to corrupt with that behaviour
        """
        self.f = f
        self.reputation_weighted = reputation_weighted
        self.inject_fault = inject_fault
        self.inject_fault_count = inject_fault_count

        # Read model names from settings so they are configurable via .env
        from app.config import settings as _settings

        # Initialize agents with different LLM backends
        self.analyzer = AnalyzerAgent(AgentConfig(
            agent_id="analyzer-claude-01",
            agent_type=AgentType.ANALYZER,
            llm_provider=LLMProvider.CLAUDE,
            model_name=_settings.anthropic_model,
            temperature=0.3,
        ))

        self.healer = HealerAgent(AgentConfig(
            agent_id="healer-gpt4-01",
            agent_type=AgentType.HEALER,
            llm_provider=LLMProvider.GPT4,
            model_name=_settings.openai_model,
            temperature=0.7,
        ))

        # Multiple validators for BFT (need 3f+1 total agents)
        self.validators: List[ValidatorAgent] = []
        for i in range(2):  # 2 validators + 1 analyzer + 1 healer = 4 agents (3f+1 for f=1)
            self.validators.append(ValidatorAgent(AgentConfig(
                agent_id=f"validator-ollama-{i+1:02d}",
                agent_type=AgentType.VALIDATOR,
                llm_provider=LLMProvider.OLLAMA,
                model_name="http://localhost:11434",
                temperature=0.1,
            )))

        # Initialize consensus engine (with optional reputation-weighted voting)
        self.consensus = PBFTConsensus(f=f, reputation_weighted=reputation_weighted)

        # Optional fault injection — wrap up to inject_fault_count validators
        if inject_fault and inject_fault != "none" and inject_fault_count > 0:
            from app.agents.byzantine_wrapper import ByzantineBehaviour, ByzantineWrapper
            for i in range(min(inject_fault_count, len(self.validators))):
                self.validators[i] = ByzantineWrapper(
                    self.validators[i], ByzantineBehaviour(inject_fault),
                )

        # Register all agents with consensus
        self._register_agents_for_consensus()

        # Metrics
        self.total_repairs = 0
        self.successful_repairs = 0

        logger.info(
            "Agent manager initialized",
            f=f,
            total_agents=1 + 1 + len(self.validators),
            analyzer=self.analyzer.agent_id,
            healer=self.healer.agent_id,
            validators=[v.agent_id for v in self.validators]
        )

    def _register_agents_for_consensus(self):
        """Register all agents with the consensus engine."""
        # Register analyzer
        self.consensus.register_agent(AgentInfo(
            agent_id=self.analyzer.agent_id,
            agent_type="analyzer",
            llm_provider=self.analyzer.llm_provider.value,
        ))

        # Register healer
        self.consensus.register_agent(AgentInfo(
            agent_id=self.healer.agent_id,
            agent_type="healer",
            llm_provider=self.healer.llm_provider.value,
        ))

        # Register validators
        for validator in self.validators:
            self.consensus.register_agent(AgentInfo(
                agent_id=validator.agent_id,
                agent_type="validator",
                llm_provider=validator.llm_provider.value,
            ))

    def set_llm_clients(
        self,
        claude_client: Any = None,
        openai_client: Any = None,
        ollama_url: str = "http://localhost:11434"
    ):
        """
        Set the LLM clients for all agents.

        Args:
            claude_client: Anthropic client instance
            openai_client: OpenAI client instance
            ollama_url: URL for local Ollama instance
        """
        if claude_client:
            self.analyzer.set_llm_client(claude_client)

        if openai_client:
            self.healer.set_llm_client(openai_client)

        # Validators use Ollama (URL-based, no client needed)
        for validator in self.validators:
            validator.config.model_name = ollama_url

    async def process_bug(
        self,
        error_message: str,
        stack_trace: str,
        code_context: str,
        file_path: str,
        line_number: int,
        language: str = "python"
    ) -> Dict[str, Any]:
        """
        Process a detected bug through the full repair pipeline.

        Pipeline:
        1. Analyzer examines the bug
        2. Healer generates fix candidates
        3. Validators verify fixes
        4. Consensus determines best fix
        5. Fix is applied (if approved)

        Args:
            error_message: The error message
            stack_trace: Full stack trace
            code_context: Code surrounding the error
            file_path: Path to the affected file
            line_number: Line where error occurred
            language: Programming language

        Returns:
            Dictionary with repair results
        """
        start_time = datetime.utcnow()
        self.total_repairs += 1

        logger.info(
            "Starting bug repair pipeline",
            file_path=file_path,
            line_number=line_number,
            error_message=error_message[:100]
        )

        try:
            # Phase 1: Bug Analysis
            logger.info("Phase 1: Analyzing bug")
            analysis_input = BugAnalysisInput(
                error_message=error_message,
                stack_trace=stack_trace,
                code_context=code_context,
                file_path=file_path,
                line_number=line_number,
                language=language,
            )
            analysis_output = await self.analyzer.process(analysis_input)

            if not analysis_output.success:
                return self._create_failure_result(
                    "analysis_failed",
                    analysis_output.reasoning,
                    start_time
                )

            bug_analysis = analysis_output.result

            # Phase 2: Fix Generation
            logger.info("Phase 2: Generating fixes")
            fix_input = FixGenerationInput(
                bug_analysis=bug_analysis,
                original_code=code_context,
                file_path=file_path,
                line_number=line_number,
                language=language,
            )
            fix_output = await self.healer.process(fix_input)

            if not fix_output.success or not fix_output.result.candidates:
                return self._create_failure_result(
                    "generation_failed",
                    fix_output.reasoning,
                    start_time
                )

            fix_result = fix_output.result
            best_candidate = fix_result.candidates[fix_result.recommended_index]

            # Phase 3: Validation
            logger.info("Phase 3: Validating fixes")
            validation_tasks = []
            for validator in self.validators:
                validation_input = ValidationInput(
                    original_code=code_context,
                    fix_candidate=best_candidate,
                    language=language,
                    file_path=file_path,
                )
                validation_tasks.append(validator.process(validation_input))

            validation_outputs = await asyncio.gather(*validation_tasks)

            # Phase 4: Consensus
            logger.info("Phase 4: Running consensus")
            fix_proposal = FixProposal(
                bug_id=f"bug-{int(start_time.timestamp())}",
                original_code=code_context,
                fixed_code=best_candidate.fixed_code,
                explanation=best_candidate.explanation,
                proposing_agent_id=self.healer.agent_id,
                confidence_score=best_candidate.confidence,
                language=language,
                file_path=file_path,
                line_number=line_number,
            )

            # Validation function for consensus
            async def validate_for_consensus(fix: FixProposal, agent_id: str):
                for vo in validation_outputs:
                    if vo.agent_id == agent_id:
                        result = vo.result
                        return result.is_valid, result.confidence, "; ".join(result.issues)
                return True, 0.8, "Default acceptance"

            consensus_result = await self.consensus.propose_fix(
                fix_proposal,
                validate_fn=validate_for_consensus
            )

            # Phase 5: Result
            duration_ms = (datetime.utcnow() - start_time).total_seconds() * 1000

            if consensus_result.success:
                self.successful_repairs += 1
                logger.info(
                    "Bug repair successful",
                    duration_ms=duration_ms,
                    consensus_votes=consensus_result.prepare_votes
                )
            else:
                logger.warning(
                    "Bug repair failed consensus",
                    reason=consensus_result.decision_reason
                )

            return {
                "success": consensus_result.success,
                "bug_id": fix_proposal.bug_id,
                "analysis": {
                    "bug_type": bug_analysis.bug_type,
                    "severity": bug_analysis.severity,
                    "root_cause": bug_analysis.root_cause,
                },
                "fix": {
                    "original_code": code_context,
                    "fixed_code": best_candidate.fixed_code,
                    "explanation": best_candidate.explanation,
                    "confidence": best_candidate.confidence,
                },
                "consensus": {
                    "approved": consensus_result.success,
                    "prepare_votes": consensus_result.prepare_votes,
                    "commit_votes": consensus_result.commit_votes,
                    "reason": consensus_result.decision_reason,
                },
                "validation_results": [
                    {
                        "agent_id": vo.agent_id,
                        "is_valid": vo.result.is_valid if vo.result else False,
                        "confidence": vo.result.confidence if vo.result else 0,
                        "issues": vo.result.issues if vo.result else [],
                    }
                    for vo in validation_outputs
                ],
                "duration_ms": duration_ms,
                "timestamp": datetime.utcnow().isoformat(),
            }

        except Exception as e:
            logger.error("Bug repair pipeline failed", error=str(e))
            return self._create_failure_result(
                "pipeline_error",
                str(e),
                start_time
            )

    def _create_failure_result(
        self,
        stage: str,
        reason: str,
        start_time: datetime
    ) -> Dict[str, Any]:
        """Create a failure result dictionary."""
        return {
            "success": False,
            "failure_stage": stage,
            "reason": reason,
            "duration_ms": (datetime.utcnow() - start_time).total_seconds() * 1000,
            "timestamp": datetime.utcnow().isoformat(),
        }

    def get_stats(self) -> Dict[str, Any]:
        """Get manager statistics."""
        return {
            "total_repairs": self.total_repairs,
            "successful_repairs": self.successful_repairs,
            "success_rate": self.successful_repairs / max(self.total_repairs, 1),
            "consensus_stats": self.consensus.get_stats(),
            "agents": {
                "analyzer": self.analyzer.get_stats(),
                "healer": self.healer.get_stats(),
                "validators": [v.get_stats() for v in self.validators],
            }
        }
