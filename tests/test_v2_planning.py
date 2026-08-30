from services.instrument_classification import classify_instrument
from services.benchmark_resolver import resolve_benchmark
from services.model_selection import applicability, select_model


def test_classification_conservative():
    assert classify_instrument('AAPL')['region'] == 'US'
    assert classify_instrument('SHOP.TO')['region'] == 'Canada'
    assert classify_instrument('BTC-USD')['asset_class'] == 'crypto'
    assert classify_instrument('SOMENEW')['asset_class'] == 'unknown'


def test_benchmark_policy():
    assert resolve_benchmark(classify_instrument('AAPL'))['family'] == 'US_LARGE_CAP'
    assert resolve_benchmark(classify_instrument('SHOP.TO'))['family'] == 'CA_BROAD_EQUITY'
    assert resolve_benchmark(classify_instrument('BTC-USD'))['supported'] is False


def test_bundled_us_model_domain():
    inst = classify_instrument('AAPL')
    bench = resolve_benchmark(inst)
    result = select_model(inst, bench, 12)
    assert result['selected'] is not None
    assert result['selected']['validation_tier'] in {'validated_research','validated_market'}
    ca = classify_instrument('SHOP.TO')
    cab = resolve_benchmark(ca)
    result2 = select_model(ca, cab, 12)
    assert result2['selected'] is None


def test_baseline_horizons_are_available_for_us():
    inst=classify_instrument('AAPL'); bench=resolve_benchmark(inst)
    for h in (6,24,36):
        result=select_model(inst,bench,h)
        assert result['selected'] is not None
        assert result['selected']['validation_tier']=='bayesian_baseline'

def test_provider_resolves_new_bare_us_ticker(monkeypatch):
    import services.market_catalog as mc
    from services.instrument_classification import resolve_instrument
    monkeypatch.setattr(mc,'search_symbol',lambda text,limit=8:{'available':True,'results':[{'ticker':'NEWX','name':'New Example','quote_type':'EQUITY','exchange':'NMS','currency':'USD','region':'us'}]})
    x=resolve_instrument('NEWX')
    assert x['asset_class']=='equity' and x['region']=='US' and x['security_type']=='common_stock'

def test_new_supported_ticker_uses_pooled_model_without_training(monkeypatch):
    import numpy as np, pandas as pd
    import services.forecast_service as fs
    dates=pd.bdate_range('2018-01-02','2026-08-28')
    rng=np.random.default_rng(42)
    bench=pd.DataFrame({'Close':100*np.exp(np.cumsum(rng.normal(.00025,.01,len(dates))))},index=dates)
    stock=pd.DataFrame({'Close':80*np.exp(np.cumsum(rng.normal(.00035,.013,len(dates))))},index=dates)
    monkeypatch.setattr(fs,'resolve_instrument',lambda t:{'symbol':'NEWX','asset_class':'equity','security_type':'common_stock','region':'US','country':'US','currency':'USD','classification_source':'provider_metadata'})
    monkeypatch.setattr(fs,'_get_price_history',lambda s: bench if s=='^GSPC' else stock)
    out=fs.forecast_ticker('NEWX',horizon_months=12)
    assert out['available'] is True
    assert out['ticker']=='NEWX'
    assert out['validation_tier'] in {'validated_research','validated_market'}
    assert 0 < out['probability']['probability_outperform'] < 1
