"""Robust peer-reference helpers for FinCompass v3.

Peer statistics are descriptive context, not forecasts. We use medians and IQRs
instead of means/standard deviations so one extreme multiple does not move the
reference point for an entire sector.
"""
from __future__ import annotations

from collections import defaultdict
from typing import Any, Dict, Iterable, List
import math

import numpy as np

# Broad sanity bounds used only for peer-stat construction. Values outside
# these ranges are treated as data-quality outliers and excluded from peer
# reference statistics; the raw company value is still retained elsewhere.
PEER_BOUNDS = {
    "pe": (0.1, 250.0),
    "pb": (0.05, 100.0),
    "ps": (0.02, 100.0),
    "ev_ebitda": (0.1, 150.0),
    "roe": (-1.0, 2.0),
    "roic": (-1.0, 1.5),
    "gross_margin": (-1.0, 1.0),
    "operating_margin": (-1.0, 1.0),
    "net_margin": (-1.0, 1.0),
    "fcf_margin": (-2.0, 2.0),
    "revenue_growth": (-1.0, 3.0),
    "earnings_growth": (-2.0, 5.0),
    "debt_to_equity": (-10.0, 30.0),
    "current_ratio": (0.0, 30.0),
    "interest_coverage": (-100.0, 500.0),
}


def _finite(v: Any):
    try:
        x = float(v)
    except (TypeError, ValueError):
        return None
    return x if math.isfinite(x) else None


def build_peer_reference(
    fundamentals: Iterable[Dict[str, Any]],
    min_sector_n: int = 5,
) -> Dict[str, Dict[str, Dict[str, float]]]:
    """Build sector -> metric -> {median,p25,p75,iqr,n}.

    The returned structure intentionally contains no ticker-level values. It is
    small, deterministic and safe to attach to a refresh run as a frozen peer
    snapshot so every company in that run is scored against the same reference.
    """
    buckets: Dict[str, Dict[str, List[float]]] = defaultdict(lambda: defaultdict(list))
    for fund in fundamentals:
        sector = str(fund.get("sector") or "").strip()
        if not sector:
            continue
        for metric, (lo, hi) in PEER_BOUNDS.items():
            x = _finite(fund.get(metric))
            if x is None or not (lo <= x <= hi):
                continue
            # yfinance commonly reports debtToEquity in percent form.
            if metric == "debt_to_equity" and x > 5:
                x /= 100.0
            buckets[sector][metric].append(x)

    out: Dict[str, Dict[str, Dict[str, float]]] = {}
    for sector, metrics in buckets.items():
        sector_out: Dict[str, Dict[str, float]] = {}
        for metric, vals in metrics.items():
            if len(vals) < min_sector_n:
                continue
            arr = np.asarray(vals, dtype=float)
            p25, med, p75 = np.percentile(arr, [25, 50, 75])
            sector_out[metric] = {
                "median": round(float(med), 8),
                "p25": round(float(p25), 8),
                "p75": round(float(p75), 8),
                "iqr": round(float(max(p75 - p25, 1e-9)), 8),
                "n": int(len(arr)),
            }
        if sector_out:
            out[sector] = sector_out
    return out


def peer_stat(reference: Dict[str, Any] | None, sector: str, metric: str):
    if not reference or not sector:
        return None
    return reference.get(sector, {}).get(metric)
