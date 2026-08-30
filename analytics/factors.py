"""Provider-independent factor / regression analytics (OLS).

Estimates linear factor exposures by ordinary least squares and exposes the
building blocks — coefficients, standard errors, t-statistics, R² / adjusted R²,
residuals — plus convenience wrappers for single- and multi-factor models and a
rolling market beta. Operates on plain return arrays the caller already holds
(numpy compute only): no market-data feed, no factor-data license, no paid
dependency. Factor return series themselves are supplied by the caller.

Governance: statistical significance is **not** investment significance. A
large t-statistic means an estimate is precisely measured in-sample, not that a
factor tilt will pay off out-of-sample; an R² describes in-sample fit, not
predictive power. Loadings are descriptive exposures, not forecasts, and no
value produced here is promoted to a forecast feature. Structurally invalid
inputs (too few observations, mismatched lengths, non-finite entries, or a
rank-deficient design) fail safely to NaN rather than raising or returning a
misleading number.
"""
from __future__ import annotations

from typing import Dict, List, Sequence

import numpy as np

from analytics.registry import register

NaN = float("nan")


def _matrix(x: Sequence, ncols: int | None = None) -> np.ndarray | None:
    a = np.asarray(x, dtype=float)
    if a.ndim == 1:
        a = a.reshape(-1, 1)
    if a.ndim != 2 or a.size == 0 or not np.all(np.isfinite(a)):
        return None
    if ncols is not None and a.shape[1] != ncols:
        return None
    return a


def _vector(y: Sequence[float]) -> np.ndarray | None:
    a = np.asarray(y, dtype=float)
    if a.ndim != 1 or a.size == 0 or not np.all(np.isfinite(a)):
        return None
    return a


def ols(y: Sequence[float], x: Sequence, *, add_intercept: bool = True) -> Dict[str, object]:
    """Ordinary least squares of ``y`` on ``x`` (columns = regressors).

    Returns coefficients (intercept first when added), standard errors,
    t-statistics, residuals, R², adjusted R², n, and degrees of freedom. All
    numeric fields are NaN on invalid or rank-deficient input.
    """
    yv = _vector(y)
    xm = _matrix(x)
    fail = {"coefficients": [NaN], "std_errors": [NaN], "t_stats": [NaN],
            "r_squared": NaN, "adj_r_squared": NaN, "residuals": [NaN],
            "n": 0, "df_resid": 0, "has_intercept": add_intercept}
    if yv is None or xm is None or xm.shape[0] != yv.size:
        return fail
    n = yv.size
    design = np.column_stack([np.ones(n), xm]) if add_intercept else xm
    k = design.shape[1]
    if n <= k:  # need more observations than parameters for a residual variance
        return fail
    if np.linalg.matrix_rank(design) < k:
        return fail
    beta, _, _, _ = np.linalg.lstsq(design, yv, rcond=None)
    fitted = design @ beta
    resid = yv - fitted
    rss = float(resid @ resid)
    tss = float(((yv - yv.mean()) ** 2).sum())
    df_resid = n - k
    sigma2 = rss / df_resid
    try:
        xtx_inv = np.linalg.inv(design.T @ design)
    except np.linalg.LinAlgError:
        return fail
    se = np.sqrt(np.maximum(np.diag(sigma2 * xtx_inv), 0.0))
    with np.errstate(divide="ignore", invalid="ignore"):
        tstat = np.where(se > 0, beta / se, NaN)
    r2 = 1.0 - rss / tss if tss > 0 else NaN
    adj_r2 = 1.0 - (1.0 - r2) * (n - 1) / df_resid if np.isfinite(r2) else NaN
    return {"coefficients": list(beta), "std_errors": list(se), "t_stats": list(tstat),
            "r_squared": r2, "adj_r_squared": adj_r2, "residuals": list(resid),
            "n": n, "df_resid": df_resid, "has_intercept": add_intercept}


def single_factor_model(asset_excess: Sequence[float], factor_excess: Sequence[float]) -> Dict[str, float]:
    """Alpha/beta of a one-factor (e.g. CAPM) regression with in-sample fit."""
    res = ols(asset_excess, factor_excess, add_intercept=True)
    coefs = res["coefficients"]
    if len(coefs) < 2 or not np.isfinite(coefs[0]):
        return {"alpha": NaN, "beta": NaN, "r_squared": NaN,
                "alpha_t": NaN, "beta_t": NaN}
    return {"alpha": coefs[0], "beta": coefs[1], "r_squared": res["r_squared"],
            "alpha_t": res["t_stats"][0], "beta_t": res["t_stats"][1]}


def factor_loadings(asset_excess: Sequence[float],
                    factor_returns: Sequence[Sequence[float]],
                    factor_names: Sequence[str] | None = None) -> Dict[str, object]:
    """Multi-factor OLS exposures: intercept (alpha) plus one loading per factor."""
    res = ols(asset_excess, factor_returns, add_intercept=True)
    coefs = res["coefficients"]
    if len(coefs) < 2 or not np.isfinite(coefs[0]):
        return {"alpha": NaN, "loadings": {}, "r_squared": NaN, "adj_r_squared": NaN}
    betas = coefs[1:]
    names = list(factor_names) if factor_names is not None else [f"factor_{i+1}" for i in range(len(betas))]
    if len(names) != len(betas):
        names = [f"factor_{i+1}" for i in range(len(betas))]
    tstats = res["t_stats"][1:]
    loadings = {nm: {"beta": b, "t_stat": t} for nm, b, t in zip(names, betas, tstats)}
    return {"alpha": coefs[0], "alpha_t": res["t_stats"][0], "loadings": loadings,
            "r_squared": res["r_squared"], "adj_r_squared": res["adj_r_squared"]}


def rolling_beta(asset_returns: Sequence[float], market_returns: Sequence[float],
                 window: int) -> List[float]:
    """Trailing market beta over a fixed window (NaN for the warm-up periods)."""
    a = _vector(asset_returns)
    m = _vector(market_returns)
    if a is None or m is None or a.size != m.size or not isinstance(window, int) \
            or window < 2 or window > a.size:
        return [NaN]
    out: List[float] = [NaN] * a.size
    for end in range(window, a.size + 1):
        aw = a[end - window:end]
        mw = m[end - window:end]
        var = float(mw.var(ddof=1))
        if var > 0:
            out[end - 1] = float(np.cov(aw, mw, ddof=1)[0, 1] / var)
    return out


def _register_all() -> None:
    fc = ["equity", "etf", "index", "factor"]
    register("factors.ols.v1", name="Ordinary least squares regression", category="factors",
             formula="beta = (X'X)^-1 X'y; se = sqrt(diag(sigma^2 (X'X)^-1)); t = beta/se",
             inputs=["y", "x"], units="mixed",
             sign_convention="context-dependent; significance is not investment significance",
             supported_asset_classes=fc, zero_denominator_policy="rank-deficient/insufficient n -> NaN",
             reference="standard OLS; in-sample fit, not predictive power")
    register("factors.single_factor.v1", name="Single-factor (CAPM-style) model", category="factors",
             formula="asset_excess = alpha + beta * factor_excess + e",
             inputs=["asset_excess", "factor_excess"], units="mixed",
             sign_convention="beta = market sensitivity; alpha in-sample only",
             supported_asset_classes=fc, reference="alpha/beta are descriptive, not a forecast")
    register("factors.loadings.v1", name="Multi-factor loadings", category="factors",
             formula="asset_excess = alpha + sum_k beta_k factor_k + e",
             inputs=["asset_excess", "factor_returns"], units="mixed",
             sign_convention="loadings are exposures, not forecasts",
             supported_asset_classes=fc)
    register("factors.rolling_beta.v1", name="Rolling market beta", category="factors",
             formula="cov(asset, market)/var(market) over a trailing window",
             inputs=["asset_returns", "market_returns", "window"], units="ratio",
             sign_convention="time-varying market sensitivity", supported_asset_classes=fc)


_register_all()
