"""Provider-independent fixed-income analytics (closed-form, user-input driven).

Prices a fixed-coupon bond as the present value of its scheduled cash flows and
derives the standard risk measures (yield to maturity, Macaulay / modified
duration, convexity, DV01, current yield). Everything is computed from explicit
user inputs — face value, coupon, yield, maturity, payment frequency — so the
library needs no market-data provider and no paid dependency.

Conventions (registered): clean-price convention on coupon dates (no accrued
interest); ``freq`` coupons per year; yield and coupon are annual nominal rates
compounded ``freq`` times per year; duration and convexity are expressed in
years. Structurally invalid inputs (non-positive face/price/frequency, negative
maturity, non-finite yield) fail safely to NaN rather than raising or returning
a misleading number.

A bond price or yield here is an arithmetic identity for the stated cash flows
and inputs; it is not a forecast, a probability, or a guaranteed return, and no
value produced here is promoted to a forecast feature.
"""
from __future__ import annotations

import math
from typing import List, Optional

from analytics.registry import register

NaN = float("nan")


def _valid_common(face: float, coupon_rate: float, years: float, freq: int) -> bool:
    return (
        _finite(face) and face > 0
        and _finite(coupon_rate)
        and _finite(years) and years > 0
        and isinstance(freq, int) and freq >= 1
    )


def _finite(x: object) -> bool:
    try:
        return math.isfinite(float(x))
    except (TypeError, ValueError):
        return False


def _cash_flows(face: float, coupon_rate: float, years: float, freq: int):
    """Yield (period_index, cash_flow) pairs; last period includes face redemption."""
    n = int(round(years * freq))
    coupon = face * coupon_rate / freq
    for t in range(1, n + 1):
        cf = coupon + (face if t == n else 0.0)
        yield t, cf


def bond_price(face: float, coupon_rate: float, ytm: float, years: float,
               freq: int = 2) -> float:
    """Clean price = sum of coupon/redemption cash flows discounted at ``ytm``."""
    if not _valid_common(face, coupon_rate, years, freq) or not _finite(ytm):
        return NaN
    y = ytm / freq
    if y <= -1.0:  # discount factor base (1+y) must be positive
        return NaN
    return sum(cf / (1.0 + y) ** t for t, cf in _cash_flows(face, coupon_rate, years, freq))


def yield_to_maturity(price: float, face: float, coupon_rate: float, years: float,
                      freq: int = 2, *, tol: float = 1e-10, max_iter: int = 200) -> float:
    """Annual nominal YTM (compounded ``freq``/yr) that reprices the bond to ``price``.

    Solved by bisection on the price-vs-yield monotone function; returns NaN if
    the inputs are invalid or no yield in the search bracket reproduces ``price``.
    """
    if not _valid_common(face, coupon_rate, years, freq) or not _finite(price) or price <= 0:
        return NaN
    lo, hi = -0.99, 5.0  # -99% to +500% annual yield
    f_lo = bond_price(face, coupon_rate, lo, years, freq) - price
    f_hi = bond_price(face, coupon_rate, hi, years, freq) - price
    if not (_finite(f_lo) and _finite(f_hi)) or f_lo * f_hi > 0:
        return NaN  # price not bracketed -> no real yield in range
    for _ in range(max_iter):
        mid = 0.5 * (lo + hi)
        f_mid = bond_price(face, coupon_rate, mid, years, freq) - price
        if not _finite(f_mid):
            return NaN
        if abs(f_mid) < tol or (hi - lo) < tol:
            return mid
        if f_lo * f_mid <= 0:
            hi = mid
        else:
            lo, f_lo = mid, f_mid
    return 0.5 * (lo + hi)


def current_yield(face: float, coupon_rate: float, price: float) -> float:
    """Annual coupon income / clean price."""
    if not (_finite(face) and _finite(coupon_rate) and _finite(price)) or price <= 0 or face <= 0:
        return NaN
    return (face * coupon_rate) / price


def macaulay_duration(face: float, coupon_rate: float, ytm: float, years: float,
                      freq: int = 2) -> float:
    """PV-weighted average time to cash flow, in years."""
    price = bond_price(face, coupon_rate, ytm, years, freq)
    if not _finite(price) or price <= 0 or not _finite(ytm):
        return NaN
    y = ytm / freq
    if y <= -1.0:
        return NaN
    weighted = sum((t / freq) * cf / (1.0 + y) ** t
                   for t, cf in _cash_flows(face, coupon_rate, years, freq))
    return weighted / price


def modified_duration(face: float, coupon_rate: float, ytm: float, years: float,
                      freq: int = 2) -> float:
    """Macaulay duration / (1 + ytm/freq): approx % price change per 1.0 yield change."""
    mac = macaulay_duration(face, coupon_rate, ytm, years, freq)
    if not _finite(mac):
        return NaN
    return mac / (1.0 + ytm / freq)


def convexity(face: float, coupon_rate: float, ytm: float, years: float,
              freq: int = 2) -> float:
    """Second-order price sensitivity to yield, in year^2."""
    price = bond_price(face, coupon_rate, ytm, years, freq)
    if not _finite(price) or price <= 0 or not _finite(ytm):
        return NaN
    y = ytm / freq
    if y <= -1.0:
        return NaN
    acc = sum(cf * t * (t + 1) / (1.0 + y) ** (t + 2)
              for t, cf in _cash_flows(face, coupon_rate, years, freq))
    return acc / (price * freq ** 2)


def dv01(face: float, coupon_rate: float, ytm: float, years: float,
         freq: int = 2) -> float:
    """Dollar value of one basis point: price change for a 1bp yield decrease (>0)."""
    p0 = bond_price(face, coupon_rate, ytm, years, freq)
    p1 = bond_price(face, coupon_rate, ytm - 1e-4, years, freq)
    if not (_finite(p0) and _finite(p1)):
        return NaN
    return p1 - p0


def _register_all() -> None:
    eq = ["fixed_income"]
    register("fixedincome.bond_price.v1", name="Bond price (PV of cash flows)",
             category="fixed_income",
             formula="sum(CF_t / (1+ytm/freq)^t); CF includes coupon each period and face at maturity",
             inputs=["face", "coupon_rate", "ytm", "years", "freq"],
             units="currency", sign_convention="price rises as yield falls",
             supported_asset_classes=eq, period_assumption="coupon date, no accrued interest",
             reference="standard bond present-value; not a forecast or guaranteed return")
    register("fixedincome.ytm.v1", name="Yield to maturity",
             category="fixed_income",
             formula="yield solving price = sum(CF_t/(1+ytm/freq)^t) via bisection",
             inputs=["price", "face", "coupon_rate", "years", "freq"],
             units="ratio", sign_convention="inverse to price",
             supported_asset_classes=eq,
             zero_denominator_policy="unbracketed/invalid price -> NaN",
             reference="internal rate of return of the bond cash flows")
    register("fixedincome.current_yield.v1", name="Current yield", category="fixed_income",
             formula="annual coupon / clean price", inputs=["face", "coupon_rate", "price"],
             units="ratio", sign_convention="inverse to price", supported_asset_classes=eq)
    register("fixedincome.macaulay_duration.v1", name="Macaulay duration",
             category="fixed_income",
             formula="sum((t/freq) * PV(CF_t)) / price", inputs=["face", "coupon_rate", "ytm", "years", "freq"],
             units="years", sign_convention="longer duration = more rate-sensitive",
             supported_asset_classes=eq)
    register("fixedincome.modified_duration.v1", name="Modified duration",
             category="fixed_income",
             formula="Macaulay / (1 + ytm/freq)", inputs=["face", "coupon_rate", "ytm", "years", "freq"],
             units="years", sign_convention="approx -dP/P per unit yield",
             supported_asset_classes=eq)
    register("fixedincome.convexity.v1", name="Convexity", category="fixed_income",
             formula="sum(CF_t * t*(t+1) / (1+y)^(t+2)) / (price * freq^2)",
             inputs=["face", "coupon_rate", "ytm", "years", "freq"],
             units="years_squared", sign_convention="positive for option-free bonds",
             supported_asset_classes=eq)
    register("fixedincome.dv01.v1", name="DV01 (price value of a basis point)",
             category="fixed_income",
             formula="price(ytm - 1bp) - price(ytm)", inputs=["face", "coupon_rate", "ytm", "years", "freq"],
             units="currency", sign_convention="positive: price gain per 1bp yield drop",
             supported_asset_classes=eq)


_register_all()
