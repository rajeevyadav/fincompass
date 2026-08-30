"""Performance metrics from a return series (provider-independent).

Inputs are pandas Series of period returns (use ``common.simple_returns`` on a
price series first). Annualization is explicit via the ``frequency`` argument and
the centralized conventions in ``common``. Functions return raw floats; wrap with
``registry.result`` when a provenance envelope is needed.
"""
from __future__ import annotations

import numpy as np
import pandas as pd

from analytics import common as C
from analytics.registry import register

_EQ = ["equity", "etf", "index"]


def _per_period_rf(rf_annual: float, frequency: str) -> float:
    # simple per-period risk-free split of an annual rate
    return float(rf_annual) / C.periods_per_year(frequency)


def annualized_return(returns: pd.Series, frequency: str = "daily") -> float:
    return C.annualize_return(returns, frequency)


def volatility(returns: pd.Series, frequency: str = "daily") -> float:
    return C.annualize_volatility(returns, frequency)


def sharpe_ratio(returns: pd.Series, rf_annual: float = 0.0, frequency: str = "daily") -> float:
    """Annualized Sharpe: mean(excess)/std(excess) * sqrt(periods_per_year)."""
    r = C._clean(returns)
    if len(r) <= C.DEFAULT_DDOF:
        return float("nan")
    excess = r - _per_period_rf(rf_annual, frequency)
    sd = excess.std(ddof=C.DEFAULT_DDOF)
    if not np.isfinite(sd) or sd < 1e-12:  # no meaningful dispersion
        return float("nan")
    return float(excess.mean() / sd * np.sqrt(C.periods_per_year(frequency)))


def downside_deviation(returns: pd.Series, mar_annual: float = 0.0,
                       frequency: str = "daily") -> float:
    """Annualized downside deviation below a minimum acceptable return (MAR)."""
    r = C._clean(returns)
    if r.empty:
        return float("nan")
    target = _per_period_rf(mar_annual, frequency)
    downside = np.minimum(0.0, r - target)
    return float(np.sqrt(np.mean(downside.values ** 2)) * np.sqrt(C.periods_per_year(frequency)))


def sortino_ratio(returns: pd.Series, mar_annual: float = 0.0, frequency: str = "daily") -> float:
    """Annualized Sortino: excess mean over downside deviation."""
    r = C._clean(returns)
    if r.empty:
        return float("nan")
    dd = downside_deviation(returns, mar_annual, frequency)
    if not np.isfinite(dd) or dd == 0:
        return float("nan")
    ann_excess = C.annualize_return(returns, frequency) - float(mar_annual)
    return float(ann_excess / dd)


def max_drawdown(returns: pd.Series) -> float:
    """Largest peak-to-trough decline of the compounded wealth curve (<= 0)."""
    r = C._clean(returns)
    if r.empty:
        return float("nan")
    wealth = (1.0 + r).cumprod()
    peak = wealth.cummax()
    return float((wealth / peak - 1.0).min())


def calmar_ratio(returns: pd.Series, frequency: str = "daily") -> float:
    """Annualized return divided by the magnitude of the max drawdown."""
    mdd = max_drawdown(returns)
    if not np.isfinite(mdd) or mdd == 0:
        return float("nan")
    return float(C.annualize_return(returns, frequency) / abs(mdd))


def beta(asset_returns: pd.Series, market_returns: pd.Series) -> float:
    """Slope of asset vs market returns: cov(a,m)/var(m) on aligned dates."""
    a = pd.Series(asset_returns, dtype="float64")
    m = pd.Series(market_returns, dtype="float64")
    df = pd.concat([a, m], axis=1, join="inner").dropna()
    if len(df) <= C.DEFAULT_DDOF:
        return float("nan")
    var_m = df.iloc[:, 1].var(ddof=C.DEFAULT_DDOF)
    if var_m == 0:
        return float("nan")
    cov = df.iloc[:, 0].cov(df.iloc[:, 1])
    return float(cov / var_m)


def tracking_error(asset_returns: pd.Series, benchmark_returns: pd.Series,
                   frequency: str = "daily") -> float:
    """Annualized volatility of the active (asset minus benchmark) return."""
    a = pd.Series(asset_returns, dtype="float64")
    b = pd.Series(benchmark_returns, dtype="float64")
    active = pd.concat([a, b], axis=1, join="inner").dropna()
    if len(active) <= C.DEFAULT_DDOF:
        return float("nan")
    diff = active.iloc[:, 0] - active.iloc[:, 1]
    return float(diff.std(ddof=C.DEFAULT_DDOF) * np.sqrt(C.periods_per_year(frequency)))


def information_ratio(asset_returns: pd.Series, benchmark_returns: pd.Series,
                      frequency: str = "daily") -> float:
    """Annualized active return divided by tracking error."""
    te = tracking_error(asset_returns, benchmark_returns, frequency)
    if not np.isfinite(te) or te == 0:
        return float("nan")
    active_ann = (C.annualize_return(asset_returns, frequency)
                  - C.annualize_return(benchmark_returns, frequency))
    return float(active_ann / te)


def _register_all() -> None:
    register("performance.annualized_return.v1", name="Annualized return", category="performance",
             formula="prod(1+r)^(P/N) - 1", inputs=["returns"], units="ratio_percent",
             sign_convention="higher is better", supported_asset_classes=_EQ,
             annualization="geometric", period_assumption="uniform periods")
    register("performance.volatility.v1", name="Annualized volatility", category="performance",
             formula="std(r, ddof=1) * sqrt(P)", inputs=["returns"], units="ratio_percent",
             sign_convention="lower is calmer", supported_asset_classes=_EQ, annualization="sqrt-time")
    register("performance.sharpe.v1", name="Sharpe ratio", category="performance",
             formula="mean(r-rf)/std(r-rf) * sqrt(P)", inputs=["returns", "rf"], units="ratio",
             sign_convention="higher is better", supported_asset_classes=_EQ, annualization="sqrt-time")
    register("performance.sortino.v1", name="Sortino ratio", category="performance",
             formula="ann_excess / downside_deviation", inputs=["returns", "mar"], units="ratio",
             sign_convention="higher is better", supported_asset_classes=_EQ, annualization="sqrt-time")
    register("performance.max_drawdown.v1", name="Maximum drawdown", category="performance",
             formula="min(wealth/cummax(wealth) - 1)", inputs=["returns"], units="ratio_percent",
             sign_convention="closer to 0 is better (<= 0)", supported_asset_classes=_EQ)
    register("performance.calmar.v1", name="Calmar ratio", category="performance",
             formula="annualized_return / |max_drawdown|", inputs=["returns"], units="ratio",
             sign_convention="higher is better", supported_asset_classes=_EQ)
    register("performance.beta.v1", name="Beta", category="performance",
             formula="cov(asset, market) / var(market)", inputs=["asset_returns", "market_returns"],
             units="ratio", sign_convention="1 = market-like", supported_asset_classes=_EQ)
    register("performance.tracking_error.v1", name="Tracking error", category="performance",
             formula="std(asset - benchmark) * sqrt(P)", inputs=["asset_returns", "benchmark_returns"],
             units="ratio_percent", sign_convention="lower = closer to benchmark", supported_asset_classes=_EQ,
             annualization="sqrt-time")
    register("performance.information_ratio.v1", name="Information ratio", category="performance",
             formula="active_annual_return / tracking_error", inputs=["asset_returns", "benchmark_returns"],
             units="ratio", sign_convention="higher is better", supported_asset_classes=_EQ)


_register_all()
