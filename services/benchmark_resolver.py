"""Documented benchmark-family resolution for supported instrument classes."""
from __future__ import annotations
from typing import Any, Dict

_POLICIES = {
    ("equity", "US"): ("^GSPC", "S&P 500", "US_LARGE_CAP"),
    ("equity", "Canada"): ("^GSPTSE", "S&P/TSX Composite", "CA_BROAD_EQUITY"),
    ("equity", "Japan"): ("^N225", "Nikkei 225", "JP_BROAD_EQUITY"),
    ("equity", "Europe"): ("^STOXX", "STOXX Europe 600", "EU_BROAD_EQUITY"),
}


def resolve_benchmark(instrument: Dict[str, Any]) -> Dict[str, Any]:
    ac = str(instrument.get("asset_class") or "unknown")
    region = str(instrument.get("region") or "Unknown")
    if instrument.get("security_type") == "etf" and ac == "equity":
        return {"supported": False, "reason": "ETF benchmark policy depends on fund mandate and is not inferred generically."}
    row = _POLICIES.get((ac, region))
    if not row:
        return {"supported": False, "reason": f"No benchmark policy for {ac}/{region}."}
    symbol, name, family = row
    return {"supported": True, "symbol": symbol, "name": name, "family": family}
