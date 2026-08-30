"""Shared transforms and centralized numerical conventions.

All annualization, compounding, and trading-day assumptions live here so no
metric silently mixes incompatible definitions. Everything operates on pandas
Series/DataFrame of prices or returns and is provider-independent.
"""
from __future__ import annotations

from typing import Optional

import numpy as np
import pandas as pd

# --- centralized conventions (never redefine these elsewhere) ---------------
TRADING_DAYS_PER_YEAR = 252
MONTHS_PER_YEAR = 12
WEEKS_PER_YEAR = 52
# Sample standard deviation (ddof=1) is the default across the analytics kernel.
DEFAULT_DDOF = 1

# periods-per-year by data frequency label
PERIODS_PER_YEAR = {
    "daily": TRADING_DAYS_PER_YEAR,
    "weekly": WEEKS_PER_YEAR,
    "monthly": MONTHS_PER_YEAR,
    "quarterly": 4,
    "annual": 1,
}


def periods_per_year(frequency: str = "daily") -> int:
    """Annualization factor for a frequency label; raises on an unknown label."""
    key = str(frequency or "daily").lower()
    if key not in PERIODS_PER_YEAR:
        raise ValueError(f"unknown frequency: {frequency!r}")
    return PERIODS_PER_YEAR[key]


def _clean(series: pd.Series) -> pd.Series:
    """Drop NaN/Inf so a single bad point cannot poison an aggregate."""
    s = pd.Series(series, dtype="float64")
    return s[np.isfinite(s)]


def simple_returns(prices: pd.Series) -> pd.Series:
    """Period-over-period simple returns p_t/p_{t-1} - 1 (first row dropped)."""
    p = pd.Series(prices, dtype="float64")
    return p.pct_change().iloc[1:]


def log_returns(prices: pd.Series) -> pd.Series:
    """Continuously-compounded (log) returns ln(p_t/p_{t-1})."""
    p = pd.Series(prices, dtype="float64")
    return np.log(p / p.shift(1)).iloc[1:]


def cumulative_return(returns: pd.Series) -> float:
    """Total compounded return over the sample: prod(1+r) - 1."""
    r = _clean(returns)
    if r.empty:
        return float("nan")
    return float(np.prod(1.0 + r.values) - 1.0)


def annualize_return(returns: pd.Series, frequency: str = "daily") -> float:
    """Geometric annualized return from period returns."""
    r = _clean(returns)
    if r.empty:
        return float("nan")
    ppy = periods_per_year(frequency)
    growth = float(np.prod(1.0 + r.values))
    return growth ** (ppy / len(r)) - 1.0


def annualize_volatility(returns: pd.Series, frequency: str = "daily",
                         ddof: int = DEFAULT_DDOF) -> float:
    """Annualized standard deviation of period returns (sqrt-time scaling)."""
    r = _clean(returns)
    if len(r) <= ddof:
        return float("nan")
    return float(r.std(ddof=ddof) * np.sqrt(periods_per_year(frequency)))


def rolling(series: pd.Series, window: int, func: str = "mean") -> pd.Series:
    """Trailing rolling transform (mean/std/sum) — strictly backward-looking."""
    s = pd.Series(series, dtype="float64")
    roll = s.rolling(window)
    if func == "mean":
        return roll.mean()
    if func == "std":
        return roll.std(ddof=DEFAULT_DDOF)
    if func == "sum":
        return roll.sum()
    raise ValueError(f"unknown rolling func: {func!r}")


def growth(series: pd.Series, periods: int = 1) -> pd.Series:
    """Percentage growth over ``periods`` (e.g. YoY when periods = one year)."""
    s = pd.Series(series, dtype="float64")
    return s.pct_change(periods=periods)


def zscore(series: pd.Series, window: Optional[int] = None,
           ddof: int = DEFAULT_DDOF) -> pd.Series:
    """Standardize a series; rolling when ``window`` is given, else full-sample."""
    s = pd.Series(series, dtype="float64")
    if window:
        mean = s.rolling(window).mean()
        std = s.rolling(window).std(ddof=ddof)
        return (s - mean) / std
    return (s - s.mean()) / s.std(ddof=ddof)
