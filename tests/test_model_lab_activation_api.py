from fastapi.testclient import TestClient

import api

client = TestClient(api.app)


def test_activate_requires_validated_experiment(monkeypatch):
    monkeypatch.setattr(api.research_store, 'get_experiment', lambda experiment_id: {
        'experiment_id': experiment_id,
        'status': 'rejected',
        'model_id': None,
        'lineage': {'live_eligible_target': True},
    })
    response = client.post('/api/v4/model-lab/experiments/exp-rejected/activate')
    assert response.status_code == 409


def test_activate_calls_registry_only_for_validated_live_eligible_experiment(monkeypatch):
    exp = {
        'experiment_id': 'exp-good',
        'status': 'validated',
        'model_id': 'model-good',
        'lineage': {'live_eligible_target': True},
    }
    monkeypatch.setattr(api.research_store, 'get_experiment', lambda experiment_id: exp)
    calls = {}

    def fake_activate(model_id, *, experiment_id=None):
        calls.update(model_id=model_id, experiment_id=experiment_id)
        return {'model_id': model_id, 'experiment_id': experiment_id}

    monkeypatch.setattr(api, 'set_active_model', fake_activate)
    response = client.post('/api/v4/model-lab/experiments/exp-good/activate')
    assert response.status_code == 200
    assert calls == {'model_id': 'model-good', 'experiment_id': 'exp-good'}
    assert response.json()['activated'] is True


def test_research_only_experiment_cannot_activate(monkeypatch):
    monkeypatch.setattr(api.research_store, 'get_experiment', lambda experiment_id: {
        'experiment_id': experiment_id,
        'status': 'validated',
        'model_id': 'research-model',
        'lineage': {'live_eligible_target': False},
    })
    response = client.post('/api/v4/model-lab/experiments/exp-research/activate')
    assert response.status_code == 409
    assert 'research-only' in response.json()['detail']
