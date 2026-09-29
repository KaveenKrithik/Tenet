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

from typing import Callable, Optional

from tenet.graph.parser import Node, extract_edges, parse_file
from tenet.graph.store import GraphStore

logger = logging.getLogger(__name__)

_SUPPORTED_EXTENSIONS = {".py", ".js", ".mjs", ".cjs", ".ts", ".tsx"}
_IGNORED_DIRS = {
    ".git", "__pycache__", ".venv", "venv", "node_modules",
    "dist", "build", ".pytest_cache", ".agents", "data",
    ".gemini", ".idea", ".vscode", ".ruff_cache",
}


def _should_ignore(path: Path) -> bool:
    """Return True if any segment of the path belongs to ignored directories."""
    return bool(set(path.parts) & _IGNORED_DIRS)


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
        if p.is_file() and p.suffix.lower() in _SUPPORTED_EXTENSIONS and not _should_ignore(p):
            files.append(str(p))
    return files


def build_full_graph(root_dir: str, store: GraphStore) -> None:
    """Initial full parse: walk the directory and ingest every source file."""
    files = _collect_source_files(root_dir)
    logger.info("build_full_graph: found %d source files in %s", len(files), root_dir)
    for file_path in files:
        _ingest_file(file_path, store)
    logger.info("build_full_graph: complete")


def update_graph(changed_files: list[str], store: GraphStore) -> list[str]:
    """Incremental update: re-parse only files that have changed content.

    For each file:
    1. Check if ignored or deleted.
    2. Compute current content hash.
    3. Compare against stored hash in ``file_hashes`` table.
    4. If different (or not yet recorded), delete old nodes/edges and re-ingest.
    5. Skip the file if hash is unchanged.
    Returns the list of reindexed/updated file paths.
    """
    updated: list[str] = []
    for file_path in changed_files:
        p = Path(file_path)
        if _should_ignore(p):
            continue

        if not p.exists():
            store.delete_file_nodes(file_path)
            logger.info("update_graph: %s deleted, removed from graph", file_path)
            updated.append(file_path)
            continue

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
        updated.append(file_path)
    return updated


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


def watch(
    root_dir: str,
    store: GraphStore,
    interval_seconds: int = 5,
    on_change: Optional[Callable[[list[str]], None]] = None,
) -> None:
    """File watcher — calls update_graph whenever files change.

    Uses ``watchdog`` if available, else falls back to mtime polling.
    """
    try:
        _watch_with_watchdog(root_dir, store, interval_seconds, on_change)
    except (ImportError, Exception) as exc:
        logger.info("watchdog unavailable (%s), falling back to polling", exc)
        _watch_with_polling(root_dir, store, interval_seconds, on_change)


def _watch_with_watchdog(
    root_dir: str,
    store: GraphStore,
    interval_seconds: int,
    on_change: Optional[Callable[[list[str]], None]] = None,
) -> None:
    from watchdog.events import FileSystemEventHandler
    from watchdog.observers import Observer

    class _Handler(FileSystemEventHandler):
        def _handle(self, src_path: str) -> None:
            p = Path(src_path)
            if not p.is_dir() and p.suffix.lower() in _SUPPORTED_EXTENSIONS and not _should_ignore(p):
                reindexed = update_graph([str(p)], store)
                if reindexed and on_change:
                    on_change(reindexed)

        def on_modified(self, event):
            self._handle(event.src_path)

        def on_created(self, event):
            self._handle(event.src_path)

        def on_deleted(self, event):
            p = Path(event.src_path)
            if p.suffix.lower() in _SUPPORTED_EXTENSIONS and not _should_ignore(p):
                store.delete_file_nodes(str(p))
                if on_change:
                    on_change([str(p)])

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


def _watch_with_polling(
    root_dir: str,
    store: GraphStore,
    interval_seconds: int,
    on_change: Optional[Callable[[list[str]], None]] = None,
) -> None:
    logger.info("watch: falling back to mtime polling for %s", root_dir)
    # Seed current mtimes on start to avoid spurious mass-reindex
    last_mtimes: dict[str, float] = {}
    for file_path in _collect_source_files(root_dir):
        try:
            last_mtimes[file_path] = Path(file_path).stat().st_mtime
        except OSError:
            pass

    try:
        while True:
            time.sleep(interval_seconds)
            changed = []
            current_files = _collect_source_files(root_dir)
            current_set = set(current_files)

            # Check deleted files
            deleted = set(last_mtimes.keys()) - current_set
            for del_path in deleted:
                store.delete_file_nodes(del_path)
                del last_mtimes[del_path]
                if on_change:
                    on_change([del_path])

            for file_path in current_files:
                try:
                    mtime = Path(file_path).stat().st_mtime
                except OSError:
                    continue
                if last_mtimes.get(file_path) != mtime:
                    last_mtimes[file_path] = mtime
                    changed.append(file_path)

            if changed:
                reindexed = update_graph(changed, store)
                if reindexed and on_change:
                    on_change(reindexed)
    except KeyboardInterrupt:
        pass
