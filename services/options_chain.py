"""Listed option-chain lookup for the options desk.

Returns the real expiry dates and the calls/puts (strike, last, bid, ask,
implied volatility) for a ticker so the option calculator can price an actual
contract rather than a hypothetical one. Quotes come from a free public feed and
can be delayed or thin; callers must present them as delayed market data.

The provider call is injected (``fetch``) so the shaping is unit-tested without
a network round trip. Any provider or shape problem degrades to
``{"available": False, "reason": ...}`` rather than raising into the request.
"""
from __future__ import annotations

import logging
import math
from typing import Any, Callable, Dict, List, Optional

logger = logging.getLogger(__name__)

# Provider rows we surface, mapped to stable snake_case keys.
_FIELDS = {
    "strike": "strike", "lastPrice": "last", "bid": "bid", "ask": "ask",
    "impliedVolatility": "implied_volatility", "volume": "volume",
    "openInterest": "open_interest",
}


def _clean(x: Any) -> Optional[float]:
    try:
        v = float(x)
        return v if math.isfinite(v) else None
    except (TypeError, ValueError):
        return None


def _yf_ticker(ticker: str):
    """Return a yfinance Ticker for option lookups, or None if unavailable."""
    try:
        import yfinance as yf
    except Exception:
        return None
    try:
        return yf.Ticker(ticker.replace(".", "-"))
    except Exception:  # pragma: no cover - provider construction variance
        return None


def _spot(t) -> Optional[float]:
    for getter in (lambda: (t.fast_info or {}).get("last_price"),
                   lambda: (t.fast_info or {}).get("lastPrice")):
        try:
            v = _clean(getter())
            if v:
                return v
        except Exception:
            continue
    return None


def _rows(frame) -> List[Dict[str, Any]]:
    if frame is None or getattr(frame, "empty", True):
        return []
    out: List[Dict[str, Any]] = []
    records = frame.to_dict("records") if hasattr(frame, "to_dict") else list(frame)
    for rec in records:
        row = {key: _clean(rec.get(src)) for src, key in _FIELDS.items()}
        if row.get("strike") is not None:
            out.append(row)
    return out


def available_expiries(ticker: str, *, fetch: Callable[[str], Any] = _yf_ticker) -> Dict[str, Any]:
    """List the ticker's option expiry dates and its spot price."""
    ticker = str(ticker or "").upper()
    t = fetch(ticker)
    if t is None:
        return {"available": False, "reason": "Option data is unavailable for this instrument."}
    try:
        expiries = [str(e) for e in (t.options or [])]
    except Exception as e:
        logger.warning("option expiries failed %s: %s", ticker, type(e).__name__)
        expiries = []
    if not expiries:
        return {"available": False, "reason": "No listed options were found for this instrument."}
    return {"available": True, "ticker": ticker, "spot": _spot(t), "expiries": expiries,
            "source_note": "Delayed public option quotes."}


def chain_for(ticker: str, expiry: str, *, fetch: Callable[[str], Any] = _yf_ticker) -> Dict[str, Any]:
    """Calls and puts for one expiry: strike, last, bid, ask, implied volatility."""
    ticker = str(ticker or "").upper()
    t = fetch(ticker)
    if t is None:
        return {"available": False, "reason": "Option data is unavailable for this instrument."}
    try:
        expiries = [str(e) for e in (t.options or [])]
        if expiry not in expiries:
            return {"available": False, "reason": "That expiry is not listed for this instrument.",
                    "expiries": expiries}
        chain = t.option_chain(expiry)
    except Exception as e:
        logger.warning("option chain failed %s %s: %s", ticker, expiry, type(e).__name__)
        return {"available": False, "reason": "The option chain could not be loaded."}
    return {"available": True, "ticker": ticker, "expiry": expiry, "spot": _spot(t),
            "calls": _rows(getattr(chain, "calls", None)),
            "puts": _rows(getattr(chain, "puts", None)),
            "source_note": "Delayed public option quotes."}
