"""
Benchmark harness for the CodeFlow / H-BFT prototype.

Provides:
  * BugCase / Dataset abstractions
  * A unified BenchmarkRunner that drives any dataset through
    RepairPipeline and collects the seven metrics
  * Three concrete datasets: synthetic, Defects4J, BugsInPy
  * A mock pipeline for free, deterministic testing of the harness itself

Author: Millicent Mufambi (H240624A)
"""
from benchmarks.bug_case import BugCase, BenchmarkReport, CaseResult
from benchmarks.runner import BenchmarkRunner

__all__ = ["BugCase", "BenchmarkReport", "CaseResult", "BenchmarkRunner"]
