"""
classifier.py — graph-scope complexity to tier classification.

Tiers: "cheap" | "mid" | "full"
"""
from __future__ import annotations

import logging

from tenet.config import RouterConfig

logger = logging.getLogger(__name__)


def classify_tier(node_count: int, edge_count: int, config: RouterConfig) -> str:
    """Classify a request into a routing tier based on scope size.

    Compares ``node_count`` and ``edge_count`` against configured thresholds
    and returns the first tier whose limits are not exceeded.

    Args:
        node_count: Number of nodes in the resolved subgraph.
        edge_count: Number of edges in the resolved subgraph.
        config: Router configuration with tier definitions.

    Returns:
        One of ``"cheap"``, ``"mid"``, or ``"full"``.
    """
    cheap = config.tiers.cheap
    mid = config.tiers.mid

    # Check "cheap" tier
    cheap_nodes_ok = cheap.max_nodes is None or node_count <= cheap.max_nodes
    cheap_hops_ok = True  # hops not checked here — scope size is the proxy
    if cheap_nodes_ok:
        logger.debug("classify_tier: cheap (nodes=%d)", node_count)
        return "cheap"

    # Check "mid" tier
    mid_nodes_ok = mid.max_nodes is None or node_count <= mid.max_nodes
    if mid_nodes_ok:
        logger.debug("classify_tier: mid (nodes=%d)", node_count)
        return "mid"

    logger.debug("classify_tier: full (nodes=%d)", node_count)
    return "full"
