"""
ledger/store.py — SQLite request log for tracking pipeline outcomes.

Tracks every request with metadata about which stage resolved it, token
counts, and module attribution.
"""
from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

import sqlite_utils

logger = logging.getLogger(__name__)

_SCHEMA_SQL = """
CREATE TABLE IF NOT EXISTS requests (
    id                        INTEGER PRIMARY KEY AUTOINCREMENT,
    timestamp                 TIMESTAMP NOT NULL,
    prompt_summary            TEXT,
    stage_reached             TEXT NOT NULL,
    -- 'cache_hit' | 'local_success' | 'escalated'
    scope_node_count          INT  DEFAULT 0,
    estimated_tokens_naive    INT  DEFAULT 0,
    estimated_tokens_actual   INT  DEFAULT 0,
    module_attribution        TEXT DEFAULT ''
);

CREATE INDEX IF NOT EXISTS idx_requests_timestamp ON requests(timestamp);
CREATE INDEX IF NOT EXISTS idx_requests_module ON requests(module_attribution);
CREATE INDEX IF NOT EXISTS idx_requests_stage ON requests(stage_reached);
"""


@dataclass
class Totals:
    total_requests: int
    cache_hits: int
    local_successes: int
    escalations: int
    tokens_naive_total: int
    tokens_actual_total: int
    tokens_saved: int
    cache_hit_rate: float


class LedgerStore:
    """SQLite-backed ledger for pipeline request logging and analytics."""

    def __init__(self, db_path: str) -> None:
        Path(db_path).parent.mkdir(parents=True, exist_ok=True)
        self._db = sqlite_utils.Database(db_path)
        self._init_schema()

    def _init_schema(self) -> None:
        self._db.execute("PRAGMA journal_mode=WAL")
        for stmt in _SCHEMA_SQL.strip().split(";"):
            stmt = stmt.strip()
            if stmt and not stmt.startswith("--"):
                try:
                    self._db.execute(stmt)
                except Exception as exc:
                    # Silently skip "already exists" for indexes; log everything else
                    if "already exists" not in str(exc).lower():
                        logger.warning("ledger schema: %s", exc)

    def log_request(
        self,
        prompt_summary: str,
        stage_reached: str,
        scope_node_count: int = 0,
        estimated_tokens_naive: int = 0,
        estimated_tokens_actual: int = 0,
        module_attribution: str = "",
    ) -> int:
        """Insert a new ledger row and return the new row ID."""
        now = datetime.now(timezone.utc).isoformat()
        row = {
            "timestamp": now,
            "prompt_summary": prompt_summary[:500] if prompt_summary else "",
            "stage_reached": stage_reached,
            "scope_node_count": scope_node_count,
            "estimated_tokens_naive": estimated_tokens_naive,
            "estimated_tokens_actual": estimated_tokens_actual,
            "module_attribution": module_attribution,
        }
        self._db["requests"].insert(row)  # type: ignore[index]
        row_id = self._db.execute("SELECT last_insert_rowid()").fetchone()[0]
        logger.debug("ledger: logged request id=%d stage=%s", row_id, stage_reached)
        return row_id

    def update_actual_tokens(self, request_id: int, actual_tokens: int) -> None:
        """Update the actual token count after the backend reports usage."""
        self._db.execute(
            "UPDATE requests SET estimated_tokens_actual = ? WHERE id = ?",
            [actual_tokens, request_id],
        )

    def get_totals(self, since: Optional[datetime] = None) -> Totals:
        """Compute aggregate statistics, optionally filtered to a time window."""
        base = "SELECT * FROM requests"
        params: list = []
        if since:
            base += " WHERE timestamp >= ?"
            params.append(since.isoformat())

        cur = self._db.execute(base, params)
        desc = cur.description or []
        col_names = [d[0] for d in desc]
        rows = cur.fetchall()

        if not col_names:
            # Table exists but has no schema description (shouldn't happen after init)
            return Totals(0, 0, 0, 0, 0, 0, 0, 0.0)

        total = len(rows)
        cache_hits = sum(1 for r in rows if r[col_names.index("stage_reached")] == "cache_hit")
        local_ok = sum(1 for r in rows if r[col_names.index("stage_reached")] == "local_success")
        escalated = sum(1 for r in rows if r[col_names.index("stage_reached")] == "escalated")

        naive_total = sum(r[col_names.index("estimated_tokens_naive")] or 0 for r in rows)
        actual_total = sum(r[col_names.index("estimated_tokens_actual")] or 0 for r in rows)
        saved = max(0, naive_total - actual_total)

        hit_rate = cache_hits / total if total > 0 else 0.0

        return Totals(
            total_requests=total,
            cache_hits=cache_hits,
            local_successes=local_ok,
            escalations=escalated,
            tokens_naive_total=naive_total,
            tokens_actual_total=actual_total,
            tokens_saved=saved,
            cache_hit_rate=hit_rate,
        )

    def get_spend_by_module(self) -> dict[str, int]:
        """Return a mapping of module_attribution → total actual tokens spent."""
        rows = self._db.execute(
            "SELECT module_attribution, SUM(estimated_tokens_actual) "
            "FROM requests GROUP BY module_attribution"
        ).fetchall()
        return {r[0] or "unknown": r[1] or 0 for r in rows}

    def get_recent_requests(self, limit: int = 50) -> list[dict]:
        cur = self._db.execute(
            "SELECT * FROM requests ORDER BY timestamp DESC LIMIT ?", [limit]
        )
        col_names = [d[0] for d in cur.description]
        return [dict(zip(col_names, row)) for row in cur.fetchall()]

    def get_module_rolling_average(self, module: str, last_n: int = 20) -> Optional[float]:
        """Return the rolling average token count for a module over the last N requests."""
        rows = self._db.execute(
            "SELECT estimated_tokens_actual FROM requests "
            "WHERE module_attribution = ? ORDER BY timestamp DESC LIMIT ?",
            [module, last_n],
        ).fetchall()
        if not rows:
            return None
        values = [r[0] for r in rows if r[0] is not None]
        return sum(values) / len(values) if values else None
