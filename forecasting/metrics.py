"""Probability-forecast validation metrics and clustered bootstrap."""
from __future__ import annotations

from typing import Any, Dict, Iterable, Tuple
import math

import numpy as np
import pandas as pd
from sklearn.linear_model import LogisticRegression
from sklearn.metrics import (
    average_precision_score,
    brier_score_loss,
    log_loss,
    roc_auc_score,
)


def clip_prob(p: np.ndarray) -> np.ndarray:
    return np.clip(np.asarray(p, dtype=float), 1e-6, 1.0 - 1e-6)


def expected_calibration_error(y: np.ndarray, p: np.ndarray, bins: int = 10) -> float:
    y = np.asarray(y, dtype=float)
    p = clip_prob(p)
    edges = np.linspace(0.0, 1.0, bins + 1)
    total = len(y)
    ece = 0.0
    for i in range(bins):
        if i == bins - 1:
            mask = (p >= edges[i]) & (p <= edges[i + 1])
        else:
            mask = (p >= edges[i]) & (p < edges[i + 1])
        if not np.any(mask):
            continue
        ece += (mask.sum() / total) * abs(float(y[mask].mean()) - float(p[mask].mean()))
    return float(ece)


def calibration_slope_intercept(y: np.ndarray, p: np.ndarray) -> Tuple[float, float]:
    y = np.asarray(y, dtype=int)
    p = clip_prob(p)
    if len(np.unique(y)) < 2:
        return float("nan"), float("nan")
    logit = np.log(p / (1.0 - p)).reshape(-1, 1)
    model = LogisticRegression(C=1e6, solver="lbfgs", max_iter=1000)
    model.fit(logit, y)
    return float(model.coef_[0, 0]), float(model.intercept_[0])


def evaluate_probabilities(y: np.ndarray, p: np.ndarray, reference_rate: float | None = None) -> Dict[str, float]:
    y = np.asarray(y, dtype=int)
    p = clip_prob(p)
    if reference_rate is None:
        reference_rate = float(np.mean(y))
    reference_rate = float(np.clip(reference_rate, 1e-6, 1 - 1e-6))
    baseline = np.full(len(y), reference_rate, dtype=float)
    brier = float(brier_score_loss(y, p))
    base_brier = float(brier_score_loss(y, baseline))
    ll = float(log_loss(y, p, labels=[0, 1]))
    base_ll = float(log_loss(y, baseline, labels=[0, 1]))
    try:
        auc = float(roc_auc_score(y, p))
    except ValueError:
        auc = float("nan")
    try:
        ap = float(average_precision_score(y, p))
    except ValueError:
        ap = float("nan")
    slope, intercept = calibration_slope_intercept(y, p)
    return {
        "samples": int(len(y)),
        "event_rate": float(np.mean(y)),
        "brier": brier,
        "baseline_brier": base_brier,
        "brier_skill": float(1.0 - brier / base_brier) if base_brier > 0 else float("nan"),
        "log_loss": ll,
        "baseline_log_loss": base_ll,
        "log_loss_skill": float(1.0 - ll / base_ll) if base_ll > 0 else float("nan"),
        "roc_auc": auc,
        "average_precision": ap,
        "ece_10": expected_calibration_error(y, p, bins=10),
        "calibration_slope": slope,
        "calibration_intercept": intercept,
    }


def date_cluster_bootstrap(
    frame: pd.DataFrame,
    probability_column: str,
    *,
    target_column: str = "target_outperform",
    date_column: str = "date",
    reference_rate: float,
    draws: int = 300,
    seed: int = 37001,
    level: float = 0.90,
    block_dates: int = 1,
) -> Dict[str, Dict[str, float]]:
    """Moving-date-block bootstrap with same-date cross-sectional clustering.

    Sampling complete dates preserves cross-sectional dependence. Sampling
    contiguous blocks of dates additionally preserves serial dependence caused
    by overlapping forward-return horizons. `block_dates=1` reduces to the
    simpler same-date-only cluster bootstrap.
    """
    work = frame[[date_column, target_column, probability_column]].dropna().copy()
    work[date_column] = pd.to_datetime(work[date_column])
    dates = np.array(sorted(work[date_column].unique()))
    if len(dates) < 5:
        return {}
    grouped = {d: work[work[date_column] == d] for d in dates}
    rng = np.random.default_rng(seed)
    names = ["brier_skill", "log_loss_skill", "roc_auc", "ece_10", "calibration_slope"]
    samples = {k: [] for k in names}
    block = max(1, min(int(block_dates), len(dates)))
    starts = np.arange(0, len(dates) - block + 1)
    for _ in range(int(draws)):
        picked = []
        while len(picked) < len(dates):
            start = int(rng.choice(starts))
            picked.extend(dates[start:start + block])
        picked = picked[:len(dates)]
        boot = pd.concat([grouped[d] for d in picked], ignore_index=True)
        m = evaluate_probabilities(
            boot[target_column].to_numpy(),
            boot[probability_column].to_numpy(),
            reference_rate=reference_rate,
        )
        for k in names:
            v = m.get(k)
            if v is not None and math.isfinite(float(v)):
                samples[k].append(float(v))
    tail = (1.0 - level) / 2.0
    out: Dict[str, Dict[str, float]] = {
        "_meta": {
            "method": "moving_date_block_cross_sectional_cluster",
            "block_dates": int(block),
            "distinct_dates": int(len(dates)),
            "draws": int(draws),
            "level": float(level),
        }
    }
    for k, vals in samples.items():
        if not vals:
            continue
        arr = np.asarray(vals)
        lo, hi = np.quantile(arr, [tail, 1.0 - tail])
        out[k] = {"low": float(lo), "median": float(np.median(arr)), "high": float(hi)}
    return out
