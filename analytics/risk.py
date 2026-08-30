"""Risk metrics from a return series (provider-independent).

Value-at-Risk here is a confidence-level loss THRESHOLD from the sample, expressed
as a positive loss fraction (e.g. 0.03 = a 3% loss). It is explicitly NOT the
maximum possible loss; losses beyond VaR occur with the complementary probability
and are summarized by CVaR / expected shortfall.
"""
from __future__ import annotations

import numpy as np
import pandas as pd

from analytics import common as C
from analytics.registry import register

_EQ = ["equity", "etf", "index"]


def volatility(returns: pd.Series, frequency: str = "daily") -> float:
    """Annualized standard deviation of returns."""
    return C.annualize_volatility(returns, frequency)


def ewma_volatility(returns: pd.Series, lam: float = 0.94, frequency: str = "daily") -> float:
    """Annualized RiskMetrics EWMA volatility (recent observations weighted more)."""
    r = C._clean(returns)
    if r.empty:
        return float("nan")
    var = 0.0
    mean = r.mean()
    for x in r.values:
        var = lam * var + (1.0 - lam) * (x - mean) ** 2
    return float(np.sqrt(var) * np.sqrt(C.periods_per_year(frequency)))


def historical_var(returns: pd.Series, confidence: float = 0.95) -> float:
    """Empirical VaR: positive loss magnitude at the given confidence level."""
    r = C._clean(returns)
    if r.empty:
        return float("nan")
    q = np.quantile(r.values, 1.0 - confidence)
    return float(max(0.0, -q))


def gaussian_var(returns: pd.Series, confidence: float = 0.95) -> float:
    """Parametric (normal) VaR as a positive loss magnitude."""
    from scipy.stats import norm
    r = C._clean(returns)
    if len(r) <= C.DEFAULT_DDOF:
        return float("nan")
    z = norm.ppf(1.0 - confidence)
    loss_return = r.mean() + z * r.std(ddof=C.DEFAULT_DDOF)
    return float(max(0.0, -loss_return))


def conditional_var(returns: pd.Series, confidence: float = 0.95) -> float:
    """CVaR / expected shortfall: mean loss magnitude in the tail beyond VaR."""
    r = C._clean(returns)
    if r.empty:
        return float("nan")
    threshold = np.quantile(r.values, 1.0 - confidence)
    tail = r.values[r.values <= threshold]
    if tail.size == 0:
        return float("nan")
    return float(max(0.0, -tail.mean()))


def drawdown_series(returns: pd.Series) -> pd.Series:
    """Per-period drawdown of the compounded wealth curve (<= 0)."""
    r = C._clean(returns)
    wealth = (1.0 + r).cumprod()
    return wealth / wealth.cummax() - 1.0


def max_drawdown(returns: pd.Series) -> float:
    """Largest peak-to-trough decline (<= 0)."""
    dd = drawdown_series(returns)
    return float(dd.min()) if not dd.empty else float("nan")


def max_drawdown_duration(returns: pd.Series) -> int:
    """Longest run (in periods) spent below a prior wealth peak."""
    dd = drawdown_series(returns)
    if dd.empty:
        return 0
    longest = run = 0
    for v in dd.values:
        run = run + 1 if v < 0 else 0
        longest = max(longest, run)
    return int(longest)


def _register_all() -> None:
    register("risk.volatility.v1", name="Annualized volatility", category="risk",
             formula="std(r, ddof=1) * sqrt(P)", inputs=["returns"], units="ratio_percent",
             sign_convention="lower is calmer", supported_asset_classes=_EQ, annualization="sqrt-time")
    register("risk.ewma_volatility.v1", name="EWMA volatility", category="risk",
             formula="RiskMetrics EWMA(var, lambda); annualized", inputs=["returns", "lambda"],
             units="ratio_percent", sign_convention="lower is calmer", supported_asset_classes=_EQ,
             annualization="sqrt-time")
    register("risk.var.historical.v1", name="Historical VaR", category="risk",
             formula="-quantile(r, 1-confidence)", inputs=["returns", "confidence"], units="ratio_percent",
             sign_convention="positive loss magnitude; NOT maximum loss", supported_asset_classes=_EQ,
             reference="empirical quantile")
    register("risk.var.gaussian.v1", name="Gaussian VaR", category="risk",
             formula="-(mean + z_{1-conf} * std)", inputs=["returns", "confidence"], units="ratio_percent",
             sign_convention="positive loss magnitude; NOT maximum loss", supported_asset_classes=_EQ)
    register("risk.cvar.v1", name="Conditional VaR (expected shortfall)", category="risk",
             formula="-mean(r | r <= VaR quantile)", inputs=["returns", "confidence"], units="ratio_percent",
             sign_convention="positive mean tail-loss magnitude", supported_asset_classes=_EQ)
    register("risk.max_drawdown.v1", name="Maximum drawdown", category="risk",
             formula="min(wealth/cummax(wealth) - 1)", inputs=["returns"], units="ratio_percent",
             sign_convention="closer to 0 is better (<= 0)", supported_asset_classes=_EQ)
    register("risk.max_drawdown_duration.v1", name="Max drawdown duration", category="risk",
             formula="longest run below a prior wealth peak", inputs=["returns"], units="periods",
             sign_convention="shorter is better", supported_asset_classes=_EQ)


_register_all()
