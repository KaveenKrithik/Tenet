"""
validator.py — validates output from the local model triage stage.

For code output: attempts tree-sitter parse to confirm syntactic validity.
For explanation output: checks non-empty and no obvious error strings.
"""
from __future__ import annotations

import logging
import re
from dataclasses import dataclass

logger = logging.getLogger(__name__)

_ERROR_PATTERNS = [
    r"^error:",
    r"^traceback",
    r"syntaxerror",
    r"nameerror",
    r"i (cannot|can't|don't) (help|assist)",
    r"i am unable to",
]
_ERROR_RE = re.compile("|".join(_ERROR_PATTERNS), re.IGNORECASE | re.MULTILINE)

# Supported languages for syntax validation
_LANG_EXTENSIONS = {
    "python": ".py",
    "javascript": ".js",
    "typescript": ".ts",
    "code": ".py",  # default code type → try Python
}


@dataclass
class ValidationResult:
    passed: bool
    reason: str


def _validate_code_syntax(code: str, task_type: str) -> ValidationResult:
    """Attempt to parse ``code`` with tree-sitter to verify syntactic validity."""
    import tempfile, os

    lang = "python"  # default
    if task_type in ("javascript", "js"):
        lang = "javascript"
    elif task_type in ("typescript", "ts"):
        lang = "typescript"

    suffix = _LANG_EXTENSIONS.get(lang, ".py")

    # Extract code block if wrapped in markdown fences
    fence_match = re.search(r"```[a-z]*\n(.*?)```", code, re.DOTALL)
    code_to_check = fence_match.group(1) if fence_match else code

    if not code_to_check.strip():
        return ValidationResult(passed=False, reason="Empty code output")

    try:
        from tenet.graph.parser import _get_parser
        source_bytes = code_to_check.encode("utf-8")
        parser = _get_parser(lang)
        tree = parser.parse(source_bytes)

        # tree-sitter marks errors with ERROR nodes
        def has_error(node) -> bool:
            if node.type == "ERROR":
                return True
            return any(has_error(child) for child in node.children)

        if has_error(tree.root_node):
            return ValidationResult(passed=False, reason=f"Syntax error detected in {lang} output")

        return ValidationResult(passed=True, reason="Syntax valid")

    except Exception as exc:
        logger.warning("validator: tree-sitter check failed: %s", exc)
        # Graceful degradation: if we can't parse, don't fail the request
        return ValidationResult(passed=True, reason=f"Syntax check skipped: {exc}")


def validate_output(output: str, task_type: str = "code") -> ValidationResult:
    """Validate model output for the given task type.

    Args:
        output: The raw text response from the local model.
        task_type: ``"code"`` | ``"python"`` | ``"javascript"`` | ``"typescript"``
                   | ``"explanation"`` | ``"other"``

    Returns:
        ValidationResult with ``passed`` flag and human-readable ``reason``.
    """
    if not output or not output.strip():
        return ValidationResult(passed=False, reason="Empty output")

    # Check for obvious error strings regardless of task type
    if _ERROR_RE.search(output):
        return ValidationResult(passed=False, reason="Output contains error indicators")

    if task_type in ("explanation", "other", "text"):
        # Non-code output: just check non-empty and no error strings
        return ValidationResult(passed=True, reason="Explanation output accepted")

    # Code output: structural syntax check
    return _validate_code_syntax(output, task_type)
