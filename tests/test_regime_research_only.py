"""The regime-aware family ships as a research alternative, not a maintained
runtime family. This pins that honest state so it cannot drift silently."""
from __future__ import annotations

import glob
import json

from services.model_builder import RESEARCH_ONLY_FAMILIES


def _regime_manifests():
    for path in glob.glob("models/bayesian-regime-*.json"):
        if path.endswith("-SUMMARY.json"):
            continue
        with open(path, encoding="utf-8") as fh:
            yield path, json.load(fh)


def test_regime_family_is_declared_research_only():
    assert "bayesian_regime" in RESEARCH_ONLY_FAMILIES


def test_bundled_regime_models_are_not_guided_or_retrainable():
    manifests = list(_regime_manifests())
    assert manifests, "expected bundled regime manifests to exist"
    for path, m in manifests:
        assert m.get("guided_eligible") is False, f"{path} must not be Guided-eligible"
        contract = m.get("training_contract") or {}
        assert contract.get("retrain_supported") is False, f"{path} must not advertise retraining"
        assert contract.get("trainer_family") == "bayesian_regime", f"{path} family mismatch"
