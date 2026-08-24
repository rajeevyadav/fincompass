"""
FinCompass Macro Context Fetcher
Pulls real macro series from FRED (Federal Reserve Economic Data, free API)
for the Cycle pillar, replacing the placeholder "valuation regime only" logic
with actual credit/rate-cycle signals.

Design constraints (see ARCHITECTURE.md Cycle Pillar rules):
- This must never produce a specific calendar prediction ("recession by 2030").
  It reports where current conditions sit relative to historical norms, as
  context, not a forecast.
- No key = no macro signal. The pillar must still work (falls back to the
  valuation-regime-only logic that shipped before this file existed).
"""

import logging
from datetime import date, datetime, timedelta, timezone
from statistics import median
from typing import Optional, Dict, Any

import requests

from config import FRED_API_KEY, FRED_SERIES, COMMODITY_SERIES_BY_SECTOR

logger = logging.getLogger("FinCompass.MacroFetcher")

FRED_BASE = "https://api.stlouisfed.org/fred/series/observations"
REQUEST_TIMEOUT = 12

_FRED_HEALTH: Dict[str, Any] = {"status": "not_checked", "configured": bool(FRED_API_KEY)}


def _mark_fred(status: str, http_status: Optional[int] = None) -> None:
    global _FRED_HEALTH
    row: Dict[str, Any] = {
        "status": status,
        "configured": bool(FRED_API_KEY),
        "checked_at": datetime.now(timezone.utc).isoformat(),
    }
    if http_status is not None:
        row["http_status"] = int(http_status)
    _FRED_HEALTH = row


def get_health_snapshot() -> Dict[str, Any]:
    if not FRED_API_KEY:
        return {"status": "not_configured", "configured": False}
    return dict(_FRED_HEALTH)


def _response_ok(response) -> bool:
    status = int(getattr(response, "status_code", 200))
    if status == 429:
        _mark_fred("rate_limited", status)
        logger.warning("[Macro] FRED rate limit (HTTP 429)")
        return False
    if status in {401, 403}:
        _mark_fred("auth_error", status)
        logger.warning("[Macro] FRED authorization failure (HTTP %s)", status)
        return False
    if status < 200 or status >= 300:
        _mark_fred("degraded", status)
        logger.warning("[Macro] FRED upstream HTTP %s", status)
        return False
    _mark_fred("ok", status)
    return True


def _fetch_latest(series_id: str) -> Optional[float]:
    """Latest non-missing observation for a FRED series."""
    try:
        r = requests.get(
            FRED_BASE,
            params={
                "series_id": series_id,
                "api_key": FRED_API_KEY,
                "file_type": "json",
                "sort_order": "desc",
                "limit": 10,  # a few rows in case the most recent are missing ('.')
            },
            timeout=REQUEST_TIMEOUT,
        )
        if not _response_ok(r):
            return None
        obs = r.json().get("observations", [])
        for o in obs:
            v = o.get("value")
            if v not in (None, ".", ""):
                return float(v)
        return None
    except Exception as e:
        # Do not log exception URLs: requests may embed the FRED API key in
        # the rendered query string. Exception class is sufficient here.
        _mark_fred("degraded")
        logger.warning("[Macro] FRED fetch failed for %s: %s", series_id, type(e).__name__)
        return None


def get_macro_context() -> Dict[str, Any]:
    """
    Universe-wide macro snapshot (not ticker-specific). Cache this once,
    globally, per MACRO_CACHE_HOURS — do not call per-ticker.
    """
    if not FRED_API_KEY:
        return {}

    yield_curve = _fetch_latest(FRED_SERIES["yield_curve"])
    credit_spread = _fetch_latest(FRED_SERIES["credit_spread"])

    if yield_curve is None and credit_spread is None:
        return {}

    return {
        "source": "fred",
        "yield_curve_10y2y": yield_curve,
        "credit_spread_hy_oas": credit_spread,
    }


def get_commodity_context(sector: str) -> Optional[Dict[str, Any]]:
    """Five-year, sector-conditional commodity context.

    v1 used ``limit=260`` and described that as roughly five years. That is
    frequency-dependent: for daily WTI it is only about one trading year. v2
    requests an explicit five-year observation window and uses the median as
    the robust trend anchor (the mean is returned for transparency as well).
    """
    entry = COMMODITY_SERIES_BY_SECTOR.get(sector)
    if not entry or not FRED_API_KEY:
        return None
    series_id = entry["series"]
    start = (date.today() - timedelta(days=365 * 5 + 3)).isoformat()

    try:
        r = requests.get(
            FRED_BASE,
            params={
                "series_id": series_id,
                "api_key": FRED_API_KEY,
                "file_type": "json",
                "observation_start": start,
                "sort_order": "asc",
            },
            timeout=REQUEST_TIMEOUT,
        )
        if not _response_ok(r):
            return None
        obs = [o for o in r.json().get("observations", []) if o.get("value") not in (None, ".", "")]
        if len(obs) < 20:
            return None
        values = [float(o["value"]) for o in obs]
        latest = values[-1]
        med = float(median(values))
        mean = float(sum(values) / len(values))
        return {
            "commodity": series_id,
            "name": entry["name"],
            "direction": entry["direction"],
            "latest": latest,
            "latest_date": obs[-1].get("date"),
            "trailing_mean": round(mean, 4),
            "trailing_median": round(med, 4),
            "relative_to_trend": round(latest / med, 4) if med else None,
            "observations": len(values),
            "window_start": start,
            "trend_definition": "5y median",
        }
    except Exception as e:
        _mark_fred("degraded")
        logger.warning("[Macro] Commodity fetch failed for %s: %s", series_id, type(e).__name__)
        return None
