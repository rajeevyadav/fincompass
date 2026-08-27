"""Purged chronological dataset splitting."""
from __future__ import annotations

from dataclasses import dataclass
from typing import Dict, Tuple

import pandas as pd

from forecasting.config import ForecastSettings


@dataclass(frozen=True)
class SplitResult:
    train: pd.DataFrame
    validation: pd.DataFrame
    test: pd.DataFrame
    metadata: Dict[str, object]


def _date_range(df: pd.DataFrame) -> Dict[str, str | None]:
    if df.empty:
        return {"start": None, "end": None}
    d = pd.to_datetime(df["date"])
    return {"start": d.min().date().isoformat(), "end": d.max().date().isoformat()}


def purged_chronological_split(df: pd.DataFrame, settings: ForecastSettings) -> SplitResult:
    settings.validate()
    required = {"date", "target_end_date", "target_outperform"}
    missing = required - set(df.columns)
    if missing:
        raise ValueError(f"dataset missing split columns: {sorted(missing)}")
    work = df.copy()
    work["date"] = pd.to_datetime(work["date"])
    work["target_end_date"] = pd.to_datetime(work["target_end_date"])
    work = work.dropna(subset=["date", "target_end_date", "target_outperform"]).sort_values(["date", "ticker" if "ticker" in work.columns else "date"])
    dates = pd.Index(sorted(work["date"].unique()))
    if len(dates) < 12:
        raise ValueError("not enough unique sample dates for chronological split")
    train_cut_i = max(1, min(len(dates)-2, int(len(dates) * settings.train_fraction)))
    val_cut_i = max(train_cut_i+1, min(len(dates)-1, int(len(dates) * (settings.train_fraction + settings.validation_fraction))))
    val_start = pd.Timestamp(dates[train_cut_i])
    test_start = pd.Timestamp(dates[val_cut_i])

    # Purge any row whose forward target reaches into the next partition and
    # honor an explicit business-day embargo. The two controls can overlap;
    # the stricter cutoff wins.
    val_embargo_cutoff = val_start - pd.offsets.BDay(settings.embargo_trading_days)
    test_embargo_cutoff = test_start - pd.offsets.BDay(settings.embargo_trading_days)
    train = work[(work["date"] < val_embargo_cutoff) & (work["target_end_date"] < val_start)].copy()
    validation = work[(work["date"] >= val_start) & (work["date"] < test_embargo_cutoff) & (work["target_end_date"] < test_start)].copy()
    test = work[work["date"] >= test_start].copy()

    meta = {
        "method": "purged_chronological",
        "val_start": val_start.date().isoformat(),
        "test_start": test_start.date().isoformat(),
        "train": {"rows": len(train), **_date_range(train)},
        "validation": {"rows": len(validation), **_date_range(validation)},
        "test": {"rows": len(test), **_date_range(test)},
        "purge_rule": "Rows whose target_end_date crosses the next partition boundary are removed; an explicit business-day embargo is also applied before each downstream partition.",
        "embargo_trading_days": settings.embargo_trading_days,
    }
    if min(len(train), len(validation), len(test)) == 0:
        raise ValueError("purged split produced an empty partition; provide a longer history or shorter horizon")
    return SplitResult(train=train, validation=validation, test=test, metadata=meta)
