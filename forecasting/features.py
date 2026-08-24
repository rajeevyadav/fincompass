"""Leakage-safe market feature construction.

All features are backward-looking and use only observations at or before the
sample date. Forward returns are created in a separate target step. The
feature set is deliberately reconstructable from adjusted OHLCV history so a
freeware deployment can reproduce it without proprietary factor databases.
"""
from __future__ import annotations

from typing import Dict, Iterable, Optional

import numpy as np
import pandas as pd


PRICE_FEATURES = [
    "ret_21", "ret_63", "ret_126", "ret_252",
    "rel_ret_21", "rel_ret_63", "rel_ret_126", "rel_ret_252",
    "vol_21", "vol_63", "vol_126",
    "benchmark_ret_21", "benchmark_ret_63", "benchmark_ret_126", "benchmark_ret_252",
    "benchmark_vol_63",
    "drawdown_126", "drawdown_252",
    "distance_52w_high", "sma_50_200",
    "volume_z_63",
]

OPTIONAL_FUNDAMENTAL_FEATURES = [
    "sec_revenue_growth_yoy",
    "sec_net_margin",
    "sec_operating_margin",
    "sec_gross_margin",
    "sec_current_ratio",
    "sec_debt_to_equity",
    "sec_fcf_margin",
    "sec_roa",
]


def _prepare_price_frame(df: pd.DataFrame) -> pd.DataFrame:
    if df is None or len(df) == 0:
        raise ValueError("price frame is empty")
    out = df.copy()
    out.index = pd.to_datetime(out.index).tz_localize(None)
    out = out.sort_index()
    cols = {str(c).lower(): c for c in out.columns}
    if "close" not in cols:
        raise ValueError("price frame must contain Close")
    rename = {cols["close"]: "Close"}
    if "volume" in cols:
        rename[cols["volume"]] = "Volume"
    out = out.rename(columns=rename)
    out["Close"] = pd.to_numeric(out["Close"], errors="coerce")
    if "Volume" in out:
        out["Volume"] = pd.to_numeric(out["Volume"], errors="coerce")
    out = out[~out.index.duplicated(keep="last")]
    return out


def build_price_features(stock: pd.DataFrame, benchmark: pd.DataFrame) -> pd.DataFrame:
    """Return a daily feature frame indexed by observation date.

    Features are calculated using only current/past observations. No shift with
    a negative lag appears here; that is enforced by tests.
    """
    s = _prepare_price_frame(stock)
    b = _prepare_price_frame(benchmark)
    aligned = pd.DataFrame(index=s.index.intersection(b.index).sort_values())
    aligned["close"] = s.reindex(aligned.index)["Close"]
    aligned["benchmark_close"] = b.reindex(aligned.index)["Close"]
    if "Volume" in s:
        aligned["volume"] = s.reindex(aligned.index)["Volume"]

    for lag in (21, 63, 126, 252):
        aligned[f"ret_{lag}"] = aligned["close"].pct_change(lag, fill_method=None)
        aligned[f"benchmark_ret_{lag}"] = aligned["benchmark_close"].pct_change(lag, fill_method=None)
        aligned[f"rel_ret_{lag}"] = aligned[f"ret_{lag}"] - aligned[f"benchmark_ret_{lag}"]

    daily_ret = aligned["close"].pct_change(fill_method=None)
    benchmark_daily_ret = aligned["benchmark_close"].pct_change(fill_method=None)
    for window in (21, 63, 126):
        aligned[f"vol_{window}"] = daily_ret.rolling(window, min_periods=max(10, window // 2)).std() * np.sqrt(252.0)
    aligned["benchmark_vol_63"] = benchmark_daily_ret.rolling(63, min_periods=30).std() * np.sqrt(252.0)

    for window in (126, 252):
        roll_max = aligned["close"].rolling(window, min_periods=max(60, window // 2)).max()
        aligned[f"drawdown_{window}"] = aligned["close"] / roll_max - 1.0
    high_252 = aligned["close"].rolling(252, min_periods=126).max()
    aligned["distance_52w_high"] = aligned["close"] / high_252 - 1.0
    sma50 = aligned["close"].rolling(50, min_periods=40).mean()
    sma200 = aligned["close"].rolling(200, min_periods=120).mean()
    aligned["sma_50_200"] = sma50 / sma200 - 1.0

    if "volume" in aligned:
        log_volume = np.log1p(aligned["volume"].clip(lower=0))
        v_mean = log_volume.rolling(63, min_periods=30).mean()
        v_std = log_volume.rolling(63, min_periods=30).std().replace(0, np.nan)
        aligned["volume_z_63"] = (log_volume - v_mean) / v_std
    else:
        aligned["volume_z_63"] = np.nan

    return aligned[PRICE_FEATURES].replace([np.inf, -np.inf], np.nan)


def attach_forward_target(
    features: pd.DataFrame,
    stock: pd.DataFrame,
    benchmark: pd.DataFrame,
    horizon: int,
    excess_return_threshold: float = 0.0,
) -> pd.DataFrame:
    """Attach forward return labels to an already backward-looking feature frame."""
    if horizon < 1:
        raise ValueError("horizon must be positive")
    s = _prepare_price_frame(stock)
    b = _prepare_price_frame(benchmark)
    idx = features.index.intersection(s.index).intersection(b.index).sort_values()
    out = features.reindex(idx).copy()
    stock_close = s.reindex(idx)["Close"]
    bench_close = b.reindex(idx)["Close"]
    out["forward_return"] = stock_close.shift(-horizon) / stock_close - 1.0
    out["benchmark_forward_return"] = bench_close.shift(-horizon) / bench_close - 1.0
    out["forward_excess_return"] = out["forward_return"] - out["benchmark_forward_return"]
    out["target_outperform"] = (out["forward_excess_return"] > float(excess_return_threshold)).astype(float)
    end_dates = pd.Series(idx, index=idx).shift(-horizon)
    out["target_end_date"] = pd.to_datetime(end_dates.values)
    out.loc[out["forward_excess_return"].isna(), "target_outperform"] = np.nan
    return out


def sample_every_n_observations(df: pd.DataFrame, step: int = 21) -> pd.DataFrame:
    if step <= 0:
        raise ValueError("step must be positive")
    if len(df) == 0:
        return df.copy()
    return df.iloc[::step].copy()


def asof_merge_fundamentals(samples: pd.DataFrame, fundamentals: Optional[pd.DataFrame]) -> pd.DataFrame:
    """Backward as-of join for point-in-time fundamentals.

    `fundamentals` must include `available_date`; values are never joined before
    that date. This function intentionally does not accept a period-end-only
    field as a substitute for the public availability date.
    """
    if fundamentals is None or fundamentals.empty:
        return samples.copy()
    if "available_date" not in fundamentals.columns:
        raise ValueError("fundamentals must include available_date")
    left = samples.copy().reset_index().rename(columns={samples.index.name or "index": "date"})
    left["date"] = pd.to_datetime(left["date"])
    right = fundamentals.copy()
    right["available_date"] = pd.to_datetime(right["available_date"])
    right = right.sort_values("available_date")
    left = left.sort_values("date")
    merged = pd.merge_asof(left, right, left_on="date", right_on="available_date", direction="backward")
    return merged.set_index("date")


def feature_columns(df: pd.DataFrame) -> Iterable[str]:
    excluded = {
        "date", "ticker", "target_end_date", "target_outperform",
        "forward_return", "benchmark_forward_return", "forward_excess_return",
        "available_date", "filing_date", "fiscal_year",
    }
    for c in df.columns:
        if c not in excluded and pd.api.types.is_numeric_dtype(df[c]):
            yield c
