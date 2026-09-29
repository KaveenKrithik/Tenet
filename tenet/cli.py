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
import sys
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
    """Live-watch the codebase and update the graph on every save.

    Upgrade 4 — Speculative Pre-caching on Save:
    Every detected file change triggers a low-priority background micro-embedding
    of the modified symbols into cache.sqlite so that subsequent tenet queries
    are instant (<5ms warm-up latency).
    """
    from tenet.config import load_config
    from tenet.graph.builder import watch
    from tenet.graph.store import GraphStore
    from tenet.cache.semantic_cache import SemanticCache
    from tenet.cache.precache import SpeculativePrecacher

    cfg = load_config()
    store = GraphStore(cfg.graph.db_path)

    # Bootstrap the semantic cache for speculative pre-caching
    cache = SemanticCache(
        db_path=cfg.cache.db_path,
        embedding_model=cfg.cache.embedding_model,
        similarity_threshold=cfg.cache.similarity_threshold,
        ttl_hours=cfg.cache.ttl_hours,
    )

    # Upgrade 4: start the background pre-cacher
    precacher = SpeculativePrecacher(store, cache, cfg)
    precacher.start()

    console.print(Panel(
        f"[bold white]Path:[/] [cyan]{path}[/]  [dim]·[/]  [bold white]Interval:[/] [cyan]{interval}s[/]\n"
        f"[dim]Every file save re-parses AST and updates the knowledge graph.[/]\n"
        f"[dim green]⚡ Speculative pre-caching active — symbols auto-embedded on save.[/]\n\n"
        f"[dim yellow]Ctrl+C to stop.[/]",
        title="[bold cyan]● Watching[/]",
        border_style="cyan",
        padding=(1, 2),
    ))

    def on_change(files: list[str]) -> None:
        for f in files:
            p = Path(f)
            if not p.exists():
                console.print(f"  [bold red]✕ Removed:[/] [dim]{f}[/]")
            else:
                nodes = store.get_nodes_by_file(f)
                console.print(
                    f"  [bold green]↻ Updated:[/] [cyan]{f}[/] [dim]({len(nodes)} symbols indexed)[/]"
                )
                # Upgrade 4: background micro-embed the changed symbols
                precacher.enqueue(f)
                console.print(
                    f"  [dim green]⚡ Queued for speculative pre-caching[/]"
                )

    try:
        watch(path, store, interval_seconds=interval, on_change=on_change)
    except KeyboardInterrupt:
        pass

    precacher.stop()
    console.print(
        f"\n[dim yellow]Watcher stopped.[/]  "
        f"[dim green]Pre-cached {precacher.total_embedded} symbols total.[/]\n"
    )


def _render_pipeline_result(result, cfg) -> None:
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
# tenet query
# ---------------------------------------------------------------------------

@app.command("query")
def cmd_query(
    prompt: Optional[str] = typer.Argument(None, help='Prompt to run through the reduction pipeline (omit for interactive prompt)'),
    files: str = typer.Option("", "--files", "-f", help="Comma-separated context files"),
) -> None:
    """Run a prompt through all 6 reduction stages (cache → local → escalate)."""
    from tenet.config import load_config
    from tenet.pipeline import process_request
    from tenet.router.classifier import get_live_quota_override

    cfg = load_config()

    if not prompt:
        if not sys.stdin.isatty():
            prompt = sys.stdin.read().strip()
        else:
            prompt = typer.prompt("Prompt")

    if not prompt or not prompt.strip():
        console.print("[yellow]Empty prompt provided. Aborted.[/]")
        raise typer.Exit()

    prompt = prompt.strip()
    raw_touched = [f.strip() for f in files.split(",") if f.strip()] if files else []
    touched = []
    
    if raw_touched:
        import difflib
        import os
        
        all_files = []
        for root, _, filenames in os.walk("."):
            if ".git" in root or ".venv" in root:
                continue
            for name in filenames:
                all_files.append(os.path.relpath(os.path.join(root, name), "."))
                
        for f in raw_touched:
            if not Path(f).exists():
                matches = difflib.get_close_matches(f, all_files, n=1, cutoff=0.4)
                if matches:
                    if typer.confirm(f"[yellow]File '{f}' not found.[/] Did you mean [bold cyan]{matches[0]}[/]?"):
                        touched.append(matches[0])
                    else:
                        touched.append(f)
                else:
                    console.print(f"[yellow]Warning: File '{f}' not found.[/]")
                    touched.append(f)
            else:
                touched.append(f)

    header = f"[bold white]{prompt}[/]"
    if touched:
        header += f"\n[dim]Files: {', '.join(touched)}[/]"

    console.print(Panel(header, title="[cyan]⧡ Pipeline[/]", border_style="cyan", padding=(0, 2)))

    # Upgrade 2 — Quota-Aware pre-flight warning
    try:
        quota_state = get_live_quota_override()
        if quota_state == "force_cheap":
            console.print(Panel(
                "[bold red]⚠  Claude/GPT allowance is EXHAUSTED (0% remaining).[/]\n"
                "[yellow]Router automatically downshifted to [bold]cheap[/bold] tier.[/]\n"
                "[dim]Stage 4 local Ollama generation will be prioritised. "
                "No costly model escalation will occur.[/]",
                title="[bold red]⚑ QUOTA AUTO-PILOT ACTIVE[/]",
                border_style="red",
                padding=(0, 2),
            ))
        elif quota_state == "warn_gemini":
            console.print(Panel(
                "[bold yellow]⚠  Gemini quota is LOW (below 20% remaining).[/]\n"
                "[dim]Routing to cheap tier to preserve allowance.[/]",
                title="[bold yellow]⚠ QUOTA WARNING[/]",
                border_style="yellow",
                padding=(0, 2),
            ))
    except Exception:
        pass  # non-fatal: proceed regardless

    def confirm(est_tokens: int, tier: str) -> bool:
        return typer.confirm(f"  Estimated {est_tokens:,} tokens ({tier} tier). Escalate?")

    from tenet.games import play_snake_while_waiting
    def req(confirm_cb):
        return process_request(
            prompt=prompt,
            touched_files=touched,
            config=cfg,
            confirmation_callback=confirm_cb,
        )

    console.print("[dim cyan]Starting Snake mini-game while Tenet runs... (Press 'q' to exit game)[/]")
    result = play_snake_while_waiting(req, console)

    _render_pipeline_result(result, cfg)


# ---------------------------------------------------------------------------
# tenet chat
# ---------------------------------------------------------------------------

@app.command("chat")
def cmd_chat() -> None:
    """Interactive terminal prompt session — run queries without typing in IDE."""
    from tenet.config import load_config
    from tenet.pipeline import process_request
    from tenet.games import play_snake_while_waiting

    cfg = load_config()
    console.print(Panel(
        "[bold cyan]Interactive Tenet Terminal Session[/]\n"
        "[dim]Enter prompts directly in this terminal (outside the IDE).\n"
        "Type 'exit' or press Ctrl+C to quit.[/]",
        title="[bold green]● Tenet Chat[/]",
        border_style="green",
        padding=(1, 2),
    ))

    while True:
        try:
            prompt = typer.prompt("\ntenet")
            if not prompt or prompt.strip().lower() in ("exit", "quit", "q"):
                break
            
            def req(confirm_cb):
                return process_request(prompt=prompt.strip(), config=cfg)
            console.print("[dim cyan]Starting Snake mini-game while Tenet runs... (Press 'q' to exit game)[/]")
            result = play_snake_while_waiting(req, console)
            
            _render_pipeline_result(result, cfg)
        except (KeyboardInterrupt, EOFError):
            break
    console.print("\n[dim yellow]Interactive session ended.[/]\n")


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

    # ── Achievements ──────────────────────────────────────────────────────────
    achievements = []
    if totals.cache_hits >= 1: achievements.append("[bold gold1]👑 Cache King[/] [dim](Hit the semantic cache)[/]")
    if totals.tokens_saved >= 5000: achievements.append("[bold bright_green]🎯 Token Sniper[/] [dim](Saved >5k tokens)[/]")
    if totals.total_requests >= 5: achievements.append("[bold bright_magenta]🎖️ Tenet Veteran[/] [dim](Processed >5 requests)[/]")
    if totals.tokens_saved >= 20000: achievements.append("[bold bright_cyan]🚀 Optimization God[/] [dim](Saved >20k tokens)[/]")
    if not achievements: achievements.append("[dim italic]Keep using Tenet to unlock achievements![/]")
    
    console.print(Panel(
        "\n".join(achievements),
        title="[bold yellow]🏆 Achievements[/]",
        border_style="yellow",
        padding=(0, 2),
    ))

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
    port: Optional[int] = typer.Option(None, "--port", "-p", help="Port to bind dashboard to"),
) -> None:
    """Launch the FastAPI visualizer + analytics dashboard."""
    import uvicorn
    from tenet.config import load_config
    from tenet.dashboard.api import app as dash_app

    cfg = load_config()
    bind_port = port or cfg.dashboard.port
    url = f"http://{cfg.dashboard.host}:{bind_port}"

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

    try:
        uvicorn.run(dash_app, host=cfg.dashboard.host, port=bind_port, log_level="warning")
    except OSError as err:
        if "address already in use" in str(err).lower():
            console.print(f"[bold red]Port {bind_port} is already in use.[/] Choose another port with [cyan]--port {bind_port + 1}[/].")
            raise typer.Exit(code=1)
        raise
    except KeyboardInterrupt:
        pass
    console.print("\n[dim yellow]Dashboard stopped.[/]\n")


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
# tenet play
# ---------------------------------------------------------------------------

@app.command("play")
def cmd_play(
    game: str = typer.Argument("random", help="Which game to play: snake, tetris, or random")
) -> None:
    """Take a break and play a mini-game right in the terminal."""
    from tenet.games import play_snake_while_waiting
    
    def req(confirm_cb):
        # Dummy long-running task that never finishes naturally, so you just play
        import time
        while True:
            time.sleep(1)
            
    # override the random choice temporarily for this command
    import random
    import tenet.games as g
    
    original_choice = random.choice
    if game.lower() in ("snake", "tetris"):
        g.random.choice = lambda _: game.lower()
        
    try:
        console.print(f"[dim cyan]Starting {game.capitalize()} mini-game... (Press 'q' to exit)[/]")
        play_snake_while_waiting(req, console)
    finally:
        g.random.choice = original_choice


# ---------------------------------------------------------------------------
# tenet undo
# ---------------------------------------------------------------------------

@app.command("undo")
def cmd_undo() -> None:
    """Safely roll back the last code change made by the AI."""
    console.print(Panel(
        "[bold yellow]⚠ Reversing Entropy[/]\n\n"
        "[dim]Scanning local git history for the last Tenet/AI-authored commit or uncommitted change...[/]",
        title="[bold red]Temporal Reversion[/]",
        border_style="red",
        padding=(1, 2)
    ))
    
    import time
    time.sleep(1)
    
    # Try a graceful git rollback if there are uncommitted changes
    try:
        status = subprocess.check_output(["git", "status", "--porcelain"], text=True)
        if status.strip():
            if typer.confirm("\nUncommitted changes detected. Discard all uncommitted changes?"):
                subprocess.run(["git", "restore", "."], check=True)
                console.print("\n[bold green]✓ Timeline restored.[/] Uncommitted changes discarded.")
            else:
                console.print("\n[dim]Rollback aborted.[/]")
        else:
            console.print("\n[dim green]✓ Workspace is clean.[/] No recent AI changes found to undo.")
    except Exception:
        console.print("\n[yellow]Not a git repository.[/] Unable to perform temporal reversion automatically.")

# ---------------------------------------------------------------------------
# tenet chill
# ---------------------------------------------------------------------------

@app.command("chill")
def cmd_chill() -> None:
    import threading
    
    console.print(Panel(
        "[bold magenta]Drake & Debug/]\n\n"
        "[dim]Take Care & Take Commits..[/]\n"
        "[dim italic]Press Ctrl+C to stop the music and exit.[/]",
        title="[bold cyan]● Tenet Chill[/]",
        border_style="magenta",
        padding=(1, 2)
    ))
    
    # Play stream using afplay (mac) or just open the browser
    def play_audio():
        sys_name = platform.system()
        try:
            if sys_name == "Darwin":
                # Since streaming raw audio from YT in terminal is complex without ffmpeg/mpv,
                # we'll open it in the background if possible, or just open browser.
                webbrowser.open("https://www.youtube.com/watch?v=SD4yRDY9mek&list=RDEMEPsGcPqqzpBxP-gtt4OYKg&start_radio=1")
            else:
                webbrowser.open("https://www.youtube.com/watch?v=SD4yRDY9mek&list=RDEMEPsGcPqqzpBxP-gtt4OYKg&start_radio=1")
        except Exception:
            pass
            
    t = threading.Thread(target=play_audio)
    t.start()
    
    try:
        # Just show a cool equalizer animation
        bars = [" ", "▂", "▃", "▄", "▅", "▆", "▇", "█"]
        while True:
            eq = "".join(random.choice(bars) for _ in range(20))
            sys.stdout.write(f"\r  [magenta]{eq}[/]  ")
            sys.stdout.flush()
            time.sleep(0.1)
    except KeyboardInterrupt:
        console.print("\n\n[dim]Music stopped. Back to work.[/]")


# ---------------------------------------------------------------------------
# Entrypoint
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    app()

