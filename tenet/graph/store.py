"""
store.py — SQLite adjacency storage for the knowledge graph.

Uses WAL mode and sqlite-utils for safe concurrent access from the CLI and
the dashboard server.
"""
from __future__ import annotations

import logging
from datetime import datetime, timezone
from pathlib import Path
from typing import Sequence

import sqlite_utils

from tenet.graph.parser import Edge, Node

logger = logging.getLogger(__name__)

_SCHEMA_SQL = """
CREATE TABLE IF NOT EXISTS nodes (
    id           TEXT PRIMARY KEY,
    type         TEXT NOT NULL,
    name         TEXT NOT NULL,
    file_path    TEXT NOT NULL,
    line_start   INT  NOT NULL,
    line_end     INT  NOT NULL,
    content_hash TEXT NOT NULL,
    updated_at   TIMESTAMP NOT NULL
);

CREATE TABLE IF NOT EXISTS edges (
    source_id TEXT NOT NULL,
    target_id TEXT NOT NULL,
    edge_type TEXT NOT NULL,
    PRIMARY KEY (source_id, target_id, edge_type)
);

CREATE TABLE IF NOT EXISTS file_hashes (
    file_path    TEXT PRIMARY KEY,
    content_hash TEXT NOT NULL,
    last_parsed  TIMESTAMP NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_nodes_file ON nodes(file_path);
CREATE INDEX IF NOT EXISTS idx_edges_source ON edges(source_id);
CREATE INDEX IF NOT EXISTS idx_edges_target ON edges(target_id);
"""


class GraphStore:
    """Thread/process-safe SQLite store for nodes, edges, and file hashes."""

    def __init__(self, db_path: str) -> None:
        self._path = db_path
        Path(db_path).parent.mkdir(parents=True, exist_ok=True)
        self._db = sqlite_utils.Database(db_path)
        self._init_schema()

    def _init_schema(self) -> None:
        self._db.execute("PRAGMA journal_mode=WAL")
        self._db.execute("PRAGMA foreign_keys=ON")
        for stmt in _SCHEMA_SQL.strip().split(";"):
            stmt = stmt.strip()
            if stmt:
                self._db.execute(stmt)

    # ------------------------------------------------------------------
    # Node operations
    # ------------------------------------------------------------------

    def upsert_nodes(self, nodes: Sequence[Node]) -> None:
        now = datetime.now(timezone.utc).isoformat()
        rows = [
            {
                "id": n.id,
                "type": n.type,
                "name": n.name,
                "file_path": n.file_path,
                "line_start": n.line_start,
                "line_end": n.line_end,
                "content_hash": n.content_hash,
                "updated_at": now,
            }
            for n in nodes
        ]
        if rows:
            self._db["nodes"].insert_all(rows, pk="id", replace=True)  # type: ignore[index]

    def delete_file_nodes(self, file_path: str) -> None:
        """Remove all nodes (and their edges) for a given file."""
        # Collect node ids for this file
        node_rows = list(
            self._db.query("SELECT id FROM nodes WHERE file_path = ?", [file_path])
        )
        node_ids = [r["id"] for r in node_rows]
        if node_ids:
            placeholders = ",".join("?" * len(node_ids))
            self._db.execute(
                f"DELETE FROM edges WHERE source_id IN ({placeholders}) "
                f"OR target_id IN ({placeholders})",
                node_ids + node_ids,
            )
            self._db.execute(
                f"DELETE FROM nodes WHERE id IN ({placeholders})", node_ids
            )
        self._db.execute(
            "DELETE FROM file_hashes WHERE file_path = ?", [file_path]
        )

    def get_all_nodes(self) -> list[dict]:
        return list(self._db.query("SELECT * FROM nodes"))

    def get_node(self, node_id: str) -> dict | None:
        rows = list(
            self._db.query("SELECT * FROM nodes WHERE id = ?", [node_id])
        )
        return rows[0] if rows else None

    # ------------------------------------------------------------------
    # Edge operations
    # ------------------------------------------------------------------

    def upsert_edges(self, edges: Sequence[Edge]) -> None:
        rows = [
            {
                "source_id": e.source_id,
                "target_id": e.target_id,
                "edge_type": e.edge_type,
            }
            for e in edges
        ]
        if rows:
            self._db["edges"].insert_all(  # type: ignore[index]
                rows, pk=["source_id", "target_id", "edge_type"], replace=True
            )

    def get_edges_for_nodes(self, node_ids: list[str]) -> list[dict]:
        if not node_ids:
            return []
        placeholders = ",".join("?" * len(node_ids))
        return list(
            self._db.query(
                f"SELECT * FROM edges WHERE source_id IN ({placeholders}) "
                f"OR target_id IN ({placeholders})",
                node_ids + node_ids,
            )
        )

    # ------------------------------------------------------------------
    # File hash operations
    # ------------------------------------------------------------------

    def upsert_file_hash(self, file_path: str, content_hash: str) -> None:
        now = datetime.now(timezone.utc).isoformat()
        self._db["file_hashes"].insert(  # type: ignore[index]
            {"file_path": file_path, "content_hash": content_hash, "last_parsed": now},
            pk="file_path",
            replace=True,
        )

    def get_file_hash(self, file_path: str) -> str | None:
        rows = list(
            self._db.query(
                "SELECT content_hash FROM file_hashes WHERE file_path = ?", [file_path]
            )
        )
        return rows[0]["content_hash"] if rows else None

    def get_all_file_hashes(self) -> dict[str, str]:
        rows = list(self._db.query("SELECT file_path, content_hash FROM file_hashes"))
        return {r["file_path"]: r["content_hash"] for r in rows}
