"""Model replacement lifecycle at the registry level (candidate immutability,
no auto-activation, explicit replacement, activation history, load resolves the
new active model). Uses a temporary model root so nothing global is touched.

Covers D5-07 (validated candidate does not auto-activate), D5-08 (explicit
replacement), D5-09 (keep current), D5-10 (load resolves the new active model),
plus candidate identity/lineage and the activation-history ledger.
"""
from pathlib import Path

import pytest

from forecasting import registry as reg


class _DummyModel:
    def __init__(self, features):
        self.settings = {"benchmark": "^GSPC", "horizon_trading_days": 252}
        self.feature_names = list(features)


def _report():
    return {"validation_tier": "validated_research", "gate": {"passed": True}}


def _dataset(cutoff):
    return {
        "schema_version": "test-1",
        "files": {}, "split": {"test": {"end": cutoff}},
        "provenance": {"live_eligible_target": True, "feature_contract": "price_relative_v1",
                       "training_period_end": cutoff},
        "target": {"benchmark": "^GSPC", "horizon_months": 12},
        "data_quality": {},
    }


@pytest.fixture
def root(tmp_path):
    return tmp_path / "models"


def _save(root, features, cutoff, lineage=None):
    return reg.save_model(_DummyModel(features), _report(), _dataset(cutoff),
                          profile_name="core-us-6m", root=root, lineage=lineage)


def test_candidates_are_distinct_immutable_artifacts_with_lineage(root):
    m1 = _save(root, ["a", "b"], "2022-06-30")
    m2 = _save(root, ["a", "b", "c"], "2026-08-28",
               lineage={"parent_model_id": m1["model_id"], "update_type": "retrain",
                        "reason": "new_data_and_matured_labels"})
    assert m1["model_id"] != m2["model_id"]                  # new id
    assert m1["model_sha256"] != m2["model_sha256"]          # new artifact
    assert m2["lineage"]["parent_model_id"] == m1["model_id"]  # predecessor recorded
    # M1 artifact still present and unchanged (never overwritten)
    assert (root / m1["model_file"]).is_file()


def test_validated_candidate_does_not_auto_activate(root):
    m1 = _save(root, ["a", "b"], "2022-06-30")
    reg.set_active_model(m1["model_id"], root=root)
    # a newer validated candidate simply exists on disk
    _save(root, ["a", "b", "c"], "2026-08-28")
    active = reg.get_active_manifest(root=root)
    assert active is not None and active["model_id"] == m1["model_id"]  # still M1


def test_explicit_replacement_switches_active_and_records_history(root):
    m1 = _save(root, ["a", "b"], "2022-06-30")
    m2 = _save(root, ["a", "b", "c"], "2026-08-28",
               lineage={"parent_model_id": m1["model_id"], "update_type": "retrain"})
    reg.set_active_model(m1["model_id"], root=root)
    assert reg.get_active_pointer(root=root)["model_id"] == m1["model_id"]

    pointer = reg.set_active_model(m2["model_id"], activated_by="local_user", root=root)
    assert pointer["model_id"] == m2["model_id"]
    assert pointer["previous_model_id"] == m1["model_id"]
    # load resolves the NEW active model (D5-10)
    active = reg.get_active_manifest(root=root)
    assert active["model_id"] == m2["model_id"]

    history = reg.get_activation_history(root=root)
    assert history[-1]["previous_model_id"] == m1["model_id"]
    assert history[-1]["new_model_id"] == m2["model_id"]
    # M1 artifact is NOT deleted by replacement
    assert (root / m1["model_file"]).is_file()


def test_keep_current_leaves_m1_active_and_m2_available(root):
    m1 = _save(root, ["a", "b"], "2022-06-30")
    m2 = _save(root, ["a", "b", "c"], "2026-08-28")
    reg.set_active_model(m1["model_id"], root=root)
    # user keeps current: no activation call for m2
    assert reg.get_active_manifest(root=root)["model_id"] == m1["model_id"]
    # m2 remains selectable in the registry
    ids = {m["model_id"] for m in reg.list_model_manifests(root=root)}
    assert m2["model_id"] in ids and m1["model_id"] in ids
