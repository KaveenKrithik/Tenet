---
name: tenet
description: Local-first token efficiency layer. Intercepts prompts to check semantic cache (0 tokens), AST graph scope, and compressed context before writing or refactoring code.
---

# Tenet — Token Efficiency Skill

Use Tenet to prune context tokens, check for cached solutions, and optimize model tier routing whenever the user asks for code implementation, debugging, or refactoring.

---

## When to Use This Skill

Activate this workflow when:
- The user requests a code change, function implementation, or refactoring in a project codebase.
- The user asks a question about an existing module or codebase symbol.
- The user explicitly types `/tenet` or asks to optimize tokens.

---

## Execution Workflow

### 1. Initialize Graph (if not already done)
If the project has not yet been indexed with Tenet:
```bash
tenet init .
```

### 2. Query the Pipeline
Before dumping raw files or large context into your prompt, run the user's request through Tenet:
```bash
tenet query "<user_prompt>" --files <comma_separated_touched_files>
```

Alternatively, if the Tenet dashboard daemon is running, you can query the REST API directly:
```bash
curl -s -X POST http://127.0.0.1:8420/api/pipeline/simulate \
  -H "Content-Type: application/json" \
  -d '{"prompt": "<user_prompt>", "touched_files": ["path/to/file.py"]}'
```

---

## Interpreting Results

- **`Stage: cache_hit`**:
  An identical or semantically equivalent request was previously solved.
  - Return the cached response directly to the user.
  - Note: **0 tokens consumed ($0.00 cost)**.

- **`Stage: local_success`**:
  Resolved by local Ollama model with verified AST syntax.
  - Provide the validated local response to the user.

- **`Stage: escalated`**:
  Tenet has extracted only the 2-hop AST dependency scope and compressed unchanged code.
  - Proceed with code generation using the scoped context, saving 60% to 80% of normal token burn.
