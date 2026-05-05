"""
Sandbox module for safe execution of candidate fixes.

Provides isolated execution of LLM-generated patches before they are applied
to the actual codebase. Uses Docker by default with subprocess fallback.

Author: Millicent Mufambi (H240624A)
"""
from app.sandbox.docker_executor import (
    SandboxExecutor,
    SandboxResult,
    SandboxBackend,
    sandbox_executor,
)

__all__ = ["SandboxExecutor", "SandboxResult", "SandboxBackend", "sandbox_executor"]
