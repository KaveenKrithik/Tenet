"""
builder.py — incremental graph build/update logic.

Build the full graph for a directory on first run; on subsequent runs only
re-parse files whose content has changed, leaving everything else intact.
"""
from __future__ import annotations

import hashlib
import logging
import time
from pathlib import Path

from tenet.graph.parser import Node, extract_edges, parse_file
from tenet.graph.store import GraphStore

logger = logging.getLogger(__name__)

_SUPPORTED_EXTENSIONS = {".py", ".js", ".mjs", ".cjs", ".ts", ".tsx"}


def _file_content_hash(path: str) -> str:
    """Return a sha256 hex digest of a file's raw bytes."""
    try:
        data = Path(path).read_bytes()
        return hashlib.sha256(data).hexdigest()[:16]
    except OSError:
        return ""


def _collect_source_files(root_dir: str) -> list[str]:
    root = Path(root_dir)
    files = []
    for p in root.rglob("*"):
        if p.is_file() and p.suffix.lower() in _SUPPORTED_EXTENSIONS:
            # Skip hidden dirs and common non-project dirs
            parts = set(p.parts)
            if parts & {".git", "__pycache__", ".venv", "venv", "node_modules", "dist", "build"}:
                continue
            files.append(str(p))
    return files


def build_full_graph(root_dir: str, store: GraphStore) -> None:
    """Initial full parse: walk the directory and ingest every source file."""
    files = _collect_source_files(root_dir)
    logger.info("build_full_graph: found %d source files in %s", len(files), root_dir)
    for file_path in files:
        _ingest_file(file_path, store)
    logger.info("build_full_graph: complete")


def update_graph(changed_files: list[str], store: GraphStore) -> None:
    """Incremental update: re-parse only files that have changed content.

    For each file:
    1. Compute current content hash.
    2. Compare against stored hash in ``file_hashes`` table.
    3. If different (or not yet recorded), delete old nodes/edges and re-ingest.
    4. Skip the file if hash is unchanged.
    """
    for file_path in changed_files:
        current_hash = _file_content_hash(file_path)
        if not current_hash:
            logger.warning("update_graph: cannot hash %s, skipping", file_path)
            continue

        stored_hash = store.get_file_hash(file_path)
        if stored_hash == current_hash:
            logger.debug("update_graph: %s unchanged, skipping", file_path)
            continue

        logger.info("update_graph: %s changed, re-ingesting", file_path)
        store.delete_file_nodes(file_path)
        _ingest_file(file_path, store)


def _ingest_file(file_path: str, store: GraphStore) -> None:
    """Parse a single file and upsert its nodes and edges into the store."""
    try:
        nodes = parse_file(file_path)
        if not nodes:
            logger.debug("_ingest_file: no nodes extracted from %s", file_path)
            # Still record the file hash so we don't re-attempt unnecessarily
            current_hash = _file_content_hash(file_path)
            if current_hash:
                store.upsert_file_hash(file_path, current_hash)
            return

        edges = extract_edges(file_path, nodes)
        store.upsert_nodes(nodes)
        store.upsert_edges(edges)

        # Use the module node's content_hash as the file-level hash
        module_node = next((n for n in nodes if n.type == "module"), None)
        file_hash = module_node.content_hash if module_node else _file_content_hash(file_path)
        store.upsert_file_hash(file_path, file_hash)

        logger.debug(
            "_ingest_file: %s → %d nodes, %d edges", file_path, len(nodes), len(edges)
        )
    except Exception as exc:
        logger.error("_ingest_file: failed for %s: %s", file_path, exc, exc_info=True)
        # Don't propagate — callers must be resilient to per-file failures


def watch(root_dir: str, store: GraphStore, interval_seconds: int = 5) -> None:
    """Polling-based file watcher — calls update_graph whenever mtimes change.

    Uses ``watchdog`` if available, else falls back to mtime polling.
    """
    try:
        _watch_with_watchdog(root_dir, store, interval_seconds)
    except ImportError:
        _watch_with_polling(root_dir, store, interval_seconds)


def _watch_with_watchdog(root_dir: str, store: GraphStore, interval_seconds: int) -> None:
    from watchdog.events import FileSystemEventHandler
    from watchdog.observers import Observer

    class _Handler(FileSystemEventHandler):
        def on_modified(self, event):
            if not event.is_directory:
                p = Path(event.src_path)
                if p.suffix.lower() in _SUPPORTED_EXTENSIONS:
                    update_graph([str(p)], store)

        def on_created(self, event):
            self.on_modified(event)

    observer = Observer()
    observer.schedule(_Handler(), root_dir, recursive=True)
    observer.start()
    logger.info("watch: watchdog observer started for %s", root_dir)
    try:
        while True:
            time.sleep(interval_seconds)
    except KeyboardInterrupt:
        observer.stop()
    observer.join()


def _watch_with_polling(root_dir: str, store: GraphStore, interval_seconds: int) -> None:
    logger.info("watch: falling back to mtime polling for %s", root_dir)
    last_mtimes: dict[str, float] = {}

    while True:
        changed = []
        files = _collect_source_files(root_dir)
        for file_path in files:
            try:
                mtime = Path(file_path).stat().st_mtime
            except OSError:
                continue
            if last_mtimes.get(file_path) != mtime:
                last_mtimes[file_path] = mtime
                changed.append(file_path)

        if changed:
            update_graph(changed, store)

        time.sleep(interval_seconds)
