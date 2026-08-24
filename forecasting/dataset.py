"""Forecast dataset construction, splitting, provenance and hashing."""
from __future__ import annotations

from hashlib import sha256
import json
from pathlib import Path
from typing import Any, Dict, Mapping, Optional

import pandas as pd

from forecasting.config import ForecastSettings
from forecasting.features import asof_merge_fundamentals, attach_forward_target, build_price_features, sample_every_n_observations
from forecasting.split import purged_chronological_split


def sha256_file(path: Path) -> str:
    h = sha256()
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


def build_ticker_samples(
    ticker: str,
    stock_prices: pd.DataFrame,
    benchmark_prices: pd.DataFrame,
    settings: ForecastSettings,
    fundamentals: Optional[pd.DataFrame] = None,
) -> pd.DataFrame:
    features = build_price_features(stock_prices, benchmark_prices)
    labeled = attach_forward_target(
        features,
        stock_prices,
        benchmark_prices,
        settings.horizon_trading_days,
        settings.excess_return_threshold,
    )
    sampled = sample_every_n_observations(labeled, settings.sample_step_trading_days)
    sampled = asof_merge_fundamentals(sampled, fundamentals)
    sampled = sampled.reset_index().rename(columns={sampled.index.name or "index": "date"})
    if "date" not in sampled.columns:
        sampled = sampled.rename(columns={sampled.columns[0]: "date"})
    sampled["ticker"] = ticker.upper()
    sampled["date"] = pd.to_datetime(sampled["date"])
    return sampled.dropna(subset=["target_outperform", "target_end_date"])


def build_universe_dataset(
    price_frames: Mapping[str, pd.DataFrame],
    benchmark_prices: pd.DataFrame,
    settings: ForecastSettings,
    fundamentals_by_ticker: Optional[Mapping[str, pd.DataFrame]] = None,
) -> pd.DataFrame:
    rows = []
    fundamentals_by_ticker = fundamentals_by_ticker or {}
    for ticker, frame in price_frames.items():
        if ticker.upper() == settings.benchmark.upper():
            continue
        try:
            part = build_ticker_samples(ticker, frame, benchmark_prices, settings, fundamentals_by_ticker.get(ticker))
            if not part.empty:
                rows.append(part)
        except Exception:
            continue
    if not rows:
        raise ValueError("no ticker samples could be built")
    out = pd.concat(rows, ignore_index=True)
    return out.sort_values(["date", "ticker"]).reset_index(drop=True)


def write_dataset_bundle(
    dataset: pd.DataFrame,
    output_dir: str | Path,
    settings: ForecastSettings,
    *,
    provenance: Dict[str, Any],
    data_quality: Dict[str, Any],
    synthetic: bool = False,
) -> Dict[str, Any]:
    out = Path(output_dir)
    out.mkdir(parents=True, exist_ok=True)
    # Prevent stale derived evidence from surviving a rebuilt dataset bundle.
    for stale_name in ("locked_test_predictions.csv", "validation_report.json", "dataset_audit.json", "dataset_manifest.sha256"):
        stale = out / stale_name
        if stale.exists():
            stale.unlink()
    split = purged_chronological_split(dataset, settings)
    files = {}
    for name, frame in [("train", split.train), ("validation", split.validation), ("test", split.test)]:
        path = out / f"{name}.csv"
        frame.to_csv(path, index=False)
        files[name] = {"file": path.name, "rows": len(frame), "sha256": sha256_file(path)}
    manifest = {
        "schema_version": "1.0.0-forecast-dataset1",
        "synthetic": bool(synthetic),
        "target": {
            "event": "stock return represented by the dataset price series over horizon exceeds benchmark return represented by its price series plus threshold",
            "return_basis": "Price-series return; corporate-action treatment is declared in data_quality/provenance.",
            "horizon_trading_days": settings.horizon_trading_days,
            "benchmark": settings.benchmark,
            "excess_return_threshold": settings.excess_return_threshold,
        },
        "settings": settings.to_dict(),
        "split": split.metadata,
        "files": files,
        "provenance": provenance,
        "data_quality": data_quality,
    }
    manifest_path = out / "dataset_manifest.json"
    manifest_path.write_text(json.dumps(manifest, indent=2, sort_keys=True), encoding="utf-8")
    (out / "dataset_manifest.sha256").write_text(sha256_file(manifest_path) + "  dataset_manifest.json\n", encoding="utf-8")
    return manifest


def load_dataset_bundle(path: str | Path):
    base = Path(path)
    manifest_path = base / "dataset_manifest.json"
    sidecar = base / "dataset_manifest.sha256"
    if sidecar.exists():
        expected = sidecar.read_text(encoding="utf-8").strip().split()[0]
        actual = sha256_file(manifest_path)
        if expected != actual:
            raise ValueError(f"dataset manifest hash mismatch: {manifest_path}")
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    frames = {}
    for name in ("train", "validation", "test"):
        meta = manifest["files"][name]
        file_path = base / meta["file"]
        if sha256_file(file_path) != meta["sha256"]:
            raise ValueError(f"dataset hash mismatch: {file_path}")
        frame = pd.read_csv(file_path)
        for c in ("date", "target_end_date", "available_date", "filing_date"):
            if c in frame.columns:
                frame[c] = pd.to_datetime(frame[c])
        frames[name] = frame
    return frames["train"], frames["validation"], frames["test"], manifest
