"""
Sandbox executor for running candidate fixes safely.

A consensus-approved fix is run inside an isolated container (Docker preferred,
subprocess fallback) before being applied to the real codebase. This is
critical for safety: a fix that satisfies the LLM consensus may still break
something at runtime, and we must not apply it without an empirical check.

The executor returns a SandboxResult capturing:
- whether the patched code runs at all
- whether the supplied test command passes
- stdout, stderr, exit code, and wall-clock duration

Author: Millicent Mufambi (H240624A)
"""

from __future__ import annotations

import asyncio
import os
import shutil
import sys
import tempfile
from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from pathlib import Path
from typing import Optional, List, Dict

import structlog

logger = structlog.get_logger(__name__)


class SandboxBackend(str, Enum):
    """Which isolation backend was used for execution."""
    DOCKER = "docker"
    SUBPROCESS = "subprocess"
    UNAVAILABLE = "unavailable"


@dataclass
class SandboxResult:
    """Outcome of running a candidate fix in the sandbox."""
    success: bool
    backend: SandboxBackend
    exit_code: int = -1
    stdout: str = ""
    stderr: str = ""
    duration_ms: float = 0.0
    timed_out: bool = False
    error: Optional[str] = None
    tests_passed: Optional[int] = None
    tests_failed: Optional[int] = None
    timestamp: datetime = field(default_factory=datetime.utcnow)

    def short_reason(self) -> str:
        """One-line description suitable for logging."""
        if self.timed_out:
            return f"timeout after {self.duration_ms:.0f}ms"
        if self.error:
            return self.error
        if self.success:
            return f"passed (exit 0, {self.duration_ms:.0f}ms)"
        return f"failed (exit {self.exit_code}, {self.duration_ms:.0f}ms)"


class SandboxExecutor:
    """
    Run candidate code in an isolated environment.

    Strategy:
      1. If Docker is available, run inside a one-shot container with no network
         and a tight CPU/memory limit.
      2. If Docker is not available, fall back to a subprocess in a tempdir
         (less isolated, but still keeps the fix off the real codebase).

    The executor never touches the real source tree directly. Callers stage
    the fix into a temporary directory and pass that to `run`.
    """

    DEFAULT_DOCKER_IMAGE = {
        "python": "python:3.11-slim",
        "javascript": "node:20-slim",
        "java": "eclipse-temurin:17-jdk",
    }

    def __init__(
        self,
        default_timeout_s: int = 30,
        memory_limit: str = "512m",
        cpu_limit: float = 1.0,
        force_backend: Optional[SandboxBackend] = None,
    ):
        self.default_timeout_s = default_timeout_s
        self.memory_limit = memory_limit
        self.cpu_limit = cpu_limit
        self._force_backend = force_backend
        self._docker_client = None
        self._docker_available: Optional[bool] = None

        logger.info(
            "Sandbox executor initialised",
            default_timeout_s=default_timeout_s,
            memory_limit=memory_limit,
            cpu_limit=cpu_limit,
        )

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------
    async def run(
        self,
        code: str,
        language: str = "python",
        test_command: Optional[List[str]] = None,
        run_command: Optional[List[str]] = None,
        timeout_s: Optional[int] = None,
        extra_files: Optional[Dict[str, str]] = None,
    ) -> SandboxResult:
        """
        Stage `code` into a temp dir and run it.

        Args:
            code: The candidate fixed source as a single file blob.
            language: Source language; controls default image and command.
            test_command: Optional command (list of args) to run the tests.
                          If None, falls back to running the file directly.
            run_command: Optional command to invoke when no test_command
                         is given. Defaults to a language-appropriate
                         "run this file" command.
            timeout_s: Wall-clock timeout in seconds.
            extra_files: Map of relative-path -> file content. Useful for
                         attaching test data alongside the candidate fix.

        Returns:
            SandboxResult.
        """
        timeout_s = timeout_s or self.default_timeout_s

        with tempfile.TemporaryDirectory(prefix="codeflow-sandbox-") as workdir:
            workpath = Path(workdir)
            main_filename = self._main_filename_for(language)
            (workpath / main_filename).write_text(code, encoding="utf-8")

            for relpath, content in (extra_files or {}).items():
                target = workpath / relpath
                target.parent.mkdir(parents=True, exist_ok=True)
                target.write_text(content, encoding="utf-8")

            command = test_command or run_command or self._default_run_command(language, main_filename)
            backend = await self._pick_backend()

            if self._force_backend:
                backend = self._force_backend

            if backend == SandboxBackend.DOCKER:
                result = await self._run_docker(workpath, command, language, timeout_s)
            elif backend == SandboxBackend.SUBPROCESS:
                result = await self._run_subprocess(workpath, command, timeout_s)
            else:
                result = SandboxResult(
                    success=False,
                    backend=SandboxBackend.UNAVAILABLE,
                    error="No execution backend available",
                )

            self._extract_test_counts(result)
            logger.info(
                "Sandbox run finished",
                backend=result.backend.value,
                success=result.success,
                duration_ms=result.duration_ms,
                reason=result.short_reason(),
            )
            return result

    # ------------------------------------------------------------------
    # Backend selection
    # ------------------------------------------------------------------
    async def _pick_backend(self) -> SandboxBackend:
        if self._docker_available is None:
            self._docker_available = await self._probe_docker()
        if self._docker_available:
            return SandboxBackend.DOCKER
        return SandboxBackend.SUBPROCESS

    async def _probe_docker(self) -> bool:
        try:
            import docker  # type: ignore  # imported lazily so app starts without docker
        except ImportError:
            logger.warning("docker SDK not installed; falling back to subprocess sandbox")
            return False
        try:
            self._docker_client = docker.from_env()
            self._docker_client.ping()
            return True
        except Exception as e:
            logger.warning("Docker daemon unreachable; falling back to subprocess sandbox", error=str(e))
            self._docker_client = None
            return False

    # ------------------------------------------------------------------
    # Docker backend
    # ------------------------------------------------------------------
    async def _run_docker(
        self,
        workpath: Path,
        command: List[str],
        language: str,
        timeout_s: int,
    ) -> SandboxResult:
        image = self.DEFAULT_DOCKER_IMAGE.get(language.lower(), self.DEFAULT_DOCKER_IMAGE["python"])

        loop = asyncio.get_event_loop()
        started = datetime.utcnow()

        def _run_blocking():
            assert self._docker_client is not None
            container = self._docker_client.containers.run(
                image=image,
                command=command,
                working_dir="/work",
                volumes={str(workpath): {"bind": "/work", "mode": "rw"}},
                network_disabled=True,
                mem_limit=self.memory_limit,
                nano_cpus=int(self.cpu_limit * 1e9),
                detach=True,
                stdout=True,
                stderr=True,
            )
            try:
                exit_status = container.wait(timeout=timeout_s)
                exit_code = exit_status.get("StatusCode", -1)
                logs_stdout = container.logs(stdout=True, stderr=False).decode("utf-8", errors="replace")
                logs_stderr = container.logs(stdout=False, stderr=True).decode("utf-8", errors="replace")
                return exit_code, logs_stdout, logs_stderr, False
            except Exception as e:
                if "timeout" in str(e).lower():
                    try:
                        container.kill()
                    except Exception:
                        pass
                    return -1, "", str(e), True
                return -1, "", str(e), False
            finally:
                try:
                    container.remove(force=True)
                except Exception:
                    pass

        try:
            exit_code, stdout, stderr, timed_out = await loop.run_in_executor(None, _run_blocking)
        except Exception as e:
            duration_ms = (datetime.utcnow() - started).total_seconds() * 1000
            return SandboxResult(
                success=False,
                backend=SandboxBackend.DOCKER,
                duration_ms=duration_ms,
                error=str(e),
            )

        duration_ms = (datetime.utcnow() - started).total_seconds() * 1000
        return SandboxResult(
            success=(exit_code == 0 and not timed_out),
            backend=SandboxBackend.DOCKER,
            exit_code=exit_code,
            stdout=stdout[-8000:],
            stderr=stderr[-8000:],
            duration_ms=duration_ms,
            timed_out=timed_out,
        )

    # ------------------------------------------------------------------
    # Subprocess backend
    # ------------------------------------------------------------------
    async def _run_subprocess(
        self,
        workpath: Path,
        command: List[str],
        timeout_s: int,
    ) -> SandboxResult:
        started = datetime.utcnow()
        try:
            proc = await asyncio.create_subprocess_exec(
                *command,
                cwd=str(workpath),
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
                env={**os.environ, "PYTHONDONTWRITEBYTECODE": "1"},
            )
        except FileNotFoundError as e:
            return SandboxResult(
                success=False,
                backend=SandboxBackend.SUBPROCESS,
                error=f"Command not found: {e}",
            )

        try:
            stdout_bytes, stderr_bytes = await asyncio.wait_for(proc.communicate(), timeout=timeout_s)
            timed_out = False
        except asyncio.TimeoutError:
            proc.kill()
            await proc.wait()
            stdout_bytes, stderr_bytes = b"", b""
            timed_out = True

        duration_ms = (datetime.utcnow() - started).total_seconds() * 1000
        exit_code = proc.returncode if not timed_out else -1
        return SandboxResult(
            success=(exit_code == 0 and not timed_out),
            backend=SandboxBackend.SUBPROCESS,
            exit_code=exit_code,
            stdout=stdout_bytes.decode("utf-8", errors="replace")[-8000:],
            stderr=stderr_bytes.decode("utf-8", errors="replace")[-8000:],
            duration_ms=duration_ms,
            timed_out=timed_out,
        )

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------
    @staticmethod
    def _main_filename_for(language: str) -> str:
        return {
            "python": "main.py",
            "javascript": "main.js",
            "java": "Main.java",
        }.get(language.lower(), "main.txt")

    def _default_run_command(self, language: str, main_filename: str) -> List[str]:
        return {
            "python": [sys.executable if self._force_backend == SandboxBackend.SUBPROCESS else "python", main_filename],
            "javascript": ["node", main_filename],
            "java": ["sh", "-c", f"javac {main_filename} && java {main_filename.replace('.java', '')}"],
        }.get(language.lower(), [sys.executable, main_filename])

    @staticmethod
    def _extract_test_counts(result: SandboxResult) -> None:
        """Best-effort parsing of pytest / unittest output."""
        import re
        for stream in (result.stdout, result.stderr):
            m = re.search(r"(\d+) passed.*?(\d+) failed", stream)
            if m:
                result.tests_passed = int(m.group(1))
                result.tests_failed = int(m.group(2))
                return
            m = re.search(r"(\d+) passed", stream)
            if m and result.tests_passed is None:
                result.tests_passed = int(m.group(1))


# Module-level singleton for convenience
sandbox_executor = SandboxExecutor()
