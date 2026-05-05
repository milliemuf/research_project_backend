"""
Patch applier — write a consensus-approved fix to disk safely.

Two operations matter here:
  1. atomic write: stage the new content under a temporary suffix, fsync,
     then rename over the original. This ensures readers never observe a
     half-written file.
  2. rollback: keep a backup so we can restore the original content if a
     follow-on check (e.g., a regression-test run) fails.

This module deliberately stays simple. It does not invoke git, run tests,
or interact with the agent manager. Higher-level orchestration lives in
`repair_pipeline.RepairPipeline`.

Author: Millicent Mufambi (H240624A)
"""

from __future__ import annotations

import os
import shutil
import tempfile
import uuid
from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from pathlib import Path
from typing import Dict, Optional

import structlog

logger = structlog.get_logger(__name__)


class PatchApplyStatus(str, Enum):
    APPLIED = "applied"
    ROLLED_BACK = "rolled_back"
    FAILED = "failed"
    DRY_RUN = "dry_run"


@dataclass
class PatchApplyResult:
    status: PatchApplyStatus
    file_path: str
    backup_id: Optional[str] = None
    backup_path: Optional[str] = None
    bytes_written: int = 0
    error: Optional[str] = None
    timestamp: datetime = field(default_factory=datetime.utcnow)


class PatchApplier:
    """
    Atomic patch application with rollback support.

    Usage:
        applier = PatchApplier(backup_root="/tmp/codeflow-backups")
        result = applier.apply(file_path, new_content)
        if not test_results_ok():
            applier.rollback(result.backup_id)
    """

    def __init__(self, backup_root: Optional[str] = None, dry_run: bool = False):
        self.backup_root = Path(backup_root or tempfile.mkdtemp(prefix="codeflow-backups-"))
        self.backup_root.mkdir(parents=True, exist_ok=True)
        self.dry_run = dry_run
        self._backups: Dict[str, Dict[str, str]] = {}
        logger.info(
            "Patch applier initialised",
            backup_root=str(self.backup_root),
            dry_run=dry_run,
        )

    # ------------------------------------------------------------------
    def apply(
        self,
        file_path: str,
        new_content: str,
        encoding: str = "utf-8",
    ) -> PatchApplyResult:
        """
        Atomically replace the contents of `file_path` with `new_content`.

        Returns a PatchApplyResult. On success the result includes a
        `backup_id` that can be passed to `rollback()`.
        """
        target = Path(file_path)

        if self.dry_run:
            logger.info("Dry-run patch apply", file_path=str(target))
            return PatchApplyResult(
                status=PatchApplyStatus.DRY_RUN,
                file_path=str(target),
                bytes_written=len(new_content.encode(encoding)),
            )

        if not target.exists():
            return PatchApplyResult(
                status=PatchApplyStatus.FAILED,
                file_path=str(target),
                error=f"target file does not exist: {target}",
            )

        backup_id = uuid.uuid4().hex[:12]
        backup_path = self.backup_root / f"{backup_id}__{target.name}"

        try:
            shutil.copy2(target, backup_path)
        except Exception as e:
            return PatchApplyResult(
                status=PatchApplyStatus.FAILED,
                file_path=str(target),
                error=f"backup failed: {e}",
            )

        # atomic write through a sibling temp file + rename
        tmp_fd, tmp_name = tempfile.mkstemp(
            dir=str(target.parent),
            prefix=f".{target.name}.",
            suffix=".codeflow-tmp",
        )
        try:
            with os.fdopen(tmp_fd, "w", encoding=encoding, newline="") as f:
                f.write(new_content)
                f.flush()
                os.fsync(f.fileno())
            os.replace(tmp_name, target)
        except Exception as e:
            try:
                os.unlink(tmp_name)
            except OSError:
                pass
            return PatchApplyResult(
                status=PatchApplyStatus.FAILED,
                file_path=str(target),
                backup_id=backup_id,
                backup_path=str(backup_path),
                error=f"write failed: {e}",
            )

        self._backups[backup_id] = {
            "file_path": str(target),
            "backup_path": str(backup_path),
            "applied_at": datetime.utcnow().isoformat(),
        }

        logger.info(
            "Patch applied",
            file_path=str(target),
            backup_id=backup_id,
            bytes=len(new_content.encode(encoding)),
        )

        return PatchApplyResult(
            status=PatchApplyStatus.APPLIED,
            file_path=str(target),
            backup_id=backup_id,
            backup_path=str(backup_path),
            bytes_written=len(new_content.encode(encoding)),
        )

    # ------------------------------------------------------------------
    def rollback(self, backup_id: str) -> PatchApplyResult:
        """
        Restore the file associated with `backup_id` to its pre-apply state.
        """
        info = self._backups.get(backup_id)
        if info is None:
            return PatchApplyResult(
                status=PatchApplyStatus.FAILED,
                file_path="",
                error=f"unknown backup_id: {backup_id}",
            )

        target = Path(info["file_path"])
        backup_path = Path(info["backup_path"])

        if not backup_path.exists():
            return PatchApplyResult(
                status=PatchApplyStatus.FAILED,
                file_path=str(target),
                error=f"backup file missing: {backup_path}",
            )

        try:
            shutil.copy2(backup_path, target)
        except Exception as e:
            return PatchApplyResult(
                status=PatchApplyStatus.FAILED,
                file_path=str(target),
                backup_id=backup_id,
                error=f"rollback copy failed: {e}",
            )

        logger.info(
            "Patch rolled back",
            file_path=str(target),
            backup_id=backup_id,
        )
        return PatchApplyResult(
            status=PatchApplyStatus.ROLLED_BACK,
            file_path=str(target),
            backup_id=backup_id,
            backup_path=str(backup_path),
        )

    def list_backups(self) -> Dict[str, Dict[str, str]]:
        return dict(self._backups)


# Module-level singleton for convenience
patch_applier = PatchApplier()
