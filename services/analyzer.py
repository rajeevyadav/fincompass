"""FinCompass analysis orchestration v2.

Single-ticker path: cache -> fundamentals -> frozen peer reference -> score -> cache.
Screener refresh path: fetch every fundamental first, then build one peer snapshot,
then score every company against that same snapshot. This removes order-dependent
peer baselines from a refresh run.
"""
from __future__ import annotations

import logging
import threading
from typing import Any, Dict, Optional

from config import DEFAULT_UNIVERSE, FUNDAMENTALS_CACHE_HOURS
from services.cache import cache
from services.data_fetcher import fetcher
from services.macro_fetcher import get_commodity_context, get_macro_context
from services.peers import build_peer_reference
from services.scoring import compute_scores

logger = logging.getLogger("FinCompass.Analyzer")


def _get_macro_cached() -> Dict[str, Any]:
    cached = cache.get_macro()
    if cached is not None:
        return cached
    macro = get_macro_context()
    if macro:
        cache.set_macro(macro)
    return macro


def _get_commodity_cached(sector: str) -> Optional[Dict[str, Any]]:
    if not sector:
        return None
    cached = cache.get_commodity(sector)
    if cached is not None:
        return cached
    data = get_commodity_context(sector)
    if data:
        cache.set_commodity(sector, data)
    return data


def _peer_reference() -> Dict[str, Any]:
    return build_peer_reference(cache.get_all_fundamentals(max_age_hours=FUNDAMENTALS_CACHE_HOURS))


def _score_fundamentals(ticker: str, fund: Dict[str, Any], peer_reference: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    macro = _get_macro_cached()
    commodity = _get_commodity_cached(str(fund.get("sector") or ""))
    result = compute_scores(
        fund,
        current_price=None,  # v2 valuation is fundamentals/peer based; avoid an unnecessary network call.
        macro=macro,
        commodity=commodity,
        peer_reference=peer_reference if peer_reference is not None else _peer_reference(),
    )
    result["ticker"] = ticker
    cache.set_score(ticker, result)
    return result


def analyze_ticker(ticker: str, force_refresh: bool = False) -> Optional[Dict[str, Any]]:
    ticker = ticker.upper().strip()
    if not force_refresh:
        cached_score = cache.get_score(ticker)
        if cached_score:
            logger.info("Cache hit for %s", ticker)
            return cached_score

    fund = None if force_refresh else cache.get_fundamentals(ticker)
    if fund is None:
        fund = fetcher.get_fundamentals(ticker)
        if not fund:
            logger.warning("No fundamentals for %s", ticker)
            return None
        cache.set_fundamentals(ticker, fund)

    return _score_fundamentals(ticker, fund)


def get_price_history_cached(ticker: str, period: str = "5y"):
    ticker = ticker.upper()
    cached = cache.get_price_history(ticker, period)
    if cached is not None:
        return cached
    df = fetcher.get_price_history(ticker, period)
    if df is not None and not df.empty:
        try:
            cache.set_price_history(ticker, period, df)
        except Exception as exc:
            logger.warning("Could not cache price history for %s: %s", ticker, exc)
    return df


def _refresh_screener_worker() -> None:
    total = len(DEFAULT_UNIVERSE)
    work_total = total * 2  # fetch phase + score phase
    failures = 0
    try:
        # Phase 1: populate a coherent, fresh peer universe first.
        for idx, ticker in enumerate(DEFAULT_UNIVERSE, start=1):
            try:
                fund = fetcher.get_fundamentals(ticker)
                if fund:
                    cache.set_fundamentals(ticker, fund)
                else:
                    failures += 1
            except Exception as exc:
                failures += 1
                logger.warning("Screener fetch failed for %s: %s", ticker, exc)
            cache.update_screener_refresh(
                phase="fetch",
                completed=idx,
                failures=failures,
                message=f"Refreshing fundamentals {idx}/{total}",
            )

        peer_ref = build_peer_reference(cache.get_all_fundamentals(max_age_hours=FUNDAMENTALS_CACHE_HOURS))
        cache.update_screener_refresh(
            phase="score",
            completed=0,
            message="Scoring against frozen sector peer references",
        )

        # Phase 2: every company is scored against the same peer reference.
        scored = 0
        for idx, ticker in enumerate(DEFAULT_UNIVERSE, start=1):
            try:
                fund = cache.get_fundamentals(ticker)
                if fund:
                    _score_fundamentals(ticker, fund, peer_reference=peer_ref)
                    scored += 1
                else:
                    failures += 1
            except Exception as exc:
                failures += 1
                logger.warning("Screener score failed for %s: %s", ticker, exc)
            cache.update_screener_refresh(
                phase="score",
                completed=total + idx,
                scored=scored,
                failures=failures,
                message=f"Scoring {idx}/{total}",
            )

        cache.update_screener_refresh(
            status="complete",
            phase="complete",
            completed=work_total,
            scored=scored,
            failures=failures,
            message=f"Refresh complete: {scored}/{total} scored",
        )
    except Exception as exc:
        logger.exception("Screener refresh failed")
        cache.update_screener_refresh(
            status="failed",
            phase="failed",
            failures=failures + 1,
            message=f"Refresh failed: {type(exc).__name__}",
        )


def start_screener_refresh() -> Dict[str, Any]:
    companies_total = len(DEFAULT_UNIVERSE)
    claimed, state = cache.claim_screener_refresh(companies_total * 2, companies_total=companies_total)
    if not claimed:
        return {**state, "started": False}
    thread = threading.Thread(target=_refresh_screener_worker, name="fincompass-screener-refresh", daemon=True)
    thread.start()
    return {**state, "started": True}


def get_screener_refresh_status() -> Dict[str, Any]:
    return cache.get_screener_refresh()
