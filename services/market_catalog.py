"""Dynamic equity discovery for FinCompass.

The curated ``DEFAULT_UNIVERSE`` remains a deterministic starter/screener
universe.  This module provides on-demand market discovery so the UI is not
limited to that starter list.  It intentionally does not persist or package
provider market data as a redistributable corpus.
"""
from __future__ import annotations

from typing import Any, Dict, List, Optional

try:
    import yfinance as yf
except ImportError:  # optional provider; application must still start offline
    yf = None

# Yahoo/yfinance EquityQuery regions currently documented by yfinance.
SUPPORTED_REGIONS = {
    "ae", "ar", "at", "au", "be", "br", "ca", "ch", "cl", "cn", "co", "cz",
    "de", "dk", "ee", "eg", "es", "fi", "fr", "gb", "gr", "hk", "hu", "id",
    "ie", "il", "in", "is", "it", "jp", "kr", "kw", "lk", "lt", "lv", "mx",
    "my", "nl", "no", "nz", "pe", "ph", "pk", "pl", "pt", "qa", "ro", "ru",
    "sa", "se", "sg", "sr", "th", "tr", "tw", "us", "ve", "vn", "za",
}

# Human-facing common sectors. Provider may return additional/variant names.
COMMON_SECTORS = [
    "Basic Materials", "Communication Services", "Consumer Cyclical",
    "Consumer Defensive", "Energy", "Financial Services", "Healthcare",
    "Industrials", "Real Estate", "Technology", "Utilities",
]


def _clean_quote(row: Dict[str, Any]) -> Dict[str, Any]:
    ticker = str(row.get("symbol") or row.get("ticker") or "").strip().upper()
    return {
        "ticker": ticker,
        "name": row.get("shortName") or row.get("longName") or row.get("displayName") or ticker,
        "sector": row.get("sector") or row.get("sectorDisp"),
        "industry": row.get("industry") or row.get("industryDisp"),
        "exchange": row.get("exchange") or row.get("fullExchangeName"),
        "region": row.get("region"),
        "market_cap": row.get("marketCap") or row.get("intradaymarketcap"),
        "price": row.get("regularMarketPrice") or row.get("intradayprice"),
        "currency": row.get("currency"),
        "quote_type": row.get("quoteType") or row.get("typeDisp"),
    }


def search_equities(
    *,
    sector: Optional[str] = None,
    region: str = "us",
    text: Optional[str] = None,
    offset: int = 0,
    limit: int = 100,
) -> Dict[str, Any]:
    """Discover equities dynamically through the installed market provider.

    ``limit`` is capped at 250 per provider request. Pagination via ``offset``
    allows the client to traverse sectors/regions well beyond FinCompass's
    curated starter universe.
    """
    region = str(region or "us").strip().lower()
    if region not in SUPPORTED_REGIONS:
        raise ValueError(f"unsupported region: {region}")
    offset = max(0, int(offset or 0))
    limit = max(1, min(int(limit or 100), 250))
    text = str(text or "").strip().lower()
    sector = str(sector or "").strip()

    if yf is None or not hasattr(yf, "EquityQuery") or not hasattr(yf, "screen"):
        return {
            "available": False,
            "provider": "yfinance",
            "reason": "dynamic market discovery requires a yfinance build with EquityQuery/screen support",
            "region": region,
            "sector": sector or None,
            "offset": offset,
            "limit": limit,
            "results": [],
        }

    clauses = [yf.EquityQuery("eq", ["region", region])]
    if sector:
        clauses.append(yf.EquityQuery("eq", ["sector", sector]))
    query = clauses[0] if len(clauses) == 1 else yf.EquityQuery("and", clauses)

    try:
        response = yf.screen(query, offset=offset, size=limit, sortField="ticker", sortAsc=True)
    except Exception as exc:
        return {
            "available": False,
            "provider": "yfinance",
            "reason": f"provider request failed: {type(exc).__name__}",
            "region": region,
            "sector": sector or None,
            "offset": offset,
            "limit": limit,
            "results": [],
        }

    quotes: List[Dict[str, Any]] = []
    total = None
    if isinstance(response, dict):
        raw = response.get("quotes") or response.get("finance", {}).get("result") or []
        if isinstance(raw, list) and raw and isinstance(raw[0], dict) and "quotes" in raw[0]:
            total = raw[0].get("total") or raw[0].get("count")
            raw = raw[0].get("quotes") or []
        total = response.get("total") or response.get("count") or total
        if isinstance(raw, list):
            quotes = [_clean_quote(x) for x in raw if isinstance(x, dict)]

    quotes = [q for q in quotes if q.get("ticker")]
    if text:
        quotes = [
            q for q in quotes
            if text in str(q.get("ticker") or "").lower()
            or text in str(q.get("name") or "").lower()
            or text in str(q.get("industry") or "").lower()
        ]

    return {
        "available": True,
        "provider": "yfinance",
        "region": region,
        "sector": sector or None,
        "offset": offset,
        "limit": limit,
        "returned": len(quotes),
        "provider_total": total,
        "has_more": bool((total is not None and offset + limit < int(total)) or len(quotes) == limit),
        "results": quotes,
        "note": "Discovery is on-demand provider data; it is not part of the packaged private training corpus.",
    }


def search_symbol(text: str, limit: int = 12) -> Dict[str, Any]:
    """Search symbols/company names globally where supported by yfinance."""
    text = str(text or "").strip()
    limit = max(1, min(int(limit or 12), 50))
    if not text:
        return {"available": True, "provider": "yfinance", "results": []}
    if yf is None or not hasattr(yf, "Search"):
        return {"available": False, "provider": "yfinance", "reason": "market search unavailable", "results": []}
    try:
        obj = yf.Search(text, max_results=limit, news_count=0, lists_count=0, include_research=False, timeout=12)
        raw = getattr(obj, "quotes", None) or []
        return {
            "available": True,
            "provider": "yfinance",
            "query": text,
            "results": [_clean_quote(x) for x in raw if isinstance(x, dict) and (x.get("symbol") or x.get("ticker"))],
        }
    except Exception as exc:
        return {"available": False, "provider": "yfinance", "reason": f"provider request failed: {type(exc).__name__}", "query": text, "results": []}
