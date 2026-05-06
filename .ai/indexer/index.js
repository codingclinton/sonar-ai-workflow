import { QdrantClient } from '@qdrant/js-client-rest';
import { createHash } from 'crypto';
import { readFile } from 'fs/promises';
import { resolve, relative, dirname } from 'path';
import { fileURLToPath } from 'url';
import glob from 'fast-glob';
import axios from 'axios';

const __dirname = dirname(fileURLToPath(import.meta.url));

const CONFIG = {
  qdrantUrl: 'http://localhost:6333',
  ollamaUrl: 'http://localhost:11434',
  ollamaModel: 'nomic-embed-text',
  collection: 'sonar_php_app',
  vectorSize: 768,
  sourceGlob: '../../sonar/app/**/*.php',
  contentLimit: 2000,
  projectRoot: resolve(__dirname, '../..'),
};

const qdrant = new QdrantClient({ url: CONFIG.qdrantUrl });

function pathToId(filePath) {
  const hash = createHash('sha256').update(filePath).digest('hex');
  return parseInt(hash.slice(0, 12), 16) % Number.MAX_SAFE_INTEGER;
}

function contentHash(content) {
  return createHash('sha256').update(content).digest('hex').slice(0, 16);
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
      with_payload: ['path', 'hash'],
      limit: 1000,
      offset,
    });
    for (const point of result.points) {
      map.set(point.payload.path, { id: point.id, hash: point.payload.hash });
    }
    offset = result.next_page_offset ?? null;
  } while (offset != null);
  return map;
}

async function embed(text) {
  const { data } = await axios.post(`${CONFIG.ollamaUrl}/api/embeddings`, {
    model: CONFIG.ollamaModel,
    prompt: text,
  });
  return data.embedding;
}

async function main() {
  await ensureCollection();

  const existing = await loadExistingPoints();
  const files = await glob(CONFIG.sourceGlob, { cwd: __dirname, absolute: true });
  const currentPaths = new Set();
  const total = files.length;

  let processed = 0, indexed = 0, skipped = 0, deleted = 0;

  function renderProgress() {
    const pct = Math.floor((processed / total) * 100);
    const filled = Math.floor(pct / 2);
    const bar = '█'.repeat(filled) + '░'.repeat(50 - filled);
    process.stdout.write(`\r[${bar}] ${pct}% (${processed}/${total}) indexed=${indexed} skipped=${skipped}`);
  }

  for (const absPath of files) {
    const relPath = relative(CONFIG.projectRoot, absPath);
    currentPaths.add(relPath);

    const content = await readFile(absPath, 'utf8');
    const hash = contentHash(content);
    const existingEntry = existing.get(relPath);

    if (existingEntry?.hash === hash) {
      skipped++;
      processed++;
      renderProgress();
      continue;
    }

    const truncated = content.slice(0, CONFIG.contentLimit);
    let vector;
    try {
      vector = await embed(truncated);
    } catch (err) {
      process.stdout.write(`\n  SKIP (embed error) ${relPath}: ${err.response?.data?.error ?? err.message}\n`);
      processed++;
      renderProgress();
      continue;
    }

    const id = pathToId(relPath);
    try {
      await qdrant.upsert(CONFIG.collection, {
        points: [{ id, vector, payload: { path: relPath, hash, content: truncated } }],
      });
    } catch (err) {
      process.stdout.write(`\n  SKIP (upsert error) ${relPath}: ${err.message} [vector.length=${vector.length}]\n`);
      processed++;
      renderProgress();
      continue;
    }

    indexed++;
    processed++;
    renderProgress();
  }

  const toDelete = [];
  for (const [path, entry] of existing) {
    if (!currentPaths.has(path)) toDelete.push(entry.id);
  }
  if (toDelete.length > 0) {
    await qdrant.delete(CONFIG.collection, { points: toDelete });
    deleted = toDelete.length;
  }

  console.log(`\nDone. indexed=${indexed} skipped=${skipped} deleted=${deleted}`);
}

main().catch(err => {
  console.error(err.message);
  if (err.response?.data) console.error(err.response.data);
  process.exit(1);
});
