from __future__ import annotations

import json
from pathlib import Path
import shutil

import numpy as np
import pandas as pd

from forecasting.features import build_monthly_relative_features
from forecasting.registry import clear_active_model, get_active_manifest, load_model, set_active_model
from tools.generate_release_manifest import non_public_model_files, release_files


def _bundled_manifest() -> dict | None:
    paths = sorted(Path("models").glob("bundled-monthly-12m-*.json"))
    paths = [p for p in paths if not p.name.endswith("-SUMMARY.json")]
    if not paths:
        return None
    assert len(paths) == 1
    return json.loads(paths[0].read_text(encoding="utf-8"))


def _daily_history(scale: float = 1.0, tilt: float = 0.0) -> pd.DataFrame:
    idx = pd.bdate_range("2018-01-02", "2026-08-20")
    t = np.arange(len(idx), dtype=float)
    close = scale * (100.0 * np.exp((0.00025 + tilt) * t) * (1.0 + 0.025 * np.sin(t / 43.0)))
    return pd.DataFrame({"Close": close, "Volume": 1_000_000 + (t % 101) * 1000}, index=idx)


def test_bundled_reference_model_loads_and_predicts_from_runtime_monthly_contract():
    manifest = _bundled_manifest()
    if manifest is None:
        # Public-safe source archives intentionally omit REVIEW_REQUIRED model bytes.
        assert not list(Path("models").glob("bundled-monthly-12m-*.joblib"))
        return
    assert manifest["validation_tier"] == "validated_research"
    assert manifest["validation"]["gate"]["passed"] is True
    assert manifest["target"]["horizon_months"] == 12
    assert (manifest.get("dataset_provenance") or {}).get("feature_contract") == "monthly_relative_v1"
    model, loaded = load_model(model_id=manifest["model_id"])
    assert model is not None and loaded is not None
    features = build_monthly_relative_features(_daily_history(1.2, 0.00003), _daily_history(1.0, 0.0))
    sample = features.tail(1)
    assert not [name for name in model.feature_names if name not in sample.columns]
    prediction = model.predict_with_uncertainty(sample)[0]
    assert 0.0 <= prediction["probability_outperform"] <= 1.0
    assert len(prediction["uncertainty_interval"]) == 2


def test_bundled_reference_model_can_be_explicitly_activated_in_isolated_registry(tmp_path):
    manifest = _bundled_manifest()
    if manifest is None:
        assert not list(Path("models").glob("bundled-monthly-12m-*.joblib"))
        return
    model_file = Path("models") / manifest["model_file"]
    manifest_file = next(p for p in Path("models").glob("bundled-monthly-12m-*.json") if not p.name.endswith("-SUMMARY.json"))
    shutil.copy2(model_file, tmp_path / model_file.name)
    shutil.copy2(manifest_file, tmp_path / manifest_file.name)
    pointer = set_active_model(manifest["model_id"], root=tmp_path)
    assert pointer["model_id"] == manifest["model_id"]
    active = get_active_manifest(root=tmp_path)
    assert active and active["validation_tier"] == "validated_research"
    assert clear_active_model(root=tmp_path) is True


def test_review_required_reference_model_is_excluded_from_public_release_set():
    blocked = non_public_model_files()
    public = {path.relative_to(Path.cwd()).as_posix() for path in release_files()}
    private_manifests = [rel for rel in blocked if rel.startswith("models/") and rel.endswith(".json") and not rel.endswith("-SUMMARY.json")]
    # In a private working tree the model must be blocked from public packaging.
    # In a public extraction there may be no non-public artifact at all.
    for rel in blocked:
        assert rel not in public
    if _bundled_manifest() is not None:
        manifest = _bundled_manifest()
        sharing = (manifest.get("dataset_provenance") or {}).get("sharing_status")
        if sharing == "PUBLIC":
            assert not any("bundled-monthly-12m-" in rel for rel in private_manifests)
        else:
            assert any("bundled-monthly-12m-" in rel for rel in private_manifests)
