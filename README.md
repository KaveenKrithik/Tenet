# Tenet

> **"What's happened, happened. What hasn't left your machine stays free."**
> 
> *Invert your LLM budget. AST graph pruning, local semantic caching, and pre-execution routing.*

Tenet is a local-first token efficiency layer for AI coding assistants. It intercepts prompts and codebase context before transmission to upstream LLM APIs, running them through a 6-stage reduction pipeline to eliminate redundant context, serve cached queries locally, and route tasks to optimal model tiers.

---

### Core Principles

- **"Reverting unnecessary LLM context burn before it hits the API."**
- **"Stop re-sending the past to build the future."**

---

## 6-Stage Reduction Pipeline

0. **Prompt Optimizer**: Intercepts and rewrites vague prompts into clear, strict, and rule-based instructions using local LLMs before entering the pipeline.
1. **AST Knowledge Graph Scope**: Multi-language Tree-sitter parsing (Python, JS, TS, TSX) resolves 2-hop caller/callee dependencies so only relevant symbols enter context.
2. **Structural Diff Compression**: Replaces unchanged code with concise semantic diff summaries, cutting context by 60%–80%.
3. **Local Semantic Cache**: Matches prompt vectors via local dense embeddings (`all-MiniLM-L6-v2`) for instant 0-token hits ($0.00 cost).
4. **Local Model Triage**: Resolves small scopes (<= 10 nodes) using local Ollama (`qwen2.5-coder`) with AST syntax verification.
5. **Dynamic Tier Routing & Multi-Agent Planning**: Classifies requests into `cheap`, `mid`, or `full` model tiers, enforces budget guardrails, and merges overlapping subagent tasks.
6. **Persistent Request Ledger & Futuristic UI**: SQLite WAL accounting with per-module attribution, anomaly spike detection, and an interactive dark-mode visualizer.

---

## Quick Setup

### 1. Install Tenet

```bash
git clone https://github.com/KaveenKrithik/Tenet.git
cd Tenet

# Create virtual environment & install
python3 -m venv .venv
source .venv/bin/activate
pip install -e .

# (Optional) Link globally to run from any folder
mkdir -p ~/.local/bin && ln -sf $(pwd)/.venv/bin/tenet ~/.local/bin/tenet
```

### 2. (Optional) Enable Local Triage with Ollama

```bash
ollama serve
ollama pull qwen2.5-coder:7b
```

---

## Usage

### In Any Codebase (CLI)

```bash
# 1. Index codebase knowledge graph
tenet init .

# 2. Optimize a rough prompt via local models (copies to clipboard)
tenet optimize "fix the thing that breaks on big files"

# 3. Launch futuristic analytics dashboard
tenet dashboard

# 4. Query through the token reduction pipeline
tenet query "Add error handling to calculate_total" --files src/calc.py

# 5. Check cumulative token savings
tenet status
```

### In AI Chat (Antigravity Assistant)

Type directly in your IDE chat:

```text
/tenet Refactor the auth token verification in auth.ts
```

Tenet will intercept the request, evaluate the local semantic cache, prune context, and return the verified result with minimal token consumption.

---

## License

MIT
