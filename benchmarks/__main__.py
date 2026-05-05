"""
CLI entry point for the benchmark harness.

Examples:
    # Quick smoke test on synthetic bugs with the mock pipeline (free)
    python -m benchmarks --dataset synthetic --limit 5 --pipeline mock

    # Real run on synthetic bugs against the live multi-agent pipeline
    python -m benchmarks --dataset synthetic --limit 10 --pipeline real

    # Real run on BugsInPy projects
    python -m benchmarks --dataset bugsinpy --bugsinpy-root data/bug_datasets/bugsinpy --limit 20

Output is written to ./benchmark_results/<dataset>__<timestamp>__cases.csv
                    ./benchmark_results/<dataset>__<timestamp>__summary.json
"""
from __future__ import annotations

import argparse
import asyncio
import json
import os
import sys
from typing import Dict, List, Optional

import structlog

from app.monitoring import MetricsCollector
from app.repair.repair_pipeline import RepairPipeline
from app.repair.single_agent_pipeline import SingleAgentPipeline
from app.sandbox.docker_executor import SandboxBackend, SandboxExecutor
from benchmarks.bug_case import BugCase
from benchmarks.mock_pipeline import MockRepairPipeline
from benchmarks.result_writer import write_report
from benchmarks.runner import BenchmarkRunner

logger = structlog.get_logger(__name__)


def parse_args(argv: Optional[List[str]] = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(prog="python -m benchmarks", description=__doc__)
    parser.add_argument(
        "--dataset",
        choices=["synthetic", "defects4j", "bugsinpy", "ecommerce"],
        default="synthetic",
        help="Which dataset to run (default: synthetic)",
    )
    parser.add_argument("--limit", type=int, default=None, help="Cap the number of cases")
    parser.add_argument(
        "--pipeline",
        choices=["mock", "real"],
        default="mock",
        help="mock = no LLM calls (free); real = use live LLMs",
    )
    parser.add_argument(
        "--mode",
        choices=["consensus", "single-agent"],
        default="consensus",
        help="consensus = full H-BFT (analyzer+healer+validators+PBFT); "
             "single-agent = baseline (analyzer+healer only)",
    )
    parser.add_argument(
        "--sandbox-backend",
        choices=["auto", "docker", "subprocess"],
        default="subprocess",
        help="Force a specific sandbox backend",
    )
    parser.add_argument("--concurrency", type=int, default=1, help="Number of cases to run in parallel")
    parser.add_argument("--case-timeout-s", type=int, default=120, help="Per-case timeout in seconds")
    parser.add_argument(
        "--reputation-weighted",
        action="store_true",
        help="Use reputation-weighted PBFT quorum instead of unweighted 2f+1 voting",
    )
    parser.add_argument(
        "--inject-fault",
        choices=["none", "always_reject", "always_approve", "random", "timeout", "garbage"],
        default="none",
        help="Byzantine behaviour to inject into one or more validators",
    )
    parser.add_argument("--inject-fault-count", type=int, default=0,
                        help="Number of validators to corrupt with --inject-fault")
    parser.add_argument("--output-dir", default="benchmark_results", help="Where to write CSV and JSON")
    parser.add_argument("--prefix", default=None, help="Output filename prefix")

    # Defects4J / BugsInPy specifics
    parser.add_argument("--defects4j-project", default="Lang", help="Defects4J project ID")
    parser.add_argument("--bugsinpy-root", default="data/bug_datasets/bugsinpy", help="BugsInPy checkout root")
    parser.add_argument("--bugsinpy-projects", nargs="*", default=None, help="Restrict BugsInPy to these projects")

    return parser.parse_args(argv)


def _load_dataset(args: argparse.Namespace) -> tuple[str, List[BugCase]]:
    if args.dataset == "synthetic":
        from benchmarks.datasets import synthetic
        return ("synthetic", synthetic.load(limit=args.limit))
    if args.dataset == "defects4j":
        from benchmarks.datasets import defects4j
        return (
            f"defects4j-{args.defects4j_project}",
            defects4j.load(project=args.defects4j_project, limit=args.limit),
        )
    if args.dataset == "bugsinpy":
        from benchmarks.datasets import bugsinpy
        return (
            "bugsinpy",
            bugsinpy.load(
                bugsinpy_root=args.bugsinpy_root,
                projects=args.bugsinpy_projects,
                limit=args.limit,
            ),
        )
    if args.dataset == "ecommerce":
        from benchmarks.datasets import ecommerce
        return ("ecommerce", ecommerce.load(limit=args.limit))
    raise ValueError(f"unknown dataset: {args.dataset}")


def _build_pipeline(args: argparse.Namespace, cases: List[BugCase]):
    backend_map = {
        "auto": None,
        "docker": SandboxBackend.DOCKER,
        "subprocess": SandboxBackend.SUBPROCESS,
    }
    sandbox = SandboxExecutor(
        default_timeout_s=30,
        force_backend=backend_map[args.sandbox_backend],
    )

    if args.pipeline == "mock":
        canonical_lookup = {
            f"mock-{abs(hash((c.file_path, c.line_number, c.error_message))) % 10**9}": c.canonical_fixed_code
            for c in cases
            if c.canonical_fixed_code
        }
        return MockRepairPipeline(sandbox=sandbox, canonical_lookup=canonical_lookup)

    # Real pipeline: build only on demand to avoid expensive startup costs
    # when the harness is invoked just for a mock run.
    from app.agents.agent_manager import AgentManager
    agent_manager = AgentManager(
        f=1,
        reputation_weighted=args.reputation_weighted,
        inject_fault=args.inject_fault,
        inject_fault_count=args.inject_fault_count,
    )
    _wire_llm_clients(agent_manager)

    if args.mode == "single-agent":
        return SingleAgentPipeline(
            agent_manager=agent_manager,
            sandbox=sandbox,
        )

    return RepairPipeline(
        agent_manager=agent_manager,
        sandbox=sandbox,
        apply_to_disk=False,  # benchmark mode: never write to disk
    )


def _wire_llm_clients(agent_manager) -> None:
    from app.config import settings

    claude_client = None
    openai_client = None
    if settings.anthropic_api_key and settings.anthropic_api_key != "your_anthropic_key_here":
        try:
            from anthropic import AsyncAnthropic  # type: ignore
            claude_client = AsyncAnthropic(api_key=settings.anthropic_api_key)
        except Exception as e:
            logger.warning("Failed to init Anthropic client", error=str(e))
    if settings.openai_api_key and not settings.openai_api_key.startswith("your_"):
        try:
            from openai import AsyncOpenAI  # type: ignore
            openai_client = AsyncOpenAI(api_key=settings.openai_api_key)
        except Exception as e:
            logger.warning("Failed to init OpenAI client", error=str(e))

    agent_manager.set_llm_clients(
        claude_client=claude_client,
        openai_client=openai_client,
        ollama_url=settings.ollama_base_url,
    )


def result_validator_votes(result) -> List[bool]:
    """Return the list of per-validator boolean votes from a CaseResult."""
    return list((result.validator_votes or {}).values())


def result_validator_vote_map(result) -> Dict[str, bool]:
    """Return the {agent_id: is_valid} map from a CaseResult."""
    return dict(result.validator_votes or {})


async def main(argv: Optional[List[str]] = None) -> int:
    args = parse_args(argv)

    dataset_name, cases = _load_dataset(args)
    if not cases:
        logger.error("No cases loaded for dataset", dataset=args.dataset)
        return 2

    metrics = MetricsCollector(history_size=max(len(cases) * 2, 100))
    pipeline = _build_pipeline(args, cases)

    # Always feed metrics through the runner's case_callback so the
    # snapshot is consistent for mock, real-consensus, and real-single-agent
    # pipelines. (RepairPipeline's internal metrics emission requires a
    # MetricsCollector reference that's awkward to pass when we're also
    # using the callback.)
    async def record_into_metrics(result):
        class _Outcome:
            duration_ms = result.duration_ms
            safety_violation = result.safety_violation
        # Synthesise a validation_results list from per-validator information
        # if available; otherwise fall back to a uniform-vote stub.
        validation_results = []
        for vote in (result_validator_votes(result) or []):
            validation_results.append({"is_valid": vote})
        if not validation_results:
            validation_results = [{"is_valid": result.consensus_approved}] * 3
        metrics.record_repair_outcome(
            outcome=_Outcome(),
            raw_agent_result={
                "consensus": {
                    "approved": result.consensus_approved,
                    "prepare_votes": result.consensus_prepare_votes,
                    "commit_votes": result.consensus_commit_votes,
                },
                "validation_results": validation_results,
            },
            ground_truth_correct=result.ground_truth_correct,
        )
        # Failure-decorrelation tracking (Gap 5 from review §VIII-E).
        votes_by_agent = result_validator_vote_map(result)
        if votes_by_agent:
            metrics.record_validator_votes(votes_by_agent)

    runner = BenchmarkRunner(
        pipeline=pipeline,
        metrics=metrics,
        concurrency=args.concurrency,
        case_timeout_s=args.case_timeout_s,
        case_callback=record_into_metrics,
    )

    report = await runner.run_dataset(
        dataset_name=dataset_name,
        cases=cases,
        pipeline_config={
            "pipeline_type": args.pipeline,
            "sandbox_backend": args.sandbox_backend,
            "concurrency": args.concurrency,
            "case_timeout_s": args.case_timeout_s,
        },
    )

    paths = write_report(report, output_dir=args.output_dir, prefix=args.prefix)

    summary = report.summary()
    print()
    print("=" * 60)
    print(f"BENCHMARK COMPLETE: {dataset_name}")
    print("=" * 60)
    print(json.dumps({
        "summary": {k: v for k, v in summary.items() if k != "metrics"},
        "metrics": summary["metrics"],
        "outputs": paths,
    }, indent=2))
    return 0


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
