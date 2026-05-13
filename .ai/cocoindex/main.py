from __future__ import annotations

import json
import os
import pathlib
import re
import yaml
from dataclasses import dataclass
from typing import Annotated, AsyncIterator
from dotenv import load_dotenv
load_dotenv(os.path.join(os.path.dirname(__file__), ".env"))

import asyncpg
from numpy.typing import NDArray

import cocoindex as coco
from cocoindex.connectors import localfs, postgres
from cocoindex.ops.sentence_transformers import SentenceTransformerEmbedder
from cocoindex.ops.text import RecursiveSplitter, detect_code_language
from cocoindex.resources.chunk import Chunk
from cocoindex.resources.file import FileLike, PatternFilePathMatcher
from cocoindex.resources.id import IdGenerator

DATABASE_URL = os.getenv(
    "COCOINDEX_DATABASE_URL",
    "postgresql://cocoindex:cocoindex@localhost:5433/cocoindex",
)
TABLE_NAME = "code_embeddings"
PG_SCHEMA_NAME = "cocoindex"
EMBED_MODEL = "krlvi/sentence-t5-base-nlpl-code_search_net"


def load_config() -> dict:
    config_path = os.path.join(os.path.dirname(__file__), "..", "indexer.yaml")
    with open(config_path) as f:
        return yaml.safe_load(f)


CONFIG = load_config()

LAYER_PATTERNS = [
    (r'/ui/app/', 'frontend'),
    (r'/Services/', 'service'),
    (r'/Http/Controllers/', 'controller'),
    (r'/Jobs/', 'job'),
    (r'/Http/Requests/', 'request'),
    (r'/GraphQL/', 'graphql'),
    (r'/Mutations/', 'graphql'),
    (r'/Console/', 'console'),
    (r'/Events/', 'event'),
    (r'/Listeners/', 'listener'),
    (r'/Notifications/', 'notification'),
    (r'/Observers/', 'observer'),
    (r'/Providers/', 'provider'),
    (r'/Models/', 'model'),
    (r'/app/[^/]+\.php$', 'model'),
]


def detect_laravel_layer(filepath: str) -> str:
    for pattern, layer in LAYER_PATTERNS:
        if re.search(pattern, filepath, re.IGNORECASE):
            return layer
    return 'other'


# File-scope use statements: matches `use Foo\Bar;` and `use Foo\Bar as Alias;`
_USE_STMT_RE = re.compile(
    r'^use\s+([\w\\]+)(?:\s+as\s+\w+)?\s*;',
    re.MULTILINE,
)


def extract_php_metadata(text: str, filepath: str) -> dict:
    ns_match = re.search(r'^namespace\s+([\w\\]+);', text, re.MULTILINE)
    class_match = re.search(r'\bclass\s+(\w+)', text)
    use_targets = [m.group(1) for m in _USE_STMT_RE.finditer(text)]
    return {
        'namespace': ns_match.group(1) if ns_match else None,
        'class_name': class_match.group(1) if class_match else None,
        'layer_type': detect_laravel_layer(filepath),
        # JSON-serialized list of file-scope imports; same value for every chunk in the file
        'uses': json.dumps(use_targets) if use_targets else None,
    }


LAYER_CHUNK_PARAMS: dict[str, dict] = {
    # krlvi T5-base: 512-token window (~1800 chars). Keep all chunks under 1500 to avoid truncation.
    'service':      {'chunk_size': 1200, 'min_chunk_size': 200, 'chunk_overlap': 100},
    'controller':   {'chunk_size': 1200, 'min_chunk_size': 200, 'chunk_overlap': 100},
    'graphql':      {'chunk_size': 1200, 'min_chunk_size': 200, 'chunk_overlap': 100},
    'console':      {'chunk_size': 1200, 'min_chunk_size': 200, 'chunk_overlap': 100},
    'job':          {'chunk_size': 1500, 'min_chunk_size': 300, 'chunk_overlap': 0},
    'request':      {'chunk_size': 1500, 'min_chunk_size': 300, 'chunk_overlap': 0},
    'model':        {'chunk_size': 1500, 'min_chunk_size': 300, 'chunk_overlap': 0},
    'event':        {'chunk_size': 1500, 'min_chunk_size': 300, 'chunk_overlap': 0},
    'listener':     {'chunk_size': 1500, 'min_chunk_size': 300, 'chunk_overlap': 0},
    'notification': {'chunk_size': 1500, 'min_chunk_size': 300, 'chunk_overlap': 0},
    'observer':     {'chunk_size': 1500, 'min_chunk_size': 300, 'chunk_overlap': 0},
    'provider':     {'chunk_size': 1500, 'min_chunk_size': 300, 'chunk_overlap': 0},
    'other':        {'chunk_size': 800,  'min_chunk_size': 200, 'chunk_overlap': 200},
    'frontend':     {'chunk_size': 800,  'min_chunk_size': 200, 'chunk_overlap': 200},
}


def get_chunk_params(layer_type: str) -> dict:
    return LAYER_CHUNK_PARAMS.get(layer_type, LAYER_CHUNK_PARAMS['other'])


# chunk_kind: detect the primary PHP declaration type in a chunk.
# No tree-sitter available; using anchored line-start patterns rather than substring matching.
# Order matters: check class/trait/interface before method/function to avoid mislabelling
# a class body that also contains method declarations.
_CHUNK_KIND_PATTERNS: list[tuple[re.Pattern, str]] = [
    (re.compile(r'^\s*(?:abstract\s+|final\s+)?class\s+\w+', re.MULTILINE), 'class'),
    (re.compile(r'^\s*trait\s+\w+', re.MULTILINE), 'trait'),
    (re.compile(r'^\s*interface\s+\w+', re.MULTILINE), 'interface'),
    (re.compile(
        r'^\s*(?:public|protected|private)(?:\s+static)?\s+function\s+\w+',
        re.MULTILINE,
    ), 'method'),
    (re.compile(r'^\s*function\s+\w+', re.MULTILINE), 'function'),
]


def extract_chunk_kind(text: str) -> str | None:
    for pattern, kind in _CHUNK_KIND_PATTERNS:
        if pattern.search(text):
            return kind
    return None


# PHPDoc summary: first non-empty prose line from a /** ... */ block, stripped of * prefixes.
_PHPDOC_BLOCK_RE = re.compile(r'/\*\*(.+?)\*/', re.DOTALL)
_PHPDOC_LINE_RE = re.compile(r'^\s*\*?\s*(.*)', re.MULTILINE)
_PHPDOC_TAG_RE = re.compile(r'^@\w+')


def extract_doc_summary(text: str) -> str | None:
    block_m = _PHPDOC_BLOCK_RE.search(text)
    if not block_m:
        return None
    body = block_m.group(1)
    for line_m in _PHPDOC_LINE_RE.finditer(body):
        line = line_m.group(1).strip()
        if line and not _PHPDOC_TAG_RE.match(line):
            return line[:200]
    return None


_METHOD_NAME_RE = re.compile(
    r'(?:public|protected|private|static)\s+function\s+(\w+)',
    re.MULTILINE,
)


def extract_method_name_from_chunk(chunk_text: str) -> str | None:
    m = _METHOD_NAME_RE.search(chunk_text)
    return m.group(1) if m else None


PG_DB = coco.ContextKey[asyncpg.Pool]("code_embedding_db")
EMBEDDER = coco.ContextKey[SentenceTransformerEmbedder]("embedder", detect_change=True)

_splitter = RecursiveSplitter()


@dataclass
class CodeEmbedding:
    id: int
    filename: str
    code: str
    embedding: Annotated[NDArray, EMBEDDER]
    start_line: int
    end_line: int
    layer_type: str | None = None
    class_name: str | None = None
    namespace: str | None = None
    symbol: str | None = None
    chunk_kind: str | None = None
    doc_summary: str | None = None
    uses: str | None = None  # JSON string of file-scope use imports (same for all chunks in file)


@coco.lifespan
async def coco_lifespan(builder: coco.EnvironmentBuilder) -> AsyncIterator[None]:
    async with await asyncpg.create_pool(DATABASE_URL) as pool:
        builder.provide(PG_DB, pool)
        builder.provide(EMBEDDER, SentenceTransformerEmbedder(EMBED_MODEL))
        yield


@coco.fn
async def process_chunk(
    chunk: Chunk,
    filename: pathlib.PurePath,
    id_gen: IdGenerator,
    table: postgres.TableTarget[CodeEmbedding],
    metadata: dict,
) -> None:
    method = extract_method_name_from_chunk(chunk.text)
    symbol = f"{metadata['class_name']}::{method}" if method and metadata.get('class_name') else method
    embedding = await coco.use_context(EMBEDDER).embed(chunk.text)
    table.declare_row(
        row=CodeEmbedding(
            id=await id_gen.next_id(chunk.text),
            filename=str(filename),
            code=chunk.text,
            embedding=embedding,
            start_line=chunk.start.line,
            end_line=chunk.end.line,
            layer_type=metadata.get('layer_type'),
            class_name=metadata.get('class_name'),
            namespace=metadata.get('namespace'),
            symbol=symbol,
            chunk_kind=extract_chunk_kind(chunk.text),
            doc_summary=extract_doc_summary(chunk.text),
            uses=metadata.get('uses'),
        )
    )


@coco.fn(memo=True)
async def process_file(
    file: FileLike,
    table: postgres.TableTarget[CodeEmbedding],
) -> None:
    text = await file.read_text()
    filepath = str(file.file_path.path)
    metadata = extract_php_metadata(text, filepath)
    params = get_chunk_params(metadata['layer_type'])
    language = detect_code_language(filename=str(file.file_path.path.name))
    chunks = _splitter.split(
        text,
        chunk_size=params['chunk_size'],
        min_chunk_size=params['min_chunk_size'],
        chunk_overlap=params['chunk_overlap'],
        language=language,
    )
    id_gen = IdGenerator()
    await coco.map(process_chunk, chunks, file.file_path.path, id_gen, table, metadata)


@coco.fn
async def app_main(sourcedirs: list[pathlib.Path]) -> None:
    target_table = await postgres.mount_table_target(
        PG_DB,
        table_name=TABLE_NAME,
        table_schema=await postgres.TableSchema.from_class(
            CodeEmbedding,
            primary_key=["id"],
        ),
        pg_schema_name=PG_SCHEMA_NAME,
    )
    target_table.declare_vector_index(column="embedding")

    included = [f"**/{p}" for p in CONFIG["patterns"]["included"]]
    excluded = [f"**/{p}" for p in CONFIG["patterns"]["excluded"]] + ["**/.*"]


    all_files = []
    for sourcedir in sourcedirs:
        files = localfs.walk_dir(
            sourcedir,
            recursive=True,
            path_matcher=PatternFilePathMatcher(
                included_patterns=included,
                excluded_patterns=excluded,
            ),
        )
        async for key, item in files.items():
            # Prefix key with sourcedir name to make globally unique
            unique_key = f"{sourcedir.name}/{key}"
            all_files.append((unique_key, item))

    await coco.mount_each(process_file, all_files, target_table)


_source_root_env = os.getenv("COCOINDEX_SOURCE_ROOT")
_SOURCE_ROOT = (
    pathlib.Path(_source_root_env).resolve()
    if _source_root_env
    else pathlib.Path(__file__).parent.parent.parent.resolve()
)

app = coco.App(
    coco.AppConfig(name="CodeEmbedding"),
    app_main,
    sourcedirs=[_SOURCE_ROOT / d for d in CONFIG["cocoindex"]["source_dirs"]],
)
