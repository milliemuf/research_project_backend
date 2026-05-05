"""
Concrete benchmark datasets.

Each module exposes a `load(limit=None, **kwargs) -> List[BugCase]` function
so the runner can treat them uniformly.
"""
from benchmarks.datasets.synthetic import load as load_synthetic
from benchmarks.datasets.bugsinpy import load as load_bugsinpy
from benchmarks.datasets.ecommerce import load as load_ecommerce

__all__ = ["load_synthetic", "load_bugsinpy", "load_ecommerce"]
