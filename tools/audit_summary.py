#!/usr/bin/env python3
"""Summarize FinCompass JSONL audit records without exposing raw identifiers."""
from __future__ import annotations

import argparse
import json
from collections import Counter
from datetime import datetime, timedelta, timezone
from pathlib import Path


def parse_ts(value: str):
    try:
        dt = datetime.fromisoformat(value)
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        return dt.astimezone(timezone.utc)
    except (TypeError, ValueError):
        return None


def main() -> int:
    parser = argparse.ArgumentParser(description="Summarize FinCompass audit activity")
    parser.add_argument("--path", default="data/audit.jsonl", help="current audit JSONL path")
    parser.add_argument("--hours", type=float, default=24.0, help="lookback window in hours")
    args = parser.parse_args()

    base = Path(args.path)
    files = [p for p in [base.with_suffix(base.suffix + ".1"), base] if p.exists()]
    cutoff = datetime.now(timezone.utc) - timedelta(hours=max(0.0, args.hours))
    statuses, paths, methods, limited_clients = Counter(), Counter(), Counter(), Counter()
    total = invalid = 0

    for path in files:
        for line in path.read_text(encoding="utf-8", errors="replace").splitlines():
            try:
                row = json.loads(line)
            except json.JSONDecodeError:
                invalid += 1
                continue
            ts = parse_ts(row.get("ts"))
            if ts is None or ts < cutoff:
                continue
            total += 1
            statuses[str(row.get("status", "?"))] += 1
            paths[str(row.get("path", "?"))] += 1
            methods[str(row.get("method", "?"))] += 1
            if int(row.get("status", 0) or 0) == 429:
                client = row.get("client_id") or "unidentified"
                # Only show the rotating/hash identifier already present in the log.
                limited_clients[str(client)] += 1

    print(f"FinCompass audit summary — last {args.hours:g}h")
    print(f"records={total} invalid_lines={invalid}")
    print("status:", dict(statuses.most_common()))
    print("methods:", dict(methods.most_common()))
    print("top_paths:", dict(paths.most_common(10)))
    if limited_clients:
        print("top_429_clients:", dict(limited_clients.most_common(10)))
    else:
        print("top_429_clients: {}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
