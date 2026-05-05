"""
Persist a BenchmarkReport to CSV and JSON for later analysis (R, pandas,
Excel, the technical paper, etc.).

CSV: one row per case, headers match CaseResult.to_dict.
JSON: full report including the metrics snapshot.
"""
from __future__ import annotations

import csv
import json
from datetime import datetime
from pathlib import Path
from typing import Any, Optional

import structlog

from benchmarks.bug_case import BenchmarkReport

logger = structlog.get_logger(__name__)


def write_report(
    report: BenchmarkReport,
    output_dir: str,
    prefix: Optional[str] = None,
) -> dict:
    """
    Write report to <output_dir>/<prefix>__cases.csv and __summary.json.

    Returns a dict with the two file paths.
    """
    out = Path(output_dir)
    out.mkdir(parents=True, exist_ok=True)

    if prefix is None:
        prefix = f"{report.dataset_name}__{datetime.utcnow().strftime('%Y%m%dT%H%M%S')}"

    cases_csv = out / f"{prefix}__cases.csv"
    summary_json = out / f"{prefix}__summary.json"

    # CSV
    rows = [c.to_dict() for c in report.cases]
    fieldnames = list(rows[0].keys()) if rows else []
    with cases_csv.open("w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(rows)

    # JSON
    payload = report.summary()
    payload["per_case"] = rows
    summary_json.write_text(json.dumps(payload, indent=2), encoding="utf-8")

    logger.info(
        "Benchmark report written",
        cases_csv=str(cases_csv),
        summary_json=str(summary_json),
        cases=len(rows),
    )

    return {
        "cases_csv": str(cases_csv),
        "summary_json": str(summary_json),
    }
