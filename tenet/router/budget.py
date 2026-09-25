"""
budget.py — token cost estimation and confirmation gate.

Token counts are estimated from node count * per-node heuristic.
Once real ledger data exists, the heuristic is refined automatically.
"""
from __future__ import annotations

import logging

from tenet.config import RouterConfig

logger = logging.getLogger(__name__)


def estimate_tokens(node_count: int, config: RouterConfig, actual_avg_per_node: float | None = None) -> int:
    """Estimate the number of tokens for a request of this scope.

    Uses ``actual_avg_per_node`` (from the ledger) when available; falls back
    to the configured heuristic ``tokens_per_node_estimate``.

    Args:
        node_count: Number of nodes in the resolved subgraph.
        config: Router configuration.
        actual_avg_per_node: Refined per-node token average from ledger history.

    Returns:
        Estimated token count (integer).
    """
    per_node = actual_avg_per_node if actual_avg_per_node else config.tokens_per_node_estimate
    estimate = int(node_count * per_node)
    logger.debug("estimate_tokens: nodes=%d, per_node=%.1f → %d tokens", node_count, per_node, estimate)
    return estimate


def requires_confirmation(estimated_tokens: int, config: RouterConfig) -> bool:
    """Return True if the estimated token cost exceeds the confirmation threshold.

    When True, the pipeline should pause and request developer confirmation
    before escalating to an expensive backend.

    Args:
        estimated_tokens: Output of ``estimate_tokens``.
        config: Router configuration.

    Returns:
        True if confirmation is required.
    """
    threshold = config.cost_confirmation_threshold_tokens
    result = estimated_tokens > threshold
    if result:
        logger.info(
            "budget: confirmation required — estimated %d tokens > threshold %d",
            estimated_tokens, threshold,
        )
    return result
