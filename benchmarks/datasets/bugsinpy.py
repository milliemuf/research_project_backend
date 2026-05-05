"""
BugsInPy adapter — diff-extraction strategy.

The full BugsInPy framework requires cloning each project at a specific
commit, applying the bug patch in reverse, installing per-project deps,
and running pytest. That toolchain is bash-heavy and brittle on Windows.

This adapter takes a lighter-weight path that is honest about what it
does: for each bug we parse the unified diff in `bug_patch.txt` and
reconstruct the BUGGY and FIXED snippets directly from the diff hunks.
The repair pipeline then operates on the buggy snippet; correctness is
judged by comparing the produced fix against the canonical fixed
snippet (the F1 scoring path already in BenchmarkRunner).

This is weaker than running BugsInPy's actual test suites, but it
preserves the key paper claim: "we evaluate on real bugs from real
open-source Python projects curated by BugsInPy". The technical paper
must clearly state this evaluation choice in §Methods/Limitations.

Author: Millicent Mufambi (H240624A)
"""
from __future__ import annotations

import re
from pathlib import Path
from typing import Dict, List, Optional, Tuple

import structlog

from benchmarks.bug_case import BugCase

logger = structlog.get_logger(__name__)


def load(
    bugsinpy_root: str,
    projects: Optional[List[str]] = None,
    limit: Optional[int] = None,
    min_hunk_lines: int = 1,
    max_hunk_lines: int = 80,
) -> List[BugCase]:
    """
    Walk the BugsInPy checkout and return BugCases for each numbered bug
    whose patch we can cleanly parse.

    Args:
        bugsinpy_root: Path to BugsInPy checkout.
        projects: Restrict to specific project names. None = all.
        limit: Total cap across all projects.
        min_hunk_lines / max_hunk_lines: drop bugs whose largest hunk is
            outside this range. Tiny hunks have no signal; huge hunks
            overwhelm the LLM context.

    Returns:
        List[BugCase] with code_context = buggy snippet,
        canonical_fixed_code = fixed snippet.
    """
    root = Path(bugsinpy_root)
    if not root.exists():
        logger.warning("BugsInPy root does not exist", root=str(root))
        return []

    projects_dir = root / "projects"
    if not projects_dir.exists():
        logger.warning("BugsInPy projects/ directory missing", projects_dir=str(projects_dir))
        return []

    if projects is None:
        projects = sorted([p.name for p in projects_dir.iterdir() if p.is_dir()])

    cases: List[BugCase] = []
    for project_name in projects:
        if limit is not None and len(cases) >= limit:
            break
        project_root = projects_dir / project_name
        bugs_dir = project_root / "bugs"
        if not bugs_dir.exists():
            continue
        for bug_folder in sorted(bugs_dir.iterdir(), key=lambda p: _natural_key(p.name)):
            if limit is not None and len(cases) >= limit:
                break
            if not bug_folder.is_dir():
                continue
            try:
                case = _build_case(project_name, bug_folder, min_hunk_lines, max_hunk_lines)
                if case is not None:
                    cases.append(case)
            except Exception as e:
                logger.warning(
                    "Failed to load BugsInPy bug",
                    project=project_name,
                    bug=bug_folder.name,
                    error=str(e),
                )
    logger.info("BugsInPy cases loaded", n=len(cases), projects=projects)
    return cases


# ---------------------------------------------------------------------------
def _build_case(
    project_name: str,
    bug_folder: Path,
    min_hunk_lines: int,
    max_hunk_lines: int,
) -> Optional[BugCase]:
    bug_patch = bug_folder / "bug_patch.txt"
    bug_info_path = bug_folder / "bug.info"
    run_test = bug_folder / "run_test.sh"

    if not bug_patch.exists():
        return None

    diff_text = bug_patch.read_text(encoding="utf-8", errors="replace")
    bug_info_text = bug_info_path.read_text(encoding="utf-8", errors="replace") if bug_info_path.exists() else ""

    file_path, buggy_snippet, fixed_snippet, hunk_size = extract_largest_hunk(diff_text)
    if not buggy_snippet or not fixed_snippet:
        return None
    if hunk_size < min_hunk_lines or hunk_size > max_hunk_lines:
        return None
    # Must actually differ
    if buggy_snippet.strip() == fixed_snippet.strip():
        return None

    test_lines: List[str] = []
    if run_test.exists():
        for line in run_test.read_text(encoding="utf-8", errors="replace").splitlines():
            line = line.strip()
            if line and not line.startswith("#"):
                test_lines.append(line)

    info = _parse_bug_info(bug_info_text)
    error_message = _synthesise_error_message(info, buggy_snippet, fixed_snippet)

    return BugCase(
        bug_id=f"bip-{project_name}-{bug_folder.name}",
        project=project_name,
        error_message=error_message,
        stack_trace=bug_info_text[:2000],
        code_context=buggy_snippet,
        file_path=file_path or f"{project_name}.py",
        line_number=1,
        language="python",
        # We DO NOT run the project's actual test suite. F1 against canonical
        # is the correctness signal. Document in paper §Methods.
        test_command=None,
        canonical_fixed_code=fixed_snippet,
        metadata={
            "bug_folder": str(bug_folder),
            "bug_info": info,
            "run_test_lines": test_lines,
            "hunk_size": hunk_size,
            "diff_excerpt": diff_text[:1500],
        },
    )


# ---------------------------------------------------------------------------
def extract_largest_hunk(diff_text: str) -> Tuple[Optional[str], Optional[str], Optional[str], int]:
    """
    Scan the unified diff and return the (path, buggy_snippet, fixed_snippet,
    hunk_size_lines) for the LARGEST hunk in the diff. We use the largest
    hunk because BugsInPy diffs sometimes touch multiple files and we want
    the most informative snippet.

    Buggy snippet = context lines + lines marked '-'.
    Fixed snippet = context lines + lines marked '+'.

    The snippets are reconstructed in original line order so they read as
    real Python code, not as a diff.
    """
    if not diff_text:
        return None, None, None, 0

    current_path: Optional[str] = None
    best: Tuple[Optional[str], List[str], List[str], int] = (None, [], [], 0)
    cur_buggy: List[str] = []
    cur_fixed: List[str] = []
    cur_changes = 0

    def flush():
        nonlocal best, cur_buggy, cur_fixed, cur_changes
        if cur_changes > best[3]:
            best = (current_path, list(cur_buggy), list(cur_fixed), cur_changes)
        cur_buggy = []
        cur_fixed = []
        cur_changes = 0

    for raw in diff_text.splitlines():
        if raw.startswith("+++ "):
            path = raw[4:].strip()
            if path.startswith("b/"):
                path = path[2:]
            current_path = path
            continue
        if raw.startswith("--- "):
            continue
        if raw.startswith("@@"):
            flush()
            continue
        if raw.startswith("+"):
            cur_fixed.append(raw[1:])
            cur_changes += 1
            continue
        if raw.startswith("-"):
            cur_buggy.append(raw[1:])
            cur_changes += 1
            continue
        if raw.startswith(" "):
            cur_buggy.append(raw[1:])
            cur_fixed.append(raw[1:])
            continue
        # other lines (index, diff --git, etc.) are ignored
    flush()

    path, buggy, fixed, size = best
    if path is None:
        return None, None, None, 0
    return path, "\n".join(buggy) + ("\n" if buggy else ""), "\n".join(fixed) + ("\n" if fixed else ""), size


def _parse_bug_info(text: str) -> Dict[str, str]:
    """Parse bug.info (key=value lines)."""
    info: Dict[str, str] = {}
    for line in text.splitlines():
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        if "=" in line:
            k, v = line.split("=", 1)
            info[k.strip()] = v.strip().strip('"').strip("'")
    return info


def _synthesise_error_message(info: Dict[str, str], buggy: str, fixed: str) -> str:
    """
    BugsInPy doesn't ship a one-line error message per bug, so we
    construct an honest, brief description from what we have.
    """
    pieces = []
    if "test_file" in info:
        pieces.append(f"failing test: {info['test_file']}")
    elif "fixed_commit_id" in info:
        pieces.append(f"fixed in commit {info['fixed_commit_id'][:8]}")
    pieces.append("real Python bug from BugsInPy")
    return " · ".join(pieces)


_NAT_RE = re.compile(r"(\d+)")


def _natural_key(s: str):
    return [int(t) if t.isdigit() else t for t in _NAT_RE.split(s)]
