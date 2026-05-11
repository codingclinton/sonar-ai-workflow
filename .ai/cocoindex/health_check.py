#!/usr/bin/env python3
import os, sys, subprocess, json
from collections import Counter

BOLD, RESET = '\033[1m', '\033[0m'
GREEN, RED, YELLOW, CYAN = '\033[32m', '\033[31m', '\033[33m', '\033[36m'

COMPOSE = 'docker compose -f docker-compose.yml -f docker-compose.local-dev.yml'
PSQL = f'{COMPOSE} exec -T cocoindex-postgres psql -U cocoindex -d cocoindex'

def query(sql):
    result = subprocess.run(
        f'{PSQL} -t -A -F"|" -c "{sql}"',
        shell=True, capture_output=True, text=True, cwd=os.path.dirname(os.path.dirname(os.path.dirname(__file__)))
    )
    if result.returncode != 0:
        print(f'{RED}✘ DB error: {result.stderr.strip()}{RESET}')
        sys.exit(1)
    return [row.split('|') for row in result.stdout.strip().splitlines() if row.strip()]

# Summary stats
rows = query("""
    SELECT
        COUNT(*) AS total_chunks,
        COUNT(DISTINCT filename) AS total_files,
        COUNT(CASE WHEN symbol IS NOT NULL THEN 1 END) AS with_symbol,
        COUNT(CASE WHEN class_name IS NOT NULL THEN 1 END) AS with_class,
        ROUND(AVG(end_line - start_line)) AS avg_chunk_lines
    FROM cocoindex.code_embeddings
""")

if not rows:
    print(f'{RED}✘ No data in cocoindex.code_embeddings{RESET}')
    sys.exit(1)

total_chunks, total_files, with_symbol, with_class, avg_lines = rows[0]
total_chunks = int(total_chunks)

status_color = GREEN if total_chunks > 0 else RED
print(f'  Status:       {status_color}{"ok" if total_chunks > 0 else "empty"}{RESET}')
print(f'  Total chunks: {total_chunks}')
print(f'  Total files:  {total_files}')
print(f'  With symbol:  {with_symbol} ({int(with_symbol)*100//max(total_chunks,1)}%)')
print(f'  With class:   {with_class} ({int(with_class)*100//max(total_chunks,1)}%)')
print(f'  Avg chunk:    ~{avg_lines} lines')

# Layer distribution
print(f'\n  Layer distribution:')
layer_rows = query("""
    SELECT layer_type, COUNT(*) AS cnt
    FROM cocoindex.code_embeddings
    GROUP BY layer_type
    ORDER BY cnt DESC
""")
for row in layer_rows:
    layer = row[0] if row[0] else 'null'
    print(f'    {layer:<16} {row[1]}')

# Sample symbols
print(f'\n  {BOLD}Sample symbols:{RESET}')
symbol_rows = query("""
    SELECT layer_type, class_name, symbol, start_line, end_line
    FROM cocoindex.code_embeddings
    WHERE symbol IS NOT NULL AND layer_type != 'other'
    ORDER BY RANDOM()
    LIMIT 5
""")
for row in symbol_rows:
    layer, cls, sym, sl, el = row
    print(f'    {BOLD}[{layer}]{RESET} {sym} (lines {sl}-{el})')
