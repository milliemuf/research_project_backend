"""
Ablation comparison: H-BFT consensus mode vs single-agent baseline.

Loads four cases.csv files written by `python -m benchmarks ...` for the
two pipeline modes across two datasets, joins them per-bug, computes
summary statistics and the Wilcoxon signed-rank test on paired
safety-violation outcomes.

Usage:
    python -m benchmarks.ablation_report \
        --consensus-csvs p4_synth_consensus__cases.csv p4_bugsinpy_consensus__cases.csv \
        --baseline-csvs  p4_synth_single__cases.csv p4_bugsinpy_single__cases.csv \
        --output-dir benchmark_results

Author: Millicent Mufambi (H240624A)
"""
from __future__ import annotations

import argparse
import csv
import json
import math
import statistics
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, List, Optional


# ---------------------------------------------------------------------------
@dataclass
class CaseRow:
    bug_id: str
    project: str
    success: bool
    consensus_approved: bool
    sandbox_passed: bool
    safety_violation: bool
    duration_ms: float
    decision_reason: str
    ground_truth_correct: Optional[bool]
    sandbox_exit_code: Optional[int]


def _b(s: str) -> bool:
    return s.lower() in ("true", "1", "yes")


def _opt_b(s: str) -> Optional[bool]:
    if s == "" or s.lower() == "none":
        return None
    return _b(s)


def _opt_int(s: str) -> Optional[int]:
    if s == "" or s.lower() == "none":
        return None
    try:
        return int(s)
    except ValueError:
        return None


def _load_csv(path: Path) -> List[CaseRow]:
    rows: List[CaseRow] = []
    with path.open("r", encoding="utf-8") as f:
        reader = csv.DictReader(f)
        for r in reader:
            rows.append(CaseRow(
                bug_id=r["bug_id"],
                project=r["project"],
                success=_b(r["success"]),
                consensus_approved=_b(r["consensus_approved"]),
                sandbox_passed=_b(r["sandbox_passed"]),
                safety_violation=_b(r["safety_violation"]),
                duration_ms=float(r["duration_ms"]),
                decision_reason=r["decision_reason"],
                ground_truth_correct=_opt_b(r.get("ground_truth_correct", "")),
                sandbox_exit_code=_opt_int(r.get("sandbox_exit_code", "")),
            ))
    return rows


def _summary(rows: List[CaseRow]) -> Dict[str, Any]:
    n = len(rows)
    if n == 0:
        return {"n": 0}

    successes = sum(1 for r in rows if r.success)
    safety_viols = sum(1 for r in rows if r.safety_violation)
    consensus_yes = sum(1 for r in rows if r.consensus_approved)
    sandbox_passes = sum(1 for r in rows if r.sandbox_passed)
    durations = [r.duration_ms for r in rows]

    gt = [r.ground_truth_correct for r in rows if r.ground_truth_correct is not None]
    gt_correct = sum(1 for x in gt if x)

    durations_sorted = sorted(durations)

    def pct(p: float) -> float:
        if not durations_sorted:
            return 0.0
        k = (p / 100.0) * (len(durations_sorted) - 1)
        lo = math.floor(k); hi = math.ceil(k)
        if lo == hi:
            return durations_sorted[int(k)]
        return durations_sorted[lo] + (durations_sorted[hi] - durations_sorted[lo]) * (k - lo)

    return {
        "n": n,
        "successes": successes,
        "success_rate": successes / n,
        "safety_violations": safety_viols,
        "safety_violation_rate": safety_viols / n,
        "consensus_yes_count": consensus_yes,
        "consensus_yes_rate": consensus_yes / n,
        "sandbox_pass_count": sandbox_passes,
        "sandbox_pass_rate": sandbox_passes / n,
        "duration_mean_ms": statistics.mean(durations),
        "duration_median_ms": statistics.median(durations),
        "duration_p50_ms": pct(50),
        "duration_p99_ms": pct(99),
        "ground_truth_evaluated": len(gt),
        "ground_truth_correct": gt_correct,
        "ground_truth_correct_rate": gt_correct / len(gt) if gt else None,
    }


# ---------------------------------------------------------------------------
def _wilcoxon_signed_rank(differences: List[float]) -> Dict[str, Any]:
    """
    Wilcoxon signed-rank test on the differences (consensus_metric - baseline_metric).
    Implements the standard rank-sum statistic with normal approximation for
    p-value (good enough for n >= 10). Zero differences are dropped per the
    Pratt-Wilcoxon convention's most common variant.
    """
    nonzero = [d for d in differences if d != 0]
    n = len(nonzero)
    if n < 5:
        return {"n_pairs": len(differences), "n_nonzero": n, "p_value": None,
                "note": "too few non-zero differences for Wilcoxon"}

    abs_diffs = sorted(((abs(d), d) for d in nonzero), key=lambda t: t[0])
    # Assign ranks, averaging ties
    ranks = [0.0] * n
    i = 0
    while i < n:
        j = i
        while j + 1 < n and abs_diffs[j + 1][0] == abs_diffs[i][0]:
            j += 1
        avg_rank = (i + j) / 2 + 1  # 1-indexed average
        for k in range(i, j + 1):
            ranks[k] = avg_rank
        i = j + 1

    w_plus = sum(r for r, (_, d) in zip(ranks, abs_diffs) if d > 0)
    w_minus = sum(r for r, (_, d) in zip(ranks, abs_diffs) if d < 0)
    w = min(w_plus, w_minus)

    mean_w = n * (n + 1) / 4
    var_w = n * (n + 1) * (2 * n + 1) / 24
    if var_w <= 0:
        return {"n_pairs": len(differences), "n_nonzero": n, "p_value": None}
    z = (w - mean_w) / math.sqrt(var_w)
    # Two-tailed p-value via normal approximation
    p = 2 * (1 - _standard_normal_cdf(abs(z)))

    return {
        "n_pairs": len(differences),
        "n_nonzero": n,
        "w_plus": w_plus,
        "w_minus": w_minus,
        "w_statistic": w,
        "z": z,
        "p_value": p,
    }


def _standard_normal_cdf(z: float) -> float:
    return 0.5 * (1 + math.erf(z / math.sqrt(2)))


# ---------------------------------------------------------------------------
def compare(
    consensus_rows: List[CaseRow],
    baseline_rows: List[CaseRow],
) -> Dict[str, Any]:
    by_id_baseline = {r.bug_id: r for r in baseline_rows}
    paired: List[Dict[str, Any]] = []
    safety_diff: List[int] = []
    success_diff: List[int] = []
    duration_diff: List[float] = []

    for c in consensus_rows:
        b = by_id_baseline.get(c.bug_id)
        if b is None:
            continue
        paired.append({
            "bug_id": c.bug_id,
            "project": c.project,
            "consensus_success": c.success,
            "baseline_success": b.success,
            "consensus_safety_violation": c.safety_violation,
            "baseline_safety_violation": b.safety_violation,
            "consensus_duration_ms": c.duration_ms,
            "baseline_duration_ms": b.duration_ms,
            "consensus_approved": c.consensus_approved,
            "baseline_approved": b.consensus_approved,
            "consensus_sandbox_passed": c.sandbox_passed,
            "baseline_sandbox_passed": b.sandbox_passed,
        })
        # Differences are consensus - baseline; positive means consensus higher
        safety_diff.append((1 if c.safety_violation else 0) - (1 if b.safety_violation else 0))
        success_diff.append((1 if c.success else 0) - (1 if b.success else 0))
        duration_diff.append(c.duration_ms - b.duration_ms)

    safety_violation_pairs = {
        "both_violated": sum(1 for p in paired if p["consensus_safety_violation"] and p["baseline_safety_violation"]),
        "only_consensus_violated": sum(1 for p in paired if p["consensus_safety_violation"] and not p["baseline_safety_violation"]),
        "only_baseline_violated": sum(1 for p in paired if not p["consensus_safety_violation"] and p["baseline_safety_violation"]),
        "neither_violated": sum(1 for p in paired if not p["consensus_safety_violation"] and not p["baseline_safety_violation"]),
    }

    return {
        "n_paired": len(paired),
        "consensus_summary": _summary(consensus_rows),
        "baseline_summary": _summary(baseline_rows),
        "safety_violation_pairs": safety_violation_pairs,
        "safety_wilcoxon": _wilcoxon_signed_rank([float(x) for x in safety_diff]),
        "success_wilcoxon": _wilcoxon_signed_rank([float(x) for x in success_diff]),
        "duration_wilcoxon": _wilcoxon_signed_rank(duration_diff),
        "mean_consensus_minus_baseline_safety_violation_rate":
            (sum(safety_diff) / len(safety_diff)) if safety_diff else 0.0,
        "mean_consensus_minus_baseline_success_rate":
            (sum(success_diff) / len(success_diff)) if success_diff else 0.0,
        "mean_consensus_minus_baseline_duration_ms":
            (sum(duration_diff) / len(duration_diff)) if duration_diff else 0.0,
        "paired_cases": paired,
    }


# ---------------------------------------------------------------------------
def parse_args(argv: Optional[List[str]] = None) -> argparse.Namespace:
    p = argparse.ArgumentParser(prog="python -m benchmarks.ablation_report", description=__doc__)
    p.add_argument("--consensus-csvs", nargs="+", required=True, help="One or more cases.csv files from consensus mode runs")
    p.add_argument("--baseline-csvs", nargs="+", required=True, help="Same files but produced by single-agent mode runs")
    p.add_argument("--output-dir", default="benchmark_results", help="Where to write the report")
    p.add_argument("--prefix", default="ablation", help="Output filename prefix")
    return p.parse_args(argv)


def main(argv: Optional[List[str]] = None) -> int:
    args = parse_args(argv)
    out_dir = Path(args.output_dir)
    out_dir.mkdir(parents=True, exist_ok=True)

    consensus_rows: List[CaseRow] = []
    for path in args.consensus_csvs:
        consensus_rows.extend(_load_csv(Path(path)))
    baseline_rows: List[CaseRow] = []
    for path in args.baseline_csvs:
        baseline_rows.extend(_load_csv(Path(path)))

    print(f"Loaded {len(consensus_rows)} consensus rows and {len(baseline_rows)} baseline rows")

    # Whole-corpus comparison
    overall = compare(consensus_rows, baseline_rows)

    # Per-dataset breakdown (split by bug_id prefix)
    def split(rows, prefix):
        return [r for r in rows if r.bug_id.startswith(prefix)]

    per_dataset: Dict[str, Any] = {}
    prefixes = {"synthetic": "syn-", "bugsinpy": "bip-", "ecommerce": "ec-"}
    for name, prefix in prefixes.items():
        cons = split(consensus_rows, prefix)
        base = split(baseline_rows, prefix)
        if cons or base:
            per_dataset[name] = compare(cons, base)

    report = {
        "n_consensus_rows": len(consensus_rows),
        "n_baseline_rows": len(baseline_rows),
        "overall": overall,
        "per_dataset": per_dataset,
    }

    out_json = out_dir / f"{args.prefix}__report.json"
    out_json.write_text(json.dumps(report, indent=2, default=str), encoding="utf-8")

    # Human-readable summary
    lines = []
    lines.append("=" * 70)
    lines.append("H-BFT CONSENSUS vs SINGLE-AGENT BASELINE — ABLATION REPORT")
    lines.append("=" * 70)
    for name, comp in [("OVERALL", overall)] + [(n.upper(), c) for n, c in per_dataset.items()]:
        lines.append("")
        lines.append(f"--- {name} ---")
        lines.append(f"  Paired cases: {comp['n_paired']}")
        cs = comp["consensus_summary"]; bs = comp["baseline_summary"]
        lines.append(f"  Success rate         : consensus {cs['success_rate']:.3f}  vs baseline {bs['success_rate']:.3f}")
        lines.append(f"  Safety violation rate: consensus {cs['safety_violation_rate']:.3f}  vs baseline {bs['safety_violation_rate']:.3f}")
        lines.append(f"  Mean duration (ms)   : consensus {cs['duration_mean_ms']:.0f}  vs baseline {bs['duration_mean_ms']:.0f}")
        lines.append(f"  Latency p99 (ms)     : consensus {cs['duration_p99_ms']:.0f}  vs baseline {bs['duration_p99_ms']:.0f}")
        if cs.get("ground_truth_correct_rate") is not None:
            lines.append(f"  Ground-truth accuracy: consensus {cs['ground_truth_correct_rate']:.3f}  vs baseline {bs.get('ground_truth_correct_rate') or 0.0:.3f}")
        lines.append("")
        lines.append("  Pairwise safety-violation breakdown:")
        for k, v in comp["safety_violation_pairs"].items():
            lines.append(f"    {k:<28}: {v}")
        sw = comp["safety_wilcoxon"]
        if sw.get("p_value") is not None:
            lines.append(f"  Wilcoxon (safety)   : W={sw['w_statistic']:.1f}  z={sw['z']:.3f}  p={sw['p_value']:.4f}")
        else:
            lines.append(f"  Wilcoxon (safety)   : {sw.get('note', 'no signal')}")
        sw2 = comp["success_wilcoxon"]
        if sw2.get("p_value") is not None:
            lines.append(f"  Wilcoxon (success)  : W={sw2['w_statistic']:.1f}  z={sw2['z']:.3f}  p={sw2['p_value']:.4f}")

    out_txt = out_dir / f"{args.prefix}__report.txt"
    out_txt.write_text("\n".join(lines), encoding="utf-8")

    print()
    print("\n".join(lines))
    print()
    print(f"Wrote {out_json}")
    print(f"Wrote {out_txt}")
    return 0


if __name__ == "__main__":
    import sys
    sys.exit(main())
