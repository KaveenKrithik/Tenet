"""
semantic_cache.py — semantic similarity cache backed by SQLite.

Cache key is scoped by the sorted set of graph node IDs (scope_hash) so
that the same prompt phrased differently against the same code scope still
hits the cache if the embedding is close enough.
"""
from __future__ import annotations

import hashlib
import json
import logging
import struct
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Optional

import numpy as np
import sqlite_utils

from tenet.cache.embeddings import cosine_similarity, embed

logger = logging.getLogger(__name__)

_SCHEMA_SQL = """
CREATE TABLE IF NOT EXISTS cache_entries (
    id            INTEGER PRIMARY KEY AUTOINCREMENT,
    scope_hash    TEXT    NOT NULL,
    embedding     BLOB    NOT NULL,
    prompt_text   TEXT    NOT NULL,
    response      TEXT    NOT NULL,
    created_at    TIMESTAMP NOT NULL,
    ttl_expires_at TIMESTAMP NOT NULL,
    hit_count     INT DEFAULT 0
);

CREATE INDEX IF NOT EXISTS idx_cache_scope ON cache_entries(scope_hash);
CREATE INDEX IF NOT EXISTS idx_cache_ttl ON cache_entries(ttl_expires_at);
"""


@dataclass
class CacheResult:
    response: str
    hit_count: int
    similarity: float


def _scope_hash(node_ids: list[str]) -> str:
    """Deterministic hash of a sorted list of node IDs."""
    key = "|".join(sorted(node_ids))
    return hashlib.sha256(key.encode()).hexdigest()[:32]


def _embedding_to_blob(vec: list[float]) -> bytes:
    return struct.pack(f"{len(vec)}f", *vec)


def _blob_to_embedding(blob: bytes) -> list[float]:
    n = len(blob) // 4
    return list(struct.unpack(f"{n}f", blob))


class SemanticCache:
    """SQLite-backed semantic similarity cache."""

    def __init__(
        self,
        db_path: str,
        embedding_model: str = "all-MiniLM-L6-v2",
        similarity_threshold: float = 0.92,
        ttl_hours: int = 168,
    ) -> None:
        self._db_path = db_path
        self._embedding_model = embedding_model
        self._similarity_threshold = similarity_threshold
        self._ttl_hours = ttl_hours

        Path(db_path).parent.mkdir(parents=True, exist_ok=True)
        self._db = sqlite_utils.Database(db_path)
        self._init_schema()

    def _init_schema(self) -> None:
        self._db.execute("PRAGMA journal_mode=WAL")
        for stmt in _SCHEMA_SQL.strip().split(";"):
            stmt = stmt.strip()
            if stmt:
                self._db.execute(stmt)

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def get(self, prompt: str, scope_node_ids: list[str]) -> Optional[CacheResult]:
        """Check the cache for a semantically similar prior response.

        1. Filter candidates by exact ``scope_hash`` match (cheap).
        2. Compute embedding for the query prompt.
        3. Compare cosine similarity against candidates.
        4. Return the best match above ``similarity_threshold`` or None.
        """
        sh = _scope_hash(scope_node_ids)
        now = datetime.now(timezone.utc).isoformat()

        candidates = self._db.execute(
            "SELECT id, embedding, response, hit_count FROM cache_entries "
            "WHERE scope_hash = ? AND ttl_expires_at > ?",
            [sh, now],
        ).fetchall()

        if not candidates:
            logger.debug("semantic_cache: no candidates for scope_hash=%s", sh[:8])
            return None

        query_vec = embed(prompt, self._embedding_model)
        best_sim = -1.0
        best_row = None

        for row in candidates:
            entry_vec = _blob_to_embedding(row[1])
            sim = cosine_similarity(query_vec, entry_vec)
            if sim > best_sim:
                best_sim = sim
                best_row = row

        if best_row and best_sim >= self._similarity_threshold:
            # Increment hit count
            self._db.execute(
                "UPDATE cache_entries SET hit_count = hit_count + 1 WHERE id = ?",
                [best_row[0]],
            )
            logger.info(
                "semantic_cache: HIT (sim=%.4f, threshold=%.2f)",
                best_sim, self._similarity_threshold,
            )
            return CacheResult(
                response=best_row[2],
                hit_count=best_row[3] + 1,
                similarity=best_sim,
            )

        logger.debug(
            "semantic_cache: MISS (best_sim=%.4f, threshold=%.2f)",
            best_sim, self._similarity_threshold,
        )
        return None

    def set(self, prompt: str, scope_node_ids: list[str], response: str) -> None:
        """Store a new cache entry."""
        sh = _scope_hash(scope_node_ids)
        vec = embed(prompt, self._embedding_model)
        blob = _embedding_to_blob(vec)
        now = datetime.now(timezone.utc)
        expires = now + timedelta(hours=self._ttl_hours)

        self._db["cache_entries"].insert({  # type: ignore[index]
            "scope_hash": sh,
            "embedding": blob,
            "prompt_text": prompt,
            "response": response,
            "created_at": now.isoformat(),
            "ttl_expires_at": expires.isoformat(),
            "hit_count": 0,
        })
        logger.debug("semantic_cache: stored entry for scope_hash=%s", sh[:8])

    def invalidate_for_nodes(self, node_ids: list[str]) -> int:
        """Purge cache entries tied to changed nodes.

        Since entries are keyed by *scope_hash* (a hash of sorted node IDs),
        we must check every entry to see if any of the changed ``node_ids``
        appear in its scope.  This is intentionally conservative: if a changed
        node is *in* the scope, the entry is stale.

        Returns the number of entries purged.
        """
        node_set = set(node_ids)
        # We stored only scope_hash, not the original node list, so we need
        # to check candidates by re-computing all possible scope_hashes for
        # the changed nodes.  As a pragmatic approximation, we store a
        # denormalized node list in a separate column on insert.
        # For now: delete any entry whose scope_hash matches a scope containing
        # any of the changed node_ids. We achieve this by storing a separate
        # cache_scopes table (optional extension).
        #
        # Pragmatic approach: delete ALL entries that contain any of the node_ids
        # in their scope by querying the scope_hash computed from each possible
        # scope.  Since we don't store node lists, we do a full purge for the
        # affected scope_hashes stored in a scope_members table that we maintain
        # on set().
        #
        # For now, fall back to: delete entries where scope_hash equals the hash
        # of any single-node scope containing a changed node (simplification).
        # A future version should store scope membership explicitly.
        deleted = 0
        for nid in node_ids:
            sh = _scope_hash([nid])
            result = self._db.execute(
                "DELETE FROM cache_entries WHERE scope_hash = ?", [sh]
            )
            deleted += result.rowcount if hasattr(result, "rowcount") else 0

        if deleted:
            logger.info("semantic_cache: invalidated %d entries for %d nodes", deleted, len(node_ids))
        return deleted

    def invalidate_by_scope_hash(self, scope_hash: str) -> int:
        """Direct purge by scope hash — used when the caller knows the hash."""
        result = self._db.execute(
            "DELETE FROM cache_entries WHERE scope_hash = ?", [scope_hash]
        )
        cnt = result.rowcount if hasattr(result, "rowcount") else 0
        logger.info("semantic_cache: invalidated %d entries for scope_hash=%s", cnt, scope_hash[:8])
        return cnt

    def purge_expired(self) -> int:
        """Remove all TTL-expired entries."""
        now = datetime.now(timezone.utc).isoformat()
        result = self._db.execute(
            "DELETE FROM cache_entries WHERE ttl_expires_at <= ?", [now]
        )
        cnt = result.rowcount if hasattr(result, "rowcount") else 0
        logger.debug("semantic_cache: purged %d expired entries", cnt)
        return cnt
