"""
classifier.py — graph-scope complexity to tier classification.

Tiers: "cheap" | "mid" | "full"

Upgrade 2: Quota-Aware Dynamic Routing
  The classifier reads live quota from detect_ide_and_plan() and applies
  self-throttling:  when Claude/GPT weekly allowance hits 0% the router
  automatically downshifts to cheap and prioritises local Ollama (Stage 4).
  When Gemini drops below 20% a developer warning is emitted.
"""
from __future__ import annotations

import logging
from typing import Optional

from tenet.config import RouterConfig

logger = logging.getLogger(__name__)

# Threshold below which Gemini is considered "low quota" (warn but don't downshift)
_GEMINI_LOW_QUOTA_PCT: float = 20.0


def get_live_quota_override() -> Optional[str]:
    """Query detect_ide_and_plan() for live quota state.

    Returns:
        ``"force_cheap"`` when Claude/GPT is exhausted (0%).
        ``"warn_gemini"`` when Gemini is below the low-quota threshold.
        ``None`` when all quotas are healthy.
    """
    try:
        from tenet.ide_detector import detect_ide_and_plan
        result = detect_ide_and_plan()
        claude_gpt = result.claude_gpt_quota
        gemini = result.gemini_quota

        if claude_gpt.remaining_pct <= 0.0 or claude_gpt.status == "exhausted":
            logger.info(
                "quota_router: Claude/GPT allowance at 0%% — forcing cheap/local tier"
            )
            return "force_cheap"

        if gemini.remaining_pct < _GEMINI_LOW_QUOTA_PCT or gemini.status == "warning":
            logger.warning(
                "quota_router: Gemini quota low (%.1f%%) — routing to cheap tier, prefer local Ollama",
                gemini.remaining_pct,
            )
            return "warn_gemini"
    except Exception as exc:
        logger.debug("quota_router: could not read live quota (%s), proceeding normally", exc)
    return None


def classify_tier(
    node_count: int,
    edge_count: int,
    config: RouterConfig,
    *,
    skip_quota_check: bool = False,
) -> str:
    """Classify a request into a routing tier based on scope size.

    **Upgrade 2 — Quota-Aware Dynamic Routing**:
    Before applying the normal node-count thresholds, the classifier queries
    live quota from detect_ide_and_plan().  When quota is exhausted or low,
    it automatically downshifts to ``"cheap"`` tier and logs a developer
    warning.  Pass ``skip_quota_check=True`` in tests to bypass this.

    Args:
        node_count: Number of nodes in the resolved subgraph.
        edge_count: Number of edges in the resolved subgraph.
        config: Router configuration with tier definitions.
        skip_quota_check: If True, bypass live quota check (useful in tests).

    Returns:
        One of ``"cheap"``, ``"mid"``, or ``"full"``.
    """
    # ── Quota-aware self-throttling ───────────────────────────────────────────
    if not skip_quota_check:
        quota_state = get_live_quota_override()
        if quota_state == "force_cheap":
            logger.warning(
                "⚠  QUOTA AUTO-PILOT: Claude/GPT exhausted — forced to 'cheap' tier. "
                "Stage 4 local Ollama will be prioritised. No costly model escalation."
            )
            return "cheap"
        if quota_state == "warn_gemini":
            logger.warning(
                "⚠  QUOTA WARNING: Gemini below %.0f%% — routing to 'cheap' tier to preserve quota.",
                _GEMINI_LOW_QUOTA_PCT,
            )
            return "cheap"

    # ── Normal tier classification ────────────────────────────────────────────
    cheap = config.tiers.cheap
    mid = config.tiers.mid

    # Check "cheap" tier
    cheap_nodes_ok = cheap.max_nodes is None or node_count <= cheap.max_nodes
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
