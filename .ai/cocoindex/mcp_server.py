"""CocoIndex MCP server for semantic code search.

Provides search_code, search_symbol, get_code, get_file_chunks, find_similar_to,
and get_project_structure tools for AI agents.
"""

import json
import logging
import os
import re

import yaml
from dotenv import load_dotenv
from mcp.server.fastmcp import FastMCP
from psycopg.rows import dict_row
from psycopg_pool import ConnectionPool

load_dotenv(os.path.join(os.path.dirname(__file__), ".env"))

from main import DATABASE_URL, EMBED_MODEL, PG_SCHEMA_NAME, TABLE_NAME

logger = logging.getLogger(__name__)


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


# Shared chunk_id parser — used by get_code and find_similar_to.
# Format: {filename}#L{start}-L{end}
_CHUNK_ID_RE = re.compile(r"^(?P<filename>.+)#L(?P<start>\d+)-L(?P<end>\d+)$")


def _parse_chunk_id(chunk_id: str) -> tuple[str, int, int] | None:
    m = _CHUNK_ID_RE.match(chunk_id)
    if not m:
        return None
    return m.group("filename"), int(m.group("start")), int(m.group("end"))


def _deserialize_uses(uses_value) -> list | None:
    """Deserialize uses field: handles both jsonb (already a list) and text (JSON string)."""
    if uses_value is None:
        return None
    if isinstance(uses_value, (list, dict)):
        return uses_value
    try:
        return json.loads(uses_value)
    except (ValueError, TypeError):
        return None


@mcp.tool(
    description="CALL THIS FIRST before writing, modifying, or explaining any code. "
    "Blended semantic search over PHP, Vue, and TypeScript source. "
    "Returns snippets + chunk_ids. After search: "
    "use get_code(chunk_id) to read full bodies, "
    "get_file_chunks(filename) to browse a file's structure, "
    "find_similar_to(chunk_id) for lateral discovery from a known chunk. "
    "Never use Read on an indexed source file when you have a chunk_id. "
    "Filter by layer_type: service, controller, job, model, graphql, console, "
    "event, listener, notification, observer, provider. "
    "Filter by chunk_kind: method, class, trait, interface, function."
)
def search_code(
    query: str,
    top_k: int = 10,
    include_code: bool = False,
    min_score: float = 0.3,
    layer_type: str | None = None,
    chunk_kind: str | None = None,
) -> list[dict]:
    """Search source code semantically. Returns matching code chunks ranked by relevance."""
    query_vector = embed_query(query)
    with get_pool().connection() as conn:
        with conn.cursor(row_factory=dict_row) as cur:
            cur.execute("SET LOCAL hnsw.ef_search = 100")
            cur.execute(
                f"""
                SELECT filename, start_line, end_line, code,
                       layer_type, class_name, symbol,
                       chunk_kind, doc_summary, uses,
                       embedding <=> %s::vector AS distance
                FROM {FULL_TABLE}
                WHERE (%s::text IS NULL OR layer_type = %s)
                  AND (%s::text IS NULL OR chunk_kind = %s)
                ORDER BY distance
                LIMIT %s
                """,
                (query_vector, layer_type, layer_type, chunk_kind, chunk_kind, top_k),
            )
            results = []
            for row in cur.fetchall():
                score = round(1.0 - row["distance"], 4)
                if score < min_score:
                    continue
                entry = {
                    "chunk_id":    f"{row['filename']}#L{row['start_line']}-L{row['end_line']}",
                    "filename":    row["filename"],
                    "location":    f"L{row['start_line']}-L{row['end_line']}",
                    "snippet":     row["code"][:200],
                    "score":       score,
                    "layer_type":  row["layer_type"],
                    "class_name":  row["class_name"],
                    "symbol":      row["symbol"],
                    "chunk_kind":  row["chunk_kind"],
                    "doc_summary": row["doc_summary"],
                    "uses":        _deserialize_uses(row["uses"]),
                    "source":      "cocoindex",
                }
                if include_code:
                    entry["code"] = row["code"]
                results.append(entry)
            return results


@mcp.tool(
    description="Precise symbol lookup by class or method name — CocoIndex only, no semantic scoring. "
    "Always returns full code bodies. Faster than search_code when you know a name. "
    "After: use get_code(chunk_id) to refetch selectively, find_similar_to(chunk_id) "
    "to discover related implementations. "
    "Filter by layer_type or chunk_kind for narrower results."
)
def search_symbol(
    symbol: str,
    top_k: int = 20,
    layer_type: str | None = None,
    chunk_kind: str | None = None,
) -> list[dict]:
    """Look up code chunks by symbol or class name substring."""
    with get_pool().connection() as conn:
        with conn.cursor(row_factory=dict_row) as cur:
            cur.execute(
                f"""
                SELECT filename, start_line, end_line, code,
                       layer_type, class_name, symbol,
                       chunk_kind, doc_summary, uses
                FROM {FULL_TABLE}
                WHERE (
                    symbol ILIKE %s
                    OR class_name ILIKE %s
                )
                AND (%s::text IS NULL OR layer_type = %s)
                AND (%s::text IS NULL OR chunk_kind = %s)
                ORDER BY
                    CASE WHEN symbol ILIKE %s THEN 0 ELSE 1 END,
                    filename
                LIMIT %s
                """,
                (
                    f"%{symbol}%", f"%{symbol}%",
                    layer_type, layer_type,
                    chunk_kind, chunk_kind,
                    f"%{symbol}%",
                    top_k,
                ),
            )
            results = []
            for row in cur.fetchall():
                results.append({
                    "chunk_id":    f"{row['filename']}#L{row['start_line']}-L{row['end_line']}",
                    "filename":    row["filename"],
                    "location":    f"L{row['start_line']}-L{row['end_line']}",
                    "code":        row["code"],
                    "layer_type":  row["layer_type"],
                    "class_name":  row["class_name"],
                    "symbol":      row["symbol"],
                    "chunk_kind":  row["chunk_kind"],
                    "doc_summary": row["doc_summary"],
                    "uses":        _deserialize_uses(row["uses"]),
                    "source":      "cocoindex",
                })
            return results


@mcp.tool(
    description="Fetch the full code body for a single chunk_id returned by search_code or "
    "search_symbol. Use AFTER search to pull implementations one at a time. "
    "Never use Read on a source file when you have a chunk_id. "
    "Cheap, precise, no embedding cost. "
    "Returns error:None on success, error:string on failure."
)
def get_code(chunk_id: str) -> dict:
    logger.info(f"get_code: {chunk_id}")
    parsed = _parse_chunk_id(chunk_id)
    if parsed is None:
        return {"error": f"malformed chunk_id: {chunk_id[:200]}"}
    filename, start_line, end_line = parsed
    with get_pool().connection() as conn:
        with conn.cursor(row_factory=dict_row) as cur:
            cur.execute(
                f"SELECT code, layer_type, class_name, symbol, chunk_kind, doc_summary, uses "
                f"FROM {FULL_TABLE} "
                f"WHERE filename = %s AND start_line = %s AND end_line = %s LIMIT 2",
                (filename, start_line, end_line),
            )
            rows = cur.fetchall()
            if not rows:
                return {"error": f"chunk not found: {chunk_id[:200]}"}
            if len(rows) > 1:
                logger.error(f"ambiguous chunk_id: {chunk_id}")
                return {"error": f"ambiguous chunk_id — reindex may be in flight: {chunk_id[:200]}"}
            r = rows[0]
            return {
                "error":       None,
                "chunk_id":    chunk_id,
                "filename":    filename,
                "location":    f"L{start_line}-L{end_line}",
                "code":        r["code"],
                "layer_type":  r["layer_type"],
                "class_name":  r["class_name"],
                "symbol":      r["symbol"],
                "chunk_kind":  r["chunk_kind"],
                "doc_summary": r["doc_summary"],
                "uses":        _deserialize_uses(r["uses"]),
            }


@mcp.tool(
    description="List all chunk_ids and their locations for a given file. "
    "Use when you have a filename from search results and want to browse the file's structure "
    "before fetching bodies with get_code. "
    "Filter by chunk_kind (method, class, trait, interface, function) to narrow results. "
    "No code bodies returned — metadata only. Use get_code for bodies."
)
def get_file_chunks(
    filename: str,
    chunk_kind: str | None = None,
) -> dict:
    logger.info(f"get_file_chunks: {filename} chunk_kind={chunk_kind}")
    with get_pool().connection() as conn:
        with conn.cursor(row_factory=dict_row) as cur:
            cur.execute(
                f"SELECT start_line, end_line, symbol, chunk_kind, doc_summary "
                f"FROM {FULL_TABLE} "
                f"WHERE filename = %s "
                f"  AND (%s::text IS NULL OR chunk_kind = %s) "
                f"ORDER BY start_line",
                (filename, chunk_kind, chunk_kind),
            )
            rows = cur.fetchall()
            if not rows:
                cur.execute(
                    f"SELECT DISTINCT filename FROM {FULL_TABLE} "
                    f"WHERE filename LIKE %s LIMIT 5",
                    (f"%{filename.split('/')[-1]}%",),
                )
                candidates = [r["filename"] for r in cur.fetchall()]
                return {
                    "error":       f"no chunks found for: {filename}",
                    "suggestions": candidates,
                    "chunks":      [],
                    "chunk_count": 0,
                }
            return {
                "error":       None,
                "filename":    filename,
                "chunk_count": len(rows),
                "chunks": [
                    {
                        "chunk_id":    f"{filename}#L{r['start_line']}-L{r['end_line']}",
                        "location":    f"L{r['start_line']}-L{r['end_line']}",
                        "symbol":      r["symbol"],
                        "chunk_kind":  r["chunk_kind"],
                        "doc_summary": r["doc_summary"],
                    }
                    for r in rows
                ],
            }


@mcp.tool(
    description="Find chunks semantically similar to a chunk_id you already have. "
    "Lateral discovery — use when you've found one relevant chunk and need related ones "
    "without composing a new query. Returns chunk_ids + snippets, no code bodies. "
    "Filter by layer_type to scope to services, controllers, etc. "
    "Default min_score=0.5; lower it only if you expect sparse results. "
    "Don't use as a substitute for search_code when you have a clear query."
)
def find_similar_to(
    chunk_id: str,
    top_k: int = 5,
    min_score: float = 0.5,
    layer_type: str | None = None,
) -> dict:
    top_k = min(top_k, 20)
    logger.info(f"find_similar_to: {chunk_id}")
    parsed = _parse_chunk_id(chunk_id)
    if parsed is None:
        return {"error": f"malformed chunk_id: {chunk_id[:200]}", "results": []}
    filename, start_line, end_line = parsed

    with get_pool().connection() as conn:
        with conn.cursor(row_factory=dict_row) as cur:
            cur.execute(
                f"SELECT embedding, symbol, class_name, layer_type AS anchor_layer, "
                f"       chunk_kind, doc_summary "
                f"FROM {FULL_TABLE} "
                f"WHERE filename = %s AND start_line = %s AND end_line = %s LIMIT 1",
                (filename, start_line, end_line),
            )
            anchor_row = cur.fetchone()
            if not anchor_row:
                return {"error": f"chunk not found: {chunk_id[:200]}", "results": []}

            anchor_embedding = anchor_row["embedding"]
            anchor_meta = {
                "chunk_id":    chunk_id,
                "symbol":      anchor_row["symbol"],
                "class_name":  anchor_row["class_name"],
                "layer_type":  anchor_row["anchor_layer"],
                "chunk_kind":  anchor_row["chunk_kind"],
                "doc_summary": anchor_row["doc_summary"],
            }

            cur.execute(
                f"SELECT filename, start_line, end_line, code, layer_type, class_name, symbol, "
                f"       chunk_kind, doc_summary, "
                f"       embedding <=> %s::vector AS distance "
                f"FROM {FULL_TABLE} "
                f"WHERE NOT (filename = %s AND start_line = %s AND end_line = %s) "
                f"  AND (%s::text IS NULL OR layer_type = %s) "
                f"ORDER BY distance LIMIT %s",
                (anchor_embedding, filename, start_line, end_line,
                 layer_type, layer_type, top_k * 3),
            )
            results = []
            for r in cur.fetchall():
                score = round(1.0 - r["distance"], 4)
                if score < min_score:
                    continue
                results.append({
                    "chunk_id":    f"{r['filename']}#L{r['start_line']}-L{r['end_line']}",
                    "filename":    r["filename"],
                    "location":    f"L{r['start_line']}-L{r['end_line']}",
                    "snippet":     r["code"][:200],
                    "score":       score,
                    "layer_type":  r["layer_type"],
                    "class_name":  r["class_name"],
                    "symbol":      r["symbol"],
                    "chunk_kind":  r["chunk_kind"],
                    "doc_summary": r["doc_summary"],
                    "source":      "cocoindex",
                })
                if len(results) >= top_k:
                    break

            return {
                "error":   None,
                "anchor":  anchor_meta,
                "results": results,
            }


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
        connector = "└── " if is_last else "├── "
        lines.append(f"{prefix}{connector}{name}")
        if tree[name]:
            extension = "    " if is_last else "│   "
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
