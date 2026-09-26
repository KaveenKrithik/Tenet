"""
cli.py — Tenet command-line interface (typer + rich).

All business logic lives in the pipeline and sub-modules.
This file is a polished, cinematic adapter layer.
"""
from __future__ import annotations

import logging
import platform
import random
import shutil
import subprocess
import time
import warnings
import webbrowser
from pathlib import Path
from typing import Optional

import typer
from rich import box
from rich.align import Align
from rich.console import Console
from rich.markdown import Markdown
from rich.panel import Panel
from rich.rule import Rule
from rich.syntax import Syntax
from rich.table import Table
from rich.text import Text

warnings.filterwarnings("ignore", category=FutureWarning)

app = typer.Typer(
    name="tenet",
    help="Tenet — local-first token efficiency layer for AI coding assistants.",
    rich_markup_mode="rich",
    no_args_is_help=True,
)
console = Console()

logging.basicConfig(
    level=logging.WARNING,
    format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    datefmt="%H:%M:%S",
)

# ---------------------------------------------------------------------------
# Cinematic constants
# ---------------------------------------------------------------------------

BANNER = r"""[bold cyan]
  ████████╗███████╗███╗   ██╗███████╗████████╗
  ╚══██╔══╝██╔════╝████╗  ██║██╔════╝╚══██╔══╝
     ██║   █████╗  ██╔██╗ ██║█████╗     ██║   
     ██║   ██╔══╝  ██║╚██╗██║██╔══╝     ██║   
     ██║   ███████╗██║ ╚████║███████╗   ██║   
     ╚═╝   ╚══════╝╚═╝  ╚═══╝╚══════╝   ╚═╝   
[/bold cyan][dim cyan]     LOCAL-FIRST TOKEN EFFICIENCY LAYER[/dim cyan]
"""

TENET_QUOTES = [
    '"Don\'t try to understand it. Feel it." — Protagonist',
    '"What\'s happened, happened. What hasn\'t left your machine stays free."',
    '"Ignorance is our armour." — Protagonist',
    '"We live in a twilight world." — Protagonist',
    '"There are no coincidences." — Neil',
    '"Inversion. Not time-travel. Causality in reverse."',
    '"Doesn\'t take you long to get your bearings, does it?" — Neil',
    '"The algorithm is all that matters. Protect it." — Protagonist',
    '"From the future, with love." — Neil',
]


def _quote() -> str:
    return random.choice(TENET_QUOTES)


def _savings_bar(pct: float, width: int = 30) -> str:
    """Return a coloured ASCII progress bar for savings %."""
    filled = int((pct / 100) * width)
    empty = width - filled
    color = "bold green" if pct >= 75 else "bold yellow" if pct >= 40 else "bold red"
    bar = f"[{color}]{'█' * filled}[/][dim]{'░' * empty}[/]"
    return bar


# ---------------------------------------------------------------------------
# tenet init [path]
# ---------------------------------------------------------------------------

@app.command("init")
def cmd_init(
    path: str = typer.Argument(".", help="Root directory of the codebase to index"),
) -> None:
    """Build the knowledge graph — parse all AST symbols into SQLite."""
    from tenet.config import load_config
    from tenet.graph.builder import build_full_graph
    from tenet.graph.store import GraphStore

    cfg = load_config()
    store = GraphStore(cfg.graph.db_path)

    # Only place where the banner appears
    console.print(Align.center(BANNER))
    console.print(Align.center(f"[dim italic]{_quote()}[/]\n"))

    with console.status(
        f"[cyan]Parsing AST & building knowledge graph for:[/] [bold white]{path}[/]",
        spinner="aesthetic",
    ):
        start = time.time()
        build_full_graph(path, store)
        elapsed = time.time() - start

    nodes = store.get_all_nodes()
    node_ids = [n["id"] for n in nodes]
    edges = store.get_edges_for_nodes(node_ids)

    t = Table(box=box.SIMPLE, show_header=False, padding=(0, 2))
    t.add_row("[dim]Nodes indexed:[/]", f"[bold cyan]{len(nodes):,}[/]")
    t.add_row("[dim]Edges indexed:[/]", f"[bold cyan]{len(edges):,}[/]")
    t.add_row("[dim]Database:[/]",      f"[white]{cfg.graph.db_path}[/]")
    t.add_row("[dim]Build time:[/]",    f"[bold green]{elapsed:.2f}s[/]")

    console.print(Panel(
        t,
        title="[bold green]✓ Knowledge Graph Ready[/]",
        subtitle="[dim italic]\"What's happened, happened.\"[/]",
        border_style="green",
        padding=(1, 2),
    ))


# ---------------------------------------------------------------------------
# tenet watch [path]
# ---------------------------------------------------------------------------

@app.command("watch")
def cmd_watch(
    path: str = typer.Argument(".", help="Root directory to watch for changes"),
    interval: int = typer.Option(5, help="Polling interval in seconds"),
) -> None:
    """Live-watch the codebase and update the graph on every save."""
    from tenet.config import load_config
    from tenet.graph.builder import watch
    from tenet.graph.store import GraphStore

    cfg = load_config()
    store = GraphStore(cfg.graph.db_path)

    console.print(Panel(
        f"[bold white]Path:[/] [cyan]{path}[/]  [dim]·[/]  [bold white]Interval:[/] [cyan]{interval}s[/]\n"
        f"[dim]Every file save re-parses AST and updates the knowledge graph.[/]\n\n"
        f"[dim yellow]Ctrl+C to stop.[/]",
        title="[bold cyan]● Watching[/]",
        border_style="cyan",
        padding=(1, 2),
    ))
    watch(path, store, interval_seconds=interval)


# ---------------------------------------------------------------------------
# tenet query
# ---------------------------------------------------------------------------

@app.command("query")
def cmd_query(
    prompt: str = typer.Argument(..., help='Prompt to run through the reduction pipeline'),
    files: str = typer.Option("", "--files", "-f", help="Comma-separated context files"),
) -> None:
    """Run a prompt through all 6 reduction stages (cache → local → escalate)."""
    from tenet.config import load_config
    from tenet.pipeline import process_request

    cfg = load_config()
    touched = [f.strip() for f in files.split(",") if f.strip()] if files else []

    header = f"[bold white]{prompt}[/]"
    if touched:
        header += f"\n[dim]Files: {', '.join(touched)}[/]"

    console.print(Panel(header, title="[cyan]⬡ Pipeline[/]", border_style="cyan", padding=(0, 2)))

    def confirm(est_tokens: int, tier: str) -> bool:
        return typer.confirm(f"  Estimated {est_tokens:,} tokens ({tier} tier). Escalate?")

    with console.status("[cyan]Running 6-stage reduction...[/]", spinner="arc"):
        result = process_request(
            prompt=prompt,
            touched_files=touched,
            config=cfg,
            confirmation_callback=confirm,
        )

    stage_map = {
        "cache_hit":     ("green",  "⚡ CACHE HIT",          "0 tokens consumed  ·  $0.00 cost"),
        "local_success": ("blue",   "🤖 LOCAL SUCCESS",       "Resolved by local Ollama + AST verified"),
        "escalated":     ("yellow", "▲  CONTEXT ESCALATED",  "Compressed stub context → upstream model"),
    }
    color, title_str, sub = stage_map.get(result.stage_reached, ("white", result.stage_reached.upper(), ""))

    if result.response:
        body: object = Markdown(result.response)
    else:
        scope_n = len(result.compressed_payload.scope_node_ids) if result.compressed_payload else 0
        naive = result.scope_node_count * cfg.router.tokens_per_node_estimate
        saved = naive - result.estimated_tokens
        saved_pct = (saved / naive * 100) if naive else 0
        body = Text(
            f"{scope_n} AST nodes in scope  ·  {result.estimated_tokens:,} tokens (was {naive:,} naive)\n"
            f"{_savings_bar(saved_pct)} {saved_pct:.0f}% compressed",
        )

    console.print(Panel(
        body,
        title=f"[bold {color}]{title_str}[/]",
        subtitle=f"[dim]{sub}[/]",
        border_style=color,
        padding=(1, 2),
    ))

    # Compact telemetry footer
    t = Table(box=None, show_header=False, padding=(0, 2))
    t.add_row(
        f"[dim]tier[/] [bold]{result.tier or '—'}[/]",
        f"[dim]nodes[/] [bold]{result.scope_node_count}[/]",
        f"[dim]tokens[/] [bold]{result.estimated_tokens:,}[/]",
        f"[dim]ledger[/] [bold cyan]#{result.ledger_id}[/]",
    )
    console.print(t)
    console.print(f"  [dim italic]{_quote()}[/]\n")


# ---------------------------------------------------------------------------
# tenet optimize
# ---------------------------------------------------------------------------

@app.command("optimize")
def cmd_optimize(
    prompt: str = typer.Argument(..., help="Rough prompt to sharpen"),
    copy: bool = typer.Option(True, "--copy/--no-copy", help="Copy result to clipboard"),
) -> None:
    """Rewrite a vague prompt into a precise, rule-based instruction."""
    from tenet.config import load_config
    from tenet.triage.prompt_optimizer import optimize_prompt

    cfg = load_config()

    with console.status("[cyan]Optimizing via local LLM...[/]", spinner="dots"):
        optimized = optimize_prompt(prompt, cfg)

    t = Table(box=box.ROUNDED, show_header=True, padding=(0, 1))
    t.add_column("[dim]Original[/]", ratio=1)
    t.add_column("[bold green]Optimized[/]", ratio=1)
    t.add_row(prompt, optimized)

    console.print(Panel(
        t,
        title="[bold green]⚡ Stage 0 — Prompt Optimizer[/]",
        subtitle=f"[dim]{len(prompt)} → {len(optimized)} chars[/]",
        border_style="green",
    ))

    if copy:
        _copy_to_clipboard(optimized)


def _copy_to_clipboard(text: str) -> None:
    sys_name = platform.system()
    try:
        copied = False
        if sys_name == "Darwin" and shutil.which("pbcopy"):
            p = subprocess.Popen(["pbcopy"], env={"LANG": "en_US.UTF-8"}, stdin=subprocess.PIPE)
            p.communicate(text.encode("utf-8"))
            copied = p.returncode == 0
        elif sys_name == "Windows" and shutil.which("clip"):
            p = subprocess.Popen(["clip"], stdin=subprocess.PIPE)
            p.communicate(text.encode("utf-8"))
            copied = p.returncode == 0
        elif sys_name == "Linux":
            for cmd, extra in [("wl-copy", []), ("xclip", ["-selection", "clipboard"]), ("xsel", ["-b", "-i"])]:
                if shutil.which(cmd):
                    p = subprocess.Popen([cmd] + extra, stdin=subprocess.PIPE)
                    p.communicate(text.encode("utf-8"))
                    copied = p.returncode == 0
                    break
        if copied:
            console.print("  [dim green]✓ Copied to clipboard[/]")
    except Exception as exc:
        console.print(f"  [yellow]Clipboard unavailable: {exc}[/]")


# ---------------------------------------------------------------------------
# tenet status
# ---------------------------------------------------------------------------

@app.command("status")
def cmd_status() -> None:
    """Show pipeline performance metrics, savings gauge, and module spend."""
    from tenet.config import load_config
    from tenet.ledger.store import LedgerStore

    cfg = load_config()

    if not Path(cfg.ledger.db_path).exists():
        console.print(Panel(
            "[yellow]No ledger data yet.[/]\nRun [bold cyan]tenet query[/] or type [bold cyan]/tenet[/] in chat.",
            border_style="yellow",
        ))
        raise typer.Exit()

    ledger = LedgerStore(cfg.ledger.db_path)
    totals = ledger.get_totals()

    naive = totals.tokens_naive_total or 1
    saved_pct = (totals.tokens_saved / naive) * 100 if naive > 0 else 0
    dollars = (totals.tokens_saved / 1000) * 0.015

    allowance = cfg.account.total_token_allowance or cfg.router.monthly_token_budget
    tokens_remaining = max(0, allowance - totals.tokens_actual_total) if allowance > 0 else 0
    rem_pct = (tokens_remaining / allowance * 100) if allowance > 0 else 100

    console.print(Panel(
        f"[bold white]User:[/] {cfg.account.user_name}  ·  [bold cyan]{cfg.account.ide_provider}[/] ([dim]{cfg.account.account_plan}[/])\n"
        f"[bold white]Quota Allowance:[/] {allowance:,} tokens  ·  [bold green]{tokens_remaining:,}[/] remaining ({rem_pct:.1f}% left)",
        title="[bold cyan]Personalized IDE Account Quota[/]",
        border_style="cyan",
        padding=(0, 2),
    ))

    # ── 3-card grid ──────────────────────────────────────────────────────────
    grid = Table.grid(expand=True)

    grid.add_column(ratio=1)
    grid.add_column(ratio=1)
    grid.add_column(ratio=1)
    grid.add_row(
        Panel(
            f"[bold white]{totals.total_requests}[/]\n[dim]{totals.escalations} escalated · {totals.cache_hits} cached[/]",
            title="[cyan]REQUESTS[/]", border_style="cyan",
        ),
        Panel(
            f"[bold green]{totals.tokens_saved:,}[/]\n[dim]≈ ${dollars:.3f} saved[/]",
            title="[green]TOKENS SAVED[/]", border_style="green",
        ),
        Panel(
            f"[bold cyan]{totals.cache_hit_rate:.1%}[/]\n[dim]semantic cache hit rate[/]",
            title="[blue]CACHE RATE[/]", border_style="blue",
        ),
    )
    console.print(grid)

    # ── Savings bar ───────────────────────────────────────────────────────────
    bar_color = "bold green" if saved_pct >= 75 else "bold yellow" if saved_pct >= 40 else "bold red"
    filled = int((saved_pct / 100) * 40)
    bar = f"[{bar_color}]{'█' * filled}[/][dim]{'░' * (40 - filled)}[/]  [{bar_color}]{saved_pct:.1f}%[/] compressed"
    console.print(Panel(bar, title="[bold]Compression Efficiency[/]", border_style="dim"))

    # ── Stage breakdown ───────────────────────────────────────────────────────
    t = Table(box=box.ROUNDED, title="Stage Breakdown", show_header=True)
    t.add_column("Stage / Metric",  style="dim")
    t.add_column("Value",           style="bold",      justify="right")
    t.add_column("Impact",          style="dim green",  justify="right")
    t.add_row("Stage 3 — Cache Hits",      str(totals.cache_hits),                  f"{totals.cache_hit_rate:.1%}  ($0.00)")
    t.add_row("Stage 4 — Local Successes", str(totals.local_successes),             "Free Ollama")
    t.add_row("Stage 5 — Escalations",     str(totals.escalations),                 "AST-scoped stub")
    t.add_row("Naive (no pipeline)",        f"{totals.tokens_naive_total:,}",        "Baseline")
    t.add_row("Actual transmitted",         f"{totals.tokens_actual_total:,}",       "Compressed")
    t.add_row("Total reduction",           f"[bold green]{totals.tokens_saved:,}[/]", f"[bold green]{saved_pct:.1f}% SAVED[/]")
    console.print(t)

    # ── Module spend ──────────────────────────────────────────────────────────
    spend = ledger.get_spend_by_module()
    if spend:
        mt = Table(box=box.SIMPLE, title="Spend by Module", show_header=True)
        mt.add_column("Module", style="cyan")
        mt.add_column("Tokens", style="bold",  justify="right")
        mt.add_column("Share",  style="dim",   justify="right")
        total_spend = sum(spend.values()) or 1
        for mod, tok in sorted(spend.items(), key=lambda x: -x[1]):
            mt.add_row(mod, f"{tok:,}", f"{(tok/total_spend)*100:.1f}%")
        console.print(mt)

    console.print(f"\n  [dim italic]{_quote()}[/]\n")


# ---------------------------------------------------------------------------
# tenet dashboard
# ---------------------------------------------------------------------------

@app.command("dashboard")
def cmd_dashboard(
    open_browser: bool = typer.Option(False, "--open", "-o", help="Open browser automatically"),
) -> None:
    """Launch the FastAPI visualizer + analytics dashboard."""
    import uvicorn
    from tenet.config import load_config
    from tenet.dashboard.api import app as dash_app

    cfg = load_config()
    url = f"http://{cfg.dashboard.host}:{cfg.dashboard.port}"

    console.print(Panel(
        f"[bold cyan]{url}[/]\n"
        f"[dim]Graph Visualizer  ·  Multi-Agent Planner  ·  Request Ledger[/]\n\n"
        f"[dim yellow]Ctrl+C to stop[/]",
        title="[bold green]● Tenet Dashboard[/]",
        border_style="green",
        padding=(1, 2),
    ))

    if open_browser:
        webbrowser.open(url)

    uvicorn.run(dash_app, host=cfg.dashboard.host, port=cfg.dashboard.port, log_level="warning")


# ---------------------------------------------------------------------------
# tenet config
# ---------------------------------------------------------------------------

@app.command("config")
def cmd_config(
    show: bool = typer.Option(True, "--show", is_flag=True, help="Print resolved configuration"),
) -> None:
    """Print the resolved YAML configuration."""
    from tenet.config import load_config
    cfg = load_config()
    console.print(Panel(
        Syntax(cfg.model_dump_json(indent=2), "json", theme="monokai"),
        title="[cyan]Configuration[/]",
        border_style="cyan",
    ))


# ---------------------------------------------------------------------------
# tenet sync
# ---------------------------------------------------------------------------

sync_app = typer.Typer(help="Export / import team graph snapshots.")
app.add_typer(sync_app, name="sync")


@sync_app.command("export")
def cmd_sync_export(
    path: str = typer.Argument("team_snapshot.sqlite", help="Destination path"),
    no_cache: bool = typer.Option(False, "--no-cache", help="Exclude cache entries"),
) -> None:
    """Export graph + cache to a portable SQLite bundle."""
    from tenet.config import load_config
    from tenet.team_sync import export_snapshot
    cfg = load_config()
    export_snapshot(path=path, graph_db_path=cfg.graph.db_path,
                    cache_db_path=cfg.cache.db_path, include_cache=not no_cache)
    console.print(Panel(
        f"[bold green]✓[/] Exported → [white]{path}[/]",
        border_style="green",
    ))


@sync_app.command("import")
def cmd_sync_import(
    path: str = typer.Argument("team_snapshot.sqlite", help="Snapshot path"),
) -> None:
    """Merge a team snapshot into local graph + cache databases."""
    from tenet.config import load_config
    from tenet.team_sync import import_snapshot
    cfg = load_config()
    counts = import_snapshot(path=path, graph_db_path=cfg.graph.db_path,
                              cache_db_path=cfg.cache.db_path)
    t = Table(box=box.SIMPLE, show_header=True)
    t.add_column("Table", style="cyan")
    t.add_column("Rows", style="bold green", justify="right")
    for tbl, count in counts.items():
        t.add_row(tbl, str(count))
    console.print(Panel(t, title="[bold green]✓ Snapshot Imported[/]", border_style="green"))


# ---------------------------------------------------------------------------
# Entrypoint
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    app()
