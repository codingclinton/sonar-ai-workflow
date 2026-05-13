"""Demo script — runs sample search_code queries and writes to call log."""
import sys, time, json, os
from datetime import datetime, timezone

import mcp_server as coco

LOG = os.path.join(os.path.dirname(__file__), '..', 'logs', 'search_calls.jsonl')
os.makedirs(os.path.dirname(LOG), exist_ok=True)


def run(query, layer=None, kind=None):
    t0 = time.monotonic()
    results = coco.search_code(query, top_k=5, layer_type=layer, chunk_kind=kind)
    scores = [r.get('score', 0) for r in results]
    ms = round((time.monotonic() - t0) * 1000)
    entry = {
        'ts': datetime.now(timezone.utc).isoformat(),
        'tool': 'search_code',
        'query': query,
        'top_k': 5,
        'layer_type': layer,
        'chunk_kind': kind,
        'result_count': len(scores),
        'max_score': round(max(scores), 4) if scores else None,
        'min_score': round(min(scores), 4) if scores else None,
        'avg_score': round(sum(scores) / len(scores), 4) if scores else None,
        'sources_used': ['cocoindex'],
        'latency_ms': ms,
    }
    with open(LOG, 'a') as f:
        f.write(json.dumps(entry) + '\n')
    flag = ' ⚠ zero results' if not scores else ''
    print(f"  [{len(scores)} results, max={entry['max_score']}, {ms}ms] {query!r}{flag}")


queries = [
    ('billing invoice generation',     None,           None),
    ('account eligibility check',      'service',      None),
    ('subscription cancellation',      'service',      None),
    ('payment retry logic',            'job',          None),
    ('tax calculation',                'service',      'method'),
    ('user authentication',            'controller',   None),
    ('send email notification',        'notification', None),
    ('overage charges',                'service',      None),
    ('service suspension',             'service',      None),
    ('invoice pdf export',             None,           None),
    ('account credit balance',         None,           None),
    ('data export csv',                None,           None),
    ('nonexistent frobnicator xyz',    None,           None),   # expected 0 results
]

print(f'\nRunning {len(queries)} demo queries...\n')
for q, layer, kind in queries:
    run(q, layer, kind)
print(f'\nLog written to {os.path.abspath(LOG)}')
