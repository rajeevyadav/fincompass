"""Benchmark resolution policy.

Guided users never pick raw benchmark symbols. Given an instrument
classification, resolve the appropriate benchmark by explicit policy — with a
human-readable name — or return ``supported=False`` where a defensible
benchmark policy does not exist (e.g. crypto, single commodities). We NEVER
silently compare a Canadian/Japanese/European/crypto/bond instrument against the
S&P 500 just because the active model happens to use ^GSPC.
"""
from __future__ import annotations

from typing import Any, Dict

# Region buckets
_EUROPE = {"DE", "FR", "CH", "GB", "IT", "ES", "NL", "SE", "BE", "AT", "FI", "IE", "PT", "NO", "DK", "EU"}
_EM = {"CN", "HK", "IN", "BR", "ZA", "MX", "TW", "KR", "TR", "TH", "ID", "MY", "PH"}

# (family) -> human-readable name
BENCHMARK_NAMES = {
    "^GSPC": "S&P 500", "^GSPTSE": "S&P/TSX Composite", "^N225": "Nikkei 225",
    "^STOXX": "STOXX Europe 600", "EEM": "MSCI Emerging Markets (EEM)",
    "AGG": "US Aggregate Bond (AGG)",
}


# Benchmark symbol -> family (S&P 500 has two common symbols: ^GSPC and the SPY ETF).
_SYMBOL_FAMILY = {
    "^GSPC": "US_LARGE_CAP", "SPY": "US_LARGE_CAP", "QQQ": "US_LARGE_CAP", "^NDX": "US_LARGE_CAP",
    "^GSPTSE": "CA_EQUITY", "^N225": "JP_EQUITY", "^STOXX": "EU_EQUITY",
    "EEM": "EM_EQUITY", "AGG": "US_AGG_BOND",
}


def benchmark_family_of(symbol) -> Any:
    return _SYMBOL_FAMILY.get(str(symbol or "").upper())


def _ok(symbol: str, family: str) -> Dict[str, Any]:
    return {
        "supported": True, "benchmark_symbol": symbol,
        "benchmark_name": BENCHMARK_NAMES.get(symbol, symbol),
        "benchmark_family": family, "reason": None,
    }


def _no(reason: str) -> Dict[str, Any]:
    return {"supported": False, "benchmark_symbol": None, "benchmark_name": None,
            "benchmark_family": None, "reason": reason}


def resolve_benchmark(classification: Dict[str, Any]) -> Dict[str, Any]:
    """Resolve a benchmark policy object from an instrument classification."""
    classification = classification or {}
    if not classification.get("available"):
        return _no("INSTRUMENT_CLASSIFICATION_UNAVAILABLE")

    asset_class = str(classification.get("asset_class") or "").lower()
    region = str(classification.get("region") or "").upper()

    if asset_class == "equity":
        if region == "US":
            return _ok("^GSPC", "US_LARGE_CAP")
        if region == "CA":
            return _ok("^GSPTSE", "CA_EQUITY")
        if region == "JP":
            return _ok("^N225", "JP_EQUITY")
        if region in _EUROPE:
            return _ok("^STOXX", "EU_EQUITY")
        if region in _EM:
            return _ok("EEM", "EM_EQUITY")
        return _no("BENCHMARK_POLICY_UNRESOLVED")
    if asset_class == "bond":
        return _ok("AGG", "US_AGG_BOND")
    if asset_class in ("commodity", "crypto", "index", "fx", "unknown"):
        # No defensible outperformance benchmark policy yet — return unsupported
        # rather than an arbitrary index. (Commodity/crypto benchmarks are an
        # explicit product-policy decision, not a technical default.)
        return _no("BENCHMARK_POLICY_UNRESOLVED")
    return _no("BENCHMARK_POLICY_UNRESOLVED")
