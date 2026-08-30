"""Failure-path safety for the retrain/replacement lifecycle.

None of these may corrupt the active model M1 or leave the registry ambiguous:
a rejected candidate, a corrupt candidate artifact, activation of a missing
model, a candidate with a missing parent, and an application "restart" between
candidate creation and activation.
"""
import pytest

from forecasting import registry as reg


class _DummyModel:
    def __init__(self, features):
        self.settings = {"benchmark": "^GSPC", "horizon_trading_days": 252}
        self.feature_names = list(features)


def _dataset(cutoff):
    return {"schema_version": "t", "files": {}, "split": {"test": {"end": cutoff}},
            "provenance": {"live_eligible_target": True, "feature_contract": "price_relative_v1"},
            "target": {"benchmark": "^GSPC", "horizon_months": 12}, "data_quality": {}}


def _save(root, features, cutoff, tier="validated_research", lineage=None):
    return reg.save_model(_DummyModel(features), {"validation_tier": tier, "gate": {"passed": True}},
                          _dataset(cutoff), profile_name="core-us-6m", root=root, lineage=lineage)


@pytest.fixture
def root(tmp_path):
    return tmp_path / "models"


def test_rejected_candidate_cannot_activate_and_m1_survives(root):
    m1 = _save(root, ["a", "b"], "2022-06-30")
    reg.set_active_model(m1["model_id"], root=root)
    m2 = _save(root, ["a", "b", "c"], "2026-08-28", tier="rejected")
    with pytest.raises(ValueError):
        reg.set_active_model(m2["model_id"], root=root)
    assert reg.get_active_manifest(root=root)["model_id"] == m1["model_id"]


def test_corrupt_candidate_artifact_blocks_activation_and_m1_survives(root):
    m1 = _save(root, ["a", "b"], "2022-06-30")
    reg.set_active_model(m1["model_id"], root=root)
    m2 = _save(root, ["a", "b", "c"], "2026-08-28")
    # corrupt the candidate artifact so its SHA-256 no longer matches the manifest
    (root / m2["model_file"]).write_bytes(b"corrupted")
    with pytest.raises(ValueError):
        reg.set_active_model(m2["model_id"], root=root)
    assert reg.get_active_manifest(root=root)["model_id"] == m1["model_id"]


def test_activating_missing_model_raises_and_m1_survives(root):
    m1 = _save(root, ["a", "b"], "2022-06-30")
    reg.set_active_model(m1["model_id"], root=root)
    with pytest.raises(ValueError):
        reg.set_active_model("deadbeefdeadbeef", root=root)
    assert reg.get_active_manifest(root=root)["model_id"] == m1["model_id"]


def test_candidate_with_missing_parent_still_valid(root):
    m1 = _save(root, ["a", "b"], "2022-06-30")
    reg.set_active_model(m1["model_id"], root=root)
    m2 = _save(root, ["a", "b", "c"], "2026-08-28",
               lineage={"parent_model_id": "0000000000000000", "update_type": "retrain"})
    # a dangling parent id is informational; the candidate itself is activatable
    reg.set_active_model(m2["model_id"], root=root)
    assert reg.get_active_manifest(root=root)["model_id"] == m2["model_id"]
    assert m1["model_id"] not in (reg.get_active_pointer(root=root)["model_id"],)


def test_restart_between_creation_and_activation_keeps_m1(root):
    m1 = _save(root, ["a", "b"], "2022-06-30")
    reg.set_active_model(m1["model_id"], root=root)
    _save(root, ["a", "b", "c"], "2026-08-28")  # candidate created, NOT activated
    # simulate a restart: re-read active state from disk
    assert reg.get_active_manifest(root=root)["model_id"] == m1["model_id"]
