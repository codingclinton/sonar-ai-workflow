from __future__ import annotations

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


def extract_php_metadata(text: str, filepath: str) -> dict:
    ns_match = re.search(r'^namespace\s+([\w\\]+);', text, re.MULTILINE)
    class_match = re.search(r'\bclass\s+(\w+)', text)
    return {
        'namespace': ns_match.group(1) if ns_match else None,
        'class_name': class_match.group(1) if class_match else None,
        'layer_type': detect_laravel_layer(filepath),
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


app = coco.App(
    coco.AppConfig(name="CodeEmbedding"),
    app_main,
    sourcedirs=[
        pathlib.Path(__file__).parent.parent.parent.resolve() / d
        for d in CONFIG["cocoindex"]["source_dirs"]
    ],
)
