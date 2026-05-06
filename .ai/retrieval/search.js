import { QdrantClient } from '@qdrant/js-client-rest';
import axios from 'axios';

const CONFIG = {
  qdrantUrl: 'http://localhost:6333',
  ollamaUrl: 'http://localhost:11434',
  ollamaModel: 'nomic-embed-text',
  collection: 'sonar_php_app',
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
    console.error('Usage: node retrieval/search.js "query" [--top-k 5]');
    process.exit(1);
  }

  const topKIdx = args.indexOf('--top-k');
  const topK = topKIdx !== -1 ? parseInt(args[topKIdx + 1]) : CONFIG.topK;
  const query = topKIdx === -1
    ? args.join(' ')
    : args.filter((_, i) => i !== topKIdx && i !== topKIdx + 1).join(' ');

  const vector = await embed(query);
  console.log(`query vector length: ${vector.length}`);

  const results = await qdrant.search(CONFIG.collection, {
    vector,
    limit: topK,
    with_payload: true,
  });

  for (let i = 0; i < results.length; i++) {
    const { payload, score } = results[i];
    console.log(`#${i + 1}  ${payload.path}  (score: ${score.toFixed(4)})`);
  }
}

main().catch(err => {
  console.error(err.message);
  if (err.response?.data) console.error(err.response.data);
  console.error(JSON.stringify(err, Object.getOwnPropertyNames(err), 2));
  process.exit(1);
});
