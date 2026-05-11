"""
Unified MCP Server for Sonar - Orchestrates code search services.

This is the root entry point for the MCP server. It delegates to:
  - .ai/cocoindex/mcp_server.py - Semantic code search via PostgreSQL+embeddings
  - .ai/search/mcp_server.py - Blended lexical + semantic search

Architecture:
  - Root MCP server created in cocoindex's Python environment (has FastMCP)
  - Imports both service modules
  - Registers tools that delegate to each service
  - Handles fallback if either service is unavailable

Tools provided:
  1. search_code(query, top_k, include_code, min_score) - Blended code search
  2. get_project_structure() - Project file tree structure
"""

import json
import logging
import os
import subprocess
import sys
from concurrent.futures import ThreadPoolExecutor
from typing import Any, Dict, List, Optional

# Setup logging
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s"
)
logger = logging.getLogger("unified_mcp")

try:
    from mcp.server.fastmcp import FastMCP
    HAS_FASTMCP = True
except ImportError:
    HAS_FASTMCP = False
    logger.error("FastMCP not available - server cannot start")
    sys.exit(1)

# Add search/ to path so blender.py can be imported without extra deps
_search_dir = os.path.join(os.path.dirname(os.path.abspath(__file__)), "search")
if _search_dir not in sys.path:
    sys.path.insert(0, _search_dir)

try:
    from blender import blend_scores
    HAS_BLENDER = True
except ImportError:
    HAS_BLENDER = False
    logger.warning("blender.py not found — blended scoring disabled, falling back to cocoindex-only")


def _get_cocoindex_venv_python() -> str:
    """Get Python path from cocoindex venv."""
    return os.path.join(
        os.path.dirname(__file__),
        "cocoindex/.venv/bin/python3"
    )


def _get_search_venv_python() -> str:
    """Get Python path from search venv."""
    return os.path.join(
        os.path.dirname(__file__),
        "search/venv/bin/python3"
    )


def call_cocoindex_search(
    query: str,
    top_k: int = 10,
    include_code: bool = False,
    min_score: float = 0.3,
    layer_type: Optional[str] = None,
) -> List[Dict[str, Any]]:
    """
    Call cocoindex search via subprocess in its venv.
    
    Args:
        query: Search query
        top_k: Number of results to return
        include_code: Whether to include full code snippets
        min_score: Minimum score threshold
        
    Returns:
        List of search results from cocoindex
    """
    try:
        python_bin = _get_cocoindex_venv_python()
        if not os.path.exists(python_bin):
            logger.warning(f"Cocoindex Python not found at {python_bin}")
            return []
        
        cocoindex_path = os.path.join(
            os.path.dirname(__file__),
            "cocoindex"
        )
        
        # Call cocoindex MCP server's search_code function directly
        # by importing and running it in a subprocess for isolation
        layer_type_arg = f", layer_type={json.dumps(layer_type)}" if layer_type else ""
        cmd = [
            python_bin,
            "-c",
            f"""
import sys
sys.path.insert(0, '{cocoindex_path}')
try:
    from mcp_server import search_code as coco_search
    import json
    results = coco_search(
        query={json.dumps(query)},
        top_k={top_k},
        include_code={include_code},
        min_score={min_score}{layer_type_arg}
    )
    print(json.dumps(results))
except Exception as e:
    print(json.dumps({{"error": str(e)}}))
""",
        ]
        
        result = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            timeout=30,
        )
        
        if result.returncode != 0:
            logger.error(f"Cocoindex search error: {result.stderr}")
            return []
        
        try:
            output = json.loads(result.stdout.strip())
            if isinstance(output, dict) and "error" in output:
                logger.error(f"Cocoindex error: {output['error']}")
                return []
            return output if isinstance(output, list) else []
        except json.JSONDecodeError:
            logger.error(f"Failed to parse cocoindex output: {result.stdout}")
            return []
        
    except subprocess.TimeoutExpired:
        logger.error("Cocoindex search timed out")
        return []
    except FileNotFoundError as e:
        logger.warning(f"Cocoindex not available: {e}")
        return []
    except Exception as e:
        logger.error(f"Error calling cocoindex search: {e}", exc_info=True)
        return []


def call_cocoindex_symbol_search(
    symbol: str,
    top_k: int = 20,
    layer_type: Optional[str] = None,
) -> List[Dict[str, Any]]:
    """Call cocoindex search_symbol via subprocess."""
    try:
        python_bin = _get_cocoindex_venv_python()
        if not os.path.exists(python_bin):
            logger.warning(f"Cocoindex Python not found at {python_bin}")
            return []

        cocoindex_path = os.path.join(os.path.dirname(__file__), "cocoindex")
        layer_type_arg = f", layer_type={json.dumps(layer_type)}" if layer_type else ""
        cmd = [
            python_bin,
            "-c",
            f"""
import sys
sys.path.insert(0, '{cocoindex_path}')
try:
    from mcp_server import search_symbol as coco_symbol
    import json
    results = coco_symbol(
        symbol={json.dumps(symbol)},
        top_k={top_k}{layer_type_arg}
    )
    print(json.dumps(results))
except Exception as e:
    print(json.dumps({{"error": str(e)}}))
""",
        ]

        result = subprocess.run(cmd, capture_output=True, text=True, timeout=30)

        if result.returncode != 0:
            logger.error(f"Cocoindex symbol search error: {result.stderr}")
            return []

        try:
            output = json.loads(result.stdout.strip())
            if isinstance(output, dict) and "error" in output:
                logger.error(f"Cocoindex symbol error: {output['error']}")
                return []
            return output if isinstance(output, list) else []
        except json.JSONDecodeError:
            logger.error(f"Failed to parse cocoindex symbol output: {result.stdout}")
            return []

    except subprocess.TimeoutExpired:
        logger.error("Cocoindex symbol search timed out")
        return []
    except FileNotFoundError as e:
        logger.warning(f"Cocoindex not available: {e}")
        return []
    except Exception as e:
        logger.error(f"Error calling cocoindex symbol search: {e}", exc_info=True)
        return []


def call_qdrant_search(
    query: str,
    top_k: int = 10,
    min_score: float = 0.3,
    layer_type: Optional[str] = None,
) -> List[Dict[str, Any]]:
    """Call qdrant semantic search via Node.js subprocess. Returns JSON."""
    search_script = os.path.join(
        os.path.dirname(os.path.abspath(__file__)),
        "qdrant/retrieval/search.js",
    )
    try:
        cmd = ["node", search_script, query, "--top-k", str(top_k)]
        if layer_type:
            cmd += ["--layer-type", layer_type]

        result = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            timeout=30,
        )

        if result.returncode != 0:
            logger.error(f"Qdrant search error: {result.stderr}")
            return []

        try:
            results = json.loads(result.stdout.strip())
        except json.JSONDecodeError:
            logger.error(f"Failed to parse qdrant JSON: {result.stdout[:200]}")
            return []

        if not isinstance(results, list):
            logger.error(f"Unexpected qdrant output shape")
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
) -> Dict[str, Any]:
    """
    Blend cocoindex (lexical) + qdrant (semantic) results.

    Weights: 70% cocoindex, 30% qdrant. Gracefully falls back to
    whichever backend is available if one fails.
    """
    with ThreadPoolExecutor(max_workers=2) as executor:
        coco_future = executor.submit(call_cocoindex_search, query, top_k, include_code, min_score, layer_type)
        qdrant_future = executor.submit(call_qdrant_search, query, top_k, min_score, layer_type)
        coco_results = coco_future.result()
        qdrant_results = qdrant_future.result()

    coco_available = len(coco_results) > 0
    qdrant_available = len(qdrant_results) > 0

    if not coco_available and not qdrant_available:
        logger.warning("No results from cocoindex or qdrant")
        return {
            "results": [],
            "query": query,
            "sources_used": [],
            "total_results": 0,
        }

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


def call_get_project_structure() -> str:
    """
    Call get_project_structure from cocoindex via subprocess.
    
    Returns:
        Tree-formatted string of project structure
    """
    try:
        python_bin = _get_cocoindex_venv_python()
        if not os.path.exists(python_bin):
            logger.warning(f"Cocoindex Python not found at {python_bin}")
            return "(project structure unavailable)"
        
        cocoindex_path = os.path.join(
            os.path.dirname(__file__),
            "cocoindex"
        )
        
        # Call cocoindex MCP server's get_project_structure function
        cmd = [
            python_bin,
            "-c",
            f"""
import sys
sys.path.insert(0, '{cocoindex_path}')
try:
    from mcp_server import get_project_structure as get_struct
    structure = get_struct()
    print(structure)
except Exception as e:
    print(f"Error: {{e}}")
""",
        ]
        
        result = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            timeout=30,
        )
        
        if result.returncode != 0:
            logger.error(f"get_project_structure error: {result.stderr}")
            return "(structure retrieval failed)"
        
        return result.stdout.strip() or "(no structure available)"
        
    except subprocess.TimeoutExpired:
        logger.error("get_project_structure timed out")
        return "(structure retrieval timed out)"
    except FileNotFoundError as e:
        logger.warning(f"Cocoindex not available: {e}")
        return "(cocoindex not available)"
    except Exception as e:
        logger.error(f"Error getting project structure: {e}", exc_info=True)
        return f"(error: {str(e)})"


# Create MCP server instance
mcp = FastMCP("unified_search")


@mcp.tool(
    description="CALL THIS FIRST before writing, modifying, or explaining any code. "
    "Blended lexical (CocoIndex 70%) + semantic (Qdrant 30%) search over all PHP, Vue, and TypeScript source. "
    "Covers sonar/app and sonar/ui/app — services, controllers, jobs, models, GraphQL, events, listeners. "
    "Use natural-language queries: 'billing invoice generation', 'account eligibility rule'. "
    "Run 2-3 focused queries for best coverage. "
    "Set include_code=True when you need to read the actual implementation. "
    "Filter by Laravel layer with layer_type: service, controller, job, model, graphql, console, event, listener, notification, observer, provider."
)
def search_code(
    query: str,
    top_k: int = 10,
    include_code: bool = False,
    min_score: float = 0.3,
    layer_type: Optional[str] = None,
) -> Dict[str, Any]:
    """Unified search_code tool — blends cocoindex + qdrant results."""
    logger.info(f"Unified search query: {query} (top_k={top_k}, layer_type={layer_type})")

    try:
        return call_search_blended(query, top_k, include_code, min_score, layer_type)
    except Exception as e:
        logger.error(f"Search failed: {e}", exc_info=True)
        return {
            "results": [],
            "query": query,
            "error": str(e),
            "total_results": 0,
        }


@mcp.tool(
    description="Precise symbol lookup by class or method name — CocoIndex only, no semantic scoring. "
    "Use when you know (or partially know) a class or method name. "
    "Matches 'ClassName::methodName' symbols and class names via substring search. "
    "Examples: 'BillingService', 'calculateTax', 'BillingService::calculateTax'. "
    "Always returns full code. Faster and more precise than search_code for known names. "
    "Optionally filter by layer_type: service, controller, job, model, graphql, etc."
)
def search_symbol(
    symbol: str,
    top_k: int = 20,
    layer_type: Optional[str] = None,
) -> Dict[str, Any]:
    """Symbol lookup — finds code chunks by class/method name substring."""
    logger.info(f"Symbol search: {symbol} (layer_type={layer_type})")
    try:
        results = call_cocoindex_symbol_search(symbol, top_k, layer_type)
        return {
            "results": results,
            "symbol": symbol,
            "total_results": len(results),
        }
    except Exception as e:
        logger.error(f"Symbol search failed: {e}", exc_info=True)
        return {
            "results": [],
            "symbol": symbol,
            "error": str(e),
            "total_results": 0,
        }


@mcp.tool(
    description="Get the full file tree of all indexed source files. "
    "Call this when orienting to an unfamiliar subsystem or before a broad refactor. "
    "Prefer search_code for targeted lookups — use this for spatial orientation."
)
def get_project_structure() -> str:
    """
    Get project structure from cocoindex.
    
    Returns a tree-formatted view of all indexed source files.
    """
    logger.info("Getting project structure")
    
    try:
        structure = call_get_project_structure()
        return structure
    except Exception as e:
        logger.error(f"Failed to get project structure: {e}", exc_info=True)
        return f"(Error retrieving structure: {str(e)})"


def main():
    """Run the unified MCP server."""
    logger.info("Starting Sonar unified MCP server")
    logger.info("Tools registered: search_code, search_symbol, get_project_structure")
    
    try:
        mcp.run(transport="stdio")
    except Exception as e:
        logger.error(f"Server failed: {e}", exc_info=True)
        sys.exit(1)


if __name__ == "__main__":
    main()
