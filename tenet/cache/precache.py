"""
precache.py — Speculative Pre-caching on Save ("Inversion Pre-computation").

Upgrade 4: When tenet watch detects a file modification, trigger a
low-priority background micro-embedding of the modified symbols into
cache.sqlite.  When the developer submits a prompt minutes later, the
semantic search is instant (<5ms) with zero cache warm-up latency.

This module exposes:
  - ``precache_file_symbols()``  — embed all symbols from a changed file.
  - ``SpeculativePrecacher``     — background thread worker for watch integration.
"""
from __future__ import annotations

import logging
import queue
import threading
import time
from pathlib import Path
from typing import Optional

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Low-level pre-computation
# ---------------------------------------------------------------------------

def precache_file_symbols(
    file_path: str,
    graph_store,
    cache,
    config,
) -> int:
    """Micro-embed all symbols from a changed file into the semantic cache.

    For each node in ``file_path`` we synthesise a short canonical prompt
    (``"implement <name> in <module>"``) and store a placeholder embedding so
    the first real query against this scope finds a warm cache vector.

    Returns the number of symbols embedded.
    """
    try:
        from tenet.cache.embeddings import embed
        from tenet.cache.semantic_cache import _scope_hash, _embedding_to_blob
        from datetime import datetime, timedelta, timezone

        nodes = graph_store.get_nodes_by_file(file_path)
        if not nodes:
            logger.debug("precache: no nodes for %s, skipping", file_path)
            return 0

        embedded = 0
        module_name = Path(file_path).stem
        ttl_hours = getattr(config.cache, "ttl_hours", 168)
        embedding_model = getattr(config.cache, "embedding_model", "all-MiniLM-L6-v2")

        for node in nodes:
            node_name = node.get("name", "")
            node_id = node.get("id", "")
            if not node_name or not node_id:
                continue

            # Synthesise a canonical prompt for this symbol
            synthetic_prompt = f"implement {node_name} in {module_name}"
            scope_node_ids = [node_id]

            try:
                # Check if already cached — avoid redundant embedding work
                existing = cache.get(synthetic_prompt, scope_node_ids)
                if existing is not None:
                    logger.debug(
                        "precache: %s already warm in cache, skipping", node_name
                    )
                    continue

                # Embed and store a speculative placeholder response
                vec = embed(synthetic_prompt, embedding_model)
                blob = _embedding_to_blob(vec)
                sh = _scope_hash(scope_node_ids)
                now = datetime.now(timezone.utc)
                expires = now + timedelta(hours=ttl_hours)

                # Direct DB insert to avoid the full cache.set() overhead
                cache._db["cache_entries"].insert(
                    {
                        "scope_hash": sh,
                        "embedding": blob,
                        "prompt_text": synthetic_prompt,
                        "response": f"[speculative pre-cache: {node_name}]",
                        "created_at": now.isoformat(),
                        "ttl_expires_at": expires.isoformat(),
                        "hit_count": 0,
                    },
                    ignore=True,  # skip if already exists (race-safe)
                )
                embedded += 1
                logger.debug("precache: embedded '%s' from %s", node_name, file_path)

            except Exception as exc:
                logger.debug(
                    "precache: failed to embed '%s': %s", node_name, exc
                )

        if embedded:
            logger.info(
                "precache: pre-warmed %d symbols from %s in cache", embedded, file_path
            )
        return embedded

    except Exception as exc:
        logger.warning("precache: precache_file_symbols failed for %s: %s", file_path, exc)
        return 0


# ---------------------------------------------------------------------------
# Background worker
# ---------------------------------------------------------------------------

class SpeculativePrecacher:
    """Low-priority background thread that processes pre-cache work items.

    Usage::

        precacher = SpeculativePrecacher(graph_store, cache, config)
        precacher.start()
        # ... in watch on_change callback:
        precacher.enqueue("path/to/changed_file.py")
        # ... on shutdown:
        precacher.stop()

    Work items are processed with a short delay (``idle_delay_s``) to ensure
    the main thread (file watcher) has already updated the graph before we
    try to read the new nodes.
    """

    def __init__(
        self,
        graph_store,
        cache,
        config,
        idle_delay_s: float = 1.5,
        max_queue_size: int = 100,
    ) -> None:
        self._graph_store = graph_store
        self._cache = cache
        self._config = config
        self._idle_delay_s = idle_delay_s
        self._queue: queue.Queue[Optional[str]] = queue.Queue(maxsize=max_queue_size)
        self._thread: Optional[threading.Thread] = None
        self._running = False
        self._total_embedded = 0

    def start(self) -> None:
        """Start the background pre-caching thread (low priority, daemon)."""
        if self._thread and self._thread.is_alive():
            return
        self._running = True
        self._thread = threading.Thread(
            target=self._worker,
            name="tenet-precacher",
            daemon=True,
        )
        self._thread.start()
        logger.info("speculative_precacher: background thread started")

    def stop(self) -> None:
        """Signal the worker to stop and wait for it to finish."""
        self._running = False
        self._queue.put(None)  # poison pill
        if self._thread:
            self._thread.join(timeout=5.0)
        logger.info(
            "speculative_precacher: stopped (%d symbols total embedded)",
            self._total_embedded,
        )

    def enqueue(self, file_path: str) -> None:
        """Queue a file for low-priority background pre-embedding."""
        try:
            self._queue.put_nowait(file_path)
            logger.debug("speculative_precacher: queued %s", file_path)
        except queue.Full:
            logger.debug("speculative_precacher: queue full, skipping %s", file_path)

    @property
    def total_embedded(self) -> int:
        return self._total_embedded

    def _worker(self) -> None:
        """Main worker loop — runs in the daemon thread."""
        while self._running:
            try:
                item = self._queue.get(timeout=2.0)
                if item is None:
                    break  # poison pill received

                # Brief delay to let the graph update complete first
                time.sleep(self._idle_delay_s)

                n = precache_file_symbols(
                    file_path=item,
                    graph_store=self._graph_store,
                    cache=self._cache,
                    config=self._config,
                )
                self._total_embedded += n
                self._queue.task_done()

            except queue.Empty:
                continue
            except Exception as exc:
                logger.warning("speculative_precacher: worker error: %s", exc)
