"""
Pytest Configuration for CodeFlow AI Tests.

Author: Millicent Mufambi (H240624A)
"""

import pytest
import asyncio
import sys
from pathlib import Path

# Add app directory to path
sys.path.insert(0, str(Path(__file__).parent.parent))


@pytest.fixture(scope="session")
def event_loop():
    """Create an event loop for async tests."""
    loop = asyncio.get_event_loop_policy().new_event_loop()
    yield loop
    loop.close()


@pytest.fixture
def sample_bug_code():
    """Provide sample buggy code for testing."""
    return {
        "python_null_check": {
            "original": "x = None\nprint(x.value)",
            "fixed": "x = None\nif x:\n    print(x.value)",
            "bug_type": "null_pointer"
        },
        "python_payment": {
            "original": "total = price * quantity",
            "fixed": "from decimal import Decimal\ntotal = Decimal(str(price)) * Decimal(str(quantity))",
            "bug_type": "payment_calculation"
        },
        "python_race": {
            "original": "if product.stock > 0:\n    product.stock -= 1",
            "fixed": "with product.lock:\n    if product.stock > 0:\n        product.stock -= 1",
            "bug_type": "race_condition"
        }
    }


@pytest.fixture
def mock_llm_response():
    """Provide mock LLM responses for testing without API calls."""
    def _mock(prompt: str):
        if "analyze" in prompt.lower() or "bug" in prompt.lower():
            return {
                "bug_type": "null_pointer",
                "severity": "high",
                "description": "Potential NullPointerException",
                "confidence": 0.85
            }
        elif "fix" in prompt.lower() or "repair" in prompt.lower():
            return {
                "fixed_code": "if x is not None:\n    print(x.value)",
                "explanation": "Added null check",
                "confidence": 0.9
            }
        elif "valid" in prompt.lower() or "verify" in prompt.lower():
            return {
                "is_valid": True,
                "confidence": 0.88,
                "reasoning": "Fix addresses the reported issue"
            }
        return {"response": "OK"}

    return _mock
