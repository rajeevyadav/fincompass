from fastapi.testclient import TestClient

import api

client = TestClient(api.app)


def test_model_lab_recipe_surface_exposes_cross_asset_catalogue():
    response = client.get('/api/v4/model-lab/recipes')
    assert response.status_code == 200
    body = response.json()
    recipes = {row['recipe_id'] for row in body['recipes']}
    symbols = {row['symbol'] for row in body['instruments']}
    assert {'core-us-6m', 'nasdaq-growth-6m', 'global-proxy-6m', 'cross-asset-regime-6m'} <= recipes
    assert {'QQQ', 'IWM', 'XIU.TO', 'EWJ', 'MCHI', 'TLT', 'GLD', '^GSPTSE', '^N225', '^HSI'} <= symbols
    assert 'request_id' in body


def test_model_lab_data_surface_exposes_audit_and_provenance():
    response = client.get('/api/v4/model-lab/data')
    assert response.status_code == 200
    body = response.json()
    assert 'audit' in body
    assert 'refresh' in body
    assert 'recent_fetches' in body
    assert 'raw_sources' in body
    assert 'request_id' in body


def test_model_lab_refresh_accepts_catalogued_reference_indices(monkeypatch):
    calls = {}

    def fake_start(symbols=None, *, overlap_calendar_days=10):
        calls['symbols'] = list(symbols or [])
        calls['overlap'] = overlap_calendar_days
        return {'status': 'running', 'started': True}

    monkeypatch.setattr(api, 'start_research_refresh', fake_start)
    response = client.post(
        '/api/v4/model-lab/data/refresh',
        json={'symbols': ['^GSPTSE', '^N225', 'QQQ'], 'overlap_calendar_days': 7},
    )
    assert response.status_code == 200
    assert calls == {'symbols': ['^GSPTSE', '^N225', 'QQQ'], 'overlap': 7}
    assert response.json()['started'] is True


def test_model_lab_recipe_surface_reports_local_data_readiness(monkeypatch):
    def fake_coverage(symbols=None):
        requested = {str(x).upper() for x in (symbols or [])}
        rows = {"MSFT": 7983, "GOOG": 1047}
        return [
            {"symbol": symbol, "rows": rows.get(symbol, 0)}
            for symbol in sorted(requested)
        ]

    monkeypatch.setattr(api.research_store, "coverage", fake_coverage)
    response = client.get('/api/v4/model-lab/recipes')
    assert response.status_code == 200
    recipes = {row['recipe_id']: row for row in response.json()['recipes']}
    bootstrap = recipes['bootstrap-real-1m']['readiness']
    assert bootstrap['trainable'] is True
    assert bootstrap['benchmark_ready'] is True
    assert bootstrap['targets_present_count'] == 1
    assert bootstrap['target_symbols_missing'] == []
    core = recipes['core-us-6m']['readiness']
    assert core['trainable'] is False
    assert core['benchmark_ready'] is False
    assert core['targets_present_count'] == 1  # MSFT exists locally, but SPY does not.


def test_model_lab_recipe_surface_recommends_live_eligible_workflow(monkeypatch):
    def fake_coverage(symbols=None):
        requested = {str(x).upper() for x in (symbols or [])}
        rows = {"SPY": 5000, "AAPL": 5000, "MSFT": 5000, "GOOG": 1000}
        return [{"symbol": symbol, "rows": rows.get(symbol, 0)} for symbol in sorted(requested)]

    monkeypatch.setattr(api.research_store, "coverage", fake_coverage)
    response = client.get('/api/v4/model-lab/recipes')
    assert response.status_code == 200
    body = response.json()
    assert body['recommended_recipe_id'] == 'core-us-6m'
    recipe = next(row for row in body['recipes'] if row['recipe_id'] == body['recommended_recipe_id'])
    assert recipe['live_eligible_target'] is True
    assert recipe['readiness']['trainable'] is True
    assert body['guided_workflow'][-1].startswith('Run Forecast')
