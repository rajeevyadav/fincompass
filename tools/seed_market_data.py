"""Seed or refresh the durable FinCompass Model Lab research corpus."""
from __future__ import annotations

import argparse
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from services.research_data import build_bundled_seed, import_seed_directory, refresh_market_data
from services.research_store import research_store


def main() -> int:
    parser = argparse.ArgumentParser(description="Seed FinCompass Model Lab market data")
    mode = parser.add_mutually_exclusive_group(required=True)
    mode.add_argument("--online", action="store_true", help="Fetch/update the default cross-asset corpus")
    mode.add_argument("--from-dir", type=Path, help="Import SYMBOL.csv files from a local directory")
    parser.add_argument("--provider", default="manual-seed", help="Provider/source label for --from-dir")
    parser.add_argument("--price-basis", choices=["adjusted", "raw"], default="adjusted")
    parser.add_argument("--symbol", action="append", dest="symbols", help="Limit --online to one or more symbols")
    parser.add_argument("--overlap-days", type=int, default=10)
    parser.add_argument("--bundle", action="store_true", help="Write datasets/market-seed bootstrap DB/raw archive after success")
    args = parser.parse_args()

    if args.online:
        result = refresh_market_data(args.symbols, overlap_calendar_days=max(0, args.overlap_days))
    else:
        result = import_seed_directory(args.from_dir, store=research_store, provider=args.provider, price_basis=args.price_basis)
    print(result)
    if args.bundle:
        print(build_bundled_seed(research_store))
    return 0 if not result.get("errors") else 2


if __name__ == "__main__":
    raise SystemExit(main())
