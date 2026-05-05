"""
Integration tests for the benchmark harness using the mock pipeline.

These tests exercise BenchmarkRunner end-to-end against the synthetic
dataset. They do not call any LLM and run in a few seconds.
"""
import asyncio
from pathlib import Path

import pytest

from app.monitoring import MetricsCollector
from app.sandbox import SandboxBackend, SandboxExecutor
from benchmarks.datasets import synthetic
from benchmarks.mock_pipeline import MockRepairPipeline
from benchmarks.result_writer import write_report
from benchmarks.runner import BenchmarkRunner


@pytest.mark.asyncio
async def test_synthetic_dataset_loads():
    cases = synthetic.load()
    assert len(cases) >= 10
    for c in cases:
        assert c.bug_id
        assert c.code_context
        assert c.canonical_fixed_code
        assert c.test_command


@pytest.mark.asyncio
async def test_mock_pipeline_runs_synthetic_dataset_end_to_end(tmp_path):
    cases = synthetic.load(limit=5)

    sandbox = SandboxExecutor(default_timeout_s=10, force_backend=SandboxBackend.SUBPROCESS)
    canonical_lookup = {
        f"mock-{abs(hash((c.file_path, c.line_number, c.error_message))) % 10**9}": c.canonical_fixed_code
        for c in cases
    }
    pipeline = MockRepairPipeline(sandbox=sandbox, canonical_lookup=canonical_lookup)

    metrics = MetricsCollector(history_size=50)

    async def record(result):
        class _Outcome:
            duration_ms = result.duration_ms
            safety_violation = result.safety_violation
        metrics.record_repair_outcome(
            outcome=_Outcome(),
            raw_agent_result={
                "consensus": {
                    "approved": result.consensus_approved,
                    "prepare_votes": result.consensus_prepare_votes,
                    "commit_votes": result.consensus_commit_votes,
                },
                "validation_results": [{"is_valid": result.consensus_approved}] * 3,
            },
            ground_truth_correct=result.ground_truth_correct,
        )

    runner = BenchmarkRunner(
        pipeline=pipeline,
        metrics=metrics,
        concurrency=1,
        case_timeout_s=30,
        case_callback=record,
    )

    report = await runner.run_dataset(
        dataset_name="synthetic-mock",
        cases=cases,
        pipeline_config={"pipeline_type": "mock", "sandbox_backend": "subprocess"},
    )

    assert report.total == 5
    # The mock returns canonical fixes, so every case should pass
    assert report.successes == 5
    assert report.safety_violations == 0

    # Metrics snapshot should reflect the run
    assert report.metrics_snapshot["total_rounds"] == 5
    assert report.metrics_snapshot["consensus_success_rate"] == 1.0

    # Result writer should produce two files
    paths = write_report(report, output_dir=str(tmp_path), prefix="harness_test")
    assert Path(paths["cases_csv"]).exists()
    assert Path(paths["summary_json"]).exists()
    assert Path(paths["cases_csv"]).read_text(encoding="utf-8").count("\n") >= 6  # header + 5 rows


@pytest.mark.asyncio
async def test_mock_pipeline_detects_safety_violation(tmp_path):
    """If the mock pipeline returns the original buggy code, the sandbox
    must reject it and the harness must record a safety violation."""
    cases = synthetic.load(limit=2)

    sandbox = SandboxExecutor(default_timeout_s=10, force_backend=SandboxBackend.SUBPROCESS)
    # No canonical lookup -> the mock falls back to the buggy original
    pipeline = MockRepairPipeline(sandbox=sandbox, canonical_lookup={})
    metrics = MetricsCollector(history_size=50)

    runner = BenchmarkRunner(pipeline=pipeline, metrics=metrics, case_timeout_s=20)
    report = await runner.run_dataset("synthetic-no-canonical", cases)

    assert report.total == 2
    # The buggy code should be rejected by the sandbox (test asserts fail)
    assert report.safety_violations == 2
    assert report.successes == 0
