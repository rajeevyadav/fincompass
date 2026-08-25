from hashlib import sha256
import json
from pathlib import Path

import joblib
import pytest

from forecasting.registry import (
    clear_active_model,
    get_active_manifest,
    list_model_manifests,
    load_model,
    registry_status,
    set_active_model,
)


def _write_model(root: Path, model_id: str, *, tier='validated_research', live_eligible=True):
    root.mkdir(parents=True, exist_ok=True)
    model_file = f'test-{model_id}.joblib'
    payload = {'model_id': model_id, 'payload': 7}
    joblib.dump(payload, root / model_file)
    digest = sha256((root / model_file).read_bytes()).hexdigest()
    manifest = {
        'forecast_engine_version': 'test',
        'profile_name': 'test',
        'validation_tier': tier,
        'created_at': '2026-08-24T12:00:00+00:00',
        'dataset_provenance': {'live_eligible_target': live_eligible},
        'model_id': model_id,
        'model_file': model_file,
        'model_sha256': digest,
    }
    (root / f'test-{model_id}.json').write_text(json.dumps(manifest), encoding='utf-8')
    return manifest


def test_validated_model_is_not_active_until_explicit_activation(tmp_path):
    _write_model(tmp_path, 'abc123')
    assert registry_status(tmp_path)['usable_models'] == 1
    assert registry_status(tmp_path)['active_model'] is None
    model, manifest = load_model(root=tmp_path)
    assert model is None and manifest is None

    pointer = set_active_model('abc123', experiment_id='exp-1', root=tmp_path)
    assert pointer['model_id'] == 'abc123'
    assert get_active_manifest(tmp_path)['model_id'] == 'abc123'
    model, manifest = load_model(root=tmp_path)
    assert model['payload'] == 7
    assert manifest['model_id'] == 'abc123'
    assert registry_status(tmp_path)['models'][0]['is_active'] is True


def test_activation_rejects_research_only_recipe_and_rejected_tier(tmp_path):
    _write_model(tmp_path, 'research-only', live_eligible=False)
    with pytest.raises(ValueError, match='research-only'):
        set_active_model('research-only', root=tmp_path)
    _write_model(tmp_path, 'rejected', tier='rejected')
    with pytest.raises(ValueError, match='validated_research'):
        set_active_model('rejected', root=tmp_path)


def test_activation_pointer_is_hash_bound_and_clearable(tmp_path):
    manifest = _write_model(tmp_path, 'bound')
    set_active_model('bound', root=tmp_path)
    assert get_active_manifest(tmp_path) is not None
    # Tampering with the serialized artifact invalidates the live pointer.
    (tmp_path / manifest['model_file']).write_bytes(b'tampered')
    assert get_active_manifest(tmp_path) is None
    assert registry_status(tmp_path)['activation_pointer_present'] is True
    assert registry_status(tmp_path)['activation_pointer_valid'] is False
    assert clear_active_model(tmp_path) is True
    assert clear_active_model(tmp_path) is False


def test_active_pointer_file_is_not_misread_as_model_manifest(tmp_path):
    _write_model(tmp_path, 'one')
    set_active_model('one', root=tmp_path)
    manifests = list_model_manifests(tmp_path)
    assert [m['model_id'] for m in manifests] == ['one']
