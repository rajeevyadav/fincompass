"""Model Lab starter recipes and cross-asset instrument catalogue.

Recipes are declarative. They define the target horizon, benchmark, target
universe and the data contract to be written into dataset/model lineage. They
do not relax validation gates and they do not claim expected market skill.
"""
from __future__ import annotations

from copy import deepcopy
from hashlib import sha256
import json
from typing import Any, Dict, Iterable, List

from config import DEFAULT_UNIVERSE

RECIPE_SCHEMA_VERSION = "1.1.0-model-lab-recipes2"

# Symbols are intentionally split into tradable proxies and reference indices.
# Training recipes use tradable instruments so the price basis has an
# interpretable total-return/adjustment contract. Reference indices are retained
# for regime/context research and are not silently treated as investable assets.
INSTRUMENTS: Dict[str, Dict[str, Any]] = {
    "SPY": {"name": "SPDR S&P 500 ETF Trust", "asset_class": "equity_index_proxy", "region": "US", "role": "benchmark", "tradable": True, "benchmark": "SPY"},
    "QQQ": {"name": "Invesco QQQ Trust", "asset_class": "equity_index_proxy", "region": "US", "role": "benchmark", "tradable": True, "benchmark": "QQQ"},
    "IWM": {"name": "iShares Russell 2000 ETF", "asset_class": "equity_index_proxy", "region": "US", "role": "context", "tradable": True, "benchmark": "SPY"},
    "VTI": {"name": "Vanguard Total Stock Market ETF", "asset_class": "equity_index_proxy", "region": "US", "role": "context", "tradable": True, "benchmark": "SPY"},
    "GOOG": {"name": "Alphabet Class C", "asset_class": "equity", "region": "US", "role": "bootstrap_research_target", "tradable": True, "benchmark": "MSFT"},
    "EWC": {"name": "iShares MSCI Canada ETF", "asset_class": "country_equity_proxy", "region": "Canada", "role": "context", "tradable": True, "benchmark": "SPY"},
    "XIC.TO": {"name": "iShares Core S&P/TSX Capped Composite Index ETF", "asset_class": "country_equity_proxy", "region": "Canada", "role": "context", "tradable": True, "benchmark": "^GSPTSE", "currency": "CAD"},
    "XIU.TO": {"name": "iShares S&P/TSX 60 Index ETF", "asset_class": "country_equity_proxy", "region": "Canada", "role": "context", "tradable": True, "benchmark": "^GSPTSE", "currency": "CAD"},
    "EWJ": {"name": "iShares MSCI Japan ETF", "asset_class": "country_equity_proxy", "region": "Japan", "role": "context", "tradable": True, "benchmark": "SPY"},
    "MCHI": {"name": "iShares MSCI China ETF", "asset_class": "country_equity_proxy", "region": "China", "role": "context", "tradable": True, "benchmark": "SPY"},
    "FXI": {"name": "iShares China Large-Cap ETF", "asset_class": "country_equity_proxy", "region": "China", "role": "context", "tradable": True, "benchmark": "SPY"},
    "EWH": {"name": "iShares MSCI Hong Kong ETF", "asset_class": "country_equity_proxy", "region": "Hong Kong", "role": "context", "tradable": True, "benchmark": "SPY"},
    "EEM": {"name": "iShares MSCI Emerging Markets ETF", "asset_class": "country_equity_proxy", "region": "Emerging Markets", "role": "context", "tradable": True, "benchmark": "SPY"},
    "TLT": {"name": "iShares 20+ Year Treasury Bond ETF", "asset_class": "fixed_income", "region": "US", "role": "context", "tradable": True, "benchmark": "SPY"},
    "IEF": {"name": "iShares 7-10 Year Treasury Bond ETF", "asset_class": "fixed_income", "region": "US", "role": "context", "tradable": True, "benchmark": "SPY"},
    "SHY": {"name": "iShares 1-3 Year Treasury Bond ETF", "asset_class": "fixed_income", "region": "US", "role": "context", "tradable": True, "benchmark": "SPY"},
    "AGG": {"name": "iShares Core US Aggregate Bond ETF", "asset_class": "fixed_income", "region": "US", "role": "context", "tradable": True, "benchmark": "SPY"},
    "LQD": {"name": "iShares iBoxx Investment Grade Corporate Bond ETF", "asset_class": "fixed_income", "region": "US", "role": "context", "tradable": True, "benchmark": "SPY"},
    "HYG": {"name": "iShares iBoxx High Yield Corporate Bond ETF", "asset_class": "fixed_income", "region": "US", "role": "context", "tradable": True, "benchmark": "SPY"},
    "GLD": {"name": "SPDR Gold Shares", "asset_class": "commodity_proxy", "region": "Global", "role": "context", "tradable": True, "benchmark": "SPY"},
    "SLV": {"name": "iShares Silver Trust", "asset_class": "commodity_proxy", "region": "Global", "role": "context", "tradable": True, "benchmark": "SPY"},
    "USO": {"name": "United States Oil Fund", "asset_class": "commodity_proxy", "region": "Global", "role": "context", "tradable": True, "benchmark": "SPY"},
    "DBC": {"name": "Invesco DB Commodity Index Tracking Fund", "asset_class": "commodity_proxy", "region": "Global", "role": "context", "tradable": True, "benchmark": "SPY"},
    "DBA": {"name": "Invesco DB Agriculture Fund", "asset_class": "commodity_proxy", "region": "Global", "role": "context", "tradable": True, "benchmark": "SPY"},
    "CPER": {"name": "United States Copper Index Fund", "asset_class": "commodity_proxy", "region": "Global", "role": "context", "tradable": True, "benchmark": "SPY"},
    "^GSPC": {"name": "S&P 500 Index", "asset_class": "reference_index", "region": "US", "role": "reference", "tradable": False, "benchmark": "SPY"},
    "^IXIC": {"name": "Nasdaq Composite Index", "asset_class": "reference_index", "region": "US", "role": "reference", "tradable": False, "benchmark": "QQQ"},
    "^RUT": {"name": "Russell 2000 Index", "asset_class": "reference_index", "region": "US", "role": "reference", "tradable": False, "benchmark": "IWM"},
    "^GSPTSE": {"name": "S&P/TSX Composite Index", "asset_class": "reference_index", "region": "Canada", "role": "reference", "tradable": False, "benchmark": "EWC"},
    "^N225": {"name": "Nikkei 225 Index", "asset_class": "reference_index", "region": "Japan", "role": "reference", "tradable": False, "benchmark": "EWJ"},
    "^HSI": {"name": "Hang Seng Index", "asset_class": "reference_index", "region": "Hong Kong", "role": "reference", "tradable": False, "benchmark": "EWH"},
    "000001.SS": {"name": "SSE Composite Index", "asset_class": "reference_index", "region": "China", "role": "reference", "tradable": False, "benchmark": "MCHI"},
    "^TNX": {"name": "US 10-Year Treasury Yield Index", "asset_class": "reference_rate", "region": "US", "role": "reference", "tradable": False, "benchmark": "IEF"},
}

# Add the existing curated equities without overwriting explicit entries above.
for _symbol in DEFAULT_UNIVERSE:
    INSTRUMENTS.setdefault(
        _symbol,
        {
            "name": _symbol,
            "asset_class": "equity",
            "region": "US",
            "role": "training_target",
            "tradable": True,
            "benchmark": "SPY",
        },
    )

NASDAQ_GROWTH = [
    "AAPL", "MSFT", "GOOGL", "AMZN", "NVDA", "META", "AVGO", "ORCL",
    "CRM", "ADBE", "CSCO", "AMD", "INTC", "QCOM", "TXN", "INTU", "AMAT",
]

GLOBAL_PROXIES = ["IWM", "EWC", "XIC.TO", "XIU.TO", "EWJ", "MCHI", "FXI", "EWH", "EEM"]
BOND_PROXIES = ["TLT", "IEF", "SHY", "AGG", "LQD", "HYG"]
COMMODITY_PROXIES = ["GLD", "SLV", "USO", "DBC", "DBA", "CPER"]
REFERENCE_INDICES = ["^GSPC", "^IXIC", "^RUT", "^GSPTSE", "^N225", "^HSI", "000001.SS", "^TNX"]


def _recipe(
    recipe_id: str,
    name: str,
    *,
    horizon: int,
    benchmark: str,
    tickers: Iterable[str],
    profile: str,
    description: str,
    feature_contract: str = "price_relative_v1",
    live_eligible_target: bool = True,
    settings_overrides: Dict[str, Any] | None = None,
    bundled_seed: bool = False,
) -> Dict[str, Any]:
    payload: Dict[str, Any] = {
        "schema_version": RECIPE_SCHEMA_VERSION,
        "recipe_id": recipe_id,
        "name": name,
        "profile": profile,
        "horizon_trading_days": int(horizon),
        "benchmark": benchmark.upper(),
        "tickers": sorted({str(x).upper() for x in tickers if str(x).strip()}),
        "feature_contract": feature_contract,
        "description": description,
        "live_eligible_target": bool(live_eligible_target),
        "settings_overrides": dict(settings_overrides or {}),
        "bundled_seed": bool(bundled_seed),
    }
    payload["settings_hash"] = sha256(
        json.dumps(payload, sort_keys=True, separators=(",", ":")).encode("utf-8")
    ).hexdigest()
    return payload


RECIPES: Dict[str, Dict[str, Any]] = {
    "bootstrap-real-1m": _recipe(
        "bootstrap-real-1m", "Bundled Real-Data Bootstrap - 1M (Research Only)",
        horizon=21, benchmark="MSFT", tickers=["GOOG"], profile="exploratory",
        description=(
            "Offline acceptance recipe using the bundled historical GOOG series versus MSFT. "
            "It exists to exercise the complete Model Lab pipeline without network access and is never live-eligible."
        ),
        settings_overrides={"sample_step_trading_days": 1, "embargo_trading_days": 21},
        live_eligible_target=False, bundled_seed=True,
    ),
    "core-us-6m": _recipe(
        "core-us-6m", "Core US Equity - 6M", horizon=126, benchmark="SPY",
        tickers=DEFAULT_UNIVERSE, profile="exploratory",
        description="Curated US equities versus SPY over approximately six trading months.",
    ),
    "core-us-12m": _recipe(
        "core-us-12m", "Core US Equity - 12M", horizon=252, benchmark="SPY",
        tickers=DEFAULT_UNIVERSE, profile="standard",
        description="Curated US equities versus SPY over approximately twelve trading months.",
    ),
    "nasdaq-growth-6m": _recipe(
        "nasdaq-growth-6m", "Nasdaq Growth - 6M", horizon=126, benchmark="QQQ",
        tickers=NASDAQ_GROWTH, profile="exploratory",
        description="Large-cap technology/growth equities versus QQQ over approximately six trading months.",
    ),
    "nasdaq-growth-12m": _recipe(
        "nasdaq-growth-12m", "Nasdaq Growth - 12M", horizon=252, benchmark="QQQ",
        tickers=NASDAQ_GROWTH, profile="standard",
        description="Large-cap technology/growth equities versus QQQ over approximately twelve trading months.",
    ),
    "global-proxy-6m": _recipe(
        "global-proxy-6m", "Global Equity Proxies - 6M", horizon=126, benchmark="SPY",
        tickers=GLOBAL_PROXIES, profile="exploratory",
        description="Russell, Canada, Japan, China/Hong Kong and emerging-market ETF proxies versus SPY.",
    ),
    "cross-asset-regime-6m": _recipe(
        "cross-asset-regime-6m", "Cross-Asset Regime Research - 6M", horizon=126, benchmark="SPY",
        tickers=GLOBAL_PROXIES + BOND_PROXIES + COMMODITY_PROXIES,
        profile="exploratory",
        description="Research-only cross-asset proxy basket spanning global equity, bonds and commodities.",
        live_eligible_target=False,
    ),
}


def get_recipe(recipe_id: str) -> Dict[str, Any]:
    key = str(recipe_id or "").strip().lower()
    if key not in RECIPES:
        raise KeyError(f"unknown Model Lab recipe: {recipe_id}")
    return deepcopy(RECIPES[key])


def list_recipes() -> List[Dict[str, Any]]:
    return [deepcopy(RECIPES[k]) for k in sorted(RECIPES)]


def list_instruments() -> List[Dict[str, Any]]:
    out = []
    for symbol in sorted(INSTRUMENTS):
        row = {"symbol": symbol, **deepcopy(INSTRUMENTS[symbol])}
        out.append(row)
    return out


def default_update_symbols() -> List[str]:
    # Includes the user-requested global/index/bond/commodity universe plus the
    # current training targets. Reference indices are fetched when supported by
    # the chosen provider but are never substituted for tradable proxies.
    return sorted(set(DEFAULT_UNIVERSE + ["SPY", "QQQ", "GOOG"] + GLOBAL_PROXIES + BOND_PROXIES + COMMODITY_PROXIES + REFERENCE_INDICES))
