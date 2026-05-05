"""
Common types for benchmark cases and results.

A BugCase is the input to one repair attempt; a CaseResult is the outcome;
a BenchmarkReport aggregates many CaseResults plus the snapshot of the
seven evaluation metrics taken at the end of the run.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Dict, List, Optional


@dataclass
class BugCase:
    """One bug-fix task pushed through the repair pipeline."""
    bug_id: str
    project: str                                  # e.g. "synthetic", "Lang", "fastapi"
    error_message: str
    stack_trace: str
    code_context: str                             # the buggy source as one blob
    file_path: str                                # logical path used for sandbox staging
    line_number: int
    language: str = "python"

    # Verification
    test_command: Optional[List[str]] = None      # command run inside the sandbox
    canonical_fixed_code: Optional[str] = None    # ground truth, used for F1

    # Optional metadata: bug type, severity tags, etc.
    metadata: Dict[str, Any] = field(default_factory=dict)


@dataclass
class CaseResult:
    """Outcome of running one BugCase through the pipeline."""
    bug_id: str
    project: str
    success: bool                                 # full pipeline success
    consensus_approved: bool                      # consensus phase succeeded
    sandbox_passed: bool                          # sandbox phase succeeded
    safety_violation: bool                        # consensus YES + sandbox NO
    duration_ms: float
    final_stage: str
    decision_reason: str
    fixed_code: Optional[str] = None
    explanation: Optional[str] = None
    consensus_prepare_votes: int = 0
    consensus_commit_votes: int = 0
    sandbox_exit_code: Optional[int] = None
    ground_truth_correct: Optional[bool] = None   # set if we could compare to canonical
    error: Optional[str] = None
    # Per-validator votes for failure-decorrelation analysis.
    validator_votes: Dict[str, bool] = field(default_factory=dict)
    timestamp: datetime = field(default_factory=datetime.utcnow)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "bug_id": self.bug_id,
            "project": self.project,
            "success": self.success,
            "consensus_approved": self.consensus_approved,
            "sandbox_passed": self.sandbox_passed,
            "safety_violation": self.safety_violation,
            "duration_ms": round(self.duration_ms, 2),
            "final_stage": self.final_stage,
            "decision_reason": self.decision_reason,
            "consensus_prepare_votes": self.consensus_prepare_votes,
            "consensus_commit_votes": self.consensus_commit_votes,
            "sandbox_exit_code": self.sandbox_exit_code,
            "ground_truth_correct": self.ground_truth_correct,
            "error": self.error,
            "timestamp": self.timestamp.isoformat(),
        }


@dataclass
class BenchmarkReport:
    """Aggregated results from running an entire dataset."""
    dataset_name: str
    started_at: datetime
    finished_at: datetime
    cases: List[CaseResult]
    metrics_snapshot: Dict[str, Any]              # seven metrics, captured at end of run
    pipeline_config: Dict[str, Any] = field(default_factory=dict)

    @property
    def total(self) -> int:
        return len(self.cases)

    @property
    def successes(self) -> int:
        return sum(1 for c in self.cases if c.success)

    @property
    def safety_violations(self) -> int:
        return sum(1 for c in self.cases if c.safety_violation)

    @property
    def duration_seconds(self) -> float:
        return (self.finished_at - self.started_at).total_seconds()

    def summary(self) -> Dict[str, Any]:
        return {
            "dataset": self.dataset_name,
            "started_at": self.started_at.isoformat(),
            "finished_at": self.finished_at.isoformat(),
            "duration_seconds": round(self.duration_seconds, 2),
            "total_cases": self.total,
            "successes": self.successes,
            "safety_violations": self.safety_violations,
            "success_rate": round(self.successes / self.total, 4) if self.total else 0.0,
            "metrics": self.metrics_snapshot,
            "pipeline_config": self.pipeline_config,
        }
