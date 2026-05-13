import { QdrantClient } from '@qdrant/js-client-rest';
import { readFile } from 'fs/promises';
import { resolve, dirname } from 'path';
import { fileURLToPath } from 'url';
import axios from 'axios';
import { load as loadYaml } from 'js-yaml';

const __dirname = dirname(fileURLToPath(import.meta.url));
const indexerConfig = loadYaml(await readFile(resolve(__dirname, '../../indexer.yaml'), 'utf8'));
const qdrantConfig = indexerConfig.qdrant;

const CONFIG = {
  qdrantUrl: 'http://localhost:6333',
  ollamaUrl: qdrantConfig.ollama_url ?? 'http://localhost:11434',
  ollamaModel: qdrantConfig.ollama_embed_model ?? 'nomic-embed-text',
  collection: 'sonar_app',
  topK: 10,
};

const qdrant = new QdrantClient({ url: CONFIG.qdrantUrl });

async function embed(text) {
  const { data } = await axios.post(`${CONFIG.ollamaUrl}/api/embeddings`, {
    model: CONFIG.ollamaModel,
    prompt: text,
  });
  return data.embedding;
}

async function main() {
  const args = process.argv.slice(2);
  if (args.length === 0) {
    console.error('Usage: node retrieval/search.js "query" [--top-k 5] [--layer-type service]');
    process.exit(1);
  }

  const topKIdx = args.indexOf('--top-k');
  const topK = topKIdx !== -1 ? parseInt(args[topKIdx + 1]) : CONFIG.topK;

  const layerTypeIdx = args.indexOf('--layer-type');
  const layerType = layerTypeIdx !== -1 ? args[layerTypeIdx + 1] : null;

  const query = args.filter((_, i) => {
    if (topKIdx !== -1 && (i === topKIdx || i === topKIdx + 1)) return false;
    if (layerTypeIdx !== -1 && (i === layerTypeIdx || i === layerTypeIdx + 1)) return false;
    return true;
  }).join(' ');

  const vector = await embed(query);

  const searchParams = {
    vector,
    limit: topK,
    with_payload: true,
  };

  if (layerType) {
    searchParams.filter = {
      must: [{ key: 'layer_type', match: { value: layerType } }],
    };
  }

  const results = await qdrant.search(CONFIG.collection, searchParams);

  const output = results.map(({ payload, score }) => ({
    chunk_id:   payload.chunk_id ?? null,
    filename:   payload.path,
    location:   payload.start_line != null ? `L${payload.start_line}-L${payload.end_line}` : null,
    start_line: payload.start_line ?? null,
    end_line:   payload.end_line ?? null,
    score:      parseFloat(score.toFixed(4)),
    snippet:    payload.summary ?? '',
    class_name: payload.class_name ?? null,
    layer_type: payload.layer_type ?? null,
    source:     'qdrant',
  }));

  console.log(JSON.stringify(output));
}

main().catch(err => {
  console.error(err.message);
  if (err.response?.data) console.error(err.response.data);
  console.error(JSON.stringify(err, Object.getOwnPropertyNames(err), 2));
  process.exit(1);
});
