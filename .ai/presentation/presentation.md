---
marp: true
theme: default
paginate: true
style: |
  section {
    font-family: 'JetBrains Mono', 'Fira Code', monospace;
    font-size: 1.1rem;
  }
  h1 { color: #1a73e8; }
  h2 { color: #444; border-bottom: 2px solid #1a73e8; padding-bottom: 0.2em; }
  code { background: #f4f4f4; border-radius: 4px; padding: 0.1em 0.3em; }
  pre code { background: none; padding: 0; }
  table { width: 100%; }
  th { background: #1a73e8; color: white; }
  .highlight { color: #1a73e8; font-weight: bold; }
---

# Local AI Code Search
## Stop grepping. Start asking.

Andrew Clinton · Sonar Engineering

---

## The Problem

Every time you touch unfamiliar code:

1. `grep -r "ServiceEligibility" app/` → 47 matches
2. Open 8 files, skim 3000 lines
3. Give up, ask a coworker
4. **30 minutes lost before writing a single line**

And every file read burns **tokens** — the AI's working memory.

---

## What We Built

A **fully local** code intelligence stack:

| Layer | Tool | Role |
|---|---|---|
| Code chunks | **CocoIndex** + pgvector | Precise code retrieval |
| Architecture | **Qdrant** + Ollama | Semantic conceptual memory |
| Bridge | **MCP server** | One tool call from any AI client |

Everything runs on your machine. **Zero code sent to any API.**

---

## How It Works

```
Your question → MCP unified_search tool
                    ↓
         ┌──────────────────────┐
         │  CocoIndex (70%)     │  pgvector HNSW
         │  code chunks         │  krlvi/sentence-t5
         │  class + symbol meta │  768-dim embeddings
         └──────────────────────┘
         ┌──────────────────────┐
         │  Qdrant (30%)        │  nomic-embed-text
         │  arch summaries      │  llama3.2 via Ollama
         │  layer_type + class  │  768-dim embeddings
         └──────────────────────┘
                    ↓
         Deduplicated, blended, ranked results
```

---

## Token Savings: Before vs After

| Approach | Tool Calls | Tokens Consumed |
|---|---|---|
| `grep` + open 8 files | 8–15 | ~15,000–40,000 |
| `search_code("billing eligibility")` | 1 | ~800–2,000 |
| **Savings** | **10–15x fewer calls** | **10–30x fewer tokens** |

Fewer tokens = **faster responses**, **longer conversations**, **lower API cost**.

---

## Precision: Symbol Lookup

When you know the class name:

```python
# Finds BillingService::calculateEligibility instantly
search_symbol("BillingService::calculateEligibility")
```

Returns:
- Exact file + line numbers
- Full method body
- Layer type (service/controller/job/…)

**No grep. No false positives.**

---

## Semantic Search: "How does account activation work?"

Old way:
```
grep -r "activate" → 200+ results
```

New way:
```
search_code("account activation flow")
→ AccountService::activate (score: 0.91)
→ AccountActivatedEvent (score: 0.87)
→ ActivateAccountJob (score: 0.84)
```

**Architectural context in one call.**

---

## Privacy: 100% Local

| Step | Where it runs |
|---|---|
| Chunking + indexing | Your machine |
| Embedding (krlvi T5) | Your machine (sentence-transformers) |
| Summary generation (llama3.2) | Your machine (Ollama) |
| Vector search | Your machine (PostgreSQL / Qdrant) |
| MCP queries | Your machine |

**After the one-time model weight download — nothing leaves this machine.**

No vendor lock-in. No API keys for search. No audit logs of your queries.

---

## What Gets Indexed

**CocoIndex** (code chunks with metadata):
- `sonar/app` — services, controllers, jobs, models, GraphQL, events
- `sonar/tests` — full test suite
- `sonar/database` — migrations, factories, upgrade tasks
- `sonar/routes`

**Qdrant** (architectural summaries per file):
- Every PHP class → 1-2 sentence LLM summary of its responsibilities
- Filter by layer: `layer_type=service`, `layer_type=job`, etc.

---

## Live Demo

```python
# "What handles network device provisioning?"
search_code("network device provisioning", layer_type="service")

# "Where is IPAM implemented?"
search_symbol("IpamService")

# "How is billing delinquency triggered?"
search_code("billing delinquency trigger", layer_type="job")
```

Each call: **~1 second**, **~1,000 tokens**, precise results.

---

## Getting Started

```bash
# 1. Install Ollama + pull models (one time)
ollama pull nomic-embed-text
ollama pull llama3.2

# 2. Start the search stack
make up

# 3. Index the codebase (runs incrementally)
make index-all

# 4. Claude/Copilot pick up the MCP server automatically
# via .mcp.json — no configuration needed
```

The MCP tools `search_code`, `search_symbol`, and `get_project_structure` are available in Claude Code and GitHub Copilot immediately.

---

## Summary

- **10–30x fewer tokens** consumed per AI task
- **Precise symbol lookup** — no grep noise
- **Semantic architecture search** — find intent, not just strings
- **Fully local** — code never leaves the machine
- **Incremental updates** — `make cocoindex-index` keeps it fresh
- **Works today** in Claude Code + Copilot via MCP

**Questions?**
