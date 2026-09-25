"""
team_sync.py — Stage 7 scaffold: export/import graph + cache snapshots.

This stage is intentionally minimal. Only export_snapshot() and
import_snapshot() are implemented, providing a portable SQLite bundle
that can be shared via a git repo, shared filesystem, or a free-tier
hosted SQLite service (e.g. Turso).

## Next steps for a full implementation:

1. **Shared git repo transport**:
   - Run `export_snapshot("team_snapshot.sqlite")`.
   - Commit the file to a shared git repo (use LFS for large DBs).
   - Team members run `git pull && tenet sync import team_snapshot.sqlite`.
   - Conflict resolution: merge strategy is "skip conflicting rows" (implemented below)
     because content_hash is the source of truth — if two members indexed the same
     function, they agree by definition.

2. **Turso (libsql) transport**:
   - Create a free Turso database at `https://turso.tech`.
   - Use `libsql-client` to stream rows from the snapshot into Turso.
   - Team members pull from Turso via `libsql-client` on demand.
   - Advantage: real-time, no git round-trip, works offline with local replica.

3. **Conflict resolution policy**:
   - Nodes: last-write-wins by `updated_at` timestamp.
   - Cache entries: additive merge, no overwrite (each entry has a unique hash).
   - File hashes: keep most recent `last_parsed`.

4. **Privacy considerations**:
   - Cache entries include `prompt_text` which may contain proprietary code.
   - Add a `--no-cache` flag to `export_snapshot` to strip them before sharing.
"""
from __future__ import annotations

import logging
import shutil
from pathlib import Path

import sqlite_utils

logger = logging.getLogger(__name__)

_TABLES_TO_EXPORT = ["nodes", "edges", "file_hashes", "cache_entries"]


def export_snapshot(
    path: str,
    graph_db_path: str = "data/graph.sqlite",
    cache_db_path: str = "data/cache.sqlite",
    include_cache: bool = True,
) -> None:
    """Export the knowledge graph (and optionally cache) to a portable SQLite file.

    The snapshot is a self-contained SQLite database containing the ``nodes``,
    ``edges``, and ``file_hashes`` tables from the graph store, plus optionally
    the ``cache_entries`` table from the cache store.

    Args:
        path: Destination path for the snapshot file.
        graph_db_path: Path to the graph SQLite database.
        cache_db_path: Path to the cache SQLite database.
        include_cache: If True, include semantic cache entries in the snapshot.
    """
    dest = Path(path)
    dest.parent.mkdir(parents=True, exist_ok=True)

    # Start from a fresh snapshot DB
    if dest.exists():
        dest.unlink()

    snap_db = sqlite_utils.Database(str(dest))
    snap_db.execute("PRAGMA journal_mode=WAL")

    # Export graph tables
    if Path(graph_db_path).exists():
        graph_db = sqlite_utils.Database(graph_db_path)
        for table_name in ("nodes", "edges", "file_hashes"):
            if table_name in graph_db.table_names():
                rows = list(graph_db[table_name].rows)  # type: ignore[index]
                if rows:
                    snap_db[table_name].insert_all(rows, ignore=True)  # type: ignore[index]
                logger.info("export_snapshot: exported %d rows from %s", len(rows), table_name)
    else:
        logger.warning("export_snapshot: graph db not found at %s", graph_db_path)

    # Export cache table
    if include_cache and Path(cache_db_path).exists():
        cache_db = sqlite_utils.Database(cache_db_path)
        if "cache_entries" in cache_db.table_names():
            rows = list(cache_db["cache_entries"].rows)  # type: ignore[index]
            if rows:
                snap_db["cache_entries"].insert_all(rows, ignore=True)  # type: ignore[index]
            logger.info("export_snapshot: exported %d cache entries", len(rows))

    logger.info("export_snapshot: snapshot written to %s", path)


def import_snapshot(
    path: str,
    graph_db_path: str = "data/graph.sqlite",
    cache_db_path: str = "data/cache.sqlite",
) -> dict[str, int]:
    """Merge a snapshot into the local databases, skipping conflicting rows.

    Conflict resolution: primary key conflicts are silently ignored (INSERT OR IGNORE).
    This is safe because identical content_hashes imply identical content.

    Args:
        path: Path to the snapshot file to import.
        graph_db_path: Target graph database path.
        cache_db_path: Target cache database path.

    Returns:
        Dict of table_name → rows_imported counts.
    """
    src = Path(path)
    if not src.exists():
        raise FileNotFoundError(f"Snapshot not found: {path}")

    snap_db = sqlite_utils.Database(str(src))
    imported: dict[str, int] = {}

    # Import graph tables
    graph_db = sqlite_utils.Database(graph_db_path)
    graph_db.execute("PRAGMA journal_mode=WAL")

    for table_name in ("nodes", "edges", "file_hashes"):
        if table_name not in snap_db.table_names():
            continue
        rows = list(snap_db[table_name].rows)  # type: ignore[index]
        if not rows:
            imported[table_name] = 0
            continue
        try:
            graph_db[table_name].insert_all(rows, ignore=True)  # type: ignore[index]
        except Exception as exc:
            logger.warning("import_snapshot: error importing %s: %s", table_name, exc)
        imported[table_name] = len(rows)
        logger.info("import_snapshot: merged %d rows into %s", len(rows), table_name)

    # Import cache entries
    if "cache_entries" in snap_db.table_names():
        cache_db = sqlite_utils.Database(cache_db_path)
        cache_db.execute("PRAGMA journal_mode=WAL")
        rows = list(snap_db["cache_entries"].rows)  # type: ignore[index]
        if rows:
            try:
                cache_db["cache_entries"].insert_all(rows, ignore=True)  # type: ignore[index]
            except Exception as exc:
                logger.warning("import_snapshot: error importing cache_entries: %s", exc)
        imported["cache_entries"] = len(rows)
        logger.info("import_snapshot: merged %d cache entries", len(rows))

    return imported
