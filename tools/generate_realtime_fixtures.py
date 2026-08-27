#!/usr/bin/env python3
from __future__ import annotations
import sys
from pathlib import Path as _Path
sys.path.insert(0, str(_Path(__file__).resolve().parents[1]))
import argparse, hashlib, json
from pathlib import Path
import numpy as np
import pandas as pd
from realtime.adaptive import FEATURE_NAMES, logit, sigmoid


def sha(path: Path): return hashlib.sha256(path.read_bytes()).hexdigest()

def main():
    ap=argparse.ArgumentParser(); ap.add_argument('--output',default='datasets/realtime-fixtures'); ap.add_argument('--seed',type=int,default=44004); args=ap.parse_args()
    out=Path(args.output); out.mkdir(parents=True,exist_ok=True)
    rng=np.random.default_rng(args.seed); n=1800
    dates=pd.date_range('2016-01-04',periods=n,freq='2D')
    rows=[]
    # Persistent latent environment plus event shocks gives the online residual a real job.
    latent=0.0
    true_beta=np.array([1.25,0.85,0.30,0.20,0.18,-0.35,0.40,0.55,0.30,0.20,-0.25,-0.45,0.15])
    for i,dt in enumerate(dates):
        latent=0.92*latent+rng.normal(0,0.35)
        x=rng.normal(0,0.55,len(FEATURE_NAMES))
        x[0]+=0.55*latent; x[1]+=0.35*latent
        # sparse filing indicators / freshness
        filing=rng.random()<0.10
        x[6]=rng.uniform(0.4,1.0) if filing else rng.uniform(0,0.2)
        x[7:10]=0
        if filing: x[7+rng.integers(0,3)]=x[6]
        x[12]=rng.uniform(0.4,1.0)
        anchor_logit=0.18*np.sin(i/70)+0.22*latent+rng.normal(0,0.08)
        anchor=float(sigmoid(anchor_logit))
        correction=float(np.dot(x,true_beta)*0.85)
        p=float(sigmoid(logit(anchor)+correction))
        y=int(rng.random()<p)
        row={'observation_date':dt.date().isoformat(),'ticker':'SIM','base_model_id':'efd41fec7d9d24fd','anchor_probability':anchor,'target_outperform':y}
        row.update({name:float(x[j]) for j,name in enumerate(FEATURE_NAMES)})
        rows.append(row)
    df=pd.DataFrame(rows)
    warm=df.iloc[:1200].copy(); locked=df.iloc[1200:].copy()
    wp=out/'warmup.csv'; lp=out/'locked_test.csv'; warm.to_csv(wp,index=False); locked.to_csv(lp,index=False)
    manifest={'schema_version':'1.0.0-event1','synthetic':True,'seed':args.seed,'rows':{'warmup':len(warm),'locked_test':len(locked)},'dates':{'warmup':[warm.observation_date.iloc[0],warm.observation_date.iloc[-1]],'locked_test':[locked.observation_date.iloc[0],locked.observation_date.iloc[-1]]},'features':FEATURE_NAMES,'base_model_id':'efd41fec7d9d24fd','files':{'warmup.csv':sha(wp),'locked_test.csv':sha(lp)},'claims_boundary':'Synthetic streaming regression fixture only; never evidence of market skill.'}
    mp=out/'fixture_manifest.json'; mp.write_text(json.dumps(manifest,indent=2,sort_keys=True)+'\n'); digest=sha(mp); (out/'fixture_manifest.sha256').write_text(digest+'  fixture_manifest.json\n')
    print(json.dumps({'output':str(out),'manifest_sha256':digest,**manifest['rows']},indent=2))
if __name__=='__main__': main()
