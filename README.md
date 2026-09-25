# Tenet

> **"What's happened, happened. What hasn't left your machine stays free."**
> 
> *Invert your LLM budget. AST graph pruning, local semantic caching, and pre-execution routing.*

Tenet is a local-first token efficiency layer for AI coding assistants. It intercepts developer prompts and codebase context before transmission to upstream LLM APIs, running them through a six-stage reduction pipeline to eliminate redundant context, serve cached queries locally, and dynamically route tasks to appropriate model tiers.

---

### Key Principles

- **"Reverting unnecessary LLM context burn before it hits the API."**
- **"Stop re-sending the past to build the future."**

```
+-------------------------------------------------------------------------------+
|                             DEVELOPER PROMPT & SCOPE                          |
+-------------------------------------------------------------------------------+
                                       |
                                       v
                     [ Stage 1: AST Knowledge Graph Scope ]
                     Traverses 2-hop caller/callee dependencies
                                       |
                                       v
                     [ Stage 2: Structural Diff Compression ]
                     Replaces unchanged AST bodies with summaries
                                       |
                                       v
                     [ Stage 3: Local Semantic Cache ] -------------> Cache Hit (0 tokens, $0)
                     Sentence embeddings + cosine similarity
                                       |
                                       v
                     [ Stage 4: Local Ollama Triage ] --------------> Resolved Locally ($0)
                     Runs open-source model + syntax validation
                                       |
                                       v
                     [ Stage 5: Dynamic Tier Routing ]
                     Classifies cheap / mid / full + budget gates
                                       |
                                       v
                     [ Stage 6: Persistent Request Ledger ]
                     Attribution, anomaly detection, analytics
```

---

## Features

### 1. AST Knowledge Graph (Stage 1)
- Multi-language Tree-sitter parsing for Python, JavaScript, and TypeScript.
- Maps functions, classes, methods, and modules alongside call/import dependency edges.
- SQLite WAL adjacency store with SHA-256 content hashing for instant incremental diffing.
- Live file watcher updates graph state in real-time as you write code.

### 2. AST Context Compression (Stage 2)
- Compares working changes against the indexed AST baseline.
- Detects `signature_changed`, `body_changed`, `added`, and `deleted` symbols.
- Compacts unchanged reference context into structural diff summaries, cutting prompt payloads by 60% to 80%.

### 3. Local Semantic Cache (Stage 3)
- Generates 384-dimensional dense vectors locally using `all-MiniLM-L6-v2` (`sentence-transformers`).
- Keyed on exact scope hash and prompt cosine similarity (default threshold: 0.92).
- Automatic node-level invalidation: modifying any referenced file purges stale entries.

### 4. Zero-Cost Local Triage (Stage 4)
- Routes small, isolated scopes (<= 10 nodes) to a local Ollama instance (`qwen2.5-coder:7b`).
- Validates syntax and AST structure before accepting output.
- Transparent fallthrough: escalates cleanly if Ollama is unreachable or produces invalid syntax.

### 5. Dynamic Routing & Multi-Agent Planning (Stage 5)
- Classifies requests into model tiers based on graph complexity:
  - `cheap`: Small scopes (<= 5 nodes) -> lightweight models (Haiku / Flash).
  - `mid`: Medium scopes (6-20 nodes) -> standard frontier models (Sonnet).
  - `full`: Architectural scopes (> 20 nodes) -> reasoning models with safety confirmation gates.
- Multi-agent planner analyzes concurrent agent task scopes and outputs `MERGE` or `PARALLEL` execution plans based on Jaccard node overlap.

### 6. Ledger, Anomaly Detection & Dashboard (Stage 6)
- Persistent request accounting in SQLite with module-level spend attribution.
- Anomaly detection engine flags requests exceeding 3x the module baseline.
- Dokploy-style web UI with an interactive Canvas Knowledge Graph visualizer, Pipeline Simulator, and Ledger Explorer.

---

## Setup Guide

### Prerequisites

- Python 3.11+
- `uv` (recommended) or `pip`
- *Optional:* [Ollama](https://ollama.com) running locally for Stage 4 triage.

### 1. Installation

Clone the repository and install dependencies in an isolated virtual environment:

```bash
# Clone repository
git clone https://github.com/your-username/tenet.git
cd tenet

# Create virtual environment with uv
uv venv .venv
source .venv/bin/activate

# Install in editable mode
uv pip install -e .
```

### 2. (Optional) Start Local Ollama for Stage 4

```bash
# Start Ollama service
ollama serve

# Pull the default triage model
ollama pull qwen2.5-coder:7b
```

---

## Usage

### Index a Codebase

Build the initial knowledge graph for any project directory:

```bash
tenet init path/to/src
```

### Query Through the Pipeline

Run a prompt against specific files or modules:

```bash
tenet query "Add error handling to calculate_totals" --files src/core/calculator.py
```

### Check Token Efficiency & Status

View cumulative token savings and cache hit metrics in the terminal:

```bash
tenet status
```

### Start the Background File Watcher

Keep the knowledge graph and AST indices updated on every file save:

```bash
tenet watch path/to/src
```

### Launch the Analytics Dashboard

Start the local web UI:

```bash
tenet dashboard
```

Navigate to `http://127.0.0.1:8420` to access:
- **Overview**: Real-time token efficiency cards, module spend charts, and anomalies.
- **Knowledge Graph Visualizer**: Interactive force-directed canvas graph with node inspection and source code drawers.
- **Pipeline Simulator**: Sandbox to test and animate prompt execution through all 6 stages.
- **Multi-Agent Planner**: Overlap matrix and merge recommendations for subagents.
- **Request Ledger**: Filterable table of historical requests.

---

## Configuration

Tenet uses a hierarchical configuration system. Place a `config.yaml` in your project root or configure via environment variables:

```yaml
graph:
  languages:
    - python
    - javascript
    - typescript
  max_hops: 2
  db_path: data/graph.sqlite

cache:
  embedding_model: all-MiniLM-L6-v2
  similarity_threshold: 0.92
  ttl_hours: 168
  db_path: data/cache.sqlite

triage:
  ollama_model: qwen2.5-coder:7b
  ollama_host: http://localhost:11434
  max_local_hops: 2
  validation_timeout_seconds: 10

router:
  tiers:
    cheap:
      max_hops: 2
      max_nodes: 5
    mid:
      max_hops: 5
      max_nodes: 20
    full:
      max_hops: null
      max_nodes: null
  cost_confirmation_threshold_tokens: 20000
  tokens_per_node_estimate: 800

ledger:
  db_path: data/ledger.sqlite
  anomaly_multiplier: 3.0

dashboard:
  host: 127.0.0.1
  port: 8420
```

---

## REST API Reference

Tenet exposes a local REST API for integration with custom tools and editor plugins:

| Method | Endpoint | Description |
| :--- | :--- | :--- |
| `GET` | `/api/totals` | Aggregate token savings, cache hit rate, and request counts. |
| `GET` | `/api/spend-by-module` | Per-module token spend dictionary. |
| `GET` | `/api/anomalies` | List of requests flagged as anomalous spikes. |
| `GET` | `/api/recent` | Recent ledger entries. |
| `GET` | `/api/graph` | Nodes, edges, and statistics for graph visualizers. |
| `GET` | `/api/node/{node_id}` | Node metadata, connections, and extracted source code. |
| `POST` | `/api/pipeline/simulate` | Execute a prompt and return the step-by-step trace. |
| `GET` | `/api/multi-agent/matrix` | Overlap analysis and recommendations for concurrent tasks. |

---

## Testing

Run the full automated test suite:

```bash
pytest -v
```

---

## License

MIT
