"""
End-to-end repair pipeline.

Stages:
  1. Multi-agent + PBFT consensus (delegated to AgentManager.process_bug)
  2. Sandbox validation of the consensus-approved fix
  3. Optional disk apply with rollback on regression-test failure
  4. Metrics emission
  5. Knowledge-graph recording

The pipeline is the single entry point used by both the FastAPI route and
the offline benchmark harness, so the same code path is exercised in
production and in evaluation runs.

Author: Millicent Mufambi (H240624A)
"""

from __future__ import annotations

import asyncio
from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from typing import Any, Dict, List, Optional

import structlog

from app.agents.agent_manager import AgentManager
from app.repair.patch_applier import PatchApplier, PatchApplyStatus
from app.sandbox.docker_executor import SandboxExecutor, SandboxResult

logger = structlog.get_logger(__name__)


class RepairStage(str, Enum):
    AGENT_PIPELINE = "agent_pipeline"
    CONSENSUS = "consensus"
    SANDBOX_VALIDATION = "sandbox_validation"
    PATCH_APPLY = "patch_apply"
    REGRESSION_CHECK = "regression_check"
    KNOWLEDGE_RECORD = "knowledge_record"
    DONE = "done"


@dataclass
class RepairOutcome:
    """End-to-end result returned by RepairPipeline.run."""
    bug_id: str
    success: bool
    final_stage: RepairStage
    decision_reason: str = ""
    duration_ms: float = 0.0
    consensus_result: Optional[Dict[str, Any]] = None
    sandbox_result: Optional[Dict[str, Any]] = None
    apply_result: Optional[Dict[str, Any]] = None
    safety_violation: bool = False
    fixed_code: Optional[str] = None
    explanation: Optional[str] = None
    # Per-validator votes from this run, used by the metrics layer for
    # failure-decorrelation analysis (Gap 5 from review §VIII-E).
    validation_results: List[Dict[str, Any]] = field(default_factory=list)
    timestamp: datetime = field(default_factory=datetime.utcnow)
    extras: Dict[str, Any] = field(default_factory=dict)


class RepairPipeline:
    """
    Orchestrates a single repair attempt from bug report to either
    "fix applied" or "fix rejected" with full metric capture.

    Designed to be reused for live runtime repair AND for batch evaluation
    on Defects4J / BugsInPy benchmarks.
    """

    def __init__(
        self,
        agent_manager: AgentManager,
        sandbox: Optional[SandboxExecutor] = None,
        applier: Optional[PatchApplier] = None,
        metrics: Optional["MetricsCollector"] = None,  # forward ref
        knowledge: Optional["KnowledgeGraph"] = None,  # forward ref
        apply_to_disk: bool = False,
        sandbox_timeout_s: int = 30,
    ):
        self.agent_manager = agent_manager
        self.sandbox = sandbox or SandboxExecutor(default_timeout_s=sandbox_timeout_s)
        self.applier = applier or PatchApplier(dry_run=True)
        self.metrics = metrics
        self.knowledge = knowledge
        self.apply_to_disk = apply_to_disk
        self.sandbox_timeout_s = sandbox_timeout_s

        logger.info(
            "Repair pipeline initialised",
            apply_to_disk=apply_to_disk,
            sandbox_timeout_s=sandbox_timeout_s,
        )

    # ------------------------------------------------------------------
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
        """
        Run a single end-to-end repair attempt.
        """
        started = datetime.utcnow()
        outcome = RepairOutcome(bug_id="", success=False, final_stage=RepairStage.AGENT_PIPELINE)

        # ----- Stage 1: agents + consensus ----- #
        agent_result = await self.agent_manager.process_bug(
            error_message=error_message,
            stack_trace=stack_trace,
            code_context=code_context,
            file_path=file_path,
            line_number=line_number,
            language=language,
        )

        outcome.bug_id = agent_result.get("bug_id", "")
        outcome.consensus_result = agent_result.get("consensus")
        outcome.validation_results = list(agent_result.get("validation_results") or [])

        if not agent_result.get("success"):
            outcome.final_stage = RepairStage.AGENT_PIPELINE
            outcome.decision_reason = agent_result.get("reason") or "agent pipeline did not produce a consensus"
            outcome.duration_ms = (datetime.utcnow() - started).total_seconds() * 1000
            self._emit_metrics(outcome, agent_result)
            return outcome

        outcome.fixed_code = agent_result["fix"]["fixed_code"]
        outcome.explanation = agent_result["fix"]["explanation"]
        outcome.final_stage = RepairStage.CONSENSUS

        # ----- Stage 2: sandbox validation ----- #
        sandbox_result = await self.sandbox.run(
            code=outcome.fixed_code,
            language=language,
            test_command=test_command,
            timeout_s=self.sandbox_timeout_s,
        )
        outcome.sandbox_result = self._sandbox_to_dict(sandbox_result)
        outcome.final_stage = RepairStage.SANDBOX_VALIDATION

        if not sandbox_result.success:
            outcome.success = False
            outcome.safety_violation = True  # consensus said yes, sandbox said no
            outcome.decision_reason = f"sandbox rejected: {sandbox_result.short_reason()}"
            outcome.duration_ms = (datetime.utcnow() - started).total_seconds() * 1000
            self._emit_metrics(outcome, agent_result)
            self._record_knowledge(outcome)
            return outcome

        # ----- Stage 3: optional apply to disk ----- #
        if self.apply_to_disk:
            apply_result = self.applier.apply(file_path=file_path, new_content=outcome.fixed_code)
            outcome.apply_result = {
                "status": apply_result.status.value,
                "backup_id": apply_result.backup_id,
                "error": apply_result.error,
            }
            outcome.final_stage = RepairStage.PATCH_APPLY

            if apply_result.status not in (PatchApplyStatus.APPLIED, PatchApplyStatus.DRY_RUN):
                outcome.success = False
                outcome.decision_reason = f"patch apply failed: {apply_result.error}"
                outcome.duration_ms = (datetime.utcnow() - started).total_seconds() * 1000
                self._emit_metrics(outcome, agent_result)
                return outcome

            # ----- Stage 4: post-apply regression check ----- #
            if regression_command:
                outcome.final_stage = RepairStage.REGRESSION_CHECK
                regression = await self.sandbox.run(
                    code=outcome.fixed_code,
                    language=language,
                    test_command=regression_command,
                    timeout_s=self.sandbox_timeout_s * 2,
                )
                if not regression.success and apply_result.backup_id:
                    rollback_result = self.applier.rollback(apply_result.backup_id)
                    outcome.success = False
                    outcome.safety_violation = True
                    outcome.decision_reason = (
                        f"regression failed; rolled back ({rollback_result.status.value})"
                    )
                    outcome.duration_ms = (datetime.utcnow() - started).total_seconds() * 1000
                    self._emit_metrics(outcome, agent_result)
                    self._record_knowledge(outcome)
                    return outcome

        # ----- Stage 5: success ----- #
        outcome.success = True
        outcome.final_stage = RepairStage.DONE
        outcome.decision_reason = "fix approved, sandbox-validated, applied" if self.apply_to_disk else "fix approved and sandbox-validated"
        outcome.duration_ms = (datetime.utcnow() - started).total_seconds() * 1000
        self._emit_metrics(outcome, agent_result)
        self._record_knowledge(outcome)
        return outcome

    # ------------------------------------------------------------------
    def _emit_metrics(self, outcome: RepairOutcome, raw_agent_result: Dict[str, Any]) -> None:
        if not self.metrics:
            return
        try:
            self.metrics.record_repair_outcome(outcome=outcome, raw_agent_result=raw_agent_result)
        except Exception as e:
            logger.warning("Metric emission failed (non-fatal)", error=str(e))

    def _record_knowledge(self, outcome: RepairOutcome) -> None:
        if not self.knowledge:
            return
        try:
            self.knowledge.record_repair(outcome)
        except Exception as e:
            logger.warning("Knowledge-graph recording failed (non-fatal)", error=str(e))

    @staticmethod
    def _sandbox_to_dict(r: SandboxResult) -> Dict[str, Any]:
        return {
            "success": r.success,
            "backend": r.backend.value,
            "exit_code": r.exit_code,
            "duration_ms": r.duration_ms,
            "timed_out": r.timed_out,
            "tests_passed": r.tests_passed,
            "tests_failed": r.tests_failed,
            "error": r.error,
            "stdout_tail": r.stdout[-1000:] if r.stdout else "",
            "stderr_tail": r.stderr[-1000:] if r.stderr else "",
        }
