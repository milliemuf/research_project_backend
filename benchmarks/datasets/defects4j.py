"""
Defects4J adapter.

Reads bug metadata from a Defects4J checkout and emits BugCase objects.
Defects4J must be installed and on PATH:

    git clone https://github.com/rjust/defects4j ./data/bug_datasets/defects4j
    cd ./data/bug_datasets/defects4j
    cpanm --installdeps .
    ./init.sh
    export PATH=$PATH:./framework/bin

This adapter does NOT itself install Defects4J; it just reads from an
already-installed checkout. The setup script
`scripts/setup_defects4j.ps1` handles installation.

Author: Millicent Mufambi (H240624A)
"""
from __future__ import annotations

import os
import shutil
import subprocess
from pathlib import Path
from typing import List, Optional

import structlog

from benchmarks.bug_case import BugCase

logger = structlog.get_logger(__name__)


# Mapping of Defects4J project ID -> {bugs, language}.
# Only Java projects are supported by Defects4J upstream; we expose them
# here for completeness even though the synthetic + BugsInPy paths cover
# the Python case the prototype actually runs.
KNOWN_PROJECTS = {
    "Lang": {"language": "java", "max_bug": 65},
    "Math": {"language": "java", "max_bug": 106},
    "Time": {"language": "java", "max_bug": 27},
    "Chart": {"language": "java", "max_bug": 26},
    "Closure": {"language": "java", "max_bug": 176},
    "Mockito": {"language": "java", "max_bug": 38},
}


def is_available() -> bool:
    """Return True iff `defects4j` is on PATH."""
    return shutil.which("defects4j") is not None


def _run_defects4j(args: List[str], cwd: Optional[str] = None) -> subprocess.CompletedProcess:
    return subprocess.run(
        ["defects4j"] + args,
        cwd=cwd,
        capture_output=True,
        text=True,
        check=False,
    )


def load(
    project: str = "Lang",
    bug_ids: Optional[List[int]] = None,
    limit: Optional[int] = None,
    workdir_root: Optional[str] = None,
) -> List[BugCase]:
    """
    Load BugCases from Defects4J. Each BugCase corresponds to one Defects4J
    bug; the test command runs the project's failing tests inside the
    sandbox.

    Args:
        project: Defects4J project ID (e.g. "Lang", "Math").
        bug_ids: Specific bug numbers to include. If None, take 1..limit.
        limit: Cap the number of bugs returned.
        workdir_root: Where to check out the buggy versions.

    Returns:
        List[BugCase].
    """
    if not is_available():
        logger.warning(
            "defects4j not on PATH; returning empty list. "
            "Run scripts/setup_defects4j.ps1 to install."
        )
        return []

    if project not in KNOWN_PROJECTS:
        logger.warning("Unknown Defects4J project", project=project)
        return []

    project_info = KNOWN_PROJECTS[project]
    if bug_ids is None:
        max_n = limit or project_info["max_bug"]
        bug_ids = list(range(1, min(max_n, project_info["max_bug"]) + 1))

    workdir_root = workdir_root or os.path.join(os.getcwd(), "data", "defects4j_workdirs")
    Path(workdir_root).mkdir(parents=True, exist_ok=True)

    cases: List[BugCase] = []
    for bug_id in bug_ids:
        try:
            case = _checkout_one(project, bug_id, workdir_root)
            if case is not None:
                cases.append(case)
        except Exception as e:
            logger.warning(
                "Failed to load Defects4J bug",
                project=project,
                bug_id=bug_id,
                error=str(e),
            )
        if limit is not None and len(cases) >= limit:
            break

    return cases


def _checkout_one(project: str, bug_id: int, workdir_root: str) -> Optional[BugCase]:
    workdir = os.path.join(workdir_root, f"{project}_{bug_id}b")
    if not Path(workdir).exists():
        result = _run_defects4j([
            "checkout", "-p", project, "-v", f"{bug_id}b", "-w", workdir,
        ])
        if result.returncode != 0:
            logger.warning(
                "defects4j checkout failed",
                project=project,
                bug_id=bug_id,
                stderr=result.stderr[-500:],
            )
            return None

    # Get the trigger test command
    trigger_proc = _run_defects4j(["export", "-p", "tests.trigger"], cwd=workdir)
    trigger = trigger_proc.stdout.strip().splitlines()[0] if trigger_proc.stdout.strip() else ""

    # Get the buggy class location (first item in modified.classes)
    classes_proc = _run_defects4j(["export", "-p", "classes.modified"], cwd=workdir)
    modified_classes = classes_proc.stdout.strip().splitlines()
    primary_class = modified_classes[0] if modified_classes else ""

    code_context = _read_class_source(workdir, primary_class) if primary_class else ""

    return BugCase(
        bug_id=f"d4j-{project}-{bug_id}",
        project=project,
        error_message=f"Defects4J bug {project}-{bug_id}; failing test: {trigger}",
        stack_trace=trigger,
        code_context=code_context[:8000],
        file_path=primary_class.replace(".", "/") + ".java" if primary_class else "Unknown.java",
        line_number=1,
        language="java",
        test_command=["defects4j", "test", "-t", trigger] if trigger else ["defects4j", "test"],
        canonical_fixed_code=None,  # available via `defects4j checkout -v {n}f` separately
        metadata={
            "trigger_test": trigger,
            "modified_classes": modified_classes,
            "workdir": workdir,
        },
    )


def _read_class_source(workdir: str, class_fqn: str) -> str:
    rel_path = class_fqn.replace(".", "/") + ".java"
    for root, _, _ in os.walk(workdir):
        candidate = Path(root) / rel_path
        if candidate.exists():
            try:
                return candidate.read_text(encoding="utf-8", errors="replace")
            except Exception:
                return ""
    return ""
