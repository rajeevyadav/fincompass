from fastapi.testclient import TestClient

import services.market_catalog as mc
from api import app


def test_market_meta_exposes_dynamic_scope():
    client = TestClient(app)
    r = client.get('/api/v1/market/meta')
    assert r.status_code == 200
    body = r.json()
    assert body['starter_universe_size'] == 72
    assert body['per_request_max'] == 250
    assert 'us' in body['regions']
    assert 'Technology' in body['sectors']


def test_universe_is_explicitly_starter_not_access_boundary():
    client = TestClient(app)
    body = client.get('/api/v1/universe').json()
    assert body['count'] == 72
    assert body['scope'] == 'curated_starter_universe'
    assert body['dynamic_market_search'] is True


def test_market_search_degrades_cleanly_without_provider(monkeypatch):
    monkeypatch.setattr(mc, 'yf', None)
    out = mc.search_equities(sector='Technology', region='us', limit=250)
    assert out['available'] is False
    assert out['results'] == []
    assert out['limit'] == 250


def test_market_search_rejects_unknown_region():
    try:
        mc.search_equities(region='xx')
    except ValueError as exc:
        assert 'unsupported region' in str(exc)
    else:
        raise AssertionError('expected ValueError')


def test_sector_ui_exposes_broad_market_browse():
    html = open('static/index.html', encoding='utf-8').read()
    js = open('static/app.js', encoding='utf-8').read()
    assert 'btn-market-browse' in html
    assert 'market-region' in html
    assert 'browseMarketSector' in js
    assert '/api/v1/market/search' in js
