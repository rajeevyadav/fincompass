"""Provider-independent European option analytics (Black-Scholes-Merton).

Prices European calls and puts and derives their Greeks from the closed-form
Black-Scholes-Merton model with a continuous dividend yield, then recovers
implied volatility by inverting the pricing function. Everything is computed
from explicit user inputs — spot, strike, risk-free rate, dividend yield,
volatility, time to expiry — so no market-data provider and no paid dependency
is required. The normal CDF/PDF are evaluated with the standard library
(``math.erf``); numpy/scipy are not needed.

Conventions (registered): continuously-compounded rates; volatility and time
are annualized; vega is reported per 1.00 (100 percentage-point) change in
volatility and theta per 1.0 year — callers scale to per-1%/per-day as needed.
Structurally invalid inputs (non-positive spot/strike/expiry/volatility, or a
market price outside the no-arbitrage bounds for implied vol) fail safely to
NaN rather than raising or returning a misleading number.

An option value or Greek here is a model identity for the stated inputs and
assumptions; it is not a forecast, a probability of profit, or a guaranteed
payoff, and no value produced here is promoted to a forecast feature.
"""
from __future__ import annotations

import math
from typing import Optional

from analytics.registry import register

NaN = float("nan")
CALL = "call"
PUT = "put"


def _finite_pos(*xs: float) -> bool:
    return all(_finite(x) and x > 0 for x in xs)


def _finite(x: object) -> bool:
    try:
        return math.isfinite(float(x))
    except (TypeError, ValueError):
        return False


def _norm_cdf(x: float) -> float:
    return 0.5 * (1.0 + math.erf(x / math.sqrt(2.0)))


def _norm_pdf(x: float) -> float:
    return math.exp(-0.5 * x * x) / math.sqrt(2.0 * math.pi)


def _d1_d2(spot: float, strike: float, rate: float, div_yield: float,
           vol: float, expiry: float):
    vsqrt = vol * math.sqrt(expiry)
    d1 = (math.log(spot / strike) + (rate - div_yield + 0.5 * vol * vol) * expiry) / vsqrt
    return d1, d1 - vsqrt


def price(option_type: str, spot: float, strike: float, rate: float,
          vol: float, expiry: float, div_yield: float = 0.0) -> float:
    """Black-Scholes-Merton price of a European call or put."""
    if option_type not in (CALL, PUT) or not _finite_pos(spot, strike, vol, expiry) \
            or not (_finite(rate) and _finite(div_yield)):
        return NaN
    d1, d2 = _d1_d2(spot, strike, rate, div_yield, vol, expiry)
    disc_s = spot * math.exp(-div_yield * expiry)
    disc_k = strike * math.exp(-rate * expiry)
    if option_type == CALL:
        return disc_s * _norm_cdf(d1) - disc_k * _norm_cdf(d2)
    return disc_k * _norm_cdf(-d2) - disc_s * _norm_cdf(-d1)


def delta(option_type: str, spot: float, strike: float, rate: float,
          vol: float, expiry: float, div_yield: float = 0.0) -> float:
    """dPrice/dSpot."""
    if option_type not in (CALL, PUT) or not _finite_pos(spot, strike, vol, expiry) \
            or not (_finite(rate) and _finite(div_yield)):
        return NaN
    d1, _ = _d1_d2(spot, strike, rate, div_yield, vol, expiry)
    edqt = math.exp(-div_yield * expiry)
    if option_type == CALL:
        return edqt * _norm_cdf(d1)
    return edqt * (_norm_cdf(d1) - 1.0)


def gamma(spot: float, strike: float, rate: float, vol: float, expiry: float,
          div_yield: float = 0.0) -> float:
    """d2Price/dSpot2 (identical for call and put)."""
    if not _finite_pos(spot, strike, vol, expiry) or not (_finite(rate) and _finite(div_yield)):
        return NaN
    d1, _ = _d1_d2(spot, strike, rate, div_yield, vol, expiry)
    return math.exp(-div_yield * expiry) * _norm_pdf(d1) / (spot * vol * math.sqrt(expiry))


def vega(spot: float, strike: float, rate: float, vol: float, expiry: float,
         div_yield: float = 0.0) -> float:
    """dPrice/dVol per 1.00 change in volatility (identical for call and put)."""
    if not _finite_pos(spot, strike, vol, expiry) or not (_finite(rate) and _finite(div_yield)):
        return NaN
    d1, _ = _d1_d2(spot, strike, rate, div_yield, vol, expiry)
    return spot * math.exp(-div_yield * expiry) * _norm_pdf(d1) * math.sqrt(expiry)


def theta(option_type: str, spot: float, strike: float, rate: float,
          vol: float, expiry: float, div_yield: float = 0.0) -> float:
    """dPrice/dTime per 1.0 year (typically negative for long options)."""
    if option_type not in (CALL, PUT) or not _finite_pos(spot, strike, vol, expiry) \
            or not (_finite(rate) and _finite(div_yield)):
        return NaN
    d1, d2 = _d1_d2(spot, strike, rate, div_yield, vol, expiry)
    disc_s = spot * math.exp(-div_yield * expiry)
    disc_k = strike * math.exp(-rate * expiry)
    term = -disc_s * _norm_pdf(d1) * vol / (2.0 * math.sqrt(expiry))
    if option_type == CALL:
        return term - rate * disc_k * _norm_cdf(d2) + div_yield * disc_s * _norm_cdf(d1)
    return term + rate * disc_k * _norm_cdf(-d2) - div_yield * disc_s * _norm_cdf(-d1)


def rho(option_type: str, spot: float, strike: float, rate: float,
        vol: float, expiry: float, div_yield: float = 0.0) -> float:
    """dPrice/dRate per 1.00 change in the rate."""
    if option_type not in (CALL, PUT) or not _finite_pos(spot, strike, vol, expiry) \
            or not (_finite(rate) and _finite(div_yield)):
        return NaN
    _, d2 = _d1_d2(spot, strike, rate, div_yield, vol, expiry)
    disc_k = strike * expiry * math.exp(-rate * expiry)
    if option_type == CALL:
        return disc_k * _norm_cdf(d2)
    return -disc_k * _norm_cdf(-d2)


def implied_volatility(option_type: str, market_price: float, spot: float,
                       strike: float, rate: float, expiry: float,
                       div_yield: float = 0.0, *, tol: float = 1e-8,
                       max_iter: int = 200) -> float:
    """Volatility that reprices the option to ``market_price`` (bisection).

    Returns NaN if the inputs are invalid or the price lies outside the
    volatility-monotone range achievable in the search bracket.
    """
    if option_type not in (CALL, PUT) or not _finite_pos(spot, strike, expiry) \
            or not (_finite(market_price) and market_price > 0) \
            or not (_finite(rate) and _finite(div_yield)):
        return NaN
    lo, hi = 1e-6, 5.0  # 0.0001% to 500% annual vol
    f_lo = price(option_type, spot, strike, rate, lo, expiry, div_yield) - market_price
    f_hi = price(option_type, spot, strike, rate, hi, expiry, div_yield) - market_price
    if not (_finite(f_lo) and _finite(f_hi)) or f_lo * f_hi > 0:
        return NaN  # price not bracketed -> no implied vol in range
    for _ in range(max_iter):
        mid = 0.5 * (lo + hi)
        f_mid = price(option_type, spot, strike, rate, mid, expiry, div_yield) - market_price
        if not _finite(f_mid):
            return NaN
        if abs(f_mid) < tol or (hi - lo) < tol:
            return mid
        if f_lo * f_mid <= 0:
            hi = mid
        else:
            lo, f_lo = mid, f_mid
    return 0.5 * (lo + hi)


def _register_all() -> None:
    oc = ["option"]
    register("options.bsm_price.v1", name="Option price (Black-Scholes-Merton)",
             category="options",
             formula="call = S e^-qT N(d1) - K e^-rT N(d2); put via -d1,-d2; d1=(ln(S/K)+(r-q+σ²/2)T)/(σ√T)",
             inputs=["option_type", "spot", "strike", "rate", "vol", "expiry", "div_yield"],
             units="currency", sign_convention="call rises with spot, put falls",
             supported_asset_classes=oc, period_assumption="European exercise; annualized inputs",
             reference="Black-Scholes-Merton; not a forecast or probability of profit")
    register("options.delta.v1", name="Delta", category="options",
             formula="e^-qT N(d1) [call]; e^-qT (N(d1)-1) [put]",
             inputs=["option_type", "spot", "strike", "rate", "vol", "expiry", "div_yield"],
             units="ratio", sign_convention="call in [0,1], put in [-1,0]", supported_asset_classes=oc)
    register("options.gamma.v1", name="Gamma", category="options",
             formula="e^-qT n(d1) / (S σ√T)",
             inputs=["spot", "strike", "rate", "vol", "expiry", "div_yield"],
             units="per_currency", sign_convention="positive for long options", supported_asset_classes=oc)
    register("options.vega.v1", name="Vega (per 1.00 vol)", category="options",
             formula="S e^-qT n(d1) √T",
             inputs=["spot", "strike", "rate", "vol", "expiry", "div_yield"],
             units="currency_per_vol", sign_convention="positive for long options", supported_asset_classes=oc)
    register("options.theta.v1", name="Theta (per year)", category="options",
             formula="-S e^-qT n(d1) σ/(2√T) -/+ r K e^-rT N(±d2) +/- q S e^-qT N(±d1)",
             inputs=["option_type", "spot", "strike", "rate", "vol", "expiry", "div_yield"],
             units="currency_per_year", sign_convention="usually negative for long options",
             supported_asset_classes=oc)
    register("options.rho.v1", name="Rho (per 1.00 rate)", category="options",
             formula="K T e^-rT N(d2) [call]; -K T e^-rT N(-d2) [put]",
             inputs=["option_type", "spot", "strike", "rate", "vol", "expiry", "div_yield"],
             units="currency_per_rate", sign_convention="call positive, put negative", supported_asset_classes=oc)
    register("options.implied_vol.v1", name="Implied volatility", category="options",
             formula="vol solving BSM(price)=market_price via bisection",
             inputs=["option_type", "market_price", "spot", "strike", "rate", "expiry", "div_yield"],
             units="ratio", sign_convention="non-negative",
             supported_asset_classes=oc, zero_denominator_policy="unbracketed/invalid price -> NaN",
             reference="inversion of the BSM price; an implied, not forecast, volatility")


_register_all()
