"""
Mock RepairPipeline used for testing the benchmark harness without
spending money on LLM calls.

The MockRepairPipeline accepts the same `run(...)` signature as the real
pipeline. By default it returns the canonical fixed code (so the harness
sees what a "perfect" pipeline would produce) and runs the real sandbox
so the test command is genuinely exercised.

This makes harness tests free, deterministic, and fast — and also gives
us a useful baseline upper-bound on what the system *could* achieve if
its LLMs were perfect.
"""
from __future__ import annotations

from datetime import datetime
from typing import Any, Dict, List, Optional

import structlog

from app.repair.repair_pipeline import RepairOutcome, RepairStage
from app.sandbox.docker_executor import SandboxExecutor

logger = structlog.get_logger(__name__)


class MockRepairPipeline:
    """
    Drop-in replacement for app.repair.repair_pipeline.RepairPipeline used
    in benchmark tests.

    The mock builds a RepairOutcome that looks just like one produced by
    the real pipeline, except the LLM stages are skipped. The sandbox is
    still real, so the verification step is honest.
    """

    def __init__(
        self,
        sandbox: Optional[SandboxExecutor] = None,
        canonical_lookup: Optional[Dict[str, str]] = None,
        always_succeed_consensus: bool = True,
    ):
        self.sandbox = sandbox or SandboxExecutor(default_timeout_s=15)
        self.canonical_lookup = canonical_lookup or {}
        self.always_succeed_consensus = always_succeed_consensus

    async def run(
        self,
        error_message: str,
        stack_trace: str,
        code_context: str,
        file_path: str,
        line_number: int,
        language: str = "python",
        test_command: Optional[List[str]] = None,
        regression_command: Optional[List[str]] = None,
    ) -> RepairOutcome:
        bug_id = f"mock-{abs(hash((file_path, line_number, error_message))) % 10**9}"
        started = datetime.utcnow()

        # Pick the "fixed" code: prefer canonical lookup, fall back to original
        fixed_code = self.canonical_lookup.get(bug_id) or code_context

        outcome = RepairOutcome(
            bug_id=bug_id,
            success=False,
            final_stage=RepairStage.AGENT_PIPELINE,
            consensus_result={
                "approved": self.always_succeed_consensus,
                "prepare_votes": 3,
                "commit_votes": 3,
                "reason": "mock consensus",
            },
            fixed_code=fixed_code,
            explanation="mock: canonical or original code",
        )

        if not self.always_succeed_consensus:
            outcome.decision_reason = "mock: consensus disabled"
            outcome.duration_ms = (datetime.utcnow() - started).total_seconds() * 1000
            return outcome

        # Real sandbox check
        sandbox_result = await self.sandbox.run(
            code=fixed_code,
            language=language,
            test_command=test_command,
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
            "stdout_tail": sandbox_result.stdout[-500:],
            "stderr_tail": sandbox_result.stderr[-500:],
        }

        if not sandbox_result.success:
            outcome.success = False
            outcome.safety_violation = True
            outcome.final_stage = RepairStage.SANDBOX_VALIDATION
            outcome.decision_reason = f"mock sandbox rejected: {sandbox_result.short_reason()}"
        else:
            outcome.success = True
            outcome.final_stage = RepairStage.DONE
            outcome.decision_reason = "mock: consensus + sandbox ok"

        outcome.duration_ms = (datetime.utcnow() - started).total_seconds() * 1000
        return outcome
