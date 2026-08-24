"""
In-app forecast model builder.

End users never touch the command line: the UI posts to /api/v4/forecast/build,
which runs this background worker. It reproduces what tools/build_market_dataset.py
and tools/train_forecast.py do, but in-process and with SQLite-backed progress so
the UI can poll /api/v4/forecast/build/status.

Honesty note: a real model trained on free public data is frequently gate-rejected
(it earns at most `validated_research` because the curated universe carries
survivorship bias). A completed build that produces no usable model is the tool
behaving correctly, not a failure.
"""
from __future__ import annotations

import logging
import threading
from pathlib import Path
from typing import Any, Dict, List, Optional

from config import DATA_DIR, DEFAULT_UNIVERSE
from services.cache import cache

logger = logging.getLogger(__name__)

# Dataset bundles are written under the writable data dir so packaged/frozen
# builds (read-only bundle) can still build models.
BUILD_OUTPUT_DIR = DATA_DIR / "forecast-build"

VALID_PROFILES = ("strict", "standard", "exploratory")


def _worker(profile: str, tickers: List[str], output_dir: Path) -> None:
    # Heavy scientific imports are deferred so they never slow API startup.
    from forecasting.config import get_profile
    from forecasting.dataset import (
        build_universe_dataset,
        load_dataset_bundle,
        write_dataset_bundle,
    )
    from forecasting.model import train_validate_ensemble
    from forecasting.registry import save_model
    from services.data_fetcher import fetcher

    try:
        settings = get_profile(profile)
        total = len(tickers)
        cache.update_model_build(phase="fetch", message=f"Fetching benchmark {settings.benchmark}")
        benchmark = fetcher.get_price_history(settings.benchmark, "max")
        if benchmark is None or benchmark.empty:
            cache.update_model_build(
                status="failed", phase="failed",
                message=f"Could not fetch benchmark {settings.benchmark}. Check your network and try again.",
            )
            return

        prices: Dict[str, Any] = {}
        failures: List[str] = []
        for i, ticker in enumerate(tickers, start=1):
            cache.update_model_build(
                phase="fetch", completed=i, failures=len(failures),
                message=f"Fetching price history {i}/{total}: {ticker}",
            )
            try:
                frame = fetcher.get_price_history(ticker, "max")
            except Exception as exc:  # network / provider hiccup on a single name
                logger.warning("Build price fetch failed for %s: %s", ticker, exc)
                frame = None
            if frame is None or frame.empty:
                failures.append(ticker)
                continue
            prices[ticker] = frame

        if len(prices) < 2:
            cache.update_model_build(
                status="failed", phase="failed", failures=len(failures),
                message="Too few price series were retrievable to build a dataset. Try again later.",
            )
            return

        cache.update_model_build(phase="build", failures=len(failures), message="Assembling training dataset")
        dataset = build_universe_dataset(prices, benchmark, settings)
        write_dataset_bundle(
            dataset,
            output_dir,
            settings,
            synthetic=False,
            provenance={
                "price_sources": "FinCompass free-provider chain (yfinance auto-adjusted preferred, Stooq fallback)",
                "fundamentals": "none",
                "universe": "current curated universe",
                "failures": failures,
                "built_by": "in-app model builder",
            },
            data_quality={
                "point_in_time_features": True,
                "survivorship_control": False,
                "delistings_included": False,
                "corporate_action_adjusted": False,
                "note": "Current-universe construction and fallback provider behavior cap this at validated_research; validated_market requires an independently controlled historical universe.",
            },
        )

        cache.update_model_build(phase="train", failures=len(failures), message="Training, calibrating and locked-testing the model")
        train, validation, test, manifest = load_dataset_bundle(output_dir)
        model, report, predictions = train_validate_ensemble(train, validation, test, manifest, settings)
        saved = save_model(model, report, manifest, profile_name="default")
        predictions.to_csv(output_dir / "locked_test_predictions.csv", index=False)

        tier = report.get("validation_tier")
        passed = bool(report.get("gate", {}).get("passed"))
        usable = tier in {"validated_research", "validated_market"}
        if usable:
            message = f"Build complete — a {tier.replace('_', ' ')} model is now active."
        else:
            message = (
                "Build complete, but the model did not pass the validation gates and was not "
                "activated. On free public data this is common and expected — the Evidence score "
                "and Screener work without a forecast model."
            )
        cache.update_model_build(
            status="complete", phase="complete", completed=total, failures=len(failures),
            model_id=saved.get("model_id"), validation_tier=tier, gate_passed=passed,
            usable=usable, message=message,
        )
    except Exception as exc:
        logger.exception("In-app model build failed")
        cache.update_model_build(
            status="failed", phase="failed",
            message=f"Build failed: {type(exc).__name__}",
        )


def start_model_build(profile: str = "strict", tickers: Optional[List[str]] = None) -> Dict[str, Any]:
    """Claim the single build slot and launch the background worker."""
    if profile not in VALID_PROFILES:
        profile = "strict"
    symbols = [str(t).strip().upper() for t in (tickers or DEFAULT_UNIVERSE) if str(t).strip()]
    if not symbols:
        symbols = list(DEFAULT_UNIVERSE)

    claimed, state = cache.claim_model_build(len(symbols))
    if not claimed:
        return {**state, "started": False}

    output_dir = BUILD_OUTPUT_DIR
    output_dir.mkdir(parents=True, exist_ok=True)
    cache.update_model_build(profile=profile, message=f"Building a {profile} forecast model from free public data")
    thread = threading.Thread(
        target=_worker,
        args=(profile, symbols, output_dir),
        name="fincompass-model-build",
        daemon=True,
    )
    thread.start()
    return {**cache.get_model_build(), "started": True}


def get_model_build_status() -> Dict[str, Any]:
    return cache.get_model_build()
