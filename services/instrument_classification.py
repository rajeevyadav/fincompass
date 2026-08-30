"""Conservative local instrument classification for Guided Forecast planning."""
from __future__ import annotations
from typing import Any, Dict

from forecasting.recipes import BOND_PROXIES, COMMODITY_PROXIES, GLOBAL_PROXIES, INSTRUMENTS

_ETFS = set(BOND_PROXIES + COMMODITY_PROXIES + GLOBAL_PROXIES + ["SPY","QQQ","IWM","VTI","DIA","EFA","VGK","VWO","VNQ","UUP"])
_CRYPTO_SUFFIXES = ("-USD", "-CAD", "-EUR")


def classify_instrument(symbol: str) -> Dict[str, Any]:
    s = str(symbol or "").strip().upper()
    known = dict(INSTRUMENTS.get(s) or {})
    if s.endswith(_CRYPTO_SUFFIXES):
        return {"symbol": s, "asset_class": "crypto", "security_type": "crypto", "region": "Global", "country": None, "currency": s.split("-")[-1], "classification_source": "symbol_policy"}
    if s.startswith("^") or s in {"000001.SS"}:
        return {"symbol": s, "asset_class": "index", "security_type": "index", "region": known.get("region") or "Unknown", "country": known.get("region"), "currency": known.get("currency"), "classification_source": "catalog"}
    if s in set(BOND_PROXIES):
        return {"symbol": s, "asset_class": "fixed_income", "security_type": "etf", "region": "US", "country": "US", "currency": "USD", "classification_source": "catalog"}
    if s in set(COMMODITY_PROXIES):
        return {"symbol": s, "asset_class": "commodity_proxy", "security_type": "etf", "region": "Global", "country": None, "currency": "USD", "classification_source": "catalog"}
    if s.endswith(".TO"):
        return {"symbol": s, "asset_class": "equity", "security_type": "etf" if s in _ETFS else "common_stock", "region": "Canada", "country": "Canada", "currency": "CAD", "classification_source": "symbol_policy"}
    if s.endswith(".T"):
        return {"symbol": s, "asset_class": "equity", "security_type": "common_stock", "region": "Japan", "country": "Japan", "currency": "JPY", "classification_source": "symbol_policy"}
    if s.endswith((".DE", ".PA", ".AS", ".L", ".MI", ".MC")):
        return {"symbol": s, "asset_class": "equity", "security_type": "common_stock", "region": "Europe", "country": None, "currency": None, "classification_source": "symbol_policy"}
    if known:
        ac = str(known.get("asset_class") or "equity")
        sec = "etf" if s in _ETFS or "proxy" in ac else "common_stock"
        return {"symbol": s, "asset_class": "equity" if ac in {"equity", "equity_index_proxy", "country_equity_proxy"} else ac, "security_type": sec, "region": known.get("region") or "US", "country": known.get("region") or "US", "currency": known.get("currency") or "USD", "classification_source": "catalog"}
    if s and all(ch.isalnum() or ch in ".-" for ch in s):
        # Unknown bare symbols are not silently promoted to scientific US equity
        # support. Discovery/provider metadata should confirm them first.
        return {"symbol": s, "asset_class": "unknown", "security_type": "unknown", "region": "Unknown", "country": None, "currency": None, "classification_source": "unresolved"}
    return {"symbol": s, "asset_class": "unknown", "security_type": "unknown", "region": "Unknown", "country": None, "currency": None, "classification_source": "unresolved"}

_US_EXCHANGES = {"NMS","NGM","NCM","NYQ","ASE","PCX","BTS","PNK","OQX","OQB","NAS","NYSE","NASDAQ","AMEX"}

def resolve_instrument(symbol: str, *, allow_provider: bool = True) -> Dict[str, Any]:
    """Resolve an unknown symbol with on-demand provider metadata when available.

    The deterministic classifier remains conservative. This resolver is used by
    Guided Forecast so a newly entered real ticker is not limited to the bundled
    starter catalog. Provider failure simply returns the conservative result.
    """
    base = classify_instrument(symbol)
    if base.get("asset_class") != "unknown" or not allow_provider:
        return base
    s = str(symbol or "").strip().upper()
    try:
        from services.market_catalog import search_symbol
        result = search_symbol(s, limit=8)
        quotes = result.get("results") or [] if isinstance(result, dict) else []
        quote = next((q for q in quotes if str(q.get("ticker") or "").upper() == s), None)
        if not quote:
            return base
        qt = str(quote.get("quote_type") or "").upper()
        exchange = str(quote.get("exchange") or "").upper()
        currency = str(quote.get("currency") or "").upper() or None
        region_raw = str(quote.get("region") or "").lower()
        if qt in {"ETF", "MUTUALFUND"}:
            sec = "etf"
        elif qt in {"EQUITY", "STOCK"}:
            sec = "common_stock"
        else:
            return base
        if region_raw in {"us", "usa", "united states"} or exchange in _US_EXCHANGES or (currency == "USD" and "." not in s):
            region, country = "US", "US"
        elif region_raw in {"ca", "canada"} or s.endswith(".TO"):
            region, country = "Canada", "Canada"
        elif region_raw in {"jp", "japan"} or s.endswith(".T"):
            region, country = "Japan", "Japan"
        elif region_raw in {"gb","de","fr","nl","it","es","europe"} or s.endswith((".L",".DE",".PA",".AS",".MI",".MC")):
            region, country = "Europe", None
        else:
            return base
        return {"symbol":s,"asset_class":"equity","security_type":sec,"region":region,"country":country,"currency":currency,"exchange":quote.get("exchange"),"name":quote.get("name"),"classification_source":"provider_metadata"}
    except Exception:
        return base
