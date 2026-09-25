"""
cli.py — Tenet command-line interface (typer).

All business logic lives in the pipeline and sub-modules.
This file is a thin adapter layer only.
"""
from __future__ import annotations

import logging
import sys
from pathlib import Path
from typing import Optional

import typer
from rich.console import Console
from rich.table import Table

app = typer.Typer(
    name="tenet",
    help="🌌 Tenet — local-first token efficiency layer for AI coding assistants.",
    rich_markup_mode="rich",
    no_args_is_help=True,
)
console = Console()

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    datefmt="%H:%M:%S",
)


# ---------------------------------------------------------------------------
# tenet init [path]
# ---------------------------------------------------------------------------

@app.command("init")
def cmd_init(
    path: str = typer.Argument(".", help="Root directory of the codebase to index"),
) -> None:
    """Build the initial knowledge graph for a codebase.

    Walks all Python, JavaScript, and TypeScript files under PATH, parses
    their ASTs, and stores nodes + edges in the configured SQLite database.
    """
    from tenet.config import load_config
    from tenet.graph.builder import build_full_graph
    from tenet.graph.store import GraphStore

    cfg = load_config()
    store = GraphStore(cfg.graph.db_path)

    console.print(f"[bold blue]⚛ Tenet — building graph for:[/] {path}")
    build_full_graph(path, store)

    nodes = store.get_all_nodes()
    console.print(f"[bold green]✓ Done.[/] Indexed [bold]{len(nodes)}[/] nodes → {cfg.graph.db_path}")


# ---------------------------------------------------------------------------
# tenet watch [path]
# ---------------------------------------------------------------------------

@app.command("watch")
def cmd_watch(
    path: str = typer.Argument(".", help="Root directory to watch for changes"),
    interval: int = typer.Option(5, help="Polling interval in seconds"),
) -> None:
    """Start the file watcher and apply incremental graph updates on change.

    Uses watchdog if installed, otherwise falls back to mtime polling.
    Press Ctrl-C to stop.
    """
    from tenet.config import load_config
    from tenet.graph.builder import watch
    from tenet.graph.store import GraphStore

    cfg = load_config()
    store = GraphStore(cfg.graph.db_path)

    console.print(f"[bold blue]👁 Watching:[/] {path} (interval={interval}s) — Ctrl-C to stop")
    watch(path, store, interval_seconds=interval)


# ---------------------------------------------------------------------------
# tenet query
# ---------------------------------------------------------------------------

@app.command("query")
def cmd_query(
    prompt: str = typer.Argument(..., help='Coding prompt (e.g. "Add error handling to auth.py")'),
    files: str = typer.Option("", "--files", "-f", help="Comma-separated list of touched files"),
) -> None:
    """Run a prompt through the full 6-stage pipeline.

    On a cache hit, returns the cached response immediately.
    On local success, prints the Ollama-generated response.
    On escalation, prints the compressed context payload for the developer
    to hand off to a paid backend.
    """
    from tenet.config import load_config
    from tenet.pipeline import process_request

    cfg = load_config()
    touched = [f.strip() for f in files.split(",") if f.strip()] if files else []

    console.print(f"\n[bold blue]⚛ Processing:[/] {prompt[:80]}{'...' if len(prompt) > 80 else ''}")
    if touched:
        console.print(f"[dim]Files:[/] {', '.join(touched)}")

    def confirm(est_tokens: int, tier: str) -> bool:
        return typer.confirm(
            f"\n⚠️  Estimated {est_tokens:,} tokens (tier: {tier}). Proceed with escalation?"
        )

    result = process_request(
        prompt=prompt,
        touched_files=touched,
        config=cfg,
        confirmation_callback=confirm,
    )

    # Display result
    stage_colors = {
        "cache_hit": "green",
        "local_success": "blue",
        "escalated": "yellow",
    }
    color = stage_colors.get(result.stage_reached, "white")
    console.print(f"\n[bold {color}]Stage:[/] {result.stage_reached}")

    if result.response:
        console.print(f"\n[bold]Response:[/]\n{result.response}")
    else:
        console.print(f"\n[dim]Escalated — compressed payload ready ({len(result.compressed_payload.scope_node_ids)} nodes in scope)[/]")

    if result.tier:
        console.print(f"[dim]Tier:[/] {result.tier} | [dim]Est. tokens:[/] {result.estimated_tokens:,}")

    console.print(f"[dim]Ledger ID:[/] #{result.ledger_id}")


# ---------------------------------------------------------------------------
# tenet status
# ---------------------------------------------------------------------------

@app.command("status")
def cmd_status() -> None:
    """Print aggregate totals from the request ledger."""
    from tenet.config import load_config
    from tenet.ledger.store import LedgerStore

    cfg = load_config()

    if not Path(cfg.ledger.db_path).exists():
        console.print("[yellow]No ledger found yet. Run `tenet query` first.[/]")
        raise typer.Exit()

    ledger = LedgerStore(cfg.ledger.db_path)
    totals = ledger.get_totals()

    table = Table(title="🌌 Tenet — Pipeline Status", show_header=True)
    table.add_column("Metric", style="dim")
    table.add_column("Value", style="bold")

    table.add_row("Total Requests",   str(totals.total_requests))
    table.add_row("Cache Hits",        f"{totals.cache_hits} ({totals.cache_hit_rate:.1%})")
    table.add_row("Local Successes",   str(totals.local_successes))
    table.add_row("Escalated",         str(totals.escalations))
    table.add_row("Tokens (naive)",    f"{totals.tokens_naive_total:,}")
    table.add_row("Tokens (actual)",   f"{totals.tokens_actual_total:,}")
    table.add_row("Tokens Saved",      f"[bold green]{totals.tokens_saved:,}[/]")

    console.print(table)

    # Spend by module
    spend = ledger.get_spend_by_module()
    if spend:
        mod_table = Table(title="Spend by Module", show_header=True)
        mod_table.add_column("Module", style="dim")
        mod_table.add_column("Tokens", style="bold")
        for mod, tok in sorted(spend.items(), key=lambda x: -x[1]):
            mod_table.add_row(mod, f"{tok:,}")
        console.print(mod_table)


# ---------------------------------------------------------------------------
# tenet dashboard
# ---------------------------------------------------------------------------

@app.command("dashboard")
def cmd_dashboard() -> None:
    """Launch the FastAPI analytics dashboard."""
    import uvicorn

    from tenet.config import load_config
    from tenet.dashboard.api import app as dash_app

    cfg = load_config()
    host = cfg.dashboard.host
    port = cfg.dashboard.port

    console.print(f"[bold blue]🌐 Dashboard:[/] http://{host}:{port}")
    uvicorn.run(dash_app, host=host, port=port, log_level="warning")


# ---------------------------------------------------------------------------
# tenet config show
# ---------------------------------------------------------------------------

@app.command("config")
def cmd_config(
    show: bool = typer.Option(True, "--show", is_flag=True, help="Print resolved configuration"),
) -> None:
    """Print the resolved configuration."""
    import json

    from tenet.config import load_config

    cfg = load_config()
    console.print_json(cfg.model_dump_json(indent=2))


# ---------------------------------------------------------------------------
# tenet sync export / import (Stage 7 scaffold)
# ---------------------------------------------------------------------------

sync_app = typer.Typer(help="Team snapshot import/export (Stage 7 scaffold).")
app.add_typer(sync_app, name="sync")


@sync_app.command("export")
def cmd_sync_export(
    path: str = typer.Argument("team_snapshot.sqlite", help="Destination snapshot path"),
    no_cache: bool = typer.Option(False, "--no-cache", help="Exclude cache entries from snapshot"),
) -> None:
    """Export graph + cache to a portable SQLite snapshot."""
    from tenet.config import load_config
    from tenet.team_sync import export_snapshot

    cfg = load_config()
    export_snapshot(
        path=path,
        graph_db_path=cfg.graph.db_path,
        cache_db_path=cfg.cache.db_path,
        include_cache=not no_cache,
    )
    console.print(f"[green]✓ Snapshot exported to {path}[/]")


@sync_app.command("import")
def cmd_sync_import(
    path: str = typer.Argument("team_snapshot.sqlite", help="Path to the snapshot file"),
) -> None:
    """Merge a team snapshot into the local graph + cache databases."""
    from tenet.config import load_config
    from tenet.team_sync import import_snapshot

    cfg = load_config()
    counts = import_snapshot(
        path=path,
        graph_db_path=cfg.graph.db_path,
        cache_db_path=cfg.cache.db_path,
    )
    console.print("[green]✓ Snapshot imported:[/]")
    for table, count in counts.items():
        console.print(f"  {table}: {count} rows merged")


# ---------------------------------------------------------------------------
# Entrypoint
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    app()
