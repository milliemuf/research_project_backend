"""
Sandbox API routes.

Exposes:
  POST /api/v1/sandbox/run    Run code in the isolated sandbox.
  GET  /api/v1/sandbox/info   Backend, defaults, recent runs.

Used by the Sandbox view in the frontend so users can see a fix being
executed live without going through the full repair pipeline.

Author: Millicent Mufambi (H240624A)
"""
from __future__ import annotations

from collections import deque
from datetime import datetime
from typing import Any, Deque, Dict, List, Optional

import structlog
from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

from app.sandbox import SandboxBackend, SandboxExecutor

logger = structlog.get_logger(__name__)

router = APIRouter()

# Module-level executor and recent-run history
_executor = SandboxExecutor(default_timeout_s=30)
_recent_runs: Deque[Dict[str, Any]] = deque(maxlen=20)


class SandboxRunRequest(BaseModel):
    code: str = Field(..., description="Source code to execute")
    language: str = Field("python", description="python | javascript | java")
    test_command: Optional[List[str]] = Field(
        None,
        description="Override the run command. If omitted, the language default is used.",
    )
    timeout_s: int = Field(15, ge=1, le=120, description="Wall-clock timeout")
    extra_files: Optional[Dict[str, str]] = Field(
        None,
        description="Optional map of relative path -> file content to stage alongside the main file",
    )


class SandboxRunResponse(BaseModel):
    success: bool
    backend: str
    exit_code: int
    duration_ms: float
    timed_out: bool
    stdout: str
    stderr: str
    tests_passed: Optional[int] = None
    tests_failed: Optional[int] = None
    error: Optional[str] = None
    timestamp: str
    short_reason: str


@router.post("/run", response_model=SandboxRunResponse)
async def run_in_sandbox(req: SandboxRunRequest) -> SandboxRunResponse:
    """
    Execute the supplied source in an isolated sandbox.

    Falls back to subprocess sandbox automatically when Docker is unavailable.
    """
    if not req.code.strip():
        raise HTTPException(status_code=400, detail="code must be non-empty")

    result = await _executor.run(
        code=req.code,
        language=req.language,
        test_command=req.test_command,
        timeout_s=req.timeout_s,
        extra_files=req.extra_files,
    )

    response = SandboxRunResponse(
        success=result.success,
        backend=result.backend.value,
        exit_code=result.exit_code,
        duration_ms=result.duration_ms,
        timed_out=result.timed_out,
        stdout=result.stdout[-4000:],
        stderr=result.stderr[-4000:],
        tests_passed=result.tests_passed,
        tests_failed=result.tests_failed,
        error=result.error,
        timestamp=result.timestamp.isoformat(),
        short_reason=result.short_reason(),
    )

    _recent_runs.appendleft({
        "timestamp": response.timestamp,
        "language": req.language,
        "success": response.success,
        "duration_ms": round(response.duration_ms, 1),
        "exit_code": response.exit_code,
        "backend": response.backend,
        "short_reason": response.short_reason,
        "code_preview": req.code[:200],
    })

    return response


@router.get("/info")
async def sandbox_info() -> Dict[str, Any]:
    """Return current sandbox configuration and recent run history."""
    backend = await _executor._pick_backend()
    return {
        "active_backend": backend.value,
        "default_timeout_s": _executor.default_timeout_s,
        "memory_limit": _executor.memory_limit,
        "cpu_limit": _executor.cpu_limit,
        "supported_languages": list(SandboxExecutor.DEFAULT_DOCKER_IMAGE.keys()),
        "recent_runs": list(_recent_runs),
    }
