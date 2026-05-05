"""
BenchmarkRunner — drives a list of BugCase through the repair pipeline,
records per-case results and the final seven-metric snapshot.

Designed so a single instance can be reused across the synthetic micro-
benchmark, Defects4J, and BugsInPy without the harness knowing the
specifics of each dataset.
"""
from __future__ import annotations

import asyncio
import difflib
from datetime import datetime
from typing import Any, Awaitable, Callable, Iterable, List, Optional, Protocol

import structlog

from app.monitoring import MetricsCollector
from app.repair.repair_pipeline import RepairOutcome, RepairPipeline
from benchmarks.bug_case import BenchmarkReport, BugCase, CaseResult

logger = structlog.get_logger(__name__)


class PipelineLike(Protocol):
    """Anything that exposes RepairPipeline.run."""
    async def run(self, **kwargs: Any) -> RepairOutcome: ...


class BenchmarkRunner:
    """
    Run a sequence of BugCase objects through a repair pipeline and
    produce a BenchmarkReport.

    Two operating modes:
      * sequential (default): one case at a time, useful for cost-controlled
        runs and when the LLMs rate-limit aggressively.
      * concurrent: limited parallelism via asyncio.Semaphore.

    The runner does NOT manage budgets (token spend, wall-clock caps);
    callers can pass a per-case timeout via `case_timeout_s`.
    """

    def __init__(
        self,
        pipeline: PipelineLike,
        metrics: MetricsCollector,
        concurrency: int = 1,
        case_timeout_s: int = 120,
        case_callback: Optional[Callable[[CaseResult], Awaitable[None]]] = None,
    ):
        self.pipeline = pipeline
        self.metrics = metrics
        self.concurrency = max(1, int(concurrency))
        self.case_timeout_s = case_timeout_s
        self.case_callback = case_callback

    # ------------------------------------------------------------------
    async def run_dataset(
        self,
        dataset_name: str,
        cases: Iterable[BugCase],
        pipeline_config: Optional[dict] = None,
    ) -> BenchmarkReport:
        cases = list(cases)
        started_at = datetime.utcnow()

        logger.info(
            "Benchmark started",
            dataset=dataset_name,
            cases=len(cases),
            concurrency=self.concurrency,
        )

        if self.concurrency == 1:
            results = await self._run_sequential(cases)
        else:
            results = await self._run_concurrent(cases)

        finished_at = datetime.utcnow()

        snapshot = self.metrics.snapshot().to_dict()
        report = BenchmarkReport(
            dataset_name=dataset_name,
            started_at=started_at,
            finished_at=finished_at,
            cases=results,
            metrics_snapshot=snapshot,
            pipeline_config=pipeline_config or {},
        )

        logger.info(
            "Benchmark finished",
            dataset=dataset_name,
            duration_s=report.duration_seconds,
            successes=report.successes,
            total=report.total,
            safety_violations=report.safety_violations,
        )
        return report

    # ------------------------------------------------------------------
    async def _run_sequential(self, cases: List[BugCase]) -> List[CaseResult]:
        results: List[CaseResult] = []
        for i, case in enumerate(cases, 1):
            logger.info("Running case", index=i, total=len(cases), bug_id=case.bug_id, project=case.project)
            result = await self._run_one(case)
            results.append(result)
            if self.case_callback:
                try:
                    await self.case_callback(result)
                except Exception as e:
                    logger.warning("case_callback raised", error=str(e))
        return results

    async def _run_concurrent(self, cases: List[BugCase]) -> List[CaseResult]:
        sem = asyncio.Semaphore(self.concurrency)

        async def guarded(case: BugCase) -> CaseResult:
            async with sem:
                return await self._run_one(case)

        return await asyncio.gather(*(guarded(c) for c in cases))

    # ------------------------------------------------------------------
    async def _run_one(self, case: BugCase) -> CaseResult:
        try:
            outcome: RepairOutcome = await asyncio.wait_for(
                self.pipeline.run(
                    error_message=case.error_message,
                    stack_trace=case.stack_trace,
                    code_context=case.code_context,
                    file_path=case.file_path,
                    line_number=case.line_number,
                    language=case.language,
                    test_command=case.test_command,
                ),
                timeout=self.case_timeout_s,
            )
        except asyncio.TimeoutError:
            logger.warning("Case timed out", bug_id=case.bug_id, timeout_s=self.case_timeout_s)
            return CaseResult(
                bug_id=case.bug_id,
                project=case.project,
                success=False,
                consensus_approved=False,
                sandbox_passed=False,
                safety_violation=False,
                duration_ms=self.case_timeout_s * 1000,
                final_stage="timeout",
                decision_reason=f"case timed out after {self.case_timeout_s}s",
                error="timeout",
            )
        except Exception as e:
            logger.exception("Case raised", bug_id=case.bug_id)
            return CaseResult(
                bug_id=case.bug_id,
                project=case.project,
                success=False,
                consensus_approved=False,
                sandbox_passed=False,
                safety_violation=False,
                duration_ms=0.0,
                final_stage="exception",
                decision_reason=str(e),
                error=type(e).__name__,
            )

        ground_truth = self._evaluate_ground_truth(case, outcome)

        consensus = outcome.consensus_result or {}
        sandbox = outcome.sandbox_result or {}

        validator_votes: dict = {}
        for v in (outcome.validation_results or []):
            agent_id = v.get("agent_id")
            if agent_id is not None:
                validator_votes[agent_id] = bool(v.get("is_valid"))

        return CaseResult(
            bug_id=case.bug_id,
            project=case.project,
            success=outcome.success,
            consensus_approved=bool(consensus.get("approved")),
            sandbox_passed=bool(sandbox.get("success")),
            safety_violation=outcome.safety_violation,
            duration_ms=outcome.duration_ms,
            final_stage=outcome.final_stage.value if hasattr(outcome.final_stage, "value") else str(outcome.final_stage),
            decision_reason=outcome.decision_reason,
            fixed_code=outcome.fixed_code,
            explanation=outcome.explanation,
            consensus_prepare_votes=int(consensus.get("prepare_votes", 0)),
            consensus_commit_votes=int(consensus.get("commit_votes", 0)),
            sandbox_exit_code=sandbox.get("exit_code"),
            ground_truth_correct=ground_truth,
            validator_votes=validator_votes,
        )

    # ------------------------------------------------------------------
    @staticmethod
    def _evaluate_ground_truth(case: BugCase, outcome: RepairOutcome) -> Optional[bool]:
        """
        Best-effort comparison of the produced fix to a canonical answer.
        Returns None if no canonical is available.

        Heuristic: compare normalised whitespace + small Levenshtein-style
        similarity. A fix is considered "correct" if its normalised text
        is identical OR if the diff is small AND the sandbox passed.

        This is intentionally generous: many bugs admit several valid
        fixes that all pass the test suite.
        """
        if not case.canonical_fixed_code or not outcome.fixed_code:
            return None

        def norm(s: str) -> str:
            return "\n".join(line.strip() for line in s.strip().splitlines() if line.strip())

        produced = norm(outcome.fixed_code)
        canonical = norm(case.canonical_fixed_code)

        if produced == canonical:
            return True

        ratio = difflib.SequenceMatcher(a=produced, b=canonical).ratio()
        if ratio >= 0.9 and outcome.success:
            return True

        # If the sandbox passed but the text differs, trust the sandbox:
        # the fix is *plausible* and the test command says it works.
        if outcome.success and ratio >= 0.5:
            return True

        return False
