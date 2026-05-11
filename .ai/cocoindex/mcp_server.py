"""CocoIndex MCP server for semantic code search.

Provides search_code and get_project_structure tools for AI agents.
"""

import os

import yaml
from dotenv import load_dotenv
from mcp.server.fastmcp import FastMCP
from psycopg_pool import ConnectionPool

load_dotenv(os.path.join(os.path.dirname(__file__), ".env"))

from main import DATABASE_URL, EMBED_MODEL, PG_SCHEMA_NAME, TABLE_NAME


def load_config():
    config_path = os.path.join(os.path.dirname(__file__), "cocoindex.yaml")
    with open(config_path) as f:
        return yaml.safe_load(f)


CONFIG = load_config()

# Lazy-loaded embedder and connection pool
_embedder = None
_pool = None

FULL_TABLE = f'"{PG_SCHEMA_NAME}"."{TABLE_NAME}"'

mcp = FastMCP(f"{CONFIG['project']}_cocoindex")


def get_embedder():
    global _embedder
    if _embedder is None:
        from sentence_transformers import SentenceTransformer
        _embedder = SentenceTransformer(EMBED_MODEL)
    return _embedder


def get_pool() -> ConnectionPool:
    global _pool
    if _pool is None:
        _pool = ConnectionPool(DATABASE_URL)
    return _pool


def embed_query(query: str) -> list[float]:
    model = get_embedder()
    vector = model.encode(query, normalize_embeddings=True)
    return vector.tolist()


@mcp.tool(
    description="Semantic search over project source code. "
    "Use this to understand how features work, find implementations, or explore architecture. "
    "Returns snippets by default — set include_code=True for full chunks. "
    "Filter by Laravel layer with layer_type (service, controller, job, model, graphql, etc)."
)
def search_code(
    query: str,
    top_k: int = 10,
    include_code: bool = False,
    min_score: float = 0.3,
    layer_type: str | None = None,
) -> list[dict]:
    """Search source code semantically. Returns matching code chunks ranked by relevance."""
    query_vector = embed_query(query)
    with get_pool().connection() as conn:
        with conn.cursor() as cur:
            cur.execute("SET LOCAL hnsw.ef_search = 100")
            cur.execute(
                f"""
                SELECT filename, start_line, end_line, code,
                       layer_type, class_name, symbol,
                       embedding <=> %s::vector AS distance
                FROM {FULL_TABLE}
                WHERE (%s::text IS NULL OR layer_type = %s)
                ORDER BY distance
                LIMIT %s
                """,
                (query_vector, layer_type, layer_type, top_k),
            )
            results = []
            for row in cur.fetchall():
                score = round(1.0 - row[7], 4)
                if score < min_score:
                    continue
                entry = {
                    "filename": row[0],
                    "location": f"L{row[1]}-L{row[2]}",
                    "snippet": row[3][:200],
                    "score": score,
                    "layer_type": row[4],
                    "class_name": row[5],
                    "symbol": row[6],
                    "source": "cocoindex",
                }
                if include_code:
                    entry["code"] = row[3]
                results.append(entry)
            return results


@mcp.tool(
    description="Exact symbol lookup by class name or method name. "
    "Use when you know (or partially know) a class or method name and want its implementation. "
    "Matches against 'ClassName::methodName' symbols and class names using substring search. "
    "Examples: 'BillingService', 'calculateTax', 'BillingService::calculateTax'. "
    "Always returns code. Much faster and more precise than search_code for known names."
)
def search_symbol(
    symbol: str,
    top_k: int = 20,
    layer_type: str | None = None,
) -> list[dict]:
    """Look up code chunks by symbol or class name substring."""
    with get_pool().connection() as conn:
        with conn.cursor() as cur:
            cur.execute(
                f"""
                SELECT filename, start_line, end_line, code,
                       layer_type, class_name, symbol
                FROM {FULL_TABLE}
                WHERE (
                    symbol ILIKE %s
                    OR class_name ILIKE %s
                )
                AND (%s::text IS NULL OR layer_type = %s)
                ORDER BY
                    CASE WHEN symbol ILIKE %s THEN 0 ELSE 1 END,
                    filename
                LIMIT %s
                """,
                (
                    f"%{symbol}%", f"%{symbol}%",
                    layer_type, layer_type,
                    f"%{symbol}%",
                    top_k,
                ),
            )
            results = []
            for row in cur.fetchall():
                results.append({
                    "filename": row[0],
                    "location": f"L{row[1]}-L{row[2]}",
                    "code": row[3],
                    "layer_type": row[4],
                    "class_name": row[5],
                    "symbol": row[6],
                    "source": "cocoindex",
                })
            return results


def _build_tree(filenames: list[str]) -> dict:
    tree: dict = {}
    for path in filenames:
        parts = path.strip("/").split("/")
        node = tree
        for part in parts:
            node = node.setdefault(part, {})
    return tree


def _render_tree(tree: dict, prefix: str = "") -> list[str]:
    lines = []
    entries = sorted(tree.keys())
    for i, name in enumerate(entries):
        is_last = i == len(entries) - 1
        connector = "\u2514\u2500\u2500 " if is_last else "\u251c\u2500\u2500 "
        lines.append(f"{prefix}{connector}{name}")
        if tree[name]:
            extension = "    " if is_last else "\u2502   "
            lines.extend(_render_tree(tree[name], prefix + extension))
    return lines


@mcp.tool(
    description="Get the file structure of the indexed project. "
    "Use this to understand project layout before searching for specific code."
)
def get_project_structure() -> str:
    """Return a tree-formatted view of all indexed source files."""
    with get_pool().connection() as conn:
        with conn.cursor() as cur:
            cur.execute(
                f"SELECT DISTINCT filename FROM {FULL_TABLE} ORDER BY filename"
            )
            filenames = [row[0] for row in cur.fetchall()]
    if not filenames:
        return "(no files indexed)"
    tree = _build_tree(filenames)
    return "\n".join(_render_tree(tree))


if __name__ == "__main__":
    mcp.run(transport="stdio")
