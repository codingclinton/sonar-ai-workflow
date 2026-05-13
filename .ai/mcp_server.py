"""
Unified MCP Server for Sonar - Orchestrates code search services.

Root entry point for the MCP server. Delegates to:
  - .ai/cocoindex/mcp_server.py  — semantic code search via PostgreSQL + embeddings
  - .ai/qdrant/retrieval/search.js — file-level semantic discovery via Qdrant (Node.js subprocess)

Architecture:
  - Runs in the cocoindex Python venv (has all dependencies)
  - Imports cocoindex tools directly (no subprocess overhead)
  - Qdrant is called via Node.js subprocess (different runtime)

Tools provided:
  1. search_code        — blended semantic search, returns chunk_ids
  2. search_symbol      — precise symbol/class name lookup
  3. get_code           — fetch full body for a chunk_id
  4. get_file_chunks    — list all chunks in a file (metadata only)
  5. find_similar_to    — lateral discovery from a known chunk_id
  6. get_project_structure — project file tree
"""

import json
import logging
import os
import subprocess
import sys
import time
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

# Setup logging
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s"
)
logger = logging.getLogger("unified_mcp")

# Structured call log — JSON Lines, one entry per tool call
_LOG_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "logs")
os.makedirs(_LOG_DIR, exist_ok=True)
_CALL_LOG = os.path.join(_LOG_DIR, "search_calls.jsonl")


def _log(entry: dict) -> None:
    entry["ts"] = datetime.now(timezone.utc).isoformat()
    try:
        with open(_CALL_LOG, "a") as f:
            f.write(json.dumps(entry) + "\n")
    except Exception as e:
        logger.warning(f"call log write failed: {e}")

try:
    from mcp.server.fastmcp import FastMCP
    HAS_FASTMCP = True
except ImportError:
    HAS_FASTMCP = False
    logger.error("FastMCP not available - server cannot start")
    sys.exit(1)

# Add search/ to path for blender.py
_search_dir = os.path.join(os.path.dirname(os.path.abspath(__file__)), "search")
if _search_dir not in sys.path:
    sys.path.insert(0, _search_dir)

try:
    from blender import blend_scores
    HAS_BLENDER = True
except ImportError:
    HAS_BLENDER = False
    logger.warning("blender.py not found — falling back to cocoindex-only results")

# Load cocoindex module by file path to avoid sys.modules['mcp_server'] collision
# (both files are named mcp_server.py; importlib with a distinct module name bypasses it)
import importlib.util as _importlib_util

_cocoindex_dir = os.path.join(os.path.dirname(os.path.abspath(__file__)), "cocoindex")
_cocoindex_file = os.path.join(_cocoindex_dir, "mcp_server.py")

try:
    if _cocoindex_dir not in sys.path:
        sys.path.insert(0, _cocoindex_dir)
    _spec = _importlib_util.spec_from_file_location("cocoindex_mcp_server", _cocoindex_file)
    _cocoindex_mod = _importlib_util.module_from_spec(_spec)
    _spec.loader.exec_module(_cocoindex_mod)
    _coco_search_code     = _cocoindex_mod.search_code
    _coco_search_symbol   = _cocoindex_mod.search_symbol
    _coco_get_code        = _cocoindex_mod.get_code
    _coco_get_file_chunks = _cocoindex_mod.get_file_chunks
    _coco_find_similar_to = _cocoindex_mod.find_similar_to
    _coco_get_structure   = _cocoindex_mod.get_project_structure
    HAS_COCOINDEX = True
except Exception as e:
    HAS_COCOINDEX = False
    logger.error(f"Could not import cocoindex tools: {e}")


def call_qdrant_search(
    query: str,
    top_k: int = 10,
    min_score: float = 0.3,
    layer_type: Optional[str] = None,
) -> List[Dict[str, Any]]:
    """Call qdrant semantic search via Node.js subprocess."""
    search_script = os.path.join(
        os.path.dirname(os.path.abspath(__file__)),
        "qdrant/retrieval/search.js",
    )
    try:
        cmd = ["node", search_script, query, "--top-k", str(top_k)]
        if layer_type:
            cmd += ["--layer-type", layer_type]

        result = subprocess.run(cmd, capture_output=True, text=True, timeout=30)

        if result.returncode != 0:
            logger.error(f"Qdrant search error: {result.stderr}")
            return []

        try:
            results = json.loads(result.stdout.strip())
        except json.JSONDecodeError:
            logger.error(f"Failed to parse qdrant JSON: {result.stdout[:200]}")
            return []

        if not isinstance(results, list):
            return []

        return [r for r in results if r.get("score", 0) >= min_score]

    except subprocess.TimeoutExpired:
        logger.error("Qdrant search timed out")
        return []
    except FileNotFoundError:
        logger.warning(f"Qdrant search.js not found at {search_script}")
        return []
    except Exception as e:
        logger.error(f"Error calling qdrant search: {e}", exc_info=True)
        return []


def call_search_blended(
    query: str,
    top_k: int = 10,
    include_code: bool = False,
    min_score: float = 0.3,
    layer_type: Optional[str] = None,
    chunk_kind: Optional[str] = None,
) -> Dict[str, Any]:
    """
    Blend cocoindex + qdrant results.
    70/30 weights (unjustified default — revisit after Phase 7 lands and trace data exists).
    """
    if not HAS_COCOINDEX:
        return {"results": [], "query": query, "sources_used": [], "total_results": 0,
                "error": "cocoindex unavailable"}

    with ThreadPoolExecutor(max_workers=2) as executor:
        coco_future = executor.submit(
            _coco_search_code, query, top_k, include_code, min_score, layer_type, chunk_kind
        )
        qdrant_future = executor.submit(call_qdrant_search, query, top_k, min_score, layer_type)
        coco_results = coco_future.result()
        qdrant_results = qdrant_future.result()

    coco_available = len(coco_results) > 0
    qdrant_available = len(qdrant_results) > 0

    if not coco_available and not qdrant_available:
        logger.warning("No results from cocoindex or qdrant")
        return {"results": [], "query": query, "sources_used": [], "total_results": 0}

    if coco_available and qdrant_available and HAS_BLENDER:
        logger.info("Blending cocoindex + qdrant results (70/30)")
        results = blend_scores(
            coco_results,
            qdrant_results,
            cocoindex_weight=0.7,
            qdrant_weight=0.3,
            top_k=top_k,
        )
        sources_used = ["cocoindex", "qdrant"]
    elif coco_available:
        logger.warning("Qdrant unavailable — using cocoindex results only")
        results = coco_results
        sources_used = ["cocoindex"]
    else:
        logger.warning("Cocoindex unavailable — using qdrant results only")
        results = qdrant_results
        sources_used = ["qdrant"]

    return {
        "results": results,
        "query": query,
        "sources_used": sources_used,
        "total_results": len(results),
    }


# Create MCP server instance
mcp = FastMCP("unified_search")


@mcp.tool(
    description="CALL THIS FIRST before writing, modifying, or explaining any code. "
    "Blended semantic search over PHP, Vue, and TypeScript source. "
    "Returns snippets + chunk_ids. After search: "
    "use get_code(chunk_id) to read a full implementation, "
    "get_file_chunks(filename) to browse a file's structure, "
    "find_similar_to(chunk_id) for lateral discovery from a known chunk. "
    "Never use Read on an indexed source file when you have a chunk_id. "
    "Use natural-language queries: 'billing invoice generation', 'account eligibility rule'. "
    "Filter by layer_type: service, controller, job, model, graphql, console, event, "
    "listener, notification, observer, provider. "
    "Filter by chunk_kind: method, class, trait, interface, function."
)
def search_code(
    query: str,
    top_k: int = 10,
    include_code: bool = False,
    min_score: float = 0.3,
    layer_type: Optional[str] = None,
    chunk_kind: Optional[str] = None,
) -> Dict[str, Any]:
    """Unified search_code tool — blends cocoindex + qdrant results."""
    logger.info(f"search_code: {query!r} top_k={top_k} layer_type={layer_type} chunk_kind={chunk_kind}")
    t0 = time.monotonic()
    try:
        result = call_search_blended(query, top_k, include_code, min_score, layer_type, chunk_kind)
        scores = [r.get("score", 0) for r in result.get("results", [])]
        _log({
            "tool": "search_code",
            "query": query,
            "top_k": top_k,
            "layer_type": layer_type,
            "chunk_kind": chunk_kind,
            "result_count": len(scores),
            "max_score": round(max(scores), 4) if scores else None,
            "min_score": round(min(scores), 4) if scores else None,
            "avg_score": round(sum(scores) / len(scores), 4) if scores else None,
            "sources_used": result.get("sources_used", []),
            "latency_ms": round((time.monotonic() - t0) * 1000),
        })
        return result
    except Exception as e:
        logger.error(f"Search failed: {e}", exc_info=True)
        _log({"tool": "search_code", "query": query, "error": str(e), "latency_ms": round((time.monotonic() - t0) * 1000)})
        return {"results": [], "query": query, "error": str(e), "total_results": 0}


@mcp.tool(
    description="Precise symbol lookup by class or method name — CocoIndex only, no semantic scoring. "
    "Always returns full code bodies. Faster than search_code when you know a name. "
    "Matches 'ClassName::methodName' symbols and class names via substring search. "
    "Examples: 'BillingService', 'calculateTax', 'BillingService::calculateTax'. "
    "After: use get_code(chunk_id) to refetch selectively, find_similar_to(chunk_id) "
    "to discover related implementations. "
    "Filter by layer_type or chunk_kind for narrower results."
)
def search_symbol(
    symbol: str,
    top_k: int = 20,
    layer_type: Optional[str] = None,
    chunk_kind: Optional[str] = None,
) -> Dict[str, Any]:
    """Symbol lookup — finds code chunks by class/method name substring."""
    logger.info(f"search_symbol: {symbol!r} layer_type={layer_type}")
    t0 = time.monotonic()
    try:
        results = _coco_search_symbol(symbol, top_k, layer_type, chunk_kind)
        _log({
            "tool": "search_symbol",
            "symbol": symbol,
            "layer_type": layer_type,
            "chunk_kind": chunk_kind,
            "result_count": len(results),
            "latency_ms": round((time.monotonic() - t0) * 1000),
        })
        return {"results": results, "symbol": symbol, "total_results": len(results)}
    except Exception as e:
        logger.error(f"Symbol search failed: {e}", exc_info=True)
        _log({"tool": "search_symbol", "symbol": symbol, "error": str(e), "latency_ms": round((time.monotonic() - t0) * 1000)})
        return {"results": [], "symbol": symbol, "error": str(e), "total_results": 0}


@mcp.tool(
    description="Fetch the full code body for a single chunk_id returned by search_code or "
    "search_symbol. Use AFTER search to pull implementations one at a time. "
    "Never use Read on a source file when you have a chunk_id. "
    "Cheap, precise, no embedding cost."
)
def get_code(chunk_id: str) -> dict:
    logger.info(f"get_code: {chunk_id}")  # Default must match cocoindex/mcp_server.py signature
    t0 = time.monotonic()
    result = _coco_get_code(chunk_id)
    _log({
        "tool": "get_code",
        "chunk_id": chunk_id,
        "found": result.get("error") is None,
        "error": result.get("error"),
        "latency_ms": round((time.monotonic() - t0) * 1000),
    })
    return result


@mcp.tool(
    description="List all chunk_ids and their locations for a given file. "
    "Use when you have a filename from search results and want to browse the file's structure "
    "before fetching bodies with get_code. "
    "Filter by chunk_kind (method, class, trait, interface, function) to narrow results. "
    "No code bodies returned — metadata only."
)
def get_file_chunks(filename: str, chunk_kind: Optional[str] = None) -> dict:
    logger.info(f"get_file_chunks: {filename}")
    t0 = time.monotonic()
    result = _coco_get_file_chunks(filename, chunk_kind=chunk_kind)
    _log({
        "tool": "get_file_chunks",
        "filename": filename,
        "chunk_kind": chunk_kind,
        "chunk_count": result.get("chunk_count", 0),
        "found": result.get("error") is None,
        "latency_ms": round((time.monotonic() - t0) * 1000),
    })
    return result


@mcp.tool(
    description="Find chunks semantically similar to a chunk_id you already have. "
    "Lateral discovery — use when you've found one relevant chunk and need related ones "
    "without composing a new query. Returns chunk_ids + snippets, no code bodies. "
    "Use when refactoring a pattern, checking for similar bugs, or learning conventions. "
    "Don't use instead of search_code when you have a clear query. "
    "Filter by layer_type to scope to services, controllers, etc."
)
def find_similar_to(
    chunk_id: str,
    top_k: int = 5,           # Default must match cocoindex/mcp_server.py. Change both if changing one.
    min_score: float = 0.5,   # Default must match cocoindex/mcp_server.py. Change both if changing one.
    layer_type: Optional[str] = None,
) -> dict:
    logger.info(f"find_similar_to: {chunk_id}")
    t0 = time.monotonic()
    result = _coco_find_similar_to(chunk_id, top_k=top_k, min_score=min_score, layer_type=layer_type)
    _log({
        "tool": "find_similar_to",
        "chunk_id": chunk_id,
        "layer_type": layer_type,
        "result_count": len(result.get("results", [])),
        "found": result.get("error") is None,
        "latency_ms": round((time.monotonic() - t0) * 1000),
    })
    return result


@mcp.tool(
    description="Get the full file tree of all indexed source files. "
    "Use this for project-level orientation: which subsystems exist, where to start. "
    "Prefer search_code for targeted lookups."
)
def get_project_structure() -> str:
    """Return a tree-formatted view of all indexed source files."""
    logger.info("get_project_structure")
    try:
        return _coco_get_structure()
    except Exception as e:
        logger.error(f"Failed to get project structure: {e}", exc_info=True)
        return f"(Error retrieving structure: {str(e)})"


def main():
    """Run the unified MCP server."""
    logger.info("Starting Sonar unified MCP server")
    logger.info("Tools: search_code, search_symbol, get_code, get_file_chunks, find_similar_to, get_project_structure")
    try:
        mcp.run(transport="stdio")
    except Exception as e:
        logger.error(f"Server failed: {e}", exc_info=True)
        sys.exit(1)


if __name__ == "__main__":
    main()
