"""Provider-independent portfolio analytics (weights + covariance).

Computes portfolio expected return, variance/volatility, and per-asset risk
contributions from explicit weights and either a covariance matrix or a matrix
of historical asset returns. Local-first and provider-independent: it operates
on plain arrays the caller already holds, needs no market-data feed, and has no
paid dependency.

Governance: a portfolio measure here aggregates *risk and return of holdings*.
It never averages forecast probabilities or model outputs — combining
per-instrument model signals into a portfolio number would fabricate a
statistic the models never produced — and no value here is promoted to a
forecast feature. Structurally invalid inputs (empty/mismatched shapes,
non-finite entries, a non-square or non-symmetric covariance, weights that do
not sum to one when normalization is required) fail safely to NaN rather than
raising or returning a misleading number.
"""
from __future__ import annotations

from typing import Dict, List, Sequence

import numpy as np

from analytics.registry import register

NaN = float("nan")


def _as_vector(x: Sequence[float]) -> np.ndarray | None:
    a = np.asarray(x, dtype=float)
    if a.ndim != 1 or a.size == 0 or not np.all(np.isfinite(a)):
        return None
    return a


def _as_cov(cov: Sequence[Sequence[float]], n: int) -> np.ndarray | None:
    c = np.asarray(cov, dtype=float)
    if c.ndim != 2 or c.shape != (n, n) or not np.all(np.isfinite(c)):
        return None
    if not np.allclose(c, c.T, atol=1e-12):
        return None
    return c


def normalize_weights(weights: Sequence[float]) -> List[float]:
    """Scale weights to sum to 1. Returns NaNs if the sum is zero/non-finite."""
    w = _as_vector(weights)
    if w is None:
        return [NaN]
    total = float(w.sum())
    if not np.isfinite(total) or abs(total) < 1e-15:
        return [NaN] * w.size
    return list(w / total)


def portfolio_return(weights: Sequence[float], expected_returns: Sequence[float]) -> float:
    """Weighted expected return: w . mu."""
    w = _as_vector(weights)
    mu = _as_vector(expected_returns)
    if w is None or mu is None or w.size != mu.size:
        return NaN
    return float(w @ mu)


def portfolio_variance(weights: Sequence[float], cov: Sequence[Sequence[float]]) -> float:
    """w' Sigma w."""
    w = _as_vector(weights)
    if w is None:
        return NaN
    c = _as_cov(cov, w.size)
    if c is None:
        return NaN
    var = float(w @ c @ w)
    return var if var >= 0 else NaN  # a valid covariance yields a non-negative variance


def portfolio_volatility(weights: Sequence[float], cov: Sequence[Sequence[float]]) -> float:
    """sqrt(w' Sigma w)."""
    var = portfolio_variance(weights, cov)
    return float(np.sqrt(var)) if np.isfinite(var) else NaN


def risk_contributions(weights: Sequence[float], cov: Sequence[Sequence[float]]) -> Dict[str, list]:
    """Per-asset marginal, component, and percentage contributions to volatility.

    Component contributions sum to the portfolio volatility (Euler allocation).
    Returns lists of NaN on invalid input or zero portfolio volatility.
    """
    w = _as_vector(weights)
    if w is None:
        return {"marginal": [NaN], "component": [NaN], "percent": [NaN]}
    c = _as_cov(cov, w.size)
    if c is None:
        return {"marginal": [NaN] * w.size, "component": [NaN] * w.size, "percent": [NaN] * w.size}
    vol = portfolio_volatility(w, c)
    if not np.isfinite(vol) or vol < 1e-15:
        nans = [NaN] * w.size
        return {"marginal": nans, "component": nans, "percent": nans}
    marginal = (c @ w) / vol           # dVol/dw_i
    component = w * marginal           # sums to vol
    percent = component / vol
    return {"marginal": list(marginal), "component": list(component), "percent": list(percent)}


def covariance_from_returns(asset_returns: Sequence[Sequence[float]]) -> list:
    """Sample covariance (ddof=1) of columns = assets, rows = periods."""
    r = np.asarray(asset_returns, dtype=float)
    if r.ndim != 2 or r.shape[0] < 2 or not np.all(np.isfinite(r)):
        return [[NaN]]
    return np.cov(r, rowvar=False, ddof=1).tolist()


def portfolio_return_series(weights: Sequence[float],
                            asset_returns: Sequence[Sequence[float]]) -> list:
    """Per-period portfolio returns R @ w (rows = periods, columns = assets)."""
    w = _as_vector(weights)
    r = np.asarray(asset_returns, dtype=float)
    if w is None or r.ndim != 2 or r.shape[1] != w.size or not np.all(np.isfinite(r)):
        return [NaN]
    return list(r @ w)


def _register_all() -> None:
    pc = ["portfolio"]
    register("portfolio.return.v1", name="Portfolio expected return", category="portfolio",
             formula="w . mu", inputs=["weights", "expected_returns"],
             units="ratio", sign_convention="weighted mean of asset returns",
             supported_asset_classes=pc,
             reference="aggregates asset returns, never forecast probabilities")
    register("portfolio.variance.v1", name="Portfolio variance", category="portfolio",
             formula="w' Sigma w", inputs=["weights", "cov"],
             units="ratio_squared", sign_convention="non-negative for a valid covariance",
             supported_asset_classes=pc)
    register("portfolio.volatility.v1", name="Portfolio volatility", category="portfolio",
             formula="sqrt(w' Sigma w)", inputs=["weights", "cov"],
             units="ratio", sign_convention="non-negative", supported_asset_classes=pc)
    register("portfolio.risk_contribution.v1", name="Risk contribution (Euler)", category="portfolio",
             formula="component_i = w_i (Sigma w)_i / vol; sum_i component_i = vol",
             inputs=["weights", "cov"], units="ratio",
             sign_convention="components sum to portfolio volatility", supported_asset_classes=pc,
             reference="Euler risk allocation")
    register("portfolio.covariance.v1", name="Sample covariance matrix", category="portfolio",
             formula="cov(columns=assets, ddof=1)", inputs=["asset_returns"],
             units="ratio_squared", sign_convention="symmetric positive semi-definite",
             supported_asset_classes=pc)


_register_all()
