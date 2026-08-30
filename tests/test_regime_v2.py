import numpy as np, pandas as pd
from dataclasses import replace
from forecasting.regime import GaussianHMMRegime, train_validate_bayesian_regime
from forecasting.config import get_profile


def _part(start, n, seed):
    rng=np.random.default_rng(seed); dates=pd.date_range(start, periods=n, freq='ME')
    b1=rng.normal(0.006,0.04,n); bv=pd.Series(b1).rolling(6,min_periods=1).std().fillna(0.04).to_numpy()*np.sqrt(12)
    rows=[]
    for ticker,shift in [('AAA',0.01),('BBB',-0.005),('CCC',0.002)]:
        rel1=rng.normal(shift,0.05,n)
        for i,d in enumerate(dates):
            rows.append({'date':d,'ticker':ticker,'benchmark_ret_1m':b1[i],'benchmark_ret_6m':float(pd.Series(b1).rolling(6,min_periods=1).sum().iloc[i]),'benchmark_vol_6m':bv[i],
                         'rel_ret_1m':rel1[i],'rel_ret_3m':rel1[i]*1.5,'rel_ret_6m':rel1[i]*2,'rel_ret_12m':rel1[i]*3,
                         'vol_6m':abs(rel1[i])+0.1,'drawdown_12m':-abs(rel1[i]),'sma_3_12':rel1[i]/2,
                         'target_outperform':int(rel1[i]+0.4*b1[i]+rng.normal(0,0.03)>0),'target_end_date':d+pd.offsets.MonthEnd(6),'forward_excess_return':rel1[i]})
    return pd.DataFrame(rows)

def test_hmm_probabilities_sum_to_one():
    x=np.column_stack([np.r_[np.full(30,-.04),np.full(30,.0),np.full(30,.04)], np.zeros(90), np.full(90,.2)])
    m=GaussianHMMRegime().fit(x); p,_=m.filtered_probabilities(x)
    assert p.shape==(90,3); assert np.allclose(p.sum(axis=1),1.0)

def test_regime_model_produces_valid_probabilities():
    tr=_part('2000-01-31',60,1); va=_part('2005-01-31',24,2); te=_part('2007-01-31',24,3)
    s=replace(get_profile('exploratory'),horizon_trading_days=126,sample_step_trading_days=21,bootstrap_draws=100,posterior_draws=200).validate()
    model, report, pred=train_validate_bayesian_regime(tr,va,te,{'data_quality':{}},s)
    assert report['validation_tier']=='bayesian_baseline'; assert report['model_family']=='bayesian_regime_hmm'
    assert pred['probability_outperform'].between(0,1).all()

def test_regime_artifacts_are_research_alternatives():
    from pathlib import Path
    import json
    manifests=[]
    for p in Path('models').glob('bayesian-regime-*.json'):
        if p.name.endswith('-SUMMARY.json'): continue
        manifests.append(json.loads(p.read_text()))
    assert manifests and all(m.get('guided_eligible') is False for m in manifests)
