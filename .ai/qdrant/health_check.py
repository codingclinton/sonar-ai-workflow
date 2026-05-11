#!/usr/bin/env python3
import json, sys
from collections import Counter
from urllib.request import urlopen
from urllib.error import URLError

BASE = 'http://localhost:6333'
COLLECTION = 'sonar_php_app'
BOLD, RESET = '\033[1m', '\033[0m'
GREEN, RED, YELLOW, CYAN = '\033[32m', '\033[31m', '\033[33m', '\033[36m'

try:
    with urlopen(f'{BASE}/collections/{COLLECTION}') as r:
        info = json.load(r)['result']
except URLError as e:
    print(f'{RED}✘ Cannot reach Qdrant at {BASE}: {e}{RESET}')
    sys.exit(1)

cfg = info['config']['params']
status = info['status']
status_color = GREEN if status == 'green' else RED
print(f'  Status:      {status_color}{status}{RESET}')
print(f'  Points:      {info["points_count"]}')
print(f'  Vector size: {cfg["vectors"]["size"]}')
print(f'  Distance:    {cfg["vectors"]["distance"]}')

# Scroll sample
with urlopen(
    f'{BASE}/collections/{COLLECTION}/points/scroll',
    data=json.dumps({'limit': 1000, 'with_payload': True, 'with_vector': False}).encode(),
) as r:
    pts = json.load(r)['result']['points']

layers = Counter(p['payload'].get('layer_type', '?') for p in pts)
has_summary = sum(1 for p in pts if p['payload'].get('summary'))
no_summary = [p['payload']['path'] for p in pts if not p['payload'].get('summary')]

summary_color = GREEN if has_summary == len(pts) else YELLOW
print(f'\n  Summary coverage: {summary_color}{has_summary}/{len(pts)}{RESET} (sample of 1000)')
if no_summary:
    print(f'  {RED}Missing summaries:{RESET}')
    for p in no_summary[:5]:
        print(f'    {p}')

print(f'\n  Layer distribution (sample {len(pts)}):')
for k, v in sorted(layers.items(), key=lambda x: -x[1]):
    print(f'    {k:<16} {v}')

php = [p for p in pts if p['payload'].get('layer_type') not in ('other',) and p['payload']['path'].endswith('.php')]
if php:
    print(f'\n  {BOLD}Sample summaries:{RESET}')
    for p in php[:3]:
        pl = p['payload']
        summary = (pl['summary'] or '')[:120]
        print(f"    {BOLD}[{pl['layer_type']}]{RESET} {pl.get('class_name', '?')}")
        print(f'      {summary}...')
        print()
