"""Instrument classification.

Resolve a raw ticker into a normalized description — asset class, security type,
country/region, exchange, currency, sector — BEFORE Forecast model selection, so
applicability can be judged honestly.

Sources, in order: the FinCompass instrument catalogue (recipes + curated US
universe), exchange-suffix inference, then an optional provider lookup (yfinance,
cached with provenance). If none resolves, the classification is returned as
``unknown`` with ``available=False`` — we NEVER assume US equity for an
unclassifiable symbol.
"""
from __future__ import annotations

import json
from datetime import datetime, timezone
from typing import Any, Dict, Optional

from config import DATA_DIR, DEFAULT_UNIVERSE, TICKER_NAMES

try:  # catalogue of proxies/indices/benchmarks with asset_class + region
    from forecasting.recipes import INSTRUMENTS as _CATALOGUE
except Exception:  # pragma: no cover - catalogue always present in practice
    _CATALOGUE = {}

_CACHE_PATH = DATA_DIR / "instrument_classifications.json"

# Exchange-suffix → (country, region, exchange, currency)
_SUFFIX = {
    ".TO": ("Canada", "CA", "Toronto Stock Exchange", "CAD"),
    ".V": ("Canada", "CA", "TSX Venture", "CAD"),
    ".DE": ("Germany", "DE", "XETRA", "EUR"),
    ".PA": ("France", "FR", "Euronext Paris", "EUR"),
    ".AS": ("Netherlands", "NL", "Euronext Amsterdam", "EUR"),
    ".SW": ("Switzerland", "CH", "SIX Swiss Exchange", "CHF"),
    ".L": ("United Kingdom", "GB", "London Stock Exchange", "GBP"),
    ".MI": ("Italy", "IT", "Borsa Italiana", "EUR"),
    ".MC": ("Spain", "ES", "Bolsa de Madrid", "EUR"),
    ".T": ("Japan", "JP", "Tokyo Stock Exchange", "JPY"),
    ".HK": ("Hong Kong", "HK", "Hong Kong Stock Exchange", "HKD"),
    ".SS": ("China", "CN", "Shanghai Stock Exchange", "CNY"),
    ".SZ": ("China", "CN", "Shenzhen Stock Exchange", "CNY"),
}

# Catalogue region names → canonical 2-letter codes used by the benchmark resolver.
_REGION_CODE = {
    "US": "US", "UNITED STATES": "US", "USA": "US",
    "CANADA": "CA", "JAPAN": "JP", "CHINA": "CN", "HONG KONG": "HK",
    "GERMANY": "DE", "FRANCE": "FR", "SWITZERLAND": "CH", "UNITED KINGDOM": "GB",
    "EMERGING MARKETS": "EM", "GLOBAL": "GLOBAL",
}


def _region_code(value) -> Optional[str]:
    if not value:
        return None
    v = str(value).strip().upper()
    return _REGION_CODE.get(v, v if len(v) == 2 else v)


# Catalogue asset_class → (normalized asset_class, security_type)
_ASSET_MAP = {
    "equity": ("equity", "equity"),
    "equity_index_proxy": ("equity", "ETF"),
    "country_equity_proxy": ("equity", "ETF"),
    "fixed_income": ("bond", "bond ETF"),
    "commodity_proxy": ("commodity", "commodity ETF"),
    "reference_index": ("index", "index"),
}


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _blank(symbol: str, available: bool, source: str) -> Dict[str, Any]:
    return {
        "symbol": symbol, "available": available, "source": source,
        "asset_class": "unknown", "security_type": "unknown",
        "country": None, "region": None, "exchange": None,
        "currency": None, "sector": None,
    }


def _from_catalogue(symbol: str) -> Optional[Dict[str, Any]]:
    row = _CATALOGUE.get(symbol)
    if row:
        raw_ac = str(row.get("asset_class") or "")
        asset_class, sec_type = _ASSET_MAP.get(raw_ac, ("unknown", "unknown"))
        code = _region_code(row.get("region"))
        if sec_type == "equity":  # plain single-name equity -> "US equity" etc.
            sec_type = f"{code} equity" if code else "equity"
        out = _blank(symbol, True, "catalogue")
        out.update(
            asset_class=asset_class, security_type=sec_type,
            region=code, country=row.get("region"),
            currency=row.get("currency"),
        )
        return out
    if symbol in DEFAULT_UNIVERSE or symbol in TICKER_NAMES:
        out = _blank(symbol, True, "catalogue")
        out.update(asset_class="equity", security_type="US equity",
                   country="US", region="US", exchange="US", currency="USD")
        return out
    return None


def _from_shape(symbol: str) -> Optional[Dict[str, Any]]:
    if symbol.startswith("^"):
        out = _blank(symbol, True, "shape")
        out.update(asset_class="index", security_type="index")
        return out
    if symbol.endswith("-USD") or symbol.endswith("-USDT"):
        out = _blank(symbol, True, "shape")
        out.update(asset_class="crypto", security_type="crypto", currency="USD")
        return out
    for suffix, (country, region, exchange, currency) in _SUFFIX.items():
        if symbol.endswith(suffix):
            out = _blank(symbol, True, "shape")
            out.update(asset_class="equity", security_type=f"{country} equity",
                       country=country, region=region, exchange=exchange, currency=currency)
            return out
    return None


def _load_cache() -> Dict[str, Any]:
    try:
        return json.loads(_CACHE_PATH.read_text(encoding="utf-8"))
    except Exception:
        return {}


def _save_cache(cache: Dict[str, Any]) -> None:
    try:
        _CACHE_PATH.write_text(json.dumps(cache, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    except Exception:
        pass


def classify_instrument(symbol: str, allow_provider: bool = False) -> Dict[str, Any]:
    """Return a normalized instrument description.

    Deterministic sources (catalogue, suffix/shape) run first and need no
    network. Provider lookup is opt-in (``allow_provider``) and cached with
    provenance. An unresolved symbol returns ``available=False`` — never a
    silent US-equity assumption.
    """
    symbol = str(symbol or "").strip().upper()
    if not symbol:
        return _blank(symbol, False, "empty")

    hit = _from_catalogue(symbol) or _from_shape(symbol)
    if hit:
        return hit

    cache = _load_cache()
    cached = cache.get(symbol)
    if cached and cached.get("available"):
        return {**cached, "source": "cache"}

    if allow_provider:
        resolved = _provider_lookup(symbol)
        if resolved and resolved.get("available"):
            cache[symbol] = {**resolved, "resolved_at": _now(), "provenance": "yfinance"}
            _save_cache(cache)
            return resolved

    return _blank(symbol, False, "unknown")


def _provider_lookup(symbol: str) -> Optional[Dict[str, Any]]:  # pragma: no cover - network
    """Best-effort yfinance classification. Never raises; returns None on failure."""
    try:
        import yfinance as yf
        info = yf.Ticker(symbol).get_info()
    except Exception:
        return None
    if not isinstance(info, dict) or not info:
        return None
    quote_type = str(info.get("quoteType") or "").lower()
    out = _blank(symbol, True, "provider")
    mapping = {
        "equity": ("equity", "equity"), "etf": ("equity", "ETF"),
        "index": ("index", "index"), "cryptocurrency": ("crypto", "crypto"),
        "currency": ("fx", "fx"), "mutualfund": ("equity", "fund"),
    }
    asset_class, sec_type = mapping.get(quote_type, ("unknown", "unknown"))
    if asset_class == "unknown":
        return None
    out.update(
        asset_class=asset_class, security_type=sec_type,
        country=info.get("country"), region=info.get("region") or info.get("country"),
        exchange=info.get("exchange"), currency=info.get("currency"),
        sector=info.get("sector"),
    )
    return out
