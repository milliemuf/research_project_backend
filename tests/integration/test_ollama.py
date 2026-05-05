"""
Integration Tests for Ollama/Local LLM.

These tests validate the Validator Agent's connection to Ollama.
Requires Ollama to be running with codellama:7b model pulled.

Author: Millicent Mufambi (H240624A)
"""

import pytest
import httpx
import os
from typing import Optional


OLLAMA_BASE_URL = os.getenv("OLLAMA_BASE_URL", "http://localhost:11434")
OLLAMA_MODEL = os.getenv("OLLAMA_MODEL", "codellama:7b")


def ollama_available() -> bool:
    """Check if Ollama server is running."""
    try:
        response = httpx.get(f"{OLLAMA_BASE_URL}/api/tags", timeout=5.0)
        return response.status_code == 200
    except Exception:
        return False


@pytest.fixture
def ollama_client():
    """Provide an Ollama HTTP client."""
    return httpx.Client(base_url=OLLAMA_BASE_URL, timeout=120.0)


@pytest.mark.skipif(not ollama_available(), reason="Ollama not running")
class TestOllamaConnection:
    """Test basic Ollama connectivity."""

    def test_ollama_connection(self, ollama_client):
        """Test that Ollama server responds."""
        response = ollama_client.get("/api/tags")
        assert response.status_code == 200
        data = response.json()
        assert "models" in data

    def test_model_available(self, ollama_client):
        """Test that required model is available."""
        response = ollama_client.get("/api/tags")
        data = response.json()

        model_names = [m.get("name", "") for m in data.get("models", [])]

        # Check if any codellama variant is available
        has_codellama = any("codellama" in name.lower() for name in model_names)
        has_llama = any("llama" in name.lower() for name in model_names)

        assert has_codellama or has_llama, (
            f"No suitable model found. Available: {model_names}. "
            f"Run 'ollama pull codellama:7b' to install."
        )


@pytest.mark.skipif(not ollama_available(), reason="Ollama not running")
class TestCodeGeneration:
    """Test code generation capabilities."""

    def test_simple_completion(self, ollama_client):
        """Test basic code completion."""
        response = ollama_client.post(
            "/api/generate",
            json={
                "model": OLLAMA_MODEL,
                "prompt": "def add(a, b):\n    ",
                "stream": False,
                "options": {"num_predict": 50}
            }
        )

        assert response.status_code == 200
        data = response.json()
        assert "response" in data
        assert len(data["response"]) > 0

    def test_code_explanation(self, ollama_client):
        """Test code explanation capability."""
        code = """
def factorial(n):
    if n <= 1:
        return 1
    return n * factorial(n - 1)
"""

        response = ollama_client.post(
            "/api/generate",
            json={
                "model": OLLAMA_MODEL,
                "prompt": f"Explain what this code does:\n{code}\n\nExplanation:",
                "stream": False,
                "options": {"num_predict": 100}
            }
        )

        assert response.status_code == 200
        data = response.json()
        assert "response" in data


@pytest.mark.skipif(not ollama_available(), reason="Ollama not running")
class TestValidationPrompt:
    """Test the validation prompt used by Validator Agent."""

    def test_validation_response_format(self, ollama_client):
        """Test that Ollama can produce structured validation responses."""

        original_code = "total = price * quantity"
        fixed_code = "total = Decimal(str(price)) * Decimal(str(quantity))"

        prompt = f"""Analyze this code fix for correctness.

Original (Buggy):
```python
{original_code}
```

Proposed Fix:
```python
{fixed_code}
```

Bug Type: payment_calculation
Explanation: Use Decimal for precise financial calculations

Is this fix correct? Respond with VALID or INVALID and explain briefly."""

        response = ollama_client.post(
            "/api/generate",
            json={
                "model": OLLAMA_MODEL,
                "prompt": prompt,
                "stream": False,
                "options": {"num_predict": 150}
            }
        )

        assert response.status_code == 200
        data = response.json()
        result = data["response"].upper()

        # Response should contain a clear judgment
        assert "VALID" in result or "INVALID" in result or "CORRECT" in result

    def test_bug_detection(self, ollama_client):
        """Test that Ollama can identify bugs in code."""

        buggy_code = """
def calculate_total(price, quantity):
    # Bug: Using float for currency
    return price * quantity

def apply_discount(total, percent):
    # Bug: Division error for percentage
    return total - (total * percent)
"""

        prompt = f"""Review this code for bugs:

```python
{buggy_code}
```

List any bugs you find:"""

        response = ollama_client.post(
            "/api/generate",
            json={
                "model": OLLAMA_MODEL,
                "prompt": prompt,
                "stream": False,
                "options": {"num_predict": 200}
            }
        )

        assert response.status_code == 200
        data = response.json()
        # Response should mention something about the code
        assert len(data["response"]) > 20


@pytest.mark.skipif(not ollama_available(), reason="Ollama not running")
class TestPerformance:
    """Test Ollama performance metrics."""

    def test_response_time(self, ollama_client):
        """Test that responses come within acceptable time."""
        import time

        start = time.time()

        response = ollama_client.post(
            "/api/generate",
            json={
                "model": OLLAMA_MODEL,
                "prompt": "def hello():\n    print(",
                "stream": False,
                "options": {"num_predict": 10}
            }
        )

        elapsed = time.time() - start

        assert response.status_code == 200
        # First token should arrive within 30 seconds (includes model loading)
        assert elapsed < 30, f"Response took too long: {elapsed:.2f}s"

    def test_concurrent_requests(self, ollama_client):
        """Test handling of concurrent validation requests."""
        import concurrent.futures

        def make_request():
            return ollama_client.post(
                "/api/generate",
                json={
                    "model": OLLAMA_MODEL,
                    "prompt": "# Python function\ndef test():",
                    "stream": False,
                    "options": {"num_predict": 20}
                }
            )

        # Test with 3 concurrent requests
        with concurrent.futures.ThreadPoolExecutor(max_workers=3) as executor:
            futures = [executor.submit(make_request) for _ in range(3)]
            results = [f.result() for f in concurrent.futures.as_completed(futures)]

        # All requests should succeed
        for response in results:
            assert response.status_code == 200


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
