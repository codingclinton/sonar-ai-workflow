import { QdrantClient } from '@qdrant/js-client-rest';
import { createHash } from 'crypto';
import { readFile } from 'fs/promises';
import { resolve, dirname } from 'path';
import { fileURLToPath } from 'url';
import axios from 'axios';
import { load as loadYaml } from 'js-yaml';
import pg from 'pg';

const { Pool } = pg;

const __dirname = dirname(fileURLToPath(import.meta.url));

const indexerConfig = loadYaml(await readFile(resolve(__dirname, '../../indexer.yaml'), 'utf8'));
const qdrantConfig = indexerConfig.qdrant;
const SUMMARY_LAYERS = new Set(qdrantConfig.summary_layers);

const CONFIG = {
  qdrantUrl: 'http://localhost:6333',
  ollamaUrl: qdrantConfig.ollama_url ?? 'http://localhost:11434',
  ollamaEmbedModel: qdrantConfig.ollama_embed_model ?? 'nomic-embed-text',
  ollamaGenerateModel: qdrantConfig.ollama_generation_model ?? 'llama3.2',
  concurrency: qdrantConfig.concurrency ?? 8,
  upsertBatchSize: qdrantConfig.upsert_batch_size ?? 50,
  collection: 'sonar_app',
  vectorSize: 768,
  pgUrl: process.env.COCOINDEX_DATABASE_URL ?? 'postgresql://cocoindex:cocoindex@localhost:5433/cocoindex',
};

const qdrant = new QdrantClient({ url: CONFIG.qdrantUrl });

class Semaphore {
  constructor(limit) {
    this.limit = limit;
    this.active = 0;
    this.queue = [];
  }
  acquire() {
    return new Promise(resolve => {
      if (this.active < this.limit) { this.active++; resolve(); }
      else { this.queue.push(resolve); }
    });
  }
  release() {
    this.active--;
    if (this.queue.length > 0) { this.active++; this.queue.shift()(); }
  }
}

function chunkToId(filename, startLine, endLine) {
  const key = `${filename}#L${startLine}-L${endLine}`;
  const hash = createHash('sha256').update(key).digest('hex');
  return parseInt(hash.slice(0, 12), 16) % Number.MAX_SAFE_INTEGER;
}

function chunkHash(filename, startLine, endLine) {
  return createHash('sha256')
    .update(`${filename}:${startLine}:${endLine}`)
    .digest('hex')
    .slice(0, 16);
}

async function ensureCollection() {
  const { collections } = await qdrant.getCollections();
  if (!collections.some(c => c.name === CONFIG.collection)) {
    await qdrant.createCollection(CONFIG.collection, {
      vectors: { size: CONFIG.vectorSize, distance: 'Cosine' },
    });
    console.log(`Created collection: ${CONFIG.collection}`);
  }
}

async function loadExistingPoints() {
  const map = new Map();
  let offset = null;
  do {
    const result = await qdrant.scroll(CONFIG.collection, {
      with_payload: ['chunk_id', 'hash'],
      limit: 1000,
      offset,
    });
    for (const point of result.points) {
      if (point.payload.chunk_id) {
        map.set(point.payload.chunk_id, { id: point.id, hash: point.payload.hash });
      }
    }
    offset = result.next_page_offset ?? null;
  } while (offset != null);
  return map;
}

async function embed(text) {
  const { data } = await axios.post(`${CONFIG.ollamaUrl}/api/embeddings`, {
    model: CONFIG.ollamaEmbedModel,
    prompt: text,
  });
  return data.embedding;
}

async function generateArchitecturalSummary(code, layerType, className) {
  const preview = code.slice(0, 3000);
  const name = className ?? 'this chunk';
  const prompt = `Write a 1-2 sentence architectural summary of the Laravel ${layerType} "${name}". Describe its responsibilities and what it handles in plain English. Output only the summary sentence(s), nothing else.\n\n${preview}`;
  const { data } = await axios.post(`${CONFIG.ollamaUrl}/api/generate`, {
    model: CONFIG.ollamaGenerateModel,
    prompt,
    stream: false,
  });
  return data.response.trim();
}

async function fetchChunksFromPostgres() {
  const pool = new Pool({ connectionString: CONFIG.pgUrl });
  try {
    const { rows } = await pool.query(
      `SELECT filename, start_line, end_line, code, class_name, namespace, layer_type, chunk_kind
       FROM "cocoindex"."code_embeddings"
       ORDER BY filename, start_line`
    );
    return rows;
  } finally {
    await pool.end();
  }
}

async function main() {
  await ensureCollection();

  console.log('Fetching chunks from CocoIndex Postgres...');
  const chunks = await fetchChunksFromPostgres();
  console.log(`Loaded ${chunks.length} chunks from Postgres.`);

  const existing = await loadExistingPoints();
  const currentChunkIds = new Set();
  const total = chunks.length;

  let processed = 0, indexed = 0, skipped = 0, deleted = 0;
  const startTime = Date.now();

  function formatEta(seconds) {
    if (!isFinite(seconds)) return '--:--';
    const h = Math.floor(seconds / 3600);
    const m = Math.floor((seconds % 3600) / 60);
    const s = Math.floor(seconds % 60);
    return h > 0
      ? `${h}:${String(m).padStart(2, '0')}:${String(s).padStart(2, '0')}`
      : `${m}:${String(s).padStart(2, '0')}`;
  }

  function renderProgress() {
    const pct = Math.floor((processed / total) * 100);
    const filled = Math.floor(pct / 2);
    const bar = '█'.repeat(filled) + '░'.repeat(50 - filled);
    const elapsed = (Date.now() - startTime) / 1000;
    const rate = processed / Math.max(elapsed, 0.001);
    const eta = formatEta((total - processed) / rate);
    process.stdout.write(`\r[${bar}] ${pct}% (${processed}/${total}) indexed=${indexed} skipped=${skipped} eta=${eta}`);
  }

  const sem = new Semaphore(CONFIG.concurrency);
  const pointBuffer = [];

  async function flushBuffer(force = false) {
    if (pointBuffer.length >= CONFIG.upsertBatchSize || (force && pointBuffer.length > 0)) {
      const batch = pointBuffer.splice(0, pointBuffer.length);
      await qdrant.upsert(CONFIG.collection, { points: batch });
    }
  }

  await Promise.all(chunks.map(async (row) => {
    await sem.acquire();
    try {
      const chunkId = `${row.filename}#L${row.start_line}-L${row.end_line}`;
      currentChunkIds.add(chunkId);

      const hash = chunkHash(row.filename, row.start_line, row.end_line);
      const existingEntry = existing.get(chunkId);

      if (existingEntry?.hash === hash) {
        skipped++;
        processed++;
        renderProgress();
        return;
      }

      const summary = row.code.slice(0, 500);

      let vector;
      try {
        vector = await embed(summary);
      } catch (err) {
        process.stdout.write(`\n  SKIP (embed error) ${chunkId}: ${err.response?.data?.error ?? err.message}\n`);
        processed++;
        renderProgress();
        return;
      }
      if (!vector || vector.length !== CONFIG.vectorSize) {
        process.stdout.write(`\n  SKIP (bad vector) ${chunkId}: length=${vector?.length ?? 0} expected=${CONFIG.vectorSize}\n`);
        processed++;
        renderProgress();
        return;
      }

      pointBuffer.push({
        id: chunkToId(row.filename, row.start_line, row.end_line),
        vector,
        payload: {
          chunk_id:   chunkId,
          path:       row.filename,
          start_line: row.start_line,
          end_line:   row.end_line,
          summary,
          class_name: row.class_name ?? null,
          namespace:  row.namespace ?? null,
          layer_type: row.layer_type ?? null,
          chunk_kind: row.chunk_kind ?? null,
          hash,
        },
      });
      try {
        await flushBuffer();
      } catch (err) {
        process.stdout.write(`\n  SKIP (upsert error) ${chunkId}: ${err.message}\n`);
        processed++;
        renderProgress();
        return;
      }

      indexed++;
      processed++;
      renderProgress();
    } finally {
      sem.release();
    }
  }));

  try {
    await flushBuffer(true);
  } catch (err) {
    const detail = err.response?.data ? JSON.stringify(err.response.data) : err.message;
    console.error(`\n\x1b[31m✘ Final upsert flush failed: ${detail}\x1b[0m`);
    throw err;
  }

  // Delete Qdrant points for chunks no longer in Postgres
  const toDelete = [];
  for (const [chunkId, entry] of existing) {
    if (!currentChunkIds.has(chunkId)) toDelete.push(entry.id);
  }
  if (toDelete.length > 0) {
    try {
      await qdrant.delete(CONFIG.collection, { points: toDelete });
      deleted = toDelete.length;
    } catch (err) {
      const detail = err.response?.data ? JSON.stringify(err.response.data) : err.message;
      console.error(`\n\x1b[31m✘ Delete stale points failed: ${detail}\x1b[0m`);
      throw err;
    }
  }

  console.log(`\nDone. indexed=${indexed} skipped=${skipped} deleted=${deleted}`);
}

main().catch(err => {
  const status = err.response?.status ?? '';
  const detail = err.response?.data ? JSON.stringify(err.response.data, null, 2) : '';
  console.error(`\x1b[31m\x1b[1m✘ Fatal: ${err.message}${status ? ` [HTTP ${status}]` : ''}\x1b[0m`);
  if (detail) console.error(detail);
  if (err.stack) console.error(err.stack);
  process.exit(1);
});
