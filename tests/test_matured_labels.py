"""Matured-label integrity + accumulated-corpus behavior.

Proves, on the actual target-construction code, that:
- a row at time t is a supervised label only once its t+H horizon endpoint exists
  (immature rows carry no target and are excluded);
- the label endpoint is exactly idx[t+H] (no shifted endpoint);
- extending the local corpus matures previously-immature rows (accumulation);
- features are strictly backward-looking (appending future data never changes a
  past feature value → no future leakage into inputs).
"""
import numpy as np
import pandas as pd

from forecasting.features import build_price_features, attach_forward_target


def _frame(start, periods, slope=1.0):
    idx = pd.bdate_range(start, periods=periods)
    px = pd.Series(np.arange(periods, dtype=float) * slope + 100.0, index=idx)
    return pd.DataFrame({"Open": px, "High": px * 1.01, "Low": px * 0.99,
                         "Close": px, "Adj Close": px, "Volume": 1000.0}, index=idx)


def _labeled(stock, bench, horizon):
    feats = build_price_features(stock, bench)
    return attach_forward_target(feats, stock, bench, horizon)


def test_immature_rows_excluded_and_endpoint_exact():
    H = 5
    stock, bench = _frame("2020-01-01", 80), _frame("2020-01-01", 80, slope=0.9)
    lab = _labeled(stock, bench, H)
    idx = lab.index
    # the final H rows have no matured outcome yet
    assert lab["target_outperform"].iloc[-H:].isna().all()
    assert lab["target_end_date"].iloc[-H:].isna().all()
    # a matured row's endpoint is EXACTLY t+H (not shifted)
    i = 10
    assert lab["target_end_date"].iloc[i] == idx[i + H]
    # every row before the final H is matured
    assert lab["target_outperform"].iloc[: len(idx) - H].notna().all()


def test_accumulation_matures_previously_immature_rows():
    H = 5
    lab_short = _labeled(_frame("2020-01-01", 50), _frame("2020-01-01", 50, 0.9), H)
    immature_dates = set(lab_short.index[lab_short["target_outperform"].isna()])
    matured_short = int(lab_short["target_outperform"].notna().sum())

    # accumulate 15 more trading days of history
    lab_long = _labeled(_frame("2020-01-01", 65), _frame("2020-01-01", 65, 0.9), H)
    matured_long = int(lab_long["target_outperform"].notna().sum())

    assert matured_long > matured_short  # more local data -> more matured labels
    # dates that were immature before (and now have their endpoint in-range) are matured
    cutoff = lab_long.index[-(H + 1)]
    for d in immature_dates:
        if d in lab_long.index and d <= cutoff:
            assert not np.isnan(lab_long.loc[d, "target_outperform"])


def test_features_are_backward_looking_no_future_leakage():
    f_short = build_price_features(_frame("2020-01-01", 60), _frame("2020-01-01", 60, 0.9))
    f_long = build_price_features(_frame("2020-01-01", 120), _frame("2020-01-01", 120, 0.9))
    common = f_short.index.intersection(f_long.index)
    assert len(common) > 10
    # every feature column is identical on shared dates regardless of future data
    for col in f_short.columns:
        pd.testing.assert_series_equal(
            f_short.loc[common, col], f_long.loc[common, col], check_names=False,
        )
