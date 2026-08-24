#!/usr/bin/env python3
"""Generate deterministic synthetic train/validation/test fixtures.

These files validate software behavior and statistical calibration plumbing.
They are deliberately marked synthetic and can never activate a live forecast.
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

import numpy as np
import pandas as pd

from forecasting.config import get_profile
from forecasting.dataset import write_dataset_bundle


def generate(rows_per_date: int = 32, dates: int = 360, seed: int = 37001) -> pd.DataFrame:
    rng = np.random.default_rng(seed)
    calendar = pd.bdate_range("1995-01-31", periods=dates, freq="20B")
    tickers = [f"SIM{i:03d}" for i in range(rows_per_date)]
    records = []
    regime = 0.0
    for di, date in enumerate(calendar):
        regime = 0.82 * regime + rng.normal(0, 0.35)
        market = rng.normal(0, 1)
        for ti, ticker in enumerate(tickers):
            quality = rng.normal(0, 1)
            momentum = rng.normal(0, 1) + 0.25 * market
            relative = rng.normal(0, 1) + 0.15 * quality
            volatility = abs(rng.normal(0.22, 0.08))
            valuation = rng.normal(0, 1)
            noise = rng.normal(0, 0.20)
            logit = -0.10 + 0.65 * relative + 0.45 * momentum + 0.30 * quality - 0.35 * volatility - 0.25 * valuation + 0.25 * regime + noise
            p = 1.0 / (1.0 + np.exp(-logit))
            y = int(rng.random() < p)
            excess = rng.normal(0.08 if y else -0.06, 0.12)
            records.append({
                "date": date,
                "target_end_date": date + pd.offsets.BDay(252),
                "ticker": ticker,
                "ret_21": 0.02 * momentum + rng.normal(0, 0.015),
                "ret_63": 0.06 * momentum + rng.normal(0, 0.03),
                "ret_126": 0.10 * momentum + rng.normal(0, 0.05),
                "ret_252": 0.16 * momentum + rng.normal(0, 0.08),
                "rel_ret_21": 0.018 * relative + rng.normal(0, 0.012),
                "rel_ret_63": 0.055 * relative + rng.normal(0, 0.025),
                "rel_ret_126": 0.095 * relative + rng.normal(0, 0.04),
                "rel_ret_252": 0.14 * relative + rng.normal(0, 0.07),
                "vol_21": volatility + rng.normal(0, 0.02),
                "vol_63": volatility + rng.normal(0, 0.015),
                "vol_126": volatility + rng.normal(0, 0.012),
                "benchmark_ret_21": 0.01 * market + rng.normal(0, 0.01),
                "benchmark_ret_63": 0.03 * market + rng.normal(0, 0.02),
                "benchmark_ret_126": 0.05 * market + rng.normal(0, 0.03),
                "benchmark_ret_252": 0.08 * market + rng.normal(0, 0.05),
                "benchmark_vol_63": abs(0.18 + 0.03 * regime + rng.normal(0, 0.02)),
                "drawdown_126": -abs(rng.normal(0.08 - 0.02 * momentum, 0.05)),
                "drawdown_252": -abs(rng.normal(0.12 - 0.03 * momentum, 0.07)),
                "distance_52w_high": -abs(rng.normal(0.09 - 0.025 * momentum, 0.05)),
                "sma_50_200": 0.04 * momentum + rng.normal(0, 0.03),
                "volume_z_63": rng.normal(0.2 * momentum, 0.9),
                "sec_revenue_growth_yoy": 0.08 + 0.06 * quality + rng.normal(0, 0.04),
                "sec_net_margin": 0.10 + 0.04 * quality + rng.normal(0, 0.025),
                "sec_operating_margin": 0.13 + 0.05 * quality + rng.normal(0, 0.03),
                "sec_gross_margin": 0.38 + 0.07 * quality + rng.normal(0, 0.04),
                "sec_current_ratio": np.clip(1.5 + 0.25 * quality + rng.normal(0, 0.25), 0.2, None),
                "sec_debt_to_equity": np.clip(0.9 - 0.20 * quality + rng.normal(0, 0.25), 0.0, None),
                "sec_fcf_margin": 0.09 + 0.04 * quality + rng.normal(0, 0.025),
                "sec_roa": 0.07 + 0.03 * quality + rng.normal(0, 0.02),
                "forward_return": excess + rng.normal(0.08, 0.10),
                "benchmark_forward_return": rng.normal(0.08, 0.08),
                "forward_excess_return": excess,
                "target_outperform": y,
            })
    return pd.DataFrame(records)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", default="datasets/fixtures")
    args = parser.parse_args()
    settings = get_profile("strict")
    dataset = generate()
    manifest = write_dataset_bundle(
        dataset,
        args.output,
        settings,
        synthetic=True,
        provenance={"generator": "tools/generate_validation_fixtures.py", "purpose": "software/statistical regression testing only", "seed": settings.random_seed},
        data_quality={
            "point_in_time_features": True,
            "survivorship_control": False,
            "delistings_included": False,
            "corporate_action_adjusted": False,
            "note": "Synthetic fixtures are never evidence of market forecasting performance.",
        },
    )
    print(f"Wrote {args.output}: {manifest['files']}")


if __name__ == "__main__":
    main()
