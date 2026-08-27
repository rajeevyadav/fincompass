#!/usr/bin/env python3
"""Audit a FinCompass forecast dataset bundle before model fitting."""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any, Dict

import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from forecasting.config import ForecastSettings
from forecasting.dataset import load_dataset_bundle


def audit_bundle(path: str | Path) -> Dict[str, Any]:
    train, validation, test, manifest = load_dataset_bundle(path)
    settings = ForecastSettings(**manifest.get("settings", {})).validate()
    parts = {"train": train, "validation": validation, "test": test}
    checks: Dict[str, bool] = {}
    details: Dict[str, Any] = {}

    for name, frame in parts.items():
        dates = pd.to_datetime(frame["date"], errors="coerce")
        ends = pd.to_datetime(frame["target_end_date"], errors="coerce")
        target = pd.to_numeric(frame["target_outperform"], errors="coerce")
        checks[f"{name}_nonempty"] = len(frame) > 0
        checks[f"{name}_dates_valid"] = bool(dates.notna().all() and ends.notna().all())
        checks[f"{name}_target_binary"] = bool(target.notna().all() and set(target.unique()).issubset({0.0, 1.0}))
        checks[f"{name}_both_classes"] = bool(target.nunique() == 2)
        details[name] = {
            "rows": int(len(frame)),
            "distinct_dates": int(dates.nunique()),
            "start": dates.min().date().isoformat() if dates.notna().any() else None,
            "end": dates.max().date().isoformat() if dates.notna().any() else None,
            "event_rate": float(target.mean()) if target.notna().any() else None,
        }

    train_dates = pd.to_datetime(train["date"])
    val_dates = pd.to_datetime(validation["date"])
    test_dates = pd.to_datetime(test["date"])
    checks["chronological_partition_order"] = bool(train_dates.max() < val_dates.min() < test_dates.min())
    checks["train_target_purged_before_validation"] = bool(pd.to_datetime(train["target_end_date"]).max() < val_dates.min())
    checks["validation_target_purged_before_test"] = bool(pd.to_datetime(validation["target_end_date"]).max() < test_dates.min())
    checks["test_temporal_breadth"] = bool(
        test_dates.nunique() >= settings.min_test_dates
        and (test_dates.max() - test_dates.min()).days >= settings.min_test_span_days
    )

    required_quality = ["point_in_time_features", "survivorship_control", "delistings_included", "corporate_action_adjusted"]
    quality = manifest.get("data_quality") or {}
    evidence = quality.get("evidence") or {}
    market_quality = {
        key: {"declared": bool(quality.get(key)), "evidence_recorded": bool(evidence.get(key))}
        for key in required_quality
    }
    details["market_quality"] = market_quality
    details["synthetic"] = bool(manifest.get("synthetic"))
    details["target"] = manifest.get("target")
    details["dataset_schema_version"] = manifest.get("schema_version")
    passed = bool(all(checks.values()))
    return {"passed": passed, "checks": checks, "details": details}


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("dataset", help="Dataset bundle directory")
    parser.add_argument("--output", help="Optional JSON audit output path")
    args = parser.parse_args()
    report = audit_bundle(args.dataset)
    rendered = json.dumps(report, indent=2, sort_keys=True)
    if args.output:
        Path(args.output).write_text(rendered + "\n", encoding="utf-8")
    print(rendered)
    return 0 if report["passed"] else 2


if __name__ == "__main__":
    raise SystemExit(main())
