"""
git_diff.py — Git-Diff Context Pinning ("Active Working Set Awareness").

Upgrade 3: Query git diff --name-only / --cached to discover which files
the developer is currently editing and inject higher centrality weights into
the BFS/PageRank traversals so the compressed context focuses on the active
working set rather than treating all nodes equally.
"""
from __future__ import annotations

import logging
import subprocess
from pathlib import Path
from typing import Optional

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Git-diff query helpers
# ---------------------------------------------------------------------------

def get_git_touched_files(repo_root: str = ".") -> list[str]:
    """Return the union of staged and unstaged changed files relative to HEAD.

    Runs two git commands:
    1. ``git diff --name-only``          — unstaged changes
    2. ``git diff --cached --name-only`` — staged changes

    Returns absolute paths.  On any git failure (not a repo, no commits, etc.)
    returns an empty list so the pipeline degrades gracefully.
    """
    touched: set[str] = set()
    root = Path(repo_root).resolve()

    for args in (
        ["git", "diff", "--name-only"],
        ["git", "diff", "--cached", "--name-only"],
    ):
        try:
            result = subprocess.run(
                args,
                capture_output=True,
                text=True,
                cwd=str(root),
                timeout=5,
            )
            if result.returncode == 0:
                for line in result.stdout.splitlines():
                    line = line.strip()
                    if line:
                        abs_path = str(root / line)
                        touched.add(abs_path)
        except (subprocess.TimeoutExpired, FileNotFoundError, OSError) as exc:
            logger.debug("get_git_touched_files: git command failed (%s)", exc)

    logger.debug("get_git_touched_files: %d touched files from git diff", len(touched))
    return list(touched)


def get_git_touched_symbols(repo_root: str = ".") -> list[str]:
    """Return the raw symbol names from git diff --unified=0 hunk headers.

    Parses the ``@@ ... @@ <symbol>`` portion of unified diff output to
    extract function/method names that are actively being edited.

    Returns a list of symbol name strings (may contain duplicates).
    """
    symbols: list[str] = []
    root = Path(repo_root).resolve()

    try:
        result = subprocess.run(
            ["git", "diff", "--unified=0"],
            capture_output=True,
            text=True,
            cwd=str(root),
            timeout=10,
        )
        if result.returncode != 0:
            return symbols

        for line in result.stdout.splitlines():
            # Hunk headers look like: @@ -10,3 +10,5 @@ def my_function(x):
            if line.startswith("@@ ") and " @@ " in line:
                after_hunk = line.split(" @@ ", 1)[-1].strip()
                if after_hunk:
                    # Extract the symbol name (first word before '(')
                    token = after_hunk.split("(")[0].strip().split()[-1] if after_hunk else ""
                    if token:
                        symbols.append(token)
    except (subprocess.TimeoutExpired, FileNotFoundError, OSError) as exc:
        logger.debug("get_git_touched_symbols: git command failed (%s)", exc)

    logger.debug("get_git_touched_symbols: %d symbols from hunk headers", len(symbols))
    return symbols


# ---------------------------------------------------------------------------
# Centrality weight computation
# ---------------------------------------------------------------------------

_GIT_TOUCHED_WEIGHT_BOOST: float = 3.0   # boost factor for actively modified files
_GIT_SYMBOL_WEIGHT_BOOST: float = 5.0    # even stronger boost for symbol-level hits


def compute_node_weights(
    nodes: list[dict],
    touched_files: list[str],
    touched_symbols: list[str],
    git_files: Optional[list[str]] = None,
    git_symbols: Optional[list[str]] = None,
) -> dict[str, float]:
    """Return a ``{node_id: weight}`` dict for BFS/PageRank guidance.

    Nodes whose file appears in the git diff receive a weight boost so that
    the scope computation focuses on the active working set.

    Args:
        nodes: Raw node dicts from the graph store.
        touched_files: Files provided explicitly by the caller (CLI --files).
        touched_symbols: Symbol names provided explicitly by the caller.
        git_files: Files discovered from git diff (from ``get_git_touched_files``).
        git_symbols: Symbol names from git diff hunk headers.

    Returns:
        Dict mapping node_id → relative weight.  Default weight is 1.0.
    """
    git_files = git_files or []
    git_symbols = git_symbols or []

    # Build lookup sets (normalised paths)
    explicit_files = set(str(Path(f).resolve()) for f in touched_files)
    all_git_files = set(str(Path(f).resolve()) for f in git_files)
    all_touched_files = explicit_files | all_git_files

    touched_symbol_set = set(touched_symbols)
    git_symbol_set = set(git_symbols)
    all_active_symbols = touched_symbol_set | git_symbol_set

    weights: dict[str, float] = {}

    for node in nodes:
        nid = node.get("id", "")
        if not nid:
            continue

        weight = 1.0
        node_file = str(Path(node.get("file_path", "")).resolve())
        node_name = node.get("name", "")

        # File-level boost from git diff
        if node_file in all_touched_files:
            weight *= _GIT_TOUCHED_WEIGHT_BOOST

        # Symbol-level boost from hunk headers (strongest signal)
        if node_name in all_active_symbols:
            weight *= _GIT_SYMBOL_WEIGHT_BOOST

        weights[nid] = weight

    return weights


def get_git_boosted_center_node(
    nodes: list[dict],
    weights: dict[str, float],
    fallback_node_id: Optional[str] = None,
) -> Optional[str]:
    """Return the highest-weighted node ID to use as BFS center.

    When git diff reveals actively modified symbols, the center of the BFS
    traversal is anchored to the most heavily modified node rather than the
    first node found in the touched files list.

    Args:
        nodes: Raw node dicts.
        weights: Output of ``compute_node_weights``.
        fallback_node_id: Return this if no weighted node is found.

    Returns:
        Node ID of the best center node.
    """
    if not weights:
        return fallback_node_id

    best_id = max(weights, key=lambda nid: weights[nid])
    best_weight = weights[best_id]

    # Only override if there's a genuine signal (weight > 1.0)
    if best_weight > 1.0:
        logger.info(
            "git_diff: pinning BFS center to '%s' (git weight=%.1f)",
            best_id, best_weight,
        )
        return best_id

    return fallback_node_id
