# Sonar AI Services - Unified MCP Architecture

This directory contains the AI integration layer for Sonar, providing code search and analysis capabilities to AI agents through the Model Context Protocol (MCP).

## Quick Start

**Run the unified MCP server:**
```bash
cd /Users/aclinton-sonar/Dev/sonar/.ai
./cocoindex/.venv/bin/python3 mcp_server.py
```

This starts the unified MCP server on stdio with tools:
- `search_code(query, top_k, include_code, min_score)` - Semantic code search
- `get_project_structure()` - Project file structure

## Architecture Overview

```
.ai/ (Unified MCP Server)
├── mcp_server.py                 # Root MCP entry point ← START HERE
│   ├── Imports FastMCP from cocoindex/.venv
│   ├── Registers search_code() tool
│   └── Registers get_project_structure() tool
│
├── cocoindex/                     # Semantic search backend
│   ├── mcp_server.py             # CocoIndex MCP service
│   ├── .venv/ (Python 3.13)      # MCP + embeddings environment
│   ├── main.py                   # Configuration & models
│   └── requirements.txt
│
├── search/                        # Blended search (under development)
│   ├── mcp_server.py             # Blended search service
│   ├── blender.py                # Score blending logic
│   ├── venv/ (Python 3.9)
│   └── requirements.txt
│
├── retrieval/                     # Vector search via Qdrant
│   ├── search.js                 # Node.js search wrapper
│   └── ...
│
├── indexer/                       # Document indexing pipeline
│   └── ...
│
├── venv/ (Python 3.9)            # Root venv - minimal
├── requirements.txt
└── README.md (this file)
```

## Key Components

### Root MCP Server (`.ai/mcp_server.py`)

**Entry Point**: Start here to launch the unified server

**How it works:**
1. Runs in cocoindex's Python 3.13 venv (has MCP + embeddings)
2. Creates single `FastMCP` server instance named `sonar_unified_search`
3. Registers tools that delegate to backend services
4. Each tool uses subprocess calls for service isolation

**Tools:**
- `search_code()` - Delegates to cocoindex semantic search
- `get_project_structure()` - Delegates to cocoindex file structure

**Error Handling:**
- Gracefully falls back if services unavailable
- Logs all operations for debugging
- 30-second timeout per subprocess call

### CocoIndex Service (`.ai/cocoindex/`)

**Backend**: PostgreSQL + sentence-transformers embeddings  
**Python**: 3.13 venv (required for FastMCP)

Implements:
- Semantic code search with vector similarity
- Project structure queries
- Direct MCP tool implementations

**Accessed by**: Root MCP via subprocess isolation

### Search Service (`.ai/search/`)

**Status**: Under development  
**Goal**: Blend lexical + semantic search results

**Components:**
- Lexical search (cocoindex backend)
- Semantic search (qdrant backend)
- Weighted score blending

### Retrieval Service (`.ai/retrieval/`)

**Backend**: Qdrant vector database  
**Language**: Node.js + TypeScript

Provides:
- Vector similarity search
- Result ranking

## Virtual Environments

| Location | Python | Purpose | MCP? |
|----------|--------|---------|------|
| `.ai/venv/` | 3.9 | Root environment | ❌ |
| `.ai/cocoindex/.venv/` | 3.13 | Semantic search (main) | ✅ **YES** |
| `.ai/search/venv/` | 3.9 | Blended search | ❌ |

**Why separate environments?**
- CocoIndex requires Python 3.13 for FastMCP compatibility
- Each service can be upgraded independently
- Isolated model loading and database connections
- Subprocess isolation for robustness

## Setup Instructions

### Install CocoIndex (required for MCP server)

```bash
cd .ai/cocoindex
python3.13 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
```

### Install Search Service (optional)

```bash
cd .ai/search
python3 -m venv venv
source venv/bin/activate
pip install -r requirements.txt
```

### Install Root Dependencies (optional)

```bash
cd .ai
python3 -m venv venv
source venv/bin/activate
pip install -r requirements.txt
```

## Usage

### Start MCP Server

```bash
.ai/cocoindex/.venv/bin/python3 .ai/mcp_server.py
```

This reads JSON-RPC requests from stdin and writes responses to stdout.

### Configure as MCP Server

Add to `~/.copilot/mcp-config.json`:

```json
{
  "mcpServers": {
    "sonar_search": {
      "command": "/Users/aclinton-sonar/Dev/sonar/.ai/cocoindex/.venv/bin/python3",
      "args": ["/Users/aclinton-sonar/Dev/sonar/.ai/mcp_server.py"]
    }
  }
}
```

Then reload with `mcp_reload` tool or restart CLI.

### Example: Search Code

```python
# Python
result = search_code("user authentication", top_k=5, include_code=True)
print(result)
# Returns:
# {
#   "results": [...],
#   "query": "user authentication",
#   "total_results": 5,
#   "backend": "cocoindex"
# }
```

### Example: Get Project Structure

```python
structure = get_project_structure()
print(structure)
# Returns tree like:
# src
# ├── main.py
# ├── utils/
# │   └── helpers.py
# └── services/
#     └── auth.py
```

## Delegation Pattern

**Request Flow:**

```
User Query
   ↓
Root MCP (mcp_server.py) handles JSON-RPC
   ↓
   ├→ search_code() tool
   │  └→ Calls call_cocoindex_search() subprocess
   │     └→ .ai/cocoindex/.venv/bin/python3
   │        └→ Imports mcp_server.search_code()
   │           └→ PostgreSQL query + embeddings
   │              └→ Returns JSON results
   │
   └→ get_project_structure() tool
      └→ Calls call_get_project_structure() subprocess
         └→ .ai/cocoindex/.venv/bin/python3
            └→ Imports mcp_server.get_project_structure()
               └→ PostgreSQL query
                  └→ Returns tree string
```

**Why Subprocess Isolation?**
- ✅ Clean environment per call
- ✅ Independent resource limits
- ✅ Easy debugging (can call service directly)
- ✅ Language-agnostic (could call Node.js, Go, etc.)
- ✅ Service can be restarted without killing server

## Troubleshooting

### "FastMCP not available"
Must use cocoindex venv (Python 3.13):
```bash
.ai/cocoindex/.venv/bin/python3 .ai/mcp_server.py
```

### "Cocoindex search timed out"
Check database connection:
```bash
.ai/cocoindex/.venv/bin/python3 -c "
import os; os.chdir('.ai/cocoindex')
from main import get_pool
pool = get_pool()
print('✓ Database connected')
"
```

### Search returns empty results
Try lower `min_score`:
```python
result = search_code("foo", min_score=0.1)
```

### Module not found errors
Verify venv paths and Python versions:
```bash
which python3.13  # Should exist
.ai/cocoindex/.venv/bin/python3 --version  # Should be 3.13.x
```

## Development

### Adding a New Search Backend

1. Create service directory: `.ai/new_service/`
2. Implement MCP tools: `new_service/mcp_server.py`
3. Setup isolated venv: `new_service/venv/`
4. Register with root MCP in `.ai/mcp_server.py`:

```python
# In mcp_server.py
def call_new_service(query):
    """Call new_service via subprocess"""
    result = subprocess.run(...)
    return json.loads(result.stdout)

@mcp.tool()
def new_tool(query):
    return call_new_service(query)
```

### Debugging

View startup logs:
```bash
.ai/cocoindex/.venv/bin/python3 .ai/mcp_server.py 2>&1 | head -20
```

Test tool directly:
```bash
cd .ai
.ai/cocoindex/.venv/bin/python3 -c "
import sys
sys.path.insert(0, '.')
from mcp_server import search_code
print(search_code('test query'))
"
```

## Performance

- **Search latency**: 50-500ms (varies by query)
- **Max results per query**: ~100
- **Memory footprint**: ~2GB (embeddings model) + ~500MB (search)
- **Concurrent requests**: JSON-RPC multiplexed

## File Reference

| File | Purpose |
|------|---------|
| `mcp_server.py` | Root MCP orchestrator |
| `cocoindex/mcp_server.py` | CocoIndex service |
| `cocoindex/main.py` | CocoIndex config & models |
| `search/mcp_server.py` | Blended search service |
| `search/blender.py` | Result blending |
| `retrieval/search.js` | Vector search wrapper |
| `requirements.txt` | Root dependencies |
| `cocoindex/requirements.txt` | CocoIndex dependencies |
| `search/requirements.txt` | Search dependencies |

## Next Steps

1. ✅ Root MCP orchestrator created
2. ⏳ Blended search integration (cocoindex + qdrant)
3. ⏳ Performance optimization (caching, batching)
4. ⏳ Web UI for debugging
5. ⏳ Multi-language support (Go, Rust, etc.)

## Notes

- This is the unified MCP server entry point for AI agents
- Individual services have isolated Python environments
- Root venv is minimal; MCP lives in cocoindex
- All service calls use subprocess for isolation
- See parent README for general Sonar architecture
