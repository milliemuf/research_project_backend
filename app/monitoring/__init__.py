"""
Monitoring module — implements the seven-metric evaluation framework
proposed in the systematic review (Section VI of the H-BFT review paper).

The metrics tracked here are:
  1. Consensus throughput (decisions per second under fault injection)
  2. Consensus latency, p50 and p99 (proposal-to-decision time)
  3. Consensus success rate (fraction of rounds that finish within timeout)
  4. Safety violation rate (fraction of consensus-approved fixes that the
     sandbox subsequently rejected — this is the headline safety metric)
  5. Recovery time (time from a Byzantine event to normal operation)
  6. Agent agreement rate (fraction of rounds with unanimous non-faulty votes)
  7. F1 score (where ground-truth is available, e.g., on Defects4J)

Author: Millicent Mufambi (H240624A)
"""
from app.monitoring.metrics import (
    MetricsCollector,
    MetricsSnapshot,
    metrics_collector,
)

__all__ = ["MetricsCollector", "MetricsSnapshot", "metrics_collector"]
