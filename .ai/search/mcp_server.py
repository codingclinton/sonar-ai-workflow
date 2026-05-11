"""
FastMCP Server for blended code search.

Combines results from cocoindex (lexical search) and qdrant (semantic search)
using a weighted blending strategy (70% cocoindex, 30% qdrant).
"""

import logging
import os
import subprocess
from typing import Any, Dict, List, Optional

try:
    from mcp.server.fastmcp import FastMCP
    HAS_FASTMCP = True
except ImportError:
    HAS_FASTMCP = False

# Import blender functions
from blender import blend_scores, normalize_scores

logger = logging.getLogger(__name__)


def call_cocoindex_search(
    query: str, top_k: int = 10, include_code: bool = False, min_score: float = 0.3
) -> List[Dict[str, Any]]:
    """
    Call cocoindex search via subprocess.
    
    Args:
        query: Search query
        top_k: Number of results to return
        include_code: Whether to include full code snippets
        min_score: Minimum score threshold
        
    Returns:
        List of search results from cocoindex
    """
    try:
        # Build command to call cocoindex MCP server search_code
        # This is a placeholder - in production, would use IPC/RPC
        logger.debug(f"Calling cocoindex search for: {query}")
        # For now, return empty list - would be replaced with actual RPC call
        return []
    except Exception as e:
        logger.error(f"Error calling cocoindex search: {e}")
        return []


def call_qdrant_search(
    query: str, top_k: int = 10, min_score: float = 0.3
) -> List[Dict[str, Any]]:
    """
    Call qdrant search via Node.js subprocess.
    
    Args:
        query: Search query
        top_k: Number of results to return
        min_score: Minimum score threshold (not used by Qdrant wrapper, but kept for API consistency)
        
    Returns:
        List of search results from qdrant
    """
    try:
        # Call the Node.js search script
        search_script = os.path.join(
            os.path.dirname(__file__), "../qdrant/retrieval/search.js"
        )
        
        result = subprocess.run(
            ["node", search_script, query, "--top-k", str(top_k)],
            capture_output=True,
            text=True,
            timeout=30,
        )
        
        if result.returncode != 0:
            logger.error(f"Qdrant search error: {result.stderr}")
            return []
        
        # Parse output - search.js outputs results as plain text
        # Format: "#1  path  (score: 0.1234)"
        results = []
        for line in result.stdout.split("\n"):
            if not line.strip() or line.startswith("query vector length"):
                continue
            
            # Parse format: "#1  /path/to/file.js  (score: 0.1234)"
            parts = line.split("(score:")
            if len(parts) == 2:
                path_part = parts[0].split()[-1]  # Get the path
                score_str = parts[1].strip().rstrip(")")
                
                try:
                    score = float(score_str)
                    results.append({
                        "filename": path_part,
                        "path": path_part,  # Include both for compatibility
                        "score": round(score, 4),
                        "snippet": "",  # Qdrant wrapper doesn't return snippets
                        "source": "qdrant",
                    })
                except ValueError:
                    continue
        
        return results
        
    except subprocess.TimeoutExpired:
        logger.error("Qdrant search timed out")
        return []
    except FileNotFoundError:
        logger.error(f"Qdrant search script not found: {search_script}")
        return []
    except Exception as e:
        logger.error(f"Error calling qdrant search: {e}")
        return []


class SearchServer:
    """MCP server for blended code search."""

    def __init__(self):
        """Initialize the search server."""
        if HAS_FASTMCP:
            self.mcp = FastMCP("search-server")
            # Register the search_code tool
            self.mcp.tool()(self.search_code)
        else:
            self.mcp = None
            logger.warning("FastMCP not available - running in compatibility mode")

    def search_code(
        self, 
        query: str, 
        top_k: int = 10, 
        include_code: bool = False,
        coco_weight: float = 0.7,
        qdrant_weight: float = 0.3,
    ) -> Dict[str, Any]:
        """
        Blend cocoindex and qdrant results for code search.

        Combines lexical search (cocoindex) with semantic search (qdrant)
        using weighted scoring: 70% cocoindex + 30% qdrant.

        Args:
            query: Search query
            top_k: Number of results to return
            include_code: Whether to include full code snippets
            coco_weight: Weight for cocoindex results (default 0.7)
            qdrant_weight: Weight for qdrant results (default 0.3)

        Returns:
            Dictionary with blended search results and metadata
        """
        logger.info(f"Blended search query: {query}")
        
        # Query both sources
        coco_results = call_cocoindex_search(query, top_k=top_k, include_code=include_code)
        qdrant_results = call_qdrant_search(query, top_k=top_k)
        
        # Log source availability
        coco_available = len(coco_results) > 0
        qdrant_available = len(qdrant_results) > 0
        
        if not coco_available and not qdrant_available:
            logger.warning("No results from either source")
            return {
                "results": [],
                "query": query,
                "sources_used": [],
                "total_results": 0,
                "note": "No results found from either cocoindex or qdrant",
            }
        
        if not coco_available:
            logger.warning("Cocoindex unavailable - using qdrant results only")
            results = qdrant_results
            sources_used = ["qdrant"]
        elif not qdrant_available:
            logger.warning("Qdrant unavailable - using cocoindex results only")
            results = coco_results
            sources_used = ["cocoindex"]
        else:
            # Blend results
            results = blend_scores(
                coco_results,
                qdrant_results,
                cocoindex_weight=coco_weight,
                qdrant_weight=qdrant_weight,
                top_k=top_k,
            )
            sources_used = ["cocoindex", "qdrant"]
        
        return {
            "results": results[:top_k],
            "query": query,
            "sources_used": sources_used,
            "total_results": len(results),
            "coco_weight": coco_weight,
            "qdrant_weight": qdrant_weight,
        }

    def run(self, host: str = "localhost", port: int = 8000) -> None:
        """
        Run the MCP server.

        Args:
            host: Server host
            port: Server port
        """
        if self.mcp:
            logger.info(f"Starting blended search server on {host}:{port}")
            self.mcp.run(host=host, port=port)
        else:
            logger.error("FastMCP not available - cannot start server")


if __name__ == "__main__":
    # Configure logging
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s - %(name)s - %(levelname)s - %(message)s"
    )
    
    server = SearchServer()
    server.run()
