"""
test_router_classifier.py — Stage 5 tests for classifier, budget, and multi_agent.
"""
from __future__ import annotations

import pytest

from tenet.config import RouterConfig, RouterTiersConfig, TierConfig
from tenet.router.budget import estimate_tokens, requires_confirmation
from tenet.router.classifier import classify_tier
from tenet.router.multi_agent import TaskScope, detect_overlaps


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture()
def default_router_config() -> RouterConfig:
    return RouterConfig(
        tiers=RouterTiersConfig(
            cheap=TierConfig(max_hops=2, max_nodes=5),
            mid=TierConfig(max_hops=5, max_nodes=20),
            full=TierConfig(max_hops=None, max_nodes=None),
        ),
        cost_confirmation_threshold_tokens=20000,
        tokens_per_node_estimate=800,
    )


# ---------------------------------------------------------------------------
# Classifier tests
# ---------------------------------------------------------------------------

class TestClassifier:
    def test_cheap_tier_small_scope(self, default_router_config):
        assert classify_tier(3, 4, default_router_config) == "cheap"

    def test_cheap_tier_at_boundary(self, default_router_config):
        assert classify_tier(5, 10, default_router_config) == "cheap"

    def test_mid_tier_medium_scope(self, default_router_config):
        assert classify_tier(10, 25, default_router_config) == "mid"

    def test_mid_tier_at_boundary(self, default_router_config):
        assert classify_tier(20, 50, default_router_config) == "mid"

    def test_full_tier_large_scope(self, default_router_config):
        assert classify_tier(50, 100, default_router_config) == "full"

    def test_zero_nodes_is_cheap(self, default_router_config):
        assert classify_tier(0, 0, default_router_config) == "cheap"


# ---------------------------------------------------------------------------
# Budget tests
# ---------------------------------------------------------------------------

class TestBudget:
    def test_estimate_uses_config_heuristic(self, default_router_config):
        est = estimate_tokens(10, default_router_config)
        assert est == 10 * 800

    def test_estimate_uses_actual_avg_when_provided(self, default_router_config):
        est = estimate_tokens(10, default_router_config, actual_avg_per_node=500.0)
        assert est == 5000

    def test_requires_confirmation_above_threshold(self, default_router_config):
        assert requires_confirmation(25000, default_router_config) is True

    def test_no_confirmation_below_threshold(self, default_router_config):
        assert requires_confirmation(10000, default_router_config) is False

    def test_no_confirmation_at_threshold(self, default_router_config):
        assert requires_confirmation(20000, default_router_config) is False

    def test_estimate_zero_nodes(self, default_router_config):
        assert estimate_tokens(0, default_router_config) == 0


# ---------------------------------------------------------------------------
# Multi-agent overlap tests
# ---------------------------------------------------------------------------

class TestMultiAgent:
    def test_disjoint_scopes_no_overlap(self, tmp_path):
        """Two tasks on completely disjoint subgraphs → no overlap groups."""
        from tenet.graph.store import GraphStore
        from tenet.graph.parser import Node
        from tenet.graph.builder import _ingest_file
        from pathlib import Path

        store = GraphStore(str(tmp_path / "ma_test.sqlite"))

        # Create two completely separate files
        file_x = str(tmp_path / "file_x.py")
        file_y = str(tmp_path / "file_y.py")
        Path(file_x).write_text("def alpha():\n    pass\n")
        Path(file_y).write_text("def beta():\n    pass\n")

        _ingest_file(file_x, store)
        _ingest_file(file_y, store)

        # Find node IDs
        all_nodes = store.get_all_nodes()
        alpha_node = next((n for n in all_nodes if n["name"] == "alpha"), None)
        beta_node = next((n for n in all_nodes if n["name"] == "beta"), None)
        assert alpha_node and beta_node

        tasks = [
            TaskScope(task_id="task_x", center_node_id=alpha_node["id"], hops=1),
            TaskScope(task_id="task_y", center_node_id=beta_node["id"], hops=1),
        ]

        groups = detect_overlaps(tasks, store)
        assert groups == [], f"Expected no overlaps for disjoint scopes, got: {groups}"

    def test_shared_node_creates_overlap_group(self, tmp_path):
        """Two tasks sharing a common function → one overlap group."""
        from tenet.graph.store import GraphStore
        from tenet.graph.builder import _ingest_file
        from pathlib import Path

        store = GraphStore(str(tmp_path / "ma_overlap.sqlite"))

        # Create a file with shared function + two callers
        shared_file = str(tmp_path / "shared.py")
        Path(shared_file).write_text(
            "def shared():\n    pass\n\n"
            "def caller_a():\n    shared()\n\n"
            "def caller_b():\n    shared()\n"
        )
        _ingest_file(shared_file, store)

        all_nodes = store.get_all_nodes()
        caller_a = next((n for n in all_nodes if n["name"] == "caller_a"), None)
        caller_b = next((n for n in all_nodes if n["name"] == "caller_b"), None)
        assert caller_a and caller_b

        tasks = [
            TaskScope(task_id="task_a", center_node_id=caller_a["id"], hops=1),
            TaskScope(task_id="task_b", center_node_id=caller_b["id"], hops=1),
        ]

        groups = detect_overlaps(tasks, store)
        assert len(groups) >= 1, "Expected at least one overlap group"

    def test_high_overlap_recommends_merge(self, tmp_path):
        """Tasks with >50% node overlap should get 'merge' recommendation."""
        from tenet.graph.store import GraphStore
        from tenet.graph.builder import _ingest_file
        from pathlib import Path

        store = GraphStore(str(tmp_path / "ma_merge.sqlite"))

        # A single file — both tasks centered on the same module node will be 100% overlap
        f = str(tmp_path / "overlap_heavy.py")
        Path(f).write_text(
            "def foo():\n    pass\n\ndef bar():\n    foo()\n"
        )
        _ingest_file(f, store)

        all_nodes = store.get_all_nodes()
        foo_node = next((n for n in all_nodes if n["name"] == "foo"), None)
        bar_node = next((n for n in all_nodes if n["name"] == "bar"), None)
        assert foo_node and bar_node

        # Both tasks centered on the same node with large hop radius
        tasks = [
            TaskScope(task_id="t1", center_node_id=foo_node["id"], hops=5),
            TaskScope(task_id="t2", center_node_id=bar_node["id"], hops=5),
        ]

        groups = detect_overlaps(tasks, store)
        assert any(g.recommendation == "merge" for g in groups), (
            f"Expected 'merge' recommendation for high-overlap tasks, got: {[g.recommendation for g in groups]}"
        )

    def test_single_task_no_overlap(self, tmp_path):
        """Single task → no pairwise comparisons possible → empty result."""
        from tenet.graph.store import GraphStore
        from tenet.graph.builder import _ingest_file
        from pathlib import Path

        store = GraphStore(str(tmp_path / "ma_single.sqlite"))
        f = str(tmp_path / "solo.py")
        Path(f).write_text("def solo():\n    pass\n")
        _ingest_file(f, store)

        all_nodes = store.get_all_nodes()
        solo = next((n for n in all_nodes if n["name"] == "solo"), None)
        assert solo

        groups = detect_overlaps([TaskScope("t1", solo["id"], 1)], store)
        assert groups == []
