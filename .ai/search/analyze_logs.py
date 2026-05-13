#!/usr/bin/env python3
"""
Search call log analyzer.

Usage:
    python3 analyze_logs.py [--log PATH] [--days N] [--json]

Reads .ai/logs/search_calls.jsonl and prints a usage report.
"""

import argparse
import json
import os
import sys
from collections import Counter, defaultdict
from datetime import datetime, timezone, timedelta

BOLD  = '\033[1m'
RESET = '\033[0m'
GREEN = '\033[32m'
RED   = '\033[31m'
CYAN  = '\033[36m'
YELLOW = '\033[33m'

DEFAULT_LOG = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "logs", "search_calls.jsonl")


def load_entries(log_path: str, since: datetime | None) -> list[dict]:
    if not os.path.exists(log_path):
        print(f"{RED}No log file at {log_path}{RESET}")
        sys.exit(0)
    entries = []
    with open(log_path) as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            try:
                e = json.loads(line)
                if since:
                    ts = datetime.fromisoformat(e.get("ts", "1970-01-01T00:00:00+00:00"))
                    if ts < since:
                        continue
                entries.append(e)
            except json.JSONDecodeError:
                continue
    return entries


def pct(n, total):
    return f"{n * 100 // max(total, 1)}%"


def report(entries: list[dict], as_json: bool = False):
    if not entries:
        print("No log entries found.")
        return

    by_tool = defaultdict(list)
    for e in entries:
        by_tool[e.get("tool", "unknown")].append(e)

    search_entries = by_tool.get("search_code", [])
    symbol_entries = by_tool.get("search_symbol", [])
    get_code_entries = by_tool.get("get_code", [])
    get_file_entries = by_tool.get("get_file_chunks", [])
    similar_entries  = by_tool.get("find_similar_to", [])

    # --- search_code stats ---
    zero_result   = [e for e in search_entries if e.get("result_count", 0) == 0 and not e.get("error")]
    low_score     = [e for e in search_entries if (e.get("max_score") or 0) < 0.4 and e.get("result_count", 0) > 0]
    errors        = [e for e in entries if e.get("error")]
    latencies     = [e["latency_ms"] for e in search_entries if "latency_ms" in e]
    layer_counts  = Counter(e.get("layer_type") for e in search_entries if e.get("layer_type"))
    kind_counts   = Counter(e.get("chunk_kind") for e in search_entries if e.get("chunk_kind"))

    # top queries
    query_counts  = Counter(e.get("query", "") for e in search_entries)

    if as_json:
        print(json.dumps({
            "period_entries": len(entries),
            "by_tool": {k: len(v) for k, v in by_tool.items()},
            "search_code": {
                "total": len(search_entries),
                "zero_result": len(zero_result),
                "low_score": len(low_score),
                "errors": len([e for e in search_entries if e.get("error")]),
                "avg_latency_ms": round(sum(latencies) / len(latencies)) if latencies else None,
                "p95_latency_ms": sorted(latencies)[int(len(latencies) * 0.95)] if latencies else None,
                "zero_result_queries": [e.get("query") for e in zero_result],
                "low_score_queries": [{"query": e.get("query"), "max_score": e.get("max_score")} for e in low_score],
            },
        }, indent=2))
        return

    total = len(entries)
    print(f"\n{BOLD}{'='*60}{RESET}")
    print(f"{BOLD}  Search Call Log Report{RESET}")
    print(f"  {total} entries total")
    print(f"{BOLD}{'='*60}{RESET}\n")

    # Tool usage
    print(f"{BOLD}Tool usage:{RESET}")
    for tool, tlist in sorted(by_tool.items(), key=lambda x: -len(x[1])):
        print(f"  {tool:<20} {len(tlist):>5} calls")

    # search_code detail
    if search_entries:
        avg_lat = round(sum(latencies) / len(latencies)) if latencies else 0
        p95_lat = sorted(latencies)[int(len(latencies) * 0.95)] if latencies else 0
        print(f"\n{BOLD}search_code quality:{RESET}")
        print(f"  Total:          {len(search_entries)}")
        zr_flag = f"  {RED}⚠ investigate{RESET}" if len(zero_result) > len(search_entries) * 0.1 else f"  {GREEN}✔{RESET}"
        print(f"  Zero results:   {len(zero_result)} ({pct(len(zero_result), len(search_entries))}){zr_flag}")
        ls_flag = f"  {YELLOW}⚠ low confidence{RESET}" if low_score else ""
        print(f"  Low score (<0.4): {len(low_score)} ({pct(len(low_score), len(search_entries))}){ls_flag}")
        print(f"  Errors:         {len([e for e in search_entries if e.get('error')])}")
        print(f"  Avg latency:    {avg_lat}ms")
        print(f"  p95 latency:    {p95_lat}ms")

        if layer_counts:
            print(f"\n{BOLD}  Layer filters used:{RESET}")
            for layer, cnt in layer_counts.most_common(8):
                print(f"    {layer:<18} {cnt}")

        if kind_counts:
            print(f"\n{BOLD}  Chunk kind filters used:{RESET}")
            for kind, cnt in kind_counts.most_common(6):
                print(f"    {kind:<18} {cnt}")

        if zero_result:
            print(f"\n{BOLD}  Zero-result queries:{RESET}")
            for e in zero_result[-10:]:
                print(f"    {RED}✘{RESET} {e.get('query', '')!r}")

        if low_score:
            print(f"\n{BOLD}  Low-score queries (max < 0.4):{RESET}")
            for e in sorted(low_score, key=lambda x: x.get("max_score", 0))[:10]:
                print(f"    {YELLOW}~{RESET} {e.get('query', '')!r}  max={e.get('max_score')}")

        print(f"\n{BOLD}  Top 10 queries:{RESET}")
        for query, cnt in query_counts.most_common(10):
            print(f"    {cnt:>3}x  {query!r}")

    # get_code misses
    if get_code_entries:
        misses = [e for e in get_code_entries if not e.get("found")]
        print(f"\n{BOLD}get_code:{RESET}")
        print(f"  Total: {len(get_code_entries)}  Misses: {len(misses)} ({pct(len(misses), len(get_code_entries))})")
        if misses:
            print(f"  {YELLOW}Miss chunk_ids (last 5):{RESET}")
            for e in misses[-5:]:
                print(f"    {e.get('chunk_id', '')}")

    # errors summary
    if errors:
        print(f"\n{BOLD}{RED}Errors ({len(errors)} total):{RESET}")
        ec = Counter(e.get("tool") for e in errors)
        for tool, cnt in ec.most_common():
            print(f"  {tool}: {cnt}")

    print(f"\n{BOLD}{'='*60}{RESET}\n")


def main():
    parser = argparse.ArgumentParser(description="Analyze search call logs")
    parser.add_argument("--log", default=DEFAULT_LOG, help="Path to search_calls.jsonl")
    parser.add_argument("--days", type=int, default=None, help="Only show last N days")
    parser.add_argument("--json", action="store_true", help="Output as JSON")
    args = parser.parse_args()

    since = None
    if args.days:
        since = datetime.now(timezone.utc) - timedelta(days=args.days)

    entries = load_entries(args.log, since)
    report(entries, as_json=args.json)


if __name__ == "__main__":
    main()
