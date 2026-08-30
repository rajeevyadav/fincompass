"""Current Treasury yield curve for the fixed-income desk.

Free public feeds do not list individual corporate or municipal bonds, so the
grounded, no-cost reference is the government yield curve: today's rates at a few
constant maturities. A user prices a bond against a real current yield instead of
guessing one. Quotes are delayed public index values and are labelled as such.

The provider call is injected (``fetch``) so the shaping is unit-tested without a
network round trip. Any provider or shape problem degrades to
``{"available": False, "reason": ...}``.
"""
from __future__ import annotations

import logging
import math
from typing import Any, Callable, Dict, List, Optional

logger = logging.getLogger(__name__)

# CBOE Treasury yield indices on the free feed, by constant maturity.
_TENORS = [
    ("3M", 0.25, "^IRX"),
    ("5Y", 5.0, "^FVX"),
    ("10Y", 10.0, "^TNX"),
    ("30Y", 30.0, "^TYX"),
]


def _clean(x: Any) -> Optional[float]:
    try:
        v = float(x)
        return v if math.isfinite(v) else None
    except (TypeError, ValueError):
        return None


def _normalize_percent(v: Optional[float]) -> Optional[float]:
    """Return a plain annual percent. Some feeds quote these indices x10
    (e.g. 42.5 for 4.25%); fold that back since real yields sit well under 20%."""
    if v is None:
        return None
    return v / 10.0 if v > 20.0 else v


def _yf_last(symbol: str) -> Optional[float]:
    try:
        import yfinance as yf
    except Exception:
        return None
    try:
        hist = yf.Ticker(symbol).history(period="5d")
        if hist is None or hist.empty:
            return None
        return _clean(hist["Close"].dropna().iloc[-1])
    except Exception:  # pragma: no cover - provider variance
        return None


def treasury_curve(*, fetch: Callable[[str], Optional[float]] = _yf_last) -> Dict[str, Any]:
    """The current Treasury yield curve as points of (tenor, years, yield_percent)."""
    points: List[Dict[str, Any]] = []
    for label, years, symbol in _TENORS:
        y = _normalize_percent(_clean(fetch(symbol)))
        if y is not None:
            points.append({"tenor": label, "years": years, "yield_percent": round(y, 3)})
    if not points:
        return {"available": False, "reason": "Current Treasury rates are unavailable right now."}
    return {"available": True, "points": points,
            "source_note": "Delayed public Treasury yield indices."}
