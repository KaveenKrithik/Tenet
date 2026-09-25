"""
pipeline.py — orchestrates all 6 stages end-to-end.

process_request() is the single entry point. It runs each stage in order,
short-circuits on success (cache hit, local success), and always writes
exactly one ledger entry regardless of which stage terminates the request.
"""
from __future__ import annotations

import hashlib
import logging
from dataclasses import dataclass, field
from typing import Callable, Optional

# These are imported at module level so patch('tenet.pipeline.generate')
# and patch('tenet.pipeline.OllamaUnavailableError') work in tests.
from tenet.triage.ollama_client import OllamaUnavailableError, generate
from tenet.triage.validator import validate_output

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Result types
# ---------------------------------------------------------------------------

@dataclass
class PipelineResult:
    """The outcome of a single pipeline run."""
    stage_reached: str            # "cache_hit" | "local_success" | "escalated"
    response: Optional[str]       # populated on cache_hit and local_success
    compressed_payload: object    # ContextPayload for escalated path
    tier: Optional[str]           # "cheap" | "mid" | "full" (router output)
    estimated_tokens: int
    scope_node_count: int
    scope_edge_count: int
    requires_confirmation: bool
    ledger_id: Optional[int] = None
    metadata: dict = field(default_factory=dict)


# ---------------------------------------------------------------------------
# Main entry point
# ---------------------------------------------------------------------------

def process_request(
    prompt: str,
    touched_files: list[str],
    config=None,
    graph_store=None,
    cache=None,
    ledger=None,
    confirmation_callback: Optional[Callable[[int, str], bool]] = None,
    actual_tokens_callback: Optional[Callable[[int, int], None]] = None,
) -> PipelineResult:
    """Run the full 6-stage pipeline for a developer prompt.

    Stages:
      1. Graph update for touched files.
      2. Scope + compressed context computation.
      3. Semantic cache lookup → return on hit.
      4. Local Ollama triage → return on validated success.
      5. Tier classification + budget guard.
      6. Return escalated result + log to ledger.

    Args:
        prompt: Developer's coding prompt.
        touched_files: Files relevant to this request (used for graph scope).
        config: Optional pre-loaded TenetConfig. Loaded from disk if None.
        graph_store: Optional GraphStore. Created from config if None.
        cache: Optional SemanticCache. Created from config if None.
        ledger: Optional LedgerStore. Created from config if None.
        confirmation_callback: Called with (estimated_tokens, tier) when confirmation
            is required. Should return True to proceed, False to abort. Defaults to
            auto-proceeding.
        actual_tokens_callback: Called with (ledger_id, actual_token_count) after
            the escalated backend reports real usage. Optional.

    Returns:
        PipelineResult with full metadata.
    """
    from tenet.config import load_config
    from tenet.graph.builder import update_graph
    from tenet.graph.query import find_nodes_for_files, get_scope_size, get_subgraph
    from tenet.graph.store import GraphStore
    from tenet.diffing.ast_diff import ContextPayload, compress_context
    from tenet.cache.semantic_cache import SemanticCache
    from tenet.router.classifier import classify_tier
    from tenet.router.budget import estimate_tokens, requires_confirmation
    from tenet.ledger.store import LedgerStore

    # ── Bootstrap dependencies ────────────────────────────────────────────
    if config is None:
        config = load_config()

    if graph_store is None:
        graph_store = GraphStore(config.graph.db_path)

    if cache is None:
        cache = SemanticCache(
            db_path=config.cache.db_path,
            embedding_model=config.cache.embedding_model,
            similarity_threshold=config.cache.similarity_threshold,
            ttl_hours=config.cache.ttl_hours,
        )

    if ledger is None:
        ledger = LedgerStore(config.ledger.db_path)

    # ── Stage 0: Prompt Optimization ──────────────────────────────────────
    from tenet.triage.prompt_optimizer import optimize_prompt
    logger.info("pipeline: stage 0 — prompt optimization")
    original_prompt = prompt
    prompt = optimize_prompt(prompt, config)
    if prompt != original_prompt:
        logger.info("pipeline: prompt optimized from %d to %d chars", len(original_prompt), len(prompt))

    # ── Stage 1: Update graph for touched files ───────────────────────────
    logger.info("pipeline: stage 1 — graph update for %d files", len(touched_files))
    if touched_files:
        try:
            update_graph(touched_files, graph_store)
        except Exception as exc:
            logger.warning("pipeline: graph update failed (non-fatal): %s", exc)

    # Resolve scope: find center node from touched files
    scope_nodes = find_nodes_for_files(touched_files, graph_store)
    if not scope_nodes:
        # Fall back to any node in the graph as a heuristic
        scope_nodes = graph_store.get_all_nodes()[:5]

    center_id = scope_nodes[0]["id"] if scope_nodes else ""

    # ── Stage 1b: Compute scope size ─────────────────────────────────────
    hops = config.graph.max_hops
    if center_id:
        node_count, edge_count = get_scope_size(center_id, hops, graph_store)
    else:
        node_count, edge_count = 0, 0

    logger.info("pipeline: scope — %d nodes, %d edges", node_count, edge_count)

    # ── Stage 2: Compressed context ───────────────────────────────────────
    logger.info("pipeline: stage 2 — context compression")
    if center_id:
        context = compress_context(center_id, hops, [], graph_store)
    else:
        context = ContextPayload()

    scope_node_ids = [n["id"] for n in scope_nodes] if scope_nodes else context.scope_node_ids

    # Token estimate for naive (no pipeline) baseline
    estimated_naive = node_count * config.router.tokens_per_node_estimate

    # ── Stage 3: Semantic cache ────────────────────────────────────────────
    logger.info("pipeline: stage 3 — semantic cache lookup")
    cache_result = None
    try:
        cache_result = cache.get(prompt, scope_node_ids)
    except Exception as exc:
        logger.warning("pipeline: cache lookup failed (non-fatal): %s", exc)

    if cache_result is not None:
        logger.info("pipeline: CACHE HIT (sim=%.4f)", cache_result.similarity)
        ledger_id = ledger.log_request(
            prompt_summary=prompt[:200],
            stage_reached="cache_hit",
            scope_node_count=node_count,
            estimated_tokens_naive=estimated_naive,
            estimated_tokens_actual=0,
            module_attribution=_module_from_files(touched_files),
        )
        return PipelineResult(
            stage_reached="cache_hit",
            response=cache_result.response,
            compressed_payload=context,
            tier=None,
            estimated_tokens=0,
            scope_node_count=node_count,
            scope_edge_count=edge_count,
            requires_confirmation=False,
            ledger_id=ledger_id,
        )

    # ── Stage 4: Local model triage ───────────────────────────────────────
    local_response: Optional[str] = None
    local_within_scope = node_count <= (config.triage.max_local_hops * 5)  # heuristic

    if local_within_scope:
        logger.info("pipeline: stage 4 — local Ollama triage")
        try:
            raw_response = generate(
                prompt=prompt,
                context=context,
                model=config.triage.ollama_model,
                host=config.triage.ollama_host,
            )
            validation = validate_output(raw_response, "code")
            if validation.passed:
                logger.info("pipeline: local success (validation: %s)", validation.reason)
                # Store in cache for future hits
                try:
                    cache.set(prompt, scope_node_ids, raw_response)
                except Exception as exc:
                    logger.warning("pipeline: cache set failed (non-fatal): %s", exc)

                ledger_id = ledger.log_request(
                    prompt_summary=prompt[:200],
                    stage_reached="local_success",
                    scope_node_count=node_count,
                    estimated_tokens_naive=estimated_naive,
                    estimated_tokens_actual=context.estimated_tokens,
                    module_attribution=_module_from_files(touched_files),
                )
                return PipelineResult(
                    stage_reached="local_success",
                    response=raw_response,
                    compressed_payload=context,
                    tier=None,
                    estimated_tokens=context.estimated_tokens,
                    scope_node_count=node_count,
                    scope_edge_count=edge_count,
                    requires_confirmation=False,
                    ledger_id=ledger_id,
                )
            else:
                logger.info("pipeline: local validation failed (%s) → escalating", validation.reason)

        except OllamaUnavailableError as exc:
            logger.warning("pipeline: Ollama unavailable (%s) → skipping stage 4", exc)
        except Exception as exc:
            logger.warning("pipeline: stage 4 unexpected error (%s) → escalating", exc)
    else:
        logger.info("pipeline: scope too large for local triage (%d nodes) → stage 5", node_count)

    # ── Stage 5: Router — tier + budget ──────────────────────────────────
    logger.info("pipeline: stage 5 — tier classification + budget")
    tier = classify_tier(node_count, edge_count, config.router)
    estimated_tokens = estimate_tokens(node_count, config.router)
    needs_confirm = requires_confirmation(estimated_tokens, config.router)

    if needs_confirm and confirmation_callback:
        proceed = confirmation_callback(estimated_tokens, tier)
        if not proceed:
            logger.info("pipeline: user declined confirmation, aborting escalation")
            ledger_id = ledger.log_request(
                prompt_summary=prompt[:200],
                stage_reached="escalated",
                scope_node_count=node_count,
                estimated_tokens_naive=estimated_naive,
                estimated_tokens_actual=0,
                module_attribution=_module_from_files(touched_files),
            )
            return PipelineResult(
                stage_reached="escalated",
                response=None,
                compressed_payload=context,
                tier=tier,
                estimated_tokens=estimated_tokens,
                scope_node_count=node_count,
                scope_edge_count=edge_count,
                requires_confirmation=True,
                ledger_id=ledger_id,
                metadata={"aborted_by_user": True},
            )

    # ── Stage 6: Log escalation, return payload ───────────────────────────
    logger.info("pipeline: escalating (tier=%s, ~%d tokens)", tier, estimated_tokens)
    ledger_id = ledger.log_request(
        prompt_summary=prompt[:200],
        stage_reached="escalated",
        scope_node_count=node_count,
        estimated_tokens_naive=estimated_naive,
        estimated_tokens_actual=estimated_tokens,
        module_attribution=_module_from_files(touched_files),
    )

    # Register callback for when the actual backend reports usage
    if actual_tokens_callback and ledger_id:
        # The caller invokes this after the backend responds
        pass  # ledger_id is in the result for the caller to use

    return PipelineResult(
        stage_reached="escalated",
        response=None,
        compressed_payload=context,
        tier=tier,
        estimated_tokens=estimated_tokens,
        scope_node_count=node_count,
        scope_edge_count=edge_count,
        requires_confirmation=needs_confirm,
        ledger_id=ledger_id,
    )


def _module_from_files(file_paths: list[str]) -> str:
    """Derive a module attribution string from the touched file paths."""
    if not file_paths:
        return "unknown"
    # Use the first file's parent directory as module attribution
    from pathlib import Path
    return str(Path(file_paths[0]).parent.name)
