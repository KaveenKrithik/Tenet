"""
ollama_client.py — wrapper around local Ollama API calls.

Gracefully handles the case where Ollama is not running so the pipeline
can skip Stage 4 without crashing.
"""
from __future__ import annotations

import logging
from dataclasses import dataclass

from tenet.diffing.ast_diff import ContextPayload

logger = logging.getLogger(__name__)


class OllamaUnavailableError(Exception):
    """Raised when the Ollama daemon cannot be reached."""


def _build_prompt(prompt: str, context: ContextPayload) -> str:
    """Assemble the final prompt text from a user prompt + compressed context."""
    parts = ["### Context\n"]
    for node_id, ctx_text in context.node_contexts.items():
        parts.append(f"--- {node_id} ---\n{ctx_text}\n")
    parts.append(f"\n### Task\n{prompt}")
    return "\n".join(parts)


def generate(
    prompt: str,
    context: ContextPayload,
    model: str = "qwen2.5-coder:7b",
    host: str = "http://localhost:11434",
) -> str:
    """Generate a response using the local Ollama model.

    Args:
        prompt: The user's coding prompt.
        context: Compressed context payload from Stage 2.
        model: Ollama model name (default: qwen2.5-coder:7b).
        host: Ollama API host (default: http://localhost:11434).

    Returns:
        The model's text response.

    Raises:
        OllamaUnavailableError: If the Ollama daemon is not reachable.
    """
    try:
        import ollama
        full_prompt = _build_prompt(prompt, context)
        logger.info("ollama_client: generating with model=%s, prompt_len=%d", model, len(full_prompt))

        client = ollama.Client(host=host)
        response = client.generate(model=model, prompt=full_prompt)
        if hasattr(response, "response"):
            return response.response or ""
        elif isinstance(response, dict):
            return response.get("response", "")
        return str(response)

    except ImportError as exc:
        raise OllamaUnavailableError("ollama package not installed") from exc
    except Exception as exc:
        # Connection refused, model not found, etc.
        err_str = str(exc).lower()
        if any(kw in err_str for kw in ("connection", "refused", "not found", "timeout", "network")):
            raise OllamaUnavailableError(f"Ollama unreachable: {exc}") from exc
        raise OllamaUnavailableError(f"Ollama error: {exc}") from exc
