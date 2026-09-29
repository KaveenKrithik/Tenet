"""
dashboard/api.py — FastAPI routes for the Tenet dashboard.

Serves ledger analytics (totals, spend by module, anomalies) and the
static single-page dashboard at GET /.

Upgrade 5 — Real-Time Token Savings HUD:
  GET /api/hud/snapshot — one-shot badge payload (JSON).
  GET /api/hud/stream   — Server-Sent Events stream that pushes HUD
                           updates every 5 seconds so IDE status bars
                           can display live badges:
                           [TENET: 61.2% Saved | $5.25 Preserved | 778k Left]
"""
from __future__ import annotations

import asyncio
import json
import logging
from pathlib import Path
from typing import Any

from fastapi import FastAPI, HTTPException
from fastapi.responses import FileResponse, JSONResponse, StreamingResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

from tenet.config import load_config
from tenet.graph.store import GraphStore
from tenet.graph.query import get_subgraph
from tenet.ledger.anomaly import check_anomaly
from tenet.ledger.store import LedgerStore
from tenet.pipeline import process_request
from tenet.router.multi_agent import detect_overlaps, TaskScope

logger = logging.getLogger(__name__)

app = FastAPI(
    title="Tenet Dashboard",
    description="Token efficiency analytics and knowledge graph for AI coding assistants",
    version="0.1.0",
)

_STATIC_DIR = Path(__file__).parent / "static"


# ---------------------------------------------------------------------------
# Models
# ---------------------------------------------------------------------------

class SimulateRequest(BaseModel):
    prompt: str
    touched_files: list[str] = []


# ---------------------------------------------------------------------------
# Dependency helpers
# ---------------------------------------------------------------------------

def _get_ledger() -> LedgerStore:
    cfg = load_config()
    return LedgerStore(cfg.ledger.db_path)


def _get_graph() -> GraphStore:
    cfg = load_config()
    return GraphStore(cfg.graph.db_path)


# ---------------------------------------------------------------------------
# Analytics API routes
# ---------------------------------------------------------------------------

from tenet.ide_detector import detect_ide_and_plan

@app.get("/api/totals", tags=["analytics"])
async def get_totals() -> dict[str, Any]:
    """Return aggregate token savings, cache hit rate, request counts, and detected IDE/plan budget info."""
    ledger = _get_ledger()
    totals = ledger.get_totals()
    cfg = load_config()

    detection = detect_ide_and_plan({
        "ide_provider": cfg.account.ide_provider,
        "account_plan": cfg.account.account_plan,
    })

    allowance = cfg.account.total_token_allowance or cfg.router.monthly_token_budget
    tokens_remaining = max(0, allowance - totals.tokens_actual_total) if allowance > 0 else None

    return {
        "total_requests": totals.total_requests,
        "cache_hits": totals.cache_hits,
        "local_successes": totals.local_successes,
        "escalations": totals.escalations,
        "tokens_naive_total": totals.tokens_naive_total,
        "tokens_actual_total": totals.tokens_actual_total,
        "tokens_saved": totals.tokens_saved,
        "cache_hit_rate": round(totals.cache_hit_rate, 4),
        "monthly_token_budget": allowance,
        "tokens_remaining": tokens_remaining,
        "account": {
            "user_name": cfg.account.user_name,
            "ide_provider": detection.ide_name,
            "account_plan": detection.plan_name,
            "plan_subtext": detection.plan_subtext,
            "total_allowance": allowance,
            "period_label": cfg.account.period_label,
        },
    }


@app.get("/api/models-usage", tags=["analytics"])
async def get_models_usage() -> dict[str, Any]:
    """Return model quota and rate limit status matching IDE Models & Usage interface."""
    cfg = load_config()
    detection = detect_ide_and_plan({
        "ide_provider": cfg.account.ide_provider,
        "account_plan": cfg.account.account_plan,
    })
    return {
        "ide_name": detection.ide_name,
        "plan_name": detection.plan_name,
        "plan_subtext": detection.plan_subtext,
        "gemini_models": {
            "name": detection.gemini_quota.name,
            "remaining_pct": detection.gemini_quota.remaining_pct,
            "description": detection.gemini_quota.description,
            "refresh_text": detection.gemini_quota.refresh_text,
            "status": detection.gemini_quota.status,
        },
        "claude_gpt_models": {
            "name": detection.claude_gpt_quota.name,
            "remaining_pct": detection.claude_gpt_quota.remaining_pct,
            "description": detection.claude_gpt_quota.description,
            "refresh_text": detection.claude_gpt_quota.refresh_text,
            "status": detection.claude_gpt_quota.status,
        }
    }




@app.get("/api/spend-by-module", tags=["analytics"])
async def get_spend_by_module() -> dict[str, int]:
    """Return per-module token spend totals."""
    ledger = _get_ledger()
    return ledger.get_spend_by_module()


@app.get("/api/anomalies", tags=["analytics"])
async def get_anomalies() -> list[dict[str, Any]]:
    """Return recent requests flagged as anomalous token spikes."""
    cfg = load_config()
    ledger = _get_ledger()
    recent = ledger.get_recent_requests(limit=100)

    anomalies = []
    for req in recent:
        module = req.get("module_attribution") or "unknown"
        tokens = req.get("estimated_tokens_actual") or 0
        if check_anomaly(tokens, module, ledger, cfg.ledger.anomaly_multiplier):
            anomalies.append({
                "id": req["id"],
                "timestamp": req["timestamp"],
                "module": module,
                "stage_reached": req["stage_reached"],
                "tokens": tokens,
                "prompt_summary": req.get("prompt_summary", ""),
            })

    return anomalies


@app.get("/api/recent", tags=["analytics"])
async def get_recent(limit: int = 50) -> list[dict[str, Any]]:
    """Return the most recent ledger entries."""
    ledger = _get_ledger()
    return ledger.get_recent_requests(limit=min(limit, 200))


# ---------------------------------------------------------------------------
# Knowledge Graph & Visualizer API routes
# ---------------------------------------------------------------------------

@app.get("/api/graph", tags=["graph"])
async def get_graph_data() -> dict[str, Any]:
    """Return complete graph nodes and edges for visualization."""
    store = _get_graph()
    nodes = store.get_all_nodes()
    node_ids = [n["id"] for n in nodes]
    edges = store.get_edges_for_nodes(node_ids)

    # Compute graph statistics
    files = set(n["file_path"] for n in nodes)
    functions = sum(1 for n in nodes if n["type"] in ("function", "method"))
    classes = sum(1 for n in nodes if n["type"] == "class")
    modules = sum(1 for n in nodes if n["type"] == "module")

    return {
        "nodes": nodes,
        "edges": edges,
        "stats": {
            "total_nodes": len(nodes),
            "total_edges": len(edges),
            "files_count": len(files),
            "functions_count": functions,
            "classes_count": classes,
            "modules_count": modules,
        },
    }


@app.get("/api/node/{node_id}", tags=["graph"])
async def get_node_details(node_id: str) -> dict[str, Any]:
    """Return detailed node information, connected dependencies, and code snippet."""
    store = _get_graph()
    node = store.get_node(node_id)
    if not node:
        raise HTTPException(status_code=404, detail="Node not found")

    # Inbound and outbound edges
    all_edges = store.get_edges_for_nodes([node_id])
    inbound = [e for e in all_edges if e["target_id"] == node_id]
    outbound = [e for e in all_edges if e["source_id"] == node_id]

    # Source snippet
    snippet = ""
    file_path = node.get("file_path", "")
    try:
        if file_path and Path(file_path).exists():
            lines = Path(file_path).read_text(errors="replace").splitlines()
            start = max(0, node.get("line_start", 1) - 1)
            end = node.get("line_end", len(lines))
            snippet = "\n".join(lines[start:end])
    except Exception as exc:
        snippet = f"# Error reading source: {exc}"

    return {
        "node": node,
        "inbound_edges": inbound,
        "outbound_edges": outbound,
        "snippet": snippet,
    }


# ---------------------------------------------------------------------------
# Pipeline Simulation & Multi-Agent Planning API routes
# ---------------------------------------------------------------------------

@app.post("/api/pipeline/simulate", tags=["pipeline"])
async def simulate_pipeline(req: SimulateRequest) -> dict[str, Any]:
    """Run a prompt through the pipeline and return the execution trace."""
    cfg = load_config()
    graph_store = _get_graph()
    ledger = _get_ledger()

    result = process_request(
        prompt=req.prompt,
        touched_files=req.touched_files,
        config=cfg,
        graph_store=graph_store,
        ledger=ledger,
    )

    return {
        "stage_reached": result.stage_reached,
        "response": result.response,
        "tier": result.tier,
        "estimated_tokens": result.estimated_tokens,
        "scope_node_count": result.scope_node_count,
        "scope_edge_count": result.scope_edge_count,
        "requires_confirmation": result.requires_confirmation,
        "ledger_id": result.ledger_id,
        "context_node_ids": result.compressed_payload.scope_node_ids if result.compressed_payload else [],
    }


@app.get("/api/multi-agent/matrix", tags=["multi-agent"])
async def get_multi_agent_matrix() -> dict[str, Any]:
    """Detect task overlap across candidate nodes in the graph."""
    store = _get_graph()
    nodes = store.get_all_nodes()
    # Filter functions/methods for task candidates
    fn_nodes = [n for n in nodes if n["type"] in ("function", "method")][:8]

    tasks = [
        TaskScope(task_id=f"Task: {n['name']} ({Path(n['file_path']).name})", center_node_id=n["id"], hops=2)
        for n in fn_nodes
    ]

    overlaps = detect_overlaps(tasks, store)
    return {
        "tasks_analyzed": len(tasks),
        "overlap_groups": [
            {
                "task_a": g.task_a.task_id,
                "task_b": g.task_b.task_id,
                "shared_nodes_count": len(g.shared_node_ids),
                "shared_nodes": g.shared_node_ids,
                "overlap_ratio": round(g.overlap_ratio, 4),
                "recommendation": g.recommendation,
            }
            for g in overlaps
        ],
    }


# ---------------------------------------------------------------------------
# Upgrade 5 — Real-Time Token Savings HUD
# ---------------------------------------------------------------------------

def _build_hud_payload() -> dict[str, Any]:
    """Compute the current HUD badge payload.

    Returns a JSON-serialisable dict with:
    - ``badge``          — compact display string for IDE status bars
    - ``saved_pct``      — float percentage of tokens saved
    - ``dollars_saved``  — estimated cost preserved in USD
    - ``tokens_left``    — remaining allowance
    - ``total_requests`` — total pipeline runs
    - ``cache_hit_rate`` — float 0–1
    """
    cfg = load_config()
    try:
        ledger = _get_ledger()
        totals = ledger.get_totals()
    except Exception:
        totals = None

    if totals:
        naive = totals.tokens_naive_total or 1
        saved_pct = (totals.tokens_saved / naive * 100) if naive > 0 else 0.0
        dollars = (totals.tokens_saved / 1000) * 0.015
        allowance = cfg.account.total_token_allowance or cfg.router.monthly_token_budget
        tokens_left = max(0, allowance - totals.tokens_actual_total) if allowance > 0 else 0
        cache_hit_rate = round(totals.cache_hit_rate, 4)
        total_requests = totals.total_requests
    else:
        saved_pct = 0.0
        dollars = 0.0
        allowance = cfg.account.total_token_allowance or cfg.router.monthly_token_budget
        tokens_left = allowance
        cache_hit_rate = 0.0
        total_requests = 0

    badge = (
        f"[TENET: {saved_pct:.1f}% Saved │ "
        f"${dollars:.2f} Preserved │ "
        f"{tokens_left:,} Left]"
    )

    return {
        "badge": badge,
        "saved_pct": round(saved_pct, 2),
        "dollars_saved": round(dollars, 4),
        "tokens_left": tokens_left,
        "total_requests": total_requests,
        "cache_hit_rate": cache_hit_rate,
    }


@app.get("/api/hud/snapshot", tags=["hud"])
async def get_hud_snapshot() -> dict[str, Any]:
    """Return a one-shot HUD badge payload (JSON).

    Suitable for polling-based IDE integrations or MCP tool calls.
    """
    return _build_hud_payload()


@app.get("/api/hud/stream", tags=["hud"])
async def hud_stream(interval: float = 5.0):
    """Server-Sent Events stream pushing live HUD badge updates.

    Connect with EventSource or curl:

        curl http://127.0.0.1:8420/api/hud/stream

    Each event contains a JSON payload identical to ``/api/hud/snapshot``.
    The stream runs indefinitely; ``interval`` controls push frequency in
    seconds (default: 5, min: 1, max: 60).
    """
    push_interval = max(1.0, min(60.0, float(interval)))

    async def event_generator():
        while True:
            try:
                payload = _build_hud_payload()
                data = json.dumps(payload)
                yield f"data: {data}\n\n"
            except Exception as exc:
                err_payload = json.dumps({"error": str(exc)})
                yield f"data: {err_payload}\n\n"
            await asyncio.sleep(push_interval)

    return StreamingResponse(
        event_generator(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "X-Accel-Buffering": "no",
            "Connection": "keep-alive",
        },
    )


# ---------------------------------------------------------------------------
# Static file serving
# ---------------------------------------------------------------------------

@app.get("/", include_in_schema=False)
async def serve_index():
    """Serve the single-page dashboard."""
    index_path = _STATIC_DIR / "index.html"
    if index_path.exists():
        return FileResponse(str(index_path))
    return JSONResponse({"error": "Dashboard not found"}, status_code=404)


# Mount static assets
if _STATIC_DIR.exists():
    app.mount("/static", StaticFiles(directory=str(_STATIC_DIR)), name="static")
