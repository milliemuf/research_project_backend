"""
Metrics collector — captures the seven measurements from the H-BFT review.

The collector keeps two parallel views:
  * an in-memory rolling history (most recent N rounds) used for percentiles
    and live dashboards
  * Prometheus counters / histograms / gauges for production scraping

Both views are updated from a single call site in RepairPipeline so the
numbers stay consistent across the live service and the offline benchmark
harness.

Author: Millicent Mufambi (H240624A)
"""

from __future__ import annotations

import math
import threading
from collections import deque
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Deque, Dict, List, Optional

import structlog

logger = structlog.get_logger(__name__)

# Prometheus client is optional. If it isn't installed we degrade silently
# and only keep the in-memory view.
try:
    from prometheus_client import Counter, Gauge, Histogram, CollectorRegistry, generate_latest
    _PROM_AVAILABLE = True
except ImportError:  # pragma: no cover
    _PROM_AVAILABLE = False
    Counter = Gauge = Histogram = CollectorRegistry = None  # type: ignore
    def generate_latest(*_args, **_kwargs):  # type: ignore
        return b""


@dataclass
class MetricsSnapshot:
    """Read-only view of the current metric values."""
    consensus_throughput_per_min: float = 0.0
    consensus_latency_p50_ms: float = 0.0
    consensus_latency_p99_ms: float = 0.0
    consensus_success_rate: float = 0.0
    safety_violation_rate: float = 0.0
    average_recovery_time_ms: float = 0.0
    agent_agreement_rate: float = 0.0
    f1_score: Optional[float] = None
    precision: Optional[float] = None
    recall: Optional[float] = None
    total_rounds: int = 0
    # Failure decorrelation: mean pairwise agreement across validators.
    # Lower = more diverse failure modes = healthier H-BFT (Gap 5 from review §VIII-E).
    mean_pairwise_validator_agreement: Optional[float] = None
    n_validator_pairs: int = 0
    captured_at: datetime = field(default_factory=datetime.utcnow)

    def to_dict(self) -> Dict[str, Any]:
        d = {
            "consensus_throughput_per_min": round(self.consensus_throughput_per_min, 3),
            "consensus_latency_p50_ms": round(self.consensus_latency_p50_ms, 1),
            "consensus_latency_p99_ms": round(self.consensus_latency_p99_ms, 1),
            "consensus_success_rate": round(self.consensus_success_rate, 4),
            "safety_violation_rate": round(self.safety_violation_rate, 4),
            "average_recovery_time_ms": round(self.average_recovery_time_ms, 1),
            "agent_agreement_rate": round(self.agent_agreement_rate, 4),
            "total_rounds": self.total_rounds,
            "captured_at": self.captured_at.isoformat(),
        }
        if self.f1_score is not None:
            d["f1_score"] = round(self.f1_score, 4)
            d["precision"] = round(self.precision or 0, 4)
            d["recall"] = round(self.recall or 0, 4)
        if self.mean_pairwise_validator_agreement is not None:
            d["mean_pairwise_validator_agreement"] = round(self.mean_pairwise_validator_agreement, 4)
            d["n_validator_pairs"] = self.n_validator_pairs
        return d


class MetricsCollector:
    """
    Thread-safe collector for the seven evaluation metrics.

    Designed to be called from the repair pipeline:
        metrics.record_repair_outcome(outcome, raw_agent_result)

    And from a Byzantine event handler when one is wired up:
        metrics.mark_byzantine_event_start()
        ...
        metrics.mark_byzantine_event_resolved()
    """

    def __init__(self, history_size: int = 1000):
        self._lock = threading.Lock()
        self._history_size = history_size

        # In-memory rolling state
        self._latencies_ms: Deque[float] = deque(maxlen=history_size)
        self._consensus_outcomes: Deque[bool] = deque(maxlen=history_size)
        self._safety_outcomes: Deque[bool] = deque(maxlen=history_size)  # True = sandbox rejected = safety violation
        self._agreement_outcomes: Deque[bool] = deque(maxlen=history_size)
        self._recovery_times_ms: Deque[float] = deque(maxlen=history_size)
        self._round_timestamps: Deque[datetime] = deque(maxlen=history_size)

        # Ground-truth tracking (for F1 — only populated in benchmark mode)
        self._tp = 0  # true positives: fix accepted AND was correct
        self._fp = 0  # false positives: fix accepted BUT was wrong (safety violation)
        self._tn = 0  # true negatives: fix rejected AND was wrong
        self._fn = 0  # false negatives: fix rejected BUT was correct

        # Active Byzantine event tracking (for recovery time)
        self._byz_event_started_at: Optional[datetime] = None

        # Per-case validator vote vectors for failure-decorrelation analysis
        # (Gap 5 from review §VIII-E). Each entry is {agent_id: bool}.
        self._validator_vote_vectors: List[Dict[str, bool]] = []

        # Prometheus instruments (optional). Each collector owns its own
        # registry so multiple instances (e.g., in tests) do not collide.
        if _PROM_AVAILABLE:
            self.registry = CollectorRegistry()
            self.prom_consensus_total = Counter(
                "codeflow_consensus_rounds_total",
                "Total consensus rounds",
                ["outcome"],
                registry=self.registry,
            )
            self.prom_consensus_latency = Histogram(
                "codeflow_consensus_latency_ms",
                "Consensus round latency in milliseconds",
                buckets=(50, 100, 200, 500, 1000, 2000, 5000, 10000, 30000),
                registry=self.registry,
            )
            self.prom_safety_violations = Counter(
                "codeflow_safety_violations_total",
                "Consensus-approved fixes that the sandbox subsequently rejected",
                registry=self.registry,
            )
            self.prom_agent_agreement = Gauge(
                "codeflow_agent_agreement_rate",
                "Fraction of rounds with unanimous non-faulty agent votes",
                registry=self.registry,
            )
            self.prom_safety_violation_rate = Gauge(
                "codeflow_safety_violation_rate",
                "Fraction of approved fixes that the sandbox rejected",
                registry=self.registry,
            )
        else:
            self.registry = None
            self.prom_consensus_total = None
            self.prom_consensus_latency = None
            self.prom_safety_violations = None
            self.prom_agent_agreement = None
            self.prom_safety_violation_rate = None

        logger.info(
            "Metrics collector initialised",
            history_size=history_size,
            prometheus_enabled=_PROM_AVAILABLE,
        )

    # ------------------------------------------------------------------
    # Recording
    # ------------------------------------------------------------------
    def record_repair_outcome(
        self,
        outcome: Any,                 # RepairOutcome (avoid circular import)
        raw_agent_result: Dict[str, Any],
        ground_truth_correct: Optional[bool] = None,
    ) -> None:
        """
        Record a single repair attempt's metrics.

        ground_truth_correct is only available in benchmark mode (e.g. running
        on Defects4J where the canonical patch is known). When provided, it
        feeds the F1 calculation.
        """
        with self._lock:
            now = datetime.utcnow()
            self._round_timestamps.append(now)

            duration = float(getattr(outcome, "duration_ms", 0.0) or 0.0)
            self._latencies_ms.append(duration)

            consensus = (raw_agent_result.get("consensus") or {})
            consensus_ok = bool(consensus.get("approved"))
            self._consensus_outcomes.append(consensus_ok)

            # Agreement = consensus reached AND no faulty agent dissent
            validation_results = raw_agent_result.get("validation_results") or []
            agreement = consensus_ok and all(v.get("is_valid") for v in validation_results)
            self._agreement_outcomes.append(agreement)

            # Safety violation = consensus approved but sandbox rejected
            safety_violation = bool(getattr(outcome, "safety_violation", False))
            self._safety_outcomes.append(safety_violation)

            # Confusion-matrix update for F1
            if ground_truth_correct is not None:
                if consensus_ok and not safety_violation:
                    if ground_truth_correct:
                        self._tp += 1
                    else:
                        self._fp += 1
                else:
                    if ground_truth_correct:
                        self._fn += 1
                    else:
                        self._tn += 1

            # Prometheus
            if _PROM_AVAILABLE:
                self.prom_consensus_total.labels(outcome="success" if consensus_ok else "failure").inc()
                self.prom_consensus_latency.observe(duration)
                if safety_violation:
                    self.prom_safety_violations.inc()
                self.prom_agent_agreement.set(self._agreement_rate_locked())
                self.prom_safety_violation_rate.set(self._safety_violation_rate_locked())

        logger.debug(
            "Metrics recorded",
            consensus_ok=consensus_ok,
            duration_ms=duration,
            safety_violation=safety_violation,
            agreement=agreement,
        )

    def record_validator_votes(self, votes_by_agent: Dict[str, bool]) -> None:
        """
        Record one round's per-validator boolean votes for later
        decorrelation analysis. Call this once per repair attempt.
        """
        if not votes_by_agent:
            return
        with self._lock:
            self._validator_vote_vectors.append(dict(votes_by_agent))

    def mark_byzantine_event_start(self) -> None:
        """Call when a Byzantine event is detected (start of recovery window)."""
        with self._lock:
            self._byz_event_started_at = datetime.utcnow()

    def mark_byzantine_event_resolved(self) -> None:
        """Call when service is verified to be back to normal."""
        with self._lock:
            if self._byz_event_started_at is None:
                logger.warning("mark_byzantine_event_resolved without a matching start")
                return
            recovery_ms = (datetime.utcnow() - self._byz_event_started_at).total_seconds() * 1000
            self._recovery_times_ms.append(recovery_ms)
            self._byz_event_started_at = None
            logger.info("Byzantine event resolved", recovery_ms=recovery_ms)

    # ------------------------------------------------------------------
    # Reading
    # ------------------------------------------------------------------
    def snapshot(self) -> MetricsSnapshot:
        """Return a coherent view of all current metric values."""
        with self._lock:
            snap = MetricsSnapshot(
                consensus_throughput_per_min=self._throughput_per_minute_locked(),
                consensus_latency_p50_ms=self._percentile_locked(self._latencies_ms, 50),
                consensus_latency_p99_ms=self._percentile_locked(self._latencies_ms, 99),
                consensus_success_rate=self._success_rate_locked(),
                safety_violation_rate=self._safety_violation_rate_locked(),
                average_recovery_time_ms=self._mean_locked(self._recovery_times_ms),
                agent_agreement_rate=self._agreement_rate_locked(),
                total_rounds=len(self._round_timestamps),
            )
            f1, precision, recall = self._f1_locked()
            if f1 is not None:
                snap.f1_score = f1
                snap.precision = precision
                snap.recall = recall
            mean_agree, n_pairs = self._decorrelation_locked()
            if mean_agree is not None:
                snap.mean_pairwise_validator_agreement = mean_agree
                snap.n_validator_pairs = n_pairs
            return snap

    def reset(self) -> None:
        """Clear all in-memory history. Prometheus counters are not reset."""
        with self._lock:
            self._latencies_ms.clear()
            self._consensus_outcomes.clear()
            self._safety_outcomes.clear()
            self._agreement_outcomes.clear()
            self._recovery_times_ms.clear()
            self._round_timestamps.clear()
            self._tp = self._fp = self._tn = self._fn = 0
            self._byz_event_started_at = None
            logger.info("Metrics history reset")

    def export_prometheus(self) -> bytes:
        """Return Prometheus text-format payload for /metrics endpoint."""
        if not _PROM_AVAILABLE or self.registry is None:
            return b"# prometheus_client not installed\n"
        return generate_latest(self.registry)

    # ------------------------------------------------------------------
    # Internals (must be called with lock held)
    # ------------------------------------------------------------------
    def _throughput_per_minute_locked(self) -> float:
        if len(self._round_timestamps) < 2:
            return 0.0
        delta_s = (self._round_timestamps[-1] - self._round_timestamps[0]).total_seconds()
        if delta_s <= 0:
            return 0.0
        return (len(self._round_timestamps) - 1) * 60.0 / delta_s

    @staticmethod
    def _percentile_locked(values: Deque[float], p: int) -> float:
        if not values:
            return 0.0
        ordered = sorted(values)
        k = (p / 100.0) * (len(ordered) - 1)
        lo = math.floor(k)
        hi = math.ceil(k)
        if lo == hi:
            return ordered[int(k)]
        frac = k - lo
        return ordered[lo] + (ordered[hi] - ordered[lo]) * frac

    @staticmethod
    def _mean_locked(values: Deque[float]) -> float:
        if not values:
            return 0.0
        return sum(values) / len(values)

    def _success_rate_locked(self) -> float:
        if not self._consensus_outcomes:
            return 0.0
        return sum(1 for ok in self._consensus_outcomes if ok) / len(self._consensus_outcomes)

    def _safety_violation_rate_locked(self) -> float:
        approved = [v for c, v in zip(self._consensus_outcomes, self._safety_outcomes) if c]
        if not approved:
            return 0.0
        return sum(1 for v in approved if v) / len(approved)

    def _agreement_rate_locked(self) -> float:
        if not self._agreement_outcomes:
            return 0.0
        return sum(1 for a in self._agreement_outcomes if a) / len(self._agreement_outcomes)

    def _f1_locked(self):
        total_labelled = self._tp + self._fp + self._fn + self._tn
        if total_labelled == 0:
            return None, None, None
        precision = self._tp / (self._tp + self._fp) if (self._tp + self._fp) else 0.0
        recall = self._tp / (self._tp + self._fn) if (self._tp + self._fn) else 0.0
        if precision + recall == 0:
            return 0.0, precision, recall
        f1 = 2 * precision * recall / (precision + recall)
        return f1, precision, recall

    def _decorrelation_locked(self):
        """
        Mean pairwise agreement across validators over all recorded rounds.

        Agreement(A, B) = fraction of rounds where A and B voted the same way.
        Mean is taken across every unique (A, B) validator pair.

        Returns (mean_agreement, n_pairs). mean_agreement of 1.0 means
        validators always vote together (no diversity); 0.5 means they
        vote independently of each other (maximum decorrelation for
        binary votes).
        """
        if len(self._validator_vote_vectors) < 2:
            return None, 0
        # Collect the set of agents that appear in at least one round
        all_agents = set()
        for v in self._validator_vote_vectors:
            all_agents.update(v.keys())
        agents = sorted(all_agents)
        if len(agents) < 2:
            return None, 0

        agreements = []
        for i in range(len(agents)):
            for j in range(i + 1, len(agents)):
                a, b = agents[i], agents[j]
                same = total = 0
                for v in self._validator_vote_vectors:
                    if a in v and b in v:
                        total += 1
                        if v[a] == v[b]:
                            same += 1
                if total > 0:
                    agreements.append(same / total)
        if not agreements:
            return None, 0
        return sum(agreements) / len(agreements), len(agreements)


# Module-level singleton used by RepairPipeline by default.
metrics_collector = MetricsCollector()
