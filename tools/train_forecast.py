#!/usr/bin/env python3
"""Train, calibrate, locked-test, gate and register a FinCompass forecast model."""
from __future__ import annotations

import argparse
import sys
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from forecasting.config import get_profile, settings_from_dict
from forecasting.dataset import load_dataset_bundle
from forecasting.model import train_validate_ensemble
from forecasting.registry import save_model


def main():
    p = argparse.ArgumentParser()
    p.add_argument("dataset", help="Dataset bundle directory containing train.csv, validation.csv, test.csv and dataset_manifest.json")
    p.add_argument("--profile", default="strict", choices=["strict", "standard", "exploratory"])
    p.add_argument("--settings-json", help="Optional JSON file overriding profile fields")
    p.add_argument("--name", default="default", help="Registry profile name")
    p.add_argument("--output-report", default=None)
    args = p.parse_args()

    settings = get_profile(args.profile)
    if args.settings_json:
        override = json.loads(Path(args.settings_json).read_text(encoding="utf-8"))
        settings = settings_from_dict(override, base=args.profile)
    train, validation, test, manifest = load_dataset_bundle(args.dataset)
    model, report, predictions = train_validate_ensemble(train, validation, test, manifest, settings)
    saved = save_model(model, report, manifest, profile_name=args.name)
    out_report = Path(args.output_report or (Path(args.dataset) / "validation_report.json"))
    out_report.write_text(json.dumps({"model": saved, "report": report}, indent=2, sort_keys=True), encoding="utf-8")
    predictions.to_csv(Path(args.dataset) / "locked_test_predictions.csv", index=False)
    print(json.dumps({
        "model_id": saved["model_id"],
        "validation_tier": report["validation_tier"],
        "gate_passed": report["gate"]["passed"],
        "locked_test_metrics": report["locked_test_metrics"],
        "report": str(out_report),
    }, indent=2))


if __name__ == "__main__":
    main()
