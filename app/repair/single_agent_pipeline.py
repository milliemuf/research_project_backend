"""
Single-agent baseline pipeline.

This is the comparison point for the H-BFT consensus pipeline. It runs the
analyzer + healer (so the bug actually gets understood and a fix is
generated), then SKIPS validators and SKIPS consensus, applying the
healer's recommended fix directly. The sandbox check is still performed
so we can measure how often a single-agent system would be wrong.

The SingleAgentPipeline returns a RepairOutcome with the same shape as
RepairPipeline so the benchmark runner does not need to know which one
it is talking to.

Author: Millicent Mufambi (H240624A)
"""
from __future__ import annotations

from datetime import datetime
from typing import Any, Dict, List, Optional

import structlog

from app.agents.agent_manager import AgentManager
from app.agents.analyzer_agent import BugAnalysisInput
from app.agents.healer_agent import FixGenerationInput
from app.repair.repair_pipeline import RepairOutcome, RepairStage
from app.sandbox.docker_executor import SandboxExecutor, SandboxResult

logger = structlog.get_logger(__name__)


class SingleAgentPipeline:
    """
    Baseline pipeline: Analyzer → Healer → Sandbox.

    No validators, no consensus. The healer's recommended fix is the
    decision the system would commit to. Used to measure how often a
    single-agent system produces a confident-but-wrong fix.
    """

    def __init__(
        self,
        agent_manager: AgentManager,
        sandbox: Optional[SandboxExecutor] = None,
        sandbox_timeout_s: int = 30,
    ):
        self.agent_manager = agent_manager
        self.sandbox = sandbox or SandboxExecutor(default_timeout_s=sandbox_timeout_s)
        self.sandbox_timeout_s = sandbox_timeout_s

    async def run(
        self,
        error_message: str,
        stack_trace: str,
        code_context: str,
        file_path: str,
        line_number: int,
        language: str = "python",
        test_command: Optional[List[str]] = None,
        regression_command: Optional[List[str]] = None,  # accepted for parity, unused
    ) -> RepairOutcome:
        started = datetime.utcnow()
        outcome = RepairOutcome(
            bug_id=f"single-{int(started.timestamp())}",
            success=False,
            final_stage=RepairStage.AGENT_PIPELINE,
        )

        # Stage 1 — Analyzer (still useful for the Healer's prompt)
        try:
            analysis_input = BugAnalysisInput(
                error_message=error_message,
                stack_trace=stack_trace,
                code_context=code_context,
                file_path=file_path,
                line_number=line_number,
                language=language,
            )
            analysis_output = await self.agent_manager.analyzer.process(analysis_input)
            if not analysis_output.success:
                outcome.decision_reason = f"analyzer failed: {analysis_output.reasoning}"
                outcome.duration_ms = (datetime.utcnow() - started).total_seconds() * 1000
                return outcome
        except Exception as e:
            outcome.decision_reason = f"analyzer raised: {e}"
            outcome.duration_ms = (datetime.utcnow() - started).total_seconds() * 1000
            return outcome

        # Stage 2 — Healer
        try:
            fix_input = FixGenerationInput(
                bug_analysis=analysis_output.result,
                original_code=code_context,
                file_path=file_path,
                line_number=line_number,
                language=language,
            )
            fix_output = await self.agent_manager.healer.process(fix_input)
            if not fix_output.success or not fix_output.result.candidates:
                outcome.decision_reason = f"healer produced no fix: {fix_output.reasoning}"
                outcome.duration_ms = (datetime.utcnow() - started).total_seconds() * 1000
                return outcome
        except Exception as e:
            outcome.decision_reason = f"healer raised: {e}"
            outcome.duration_ms = (datetime.utcnow() - started).total_seconds() * 1000
            return outcome

        fix_result = fix_output.result
        best_candidate = fix_result.candidates[fix_result.recommended_index]
        outcome.fixed_code = best_candidate.fixed_code
        outcome.explanation = best_candidate.explanation

        # In the baseline, the healer's recommendation IS the decision.
        # We model "approved" as: a non-trivial fix was produced.
        single_agent_approved = bool(best_candidate.fixed_code) and best_candidate.fixed_code.strip() != code_context.strip()
        outcome.consensus_result = {
            "approved": single_agent_approved,
            "prepare_votes": 1 if single_agent_approved else 0,
            "commit_votes": 1 if single_agent_approved else 0,
            "reason": "single-agent baseline (no consensus)",
        }

        if not single_agent_approved:
            outcome.decision_reason = "healer returned the original code unchanged"
            outcome.duration_ms = (datetime.utcnow() - started).total_seconds() * 1000
            return outcome

        # Stage 3 — Sandbox check (same as consensus pipeline so the
        # "would the change actually work?" measurement is identical)
        sandbox_result: SandboxResult = await self.sandbox.run(
            code=best_candidate.fixed_code,
            language=language,
            test_command=test_command,
            timeout_s=self.sandbox_timeout_s,
        )
        outcome.sandbox_result = {
            "success": sandbox_result.success,
            "backend": sandbox_result.backend.value,
            "exit_code": sandbox_result.exit_code,
            "duration_ms": sandbox_result.duration_ms,
            "timed_out": sandbox_result.timed_out,
            "tests_passed": sandbox_result.tests_passed,
            "tests_failed": sandbox_result.tests_failed,
            "error": sandbox_result.error,
            "stdout_tail": sandbox_result.stdout[-1000:] if sandbox_result.stdout else "",
            "stderr_tail": sandbox_result.stderr[-1000:] if sandbox_result.stderr else "",
        }

        outcome.success = sandbox_result.success
        outcome.safety_violation = single_agent_approved and not sandbox_result.success
        outcome.final_stage = RepairStage.SANDBOX_VALIDATION if not sandbox_result.success else RepairStage.DONE
        outcome.decision_reason = (
            "single-agent baseline: fix passed sandbox" if outcome.success
            else f"single-agent baseline: sandbox rejected ({sandbox_result.short_reason()})"
        )
        outcome.duration_ms = (datetime.utcnow() - started).total_seconds() * 1000
        return outcome
