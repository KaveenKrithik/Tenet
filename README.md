# Tenet

> "What's happened, happened. What hasn't left your machine stays free."
>
> *Invert your LLM budget. AST graph pruning, local semantic caching, and pre-execution routing.*

Tenet is a local-first token efficiency layer for AI coding assistants. It intercepts prompts and codebase context before transmission to upstream LLM APIs, running them through a 6-stage reduction pipeline to eliminate redundant context, serve cached queries locally, and route tasks to optimal model tiers. It also ships with a real-time analytics dashboard, a built-in developer experience layer (mini-games, lofi music, achievements), and a cinematic CLI designed to be used daily.

---

## Core Principles

- Revert unnecessary LLM context burn before it hits the API.
- Stop re-sending the past to build the future.
- A great tool should be enjoyable to use, not just functional.

---

## 6-Stage Reduction Pipeline

| Stage | Name | Description |
|-------|------|-------------|
| 0 | Prompt Optimizer | Rewrites vague prompts into strict, rule-based instructions via local LLM before entering the pipeline |
| 1 | AST Knowledge Graph | Multi-language Tree-sitter parsing (Python, JS, TS, TSX). Resolves 2-hop caller/callee dependencies so only relevant symbols enter context |
| 2 | Structural Diff Compression | Replaces unchanged code with concise semantic diff summaries, cutting context 60%–80% |
| 3 | Local Semantic Cache | Matches prompt vectors via local dense embeddings (`all-MiniLM-L6-v2`) for instant 0-token hits |
| 4 | Local Model Triage | Resolves small scopes via local Ollama (`qwen2.5-coder`) with AST syntax verification |
| 5 | Dynamic Tier Routing | Classifies requests into `cheap`, `mid`, or `full` tiers and enforces budget guardrails |
| 6 | Persistent Ledger | SQLite WAL accounting with per-module attribution, anomaly detection, and real-time dashboard |

---

## Requirements

- Python 3.11+
- `uv` or `pip` for package management
- (Optional) [Ollama](https://ollama.com) for local model triage

---

## Installation

```bash
git clone https://github.com/KaveenKrithik/Tenet.git
cd Tenet

# Create virtual environment and install
python3 -m venv .venv
source .venv/bin/activate     # On Windows: .venv\Scripts\activate
pip install -e .

# Optionally link globally so 'tenet' works from any directory
mkdir -p ~/.local/bin && ln -sf $(pwd)/.venv/bin/tenet ~/.local/bin/tenet
```

### Optional: Enable Local Triage with Ollama

```bash
ollama serve
ollama pull qwen2.5-coder:7b
```

### Optional: Set Model Quota Percentages

Tenet reads live quota values from environment variables. Set these in your shell profile or CI environment:

```bash
export TENET_GEMINI_PCT=17      # % of Gemini weekly quota remaining
export TENET_CLAUDE_PCT=0       # % of Claude/GPT weekly quota remaining
```

Or write them to `~/.tenet/quota_cache.json`:

```json
{
  "gemini_pct": 17.0,
  "claude_pct": 0.0,
  "refresh_text": "in 2 days, 11 hours"
}
```

---

## CLI Reference

### Core Pipeline

```bash
# Index codebase — build the AST knowledge graph
tenet init .

# Run a prompt through the full 6-stage pipeline
tenet query "Add error handling to calculate_total"
tenet query "Refactor auth module" --files src/auth.py,src/models.py

# Interactive chat session
tenet chat

# Optimize a rough prompt via local LLM (copies result to clipboard)
tenet optimize "fix the thing that breaks on big files"
```

### Analytics and Status

```bash
# Show token savings, achievements, and quota status
tenet status

# Launch the real-time web dashboard
tenet dashboard
tenet dashboard --open          # Opens browser automatically
tenet dashboard --port 9000     # Custom port

# Print resolved configuration
tenet config
```

### Live Watch Mode

```bash
# Watch for file changes and auto-update the knowledge graph
tenet watch .
tenet watch . --interval 10     # Set polling interval in seconds
```

### Team Sync

```bash
# Export graph and cache as a portable SQLite bundle
tenet sync export team_snapshot.sqlite
tenet sync export --no-cache    # Exclude cache entries

# Import a team snapshot to merge into local databases
tenet sync import team_snapshot.sqlite
```

### Developer Experience

```bash
# Play a mini-game directly in the terminal (Snake or Tetris)
tenet play
tenet play snake
tenet play tetris

# Open playlist radio in the browser with an animated terminal equalizer
tenet chill

# Roll back the last AI-authored change (git restore)
tenet undo
```

---

## Dashboard

Start the dashboard with `tenet dashboard` and open `http://127.0.0.1:8420` in your browser.

| Tab | Description |
|-----|-------------|
| Overview | Live metrics: tokens saved, cache hit rate, total requests, budget gauge |
| Knowledge Graph | Interactive force-directed graph of your codebase's AST dependencies |
| Pipeline Simulator | Simulate any prompt through the reduction pipeline without writing to the ledger |
| Multi-Agent Planner | Detect task overlap and shared AST scope across parallel agent tasks |
| Request Ledger | Full history of every pipeline run with token attribution per module |
| Models and Usage | Your account plan, Gemini quota gauge, and Claude/GPT quota gauge |

The dashboard auto-refreshes every 6 seconds. Model quota data refreshes every 60 seconds.

---

## Achievements

Run `tenet status` to see unlocked achievements based on your usage:

| Achievement | Condition |
|-------------|-----------|
| Cache King | Hit the semantic cache at least once |
| Token Sniper | Saved more than 5,000 tokens |
| Tenet Veteran | Processed more than 5 requests |
| Optimization God | Saved more than 20,000 tokens |

---

## Developer Games

While `tenet query` or `tenet chat` processes your request, a mini-game launches automatically in the terminal:

- **Snake** — Classic. Navigate with arrow keys, eat the food (`*`), grow your snake.
- **Tetris** — Stack falling blocks with arrow keys. Up arrow rotates the piece.

Both games randomly alternate per session. Press `q` to hide the game and show a standard loading spinner instead.

To launch a game independently at any time:

```bash
tenet play          # random game
tenet play snake
tenet play tetris
```

---

## Auto Model Routing

Tenet auto-detects your IDE environment by scanning environment variables and filesystem markers:

| IDE | Detection Method |
|-----|-----------------|
| Antigravity IDE | `ANTIGRAVITY_IDE` env var or `~/.gemini/antigravity-ide` directory |
| Cursor | `CURSOR_TRACE` env var or `~/.cursor` directory |
| VS Code | `VSCODE_PID` or `VSCODE_IPC_HOOK` env var |
| JetBrains | `IDEA_INITIAL_DIRECTORY` or `JETBRAINS_CLIENT` env var |

To test with a different IDE environment from a plain terminal:

```bash
CURSOR_TRACE=1 tenet status
VSCODE_PID=1 tenet status
```

Model tier routing (`cheap`, `mid`, `full`) is configured in `config.yaml` under the `router` key. The pipeline automatically selects the cheapest tier that satisfies the scope requirements.

---

## AI Assistant Integration

In Antigravity IDE (or any supported AI chat), prefix your request with `/tenet`:

```text
/tenet Refactor the auth token verification in auth.ts
```

Tenet intercepts the request, runs it through the full 6-stage pipeline, and returns the result using the minimum possible tokens.

---

## Configuration

All settings live in `config.yaml` at the project root. Key sections:

```yaml
account:
  user_name: "Your Name"
  ide_provider: "Antigravity IDE"
  account_plan: "Antigravity Starter Quota"
  total_token_allowance: 1000000
  period_label: "Starter Quota"

graph:
  languages: [python, javascript, typescript]
  max_hops: 2
  db_path: "data/graph.sqlite"

cache:
  embedding_model: "all-MiniLM-L6-v2"
  similarity_threshold: 0.92
  ttl_hours: 168
  db_path: "data/cache.sqlite"

triage:
  ollama_model: "qwen2.5-coder:7b"
  ollama_host: "http://localhost:11434"

router:
  cost_confirmation_threshold_tokens: 20000
  tokens_per_node_estimate: 800

ledger:
  db_path: "data/ledger.sqlite"
  anomaly_multiplier: 3.0

dashboard:
  host: "127.0.0.1"
  port: 8420
```

---

## REST API

When the dashboard is running, the following endpoints are available:

| Method | Endpoint | Description |
|--------|----------|-------------|
| GET | `/api/totals` | Aggregate savings, cache rate, request counts, account info |
| GET | `/api/models-usage` | Model quota percentages and plan details |
| GET | `/api/spend-by-module` | Token spend broken down by module |
| GET | `/api/anomalies` | Requests flagged as token spikes |
| GET | `/api/recent` | Most recent ledger entries |
| GET | `/api/graph` | Full AST graph nodes and edges |
| GET | `/api/node/{id}` | Node details, dependencies, and source snippet |
| POST | `/api/pipeline/simulate` | Simulate a prompt without writing to ledger |
| GET | `/api/multi-agent/matrix` | Detect overlapping task scopes |
| GET | `/api/hud/snapshot` | One-shot HUD badge payload for IDE status bars |
| GET | `/api/hud/stream` | Server-Sent Events stream for live HUD updates |

---

## License

MIT
