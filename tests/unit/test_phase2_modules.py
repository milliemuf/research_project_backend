"""
Smoke test for the Phase-2 modules: sandbox, repair, monitoring, knowledge.

These tests do NOT require any LLM API keys, Docker, or Neo4j. They exercise
each module's code path with stubs / fallbacks so they can run in CI on a
plain laptop.
"""

import asyncio
import sys
from datetime import datetime
from pathlib import Path

import pytest


# ---------------------------------------------------------------------------
# Sandbox: subprocess fallback should run a tiny Python program.
# ---------------------------------------------------------------------------
@pytest.mark.asyncio
async def test_sandbox_subprocess_python_runs():
    from app.sandbox import SandboxExecutor, SandboxBackend

    executor = SandboxExecutor(default_timeout_s=10, force_backend=SandboxBackend.SUBPROCESS)
    result = await executor.run(
        code="print('codeflow ok'); import sys; sys.exit(0)",
        language="python",
        run_command=[sys.executable, "main.py"],
        timeout_s=10,
    )
    assert result.success, f"sandbox failed: {result.short_reason()} | stderr={result.stderr}"
    assert "codeflow ok" in result.stdout
    assert result.backend == SandboxBackend.SUBPROCESS


@pytest.mark.asyncio
async def test_sandbox_detects_failure():
    from app.sandbox import SandboxExecutor, SandboxBackend

    executor = SandboxExecutor(default_timeout_s=10, force_backend=SandboxBackend.SUBPROCESS)
    result = await executor.run(
        code="raise SystemExit(1)",
        language="python",
        run_command=[sys.executable, "main.py"],
        timeout_s=10,
    )
    assert not result.success
    assert result.exit_code == 1


# ---------------------------------------------------------------------------
# Patch applier: atomic write + rollback round-trip.
# ---------------------------------------------------------------------------
def test_patch_apply_and_rollback(tmp_path):
    from app.repair import PatchApplier, PatchApplyStatus

    target = tmp_path / "demo.py"
    target.write_text("print('original')\n", encoding="utf-8")

    applier = PatchApplier(backup_root=str(tmp_path / "backups"))
    applied = applier.apply(str(target), "print('patched')\n")
    assert applied.status == PatchApplyStatus.APPLIED
    assert target.read_text() == "print('patched')\n"

    rolled = applier.rollback(applied.backup_id)
    assert rolled.status == PatchApplyStatus.ROLLED_BACK
    assert target.read_text() == "print('original')\n"


def test_patch_apply_dry_run(tmp_path):
    from app.repair import PatchApplier, PatchApplyStatus

    target = tmp_path / "demo.py"
    target.write_text("print('original')\n", encoding="utf-8")

    applier = PatchApplier(backup_root=str(tmp_path / "backups"), dry_run=True)
    result = applier.apply(str(target), "print('would change')\n")
    assert result.status == PatchApplyStatus.DRY_RUN
    assert target.read_text() == "print('original')\n"  # unchanged


# ---------------------------------------------------------------------------
# Metrics collector: percentiles and rates.
# ---------------------------------------------------------------------------
def test_metrics_records_and_snapshots():
    from app.monitoring import MetricsCollector

    class FakeOutcome:
        def __init__(self, duration_ms, safety_violation=False):
            self.duration_ms = duration_ms
            self.safety_violation = safety_violation

    collector = MetricsCollector(history_size=100)

    # 8 successes, 2 failures, one safety violation
    for ms in [100, 110, 130, 150, 200, 210, 220, 250]:
        collector.record_repair_outcome(
            outcome=FakeOutcome(duration_ms=ms),
            raw_agent_result={
                "consensus": {"approved": True, "prepare_votes": 3, "commit_votes": 3},
                "validation_results": [{"is_valid": True}, {"is_valid": True}],
            },
            ground_truth_correct=True,
        )
    # safety violation: consensus approved but sandbox rejected
    collector.record_repair_outcome(
        outcome=FakeOutcome(duration_ms=300, safety_violation=True),
        raw_agent_result={
            "consensus": {"approved": True, "prepare_votes": 3, "commit_votes": 3},
            "validation_results": [{"is_valid": True}, {"is_valid": False}],
        },
        ground_truth_correct=False,
    )
    # consensus failure
    collector.record_repair_outcome(
        outcome=FakeOutcome(duration_ms=500),
        raw_agent_result={
            "consensus": {"approved": False, "prepare_votes": 1, "commit_votes": 0},
            "validation_results": [{"is_valid": False}, {"is_valid": False}],
        },
        ground_truth_correct=True,
    )

    snap = collector.snapshot()
    assert snap.total_rounds == 10
    assert 0.7 < snap.consensus_success_rate < 1.0  # 9/10
    assert 0.0 < snap.safety_violation_rate < 1.0   # 1/9 approved had a sandbox rejection
    assert snap.consensus_latency_p50_ms > 0
    assert snap.consensus_latency_p99_ms >= snap.consensus_latency_p50_ms
    assert snap.f1_score is not None  # ground truth was supplied


def test_metrics_recovery_time():
    from app.monitoring import MetricsCollector
    import time

    collector = MetricsCollector()
    collector.mark_byzantine_event_start()
    time.sleep(0.05)
    collector.mark_byzantine_event_resolved()
    snap = collector.snapshot()
    assert snap.average_recovery_time_ms >= 50  # at least 50ms


# ---------------------------------------------------------------------------
# Knowledge graph: degrades gracefully when Neo4j is unreachable.
# ---------------------------------------------------------------------------
@pytest.mark.asyncio
async def test_knowledge_graph_degrades_when_unavailable():
    from app.knowledge import KnowledgeGraph, KnowledgeGraphState

    # Point at a deliberately-wrong port
    kg = KnowledgeGraph(uri="bolt://127.0.0.1:1", user="x", password="x")
    state = await kg.connect()
    assert state == KnowledgeGraphState.UNAVAILABLE

    # Operations on an unavailable graph must be safe no-ops
    class FakeOutcome:
        bug_id = "test-bug"
        fixed_code = "print('fixed')"
        explanation = "test"
        success = True
        consensus_result = {"prepare_votes": 3, "commit_votes": 3}

    ok = await kg.record_repair(FakeOutcome())
    assert ok is False  # write declined gracefully

    similar = await kg.find_similar_bugs(error_signature="abcdef")
    assert similar == []
