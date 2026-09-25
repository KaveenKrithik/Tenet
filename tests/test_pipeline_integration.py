"""
test_pipeline_integration.py — end-to-end pipeline integration tests.

Ollama is mocked so no local GPU/daemon is required.
Three scenarios are tested:
  (a) Repeated prompt → cache_hit
  (b) Trivial new prompt → local_success (mocked valid Ollama output)
  (c) Large-scope prompt → escalated
"""
from __future__ import annotations

import shutil
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from tenet.cache.semantic_cache import SemanticCache, _scope_hash
from tenet.config import TenetConfig, load_config, reset_config_cache
from tenet.graph.builder import build_full_graph
from tenet.graph.store import GraphStore
from tenet.ledger.store import LedgerStore
from tenet.pipeline import process_request

FIXTURES_DIR = Path(__file__).parent / "fixtures"

VALID_PYTHON_RESPONSE = '''\
def add(x: int, y: int) -> int:
    return x + y
'''

INVALID_PYTHON_RESPONSE = '''\
def add(x: int y: int) -> int
    return x + y
'''


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_config(tmp_path) -> TenetConfig:
    """Create a test config pointing all db_paths to tmp_path."""
    reset_config_cache()
    cfg = TenetConfig()
    cfg.graph.db_path = str(tmp_path / "graph.sqlite")
    cfg.cache.db_path = str(tmp_path / "cache.sqlite")
    cfg.ledger.db_path = str(tmp_path / "ledger.sqlite")
    cfg.router.tokens_per_node_estimate = 800
    cfg.router.cost_confirmation_threshold_tokens = 20000
    # Make it easy to hit "large scope" — set a very low node limit
    return cfg


def _mock_embed(text, model_name="all-MiniLM-L6-v2"):
    """Deterministic fake embedder returning a stable unit vector."""
    import hashlib, struct
    import numpy as np
    h = hashlib.sha256(text.encode()).digest()[:32]
    vec = np.frombuffer(h, dtype=np.float32).copy()
    norm = np.linalg.norm(vec)
    vec = vec / norm if norm > 0 else vec
    return vec.tolist()


def _same_embed(text, model_name="all-MiniLM-L6-v2"):
    """Always returns the same vector — guaranteed cache hit."""
    import numpy as np
    rng = np.random.default_rng(42)
    vec = rng.random(8).astype(np.float32)
    vec /= np.linalg.norm(vec)
    return vec.tolist()


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture()
def tmp_infra(tmp_path):
    """Set up a full pipeline stack pointing at tmp_path."""
    cfg = _make_config(tmp_path)

    # Copy fixtures to tmp so we can safely modify them
    fixtures_copy = tmp_path / "src"
    shutil.copytree(str(FIXTURES_DIR), str(fixtures_copy))

    graph_store = GraphStore(cfg.graph.db_path)
    build_full_graph(str(fixtures_copy), graph_store)

    ledger = LedgerStore(cfg.ledger.db_path)
    touched_files = [str(p) for p in fixtures_copy.glob("*.py")]

    return {
        "cfg": cfg,
        "graph_store": graph_store,
        "ledger": ledger,
        "touched_files": touched_files,
        "fixtures_copy": fixtures_copy,
    }


# ---------------------------------------------------------------------------
# Test (a): Repeated prompt → cache_hit
# ---------------------------------------------------------------------------

class TestCacheHit:
    def test_repeated_prompt_returns_cache_hit(self, tmp_infra):
        cfg = tmp_infra["cfg"]
        graph_store = tmp_infra["graph_store"]
        ledger = tmp_infra["ledger"]
        touched = tmp_infra["touched_files"]

        # Use same-vector embedder so both prompts are identical in embedding space
        with patch("tenet.cache.semantic_cache.embed", side_effect=_same_embed):
            cache = SemanticCache(
                db_path=cfg.cache.db_path,
                similarity_threshold=0.90,
            )

            prompt = "How do I add two numbers in Python?"

            # First request — should not hit cache (nothing stored yet)
            # We'll seed the cache manually to guarantee the second call hits
            from tenet.graph.query import find_nodes_for_files
            scope_nodes = find_nodes_for_files(touched, graph_store)
            scope_ids = [n["id"] for n in scope_nodes]
            cache.set(prompt, scope_ids, "Stored response: use the + operator")

            # Second request — same prompt, same files → should hit cache
            result = process_request(
                prompt=prompt,
                touched_files=touched,
                config=cfg,
                graph_store=graph_store,
                cache=cache,
                ledger=ledger,
            )

        assert result.stage_reached == "cache_hit", (
            f"Expected cache_hit, got {result.stage_reached}"
        )
        assert result.response is not None
        assert result.ledger_id is not None

        # Verify ledger entry
        rows = ledger.get_recent_requests(limit=1)
        assert rows[0]["stage_reached"] == "cache_hit"

    def test_cache_hit_writes_exactly_one_ledger_entry(self, tmp_infra):
        cfg = tmp_infra["cfg"]
        graph_store = tmp_infra["graph_store"]
        ledger = tmp_infra["ledger"]
        touched = tmp_infra["touched_files"]

        with patch("tenet.cache.semantic_cache.embed", side_effect=_same_embed):
            cache = SemanticCache(db_path=cfg.cache.db_path, similarity_threshold=0.90)
            from tenet.graph.query import find_nodes_for_files
            scope_ids = [n["id"] for n in find_nodes_for_files(touched, graph_store)]
            prompt = "unique prompt xyz123"
            cache.set(prompt, scope_ids, "cached response")

            process_request(
                prompt=prompt, touched_files=touched,
                config=cfg, graph_store=graph_store, cache=cache, ledger=ledger,
            )

        totals = ledger.get_totals()
        assert totals.total_requests == 1


# ---------------------------------------------------------------------------
# Test (b): Trivial new prompt → local_success (mocked Ollama)
# ---------------------------------------------------------------------------

class TestLocalSuccess:
    def test_valid_ollama_response_returns_local_success(self, tmp_infra):
        cfg = tmp_infra["cfg"]
        graph_store = tmp_infra["graph_store"]
        ledger = tmp_infra["ledger"]
        touched = tmp_infra["touched_files"]

        with (
            patch("tenet.cache.semantic_cache.embed", side_effect=_mock_embed),
            patch("tenet.pipeline.generate", return_value=VALID_PYTHON_RESPONSE),
        ):
            cache = SemanticCache(db_path=cfg.cache.db_path, similarity_threshold=0.99)
            result = process_request(
                prompt="Write a simple add function",
                touched_files=touched,
                config=cfg,
                graph_store=graph_store,
                cache=cache,
                ledger=ledger,
            )

        assert result.stage_reached == "local_success", (
            f"Expected local_success, got {result.stage_reached}"
        )
        assert result.response == VALID_PYTHON_RESPONSE
        assert result.ledger_id is not None

        rows = ledger.get_recent_requests(limit=1)
        assert rows[0]["stage_reached"] == "local_success"

    def test_invalid_ollama_response_escalates(self, tmp_infra):
        cfg = tmp_infra["cfg"]
        graph_store = tmp_infra["graph_store"]
        ledger = tmp_infra["ledger"]
        touched = tmp_infra["touched_files"]

        with (
            patch("tenet.cache.semantic_cache.embed", side_effect=_mock_embed),
            patch("tenet.pipeline.generate", return_value=INVALID_PYTHON_RESPONSE),
        ):
            cache = SemanticCache(db_path=cfg.cache.db_path, similarity_threshold=0.99)
            result = process_request(
                prompt="Write broken code",
                touched_files=touched,
                config=cfg,
                graph_store=graph_store,
                cache=cache,
                ledger=ledger,
            )

        assert result.stage_reached == "escalated"


# ---------------------------------------------------------------------------
# Test (c): Large-scope → escalated
# ---------------------------------------------------------------------------

class TestEscalation:
    def test_large_scope_escalates(self, tmp_infra):
        cfg = tmp_infra["cfg"]
        graph_store = tmp_infra["graph_store"]
        ledger = tmp_infra["ledger"]
        touched = tmp_infra["touched_files"]

        # Force local triage to be skipped by making the scope appear huge
        # We do this by setting max_local_hops to 0 (scope always exceeds threshold)
        cfg.triage.max_local_hops = 0

        with patch("tenet.cache.semantic_cache.embed", side_effect=_mock_embed):
            cache = SemanticCache(db_path=cfg.cache.db_path, similarity_threshold=0.99)
            result = process_request(
                prompt="Explain the entire codebase architecture in full detail with all edge cases",
                touched_files=touched,
                config=cfg,
                graph_store=graph_store,
                cache=cache,
                ledger=ledger,
            )

        assert result.stage_reached == "escalated"
        assert result.ledger_id is not None

        rows = ledger.get_recent_requests(limit=1)
        assert rows[0]["stage_reached"] == "escalated"

    def test_escalation_includes_tier(self, tmp_infra):
        cfg = tmp_infra["cfg"]
        graph_store = tmp_infra["graph_store"]
        ledger = tmp_infra["ledger"]
        touched = tmp_infra["touched_files"]
        cfg.triage.max_local_hops = 0

        with patch("tenet.cache.semantic_cache.embed", side_effect=_mock_embed):
            cache = SemanticCache(db_path=cfg.cache.db_path, similarity_threshold=0.99)
            result = process_request(
                prompt="Large scope prompt",
                touched_files=touched,
                config=cfg,
                graph_store=graph_store,
                cache=cache,
                ledger=ledger,
            )

        assert result.tier in ("cheap", "mid", "full"), f"Unexpected tier: {result.tier}"

    def test_ollama_unavailable_escalates_gracefully(self, tmp_infra):
        """When Ollama is not running, pipeline should not crash and should escalate."""
        from tenet.triage.ollama_client import OllamaUnavailableError

        cfg = tmp_infra["cfg"]
        graph_store = tmp_infra["graph_store"]
        ledger = tmp_infra["ledger"]
        touched = tmp_infra["touched_files"]

        with (
            patch("tenet.cache.semantic_cache.embed", side_effect=_mock_embed),
            patch("tenet.pipeline.generate", side_effect=OllamaUnavailableError("not running")),
        ):
            cache = SemanticCache(db_path=cfg.cache.db_path, similarity_threshold=0.99)
            result = process_request(
                prompt="Test Ollama unavailability",
                touched_files=touched,
                config=cfg,
                graph_store=graph_store,
                cache=cache,
                ledger=ledger,
            )

        assert result.stage_reached == "escalated"
        assert result.ledger_id is not None


# ---------------------------------------------------------------------------
# Ledger integrity tests
# ---------------------------------------------------------------------------

class TestLedgerIntegrity:
    def test_every_path_writes_exactly_one_ledger_entry(self, tmp_infra, tmp_path):
        """Three different pipeline paths should each produce exactly one ledger row."""
        cfg = tmp_infra["cfg"]
        graph_store = tmp_infra["graph_store"]
        ledger = tmp_infra["ledger"]
        touched = tmp_infra["touched_files"]
        from tenet.triage.ollama_client import OllamaUnavailableError

        # Path 1: escalated (Ollama unavailable, scope 0 to skip local)
        cfg.triage.max_local_hops = 0
        with patch("tenet.cache.semantic_cache.embed", side_effect=_mock_embed):
            cache = SemanticCache(db_path=cfg.cache.db_path, similarity_threshold=0.99)
            process_request("prompt_1", touched, cfg, graph_store, cache, ledger)

        # Path 2: local_success
        cfg.triage.max_local_hops = 100
        with (
            patch("tenet.cache.semantic_cache.embed", side_effect=_mock_embed),
            patch("tenet.pipeline.generate", return_value=VALID_PYTHON_RESPONSE),
        ):
            cache2 = SemanticCache(
                db_path=str(tmp_path / "cache2.sqlite"), similarity_threshold=0.99
            )
            ledger2 = LedgerStore(str(tmp_path / "ledger2.sqlite"))
            process_request("prompt_2", touched, cfg, graph_store, cache2, ledger2)

        # Path 3: cache_hit
        with patch("tenet.cache.semantic_cache.embed", side_effect=_same_embed):
            cache3 = SemanticCache(
                db_path=str(tmp_path / "cache3.sqlite"), similarity_threshold=0.90
            )
            ledger3 = LedgerStore(str(tmp_path / "ledger3.sqlite"))
            from tenet.graph.query import find_nodes_for_files
            scope_ids = [n["id"] for n in find_nodes_for_files(touched, graph_store)]
            cache3.set("prompt_3", scope_ids, "cached")
            process_request("prompt_3", touched, cfg, graph_store, cache3, ledger3)

        assert ledger.get_totals().total_requests == 1
        assert ledger2.get_totals().total_requests == 1
        assert ledger3.get_totals().total_requests == 1
