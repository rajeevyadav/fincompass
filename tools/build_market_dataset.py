#!/usr/bin/env python3
"""Build a reproducible historical forecast dataset from free public sources.

Default mode uses the current FinCompass universe, so survivorship bias remains
and the resulting model can at most earn `validated_research`. To qualify for
`validated_market`, import a point-in-time universe that includes delistings and
set the corresponding data-quality assertions only after independently
verifying them.
"""
from __future__ import annotations

import argparse
import sys
import os
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from config import DEFAULT_UNIVERSE
from forecasting.config import get_profile
from forecasting.dataset import build_universe_dataset, write_dataset_bundle
from forecasting.sec_fundamentals import SecClient, fetch_ticker_fundamental_history
from services.data_fetcher import fetcher


def main():
    p = argparse.ArgumentParser()
    p.add_argument("--output", default="datasets/market")
    p.add_argument("--profile", default="strict", choices=["strict", "standard", "exploratory"])
    p.add_argument("--tickers", default="", help="Comma-separated symbols; default is curated universe")
    p.add_argument("--limit", type=int, default=0)
    p.add_argument("--with-sec", action="store_true", help="Add filing-date-gated annual SEC CompanyFacts features")
    args = p.parse_args()
    settings = get_profile(args.profile)
    tickers = [x.strip().upper() for x in args.tickers.split(",") if x.strip()] or list(DEFAULT_UNIVERSE)
    if args.limit > 0:
        tickers = tickers[: args.limit]
    benchmark = fetcher.get_price_history(settings.benchmark, "max")
    if benchmark is None or benchmark.empty:
        raise SystemExit(f"Could not fetch benchmark {settings.benchmark}")

    sec_client = None
    if args.with_sec:
        sec_client = SecClient(user_agent=os.getenv("SEC_USER_AGENT", ""))
    prices = {}
    fundamentals = {}
    failures = []
    for i, ticker in enumerate(tickers, start=1):
        print(f"[{i}/{len(tickers)}] {ticker}")
        frame = fetcher.get_price_history(ticker, "max")
        if frame is None or frame.empty:
            failures.append(ticker)
            continue
        prices[ticker] = frame
        if sec_client is not None:
            try:
                history = fetch_ticker_fundamental_history(ticker, sec_client)
                if not history.empty:
                    fundamentals[ticker] = history
            except Exception as exc:
                print(f"  SEC features unavailable: {type(exc).__name__}")

    dataset = build_universe_dataset(prices, benchmark, settings, fundamentals_by_ticker=fundamentals)
    manifest = write_dataset_bundle(
        dataset,
        args.output,
        settings,
        synthetic=False,
        provenance={
            "price_sources": "FinCompass free-provider chain (yfinance auto-adjusted preferred, Stooq fallback)",
            "fundamentals": "SEC CompanyFacts annual filings gated by filing date" if args.with_sec else "none",
            "universe": "current curated universe unless --tickers supplied",
            "failures": failures,
        },
        data_quality={
            "point_in_time_features": True,
            "survivorship_control": False,
            "delistings_included": False,
            "corporate_action_adjusted": False,
            "note": "Conservative flags: current-universe construction and fallback provider behavior prevent validated_market status without an independently controlled historical universe/price source.",
        },
    )
    print(f"Dataset written to {args.output}; rows: {sum(v['rows'] for v in manifest['files'].values())}")


if __name__ == "__main__":
    main()
