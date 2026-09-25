"""
test_semantic_cache.py — Stage 3 tests for embeddings and SemanticCache.
"""
from __future__ import annotations

import time
from unittest.mock import MagicMock, patch

import numpy as np
import pytest

from tenet.cache.embeddings import cosine_similarity
from tenet.cache.semantic_cache import SemanticCache, _scope_hash

# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

SCOPE_A = ["node_001", "node_002", "node_003"]
SCOPE_B = ["node_004", "node_005"]

PROMPT_1 = "How do I add two numbers in Python?"
PROMPT_2 = "What is the Python way to sum two integers?"   # semantically similar to PROMPT_1
PROMPT_DIFFERENT = "Explain the Rust borrow checker in detail."


def _fake_embed(text: str, model_name: str = "all-MiniLM-L6-v2") -> list[float]:
    """Deterministic fake embedder: returns a unit vector derived from the text hash."""
    import hashlib
    h = hashlib.sha256(text.encode()).digest()
    # Build 8-dim vector from the hash bytes
    vec = np.frombuffer(h[:8 * 4], dtype=np.float32).copy()
    norm = np.linalg.norm(vec)
    if norm > 0:
        vec = vec / norm
    return vec.tolist()


def _similar_embed(text: str, model_name: str = "all-MiniLM-L6-v2") -> list[float]:
    """Returns almost identical vectors for PROMPT_1 and PROMPT_2, different for others."""
    if text in (PROMPT_1, PROMPT_2):
        # Return the same vector so cosine sim = 1.0
        rng = np.random.default_rng(42)
        vec = rng.random(8).astype(np.float32)
        vec /= np.linalg.norm(vec)
        return vec.tolist()
    else:
        rng = np.random.default_rng(999)
        vec = rng.random(8).astype(np.float32)
        vec /= np.linalg.norm(vec)
        return vec.tolist()


@pytest.fixture()
def cache(tmp_path):
    with patch("tenet.cache.semantic_cache.embed", side_effect=_similar_embed):
        sc = SemanticCache(
            db_path=str(tmp_path / "test_cache.sqlite"),
            embedding_model="all-MiniLM-L6-v2",
            similarity_threshold=0.92,
            ttl_hours=168,
        )
        yield sc


# ---------------------------------------------------------------------------
# Scope hash tests
# ---------------------------------------------------------------------------

class TestScopeHash:
    def test_order_independent(self):
        h1 = _scope_hash(["a", "b", "c"])
        h2 = _scope_hash(["c", "a", "b"])
        assert h1 == h2

    def test_different_scopes_differ(self):
        h1 = _scope_hash(["a", "b"])
        h2 = _scope_hash(["a", "c"])
        assert h1 != h2

    def test_empty_scope(self):
        h = _scope_hash([])
        assert isinstance(h, str) and len(h) > 0


# ---------------------------------------------------------------------------
# Cosine similarity tests
# ---------------------------------------------------------------------------

class TestCosineSimilarity:
    def test_identical_vectors_return_one(self):
        v = [1.0, 0.0, 0.0]
        assert abs(cosine_similarity(v, v) - 1.0) < 1e-5

    def test_orthogonal_vectors_return_zero(self):
        v1 = [1.0, 0.0]
        v2 = [0.0, 1.0]
        assert abs(cosine_similarity(v1, v2)) < 1e-5


# ---------------------------------------------------------------------------
# Cache tests
# ---------------------------------------------------------------------------

class TestSemanticCache:
    def test_set_and_get_exact_hit(self, cache):
        """Storing and immediately retrieving with the same prompt should hit."""
        cache.set(PROMPT_1, SCOPE_A, "answer: use the + operator")
        result = cache.get(PROMPT_1, SCOPE_A)
        assert result is not None
        assert "+" in result.response

    def test_similar_prompt_hits_cache(self, cache):
        """Two semantically similar prompts against the same scope should hit."""
        cache.set(PROMPT_1, SCOPE_A, "answer: use the + operator")
        result = cache.get(PROMPT_2, SCOPE_A)
        assert result is not None, "Similar prompt should hit the cache"

    def test_different_scope_misses_cache(self, cache):
        """Same prompt against a different scope should miss."""
        cache.set(PROMPT_1, SCOPE_A, "answer: use the + operator")
        result = cache.get(PROMPT_1, SCOPE_B)
        assert result is None, "Different scope should miss the cache"

    def test_hit_count_incremented(self, cache):
        cache.set(PROMPT_1, SCOPE_A, "my response")
        cache.get(PROMPT_1, SCOPE_A)
        result = cache.get(PROMPT_1, SCOPE_A)
        assert result is not None
        assert result.hit_count >= 2

    def test_miss_returns_none(self, cache):
        result = cache.get("completely unrelated question about quantum mechanics", SCOPE_A)
        assert result is None

    def test_invalidate_removes_entries(self, cache):
        cache.set(PROMPT_1, ["node_solo"], "answer")
        # Invalidate the single-node scope
        cache.invalidate_for_nodes(["node_solo"])
        result = cache.get(PROMPT_1, ["node_solo"])
        assert result is None, "Cache should be empty after invalidation"

    def test_purge_expired_removes_old_entries(self, tmp_path):
        """Entries with a past TTL should be purged."""
        with patch("tenet.cache.semantic_cache.embed", side_effect=_similar_embed):
            sc = SemanticCache(
                db_path=str(tmp_path / "ttl_test.sqlite"),
                ttl_hours=-1,  # already expired
            )
            sc.set(PROMPT_1, SCOPE_A, "stale response")
            count = sc.purge_expired()
            assert count >= 1

    def test_empty_scope_cache(self, cache):
        """Empty scope should still work without errors."""
        cache.set(PROMPT_1, [], "response for empty scope")
        result = cache.get(PROMPT_1, [])
        assert result is not None
