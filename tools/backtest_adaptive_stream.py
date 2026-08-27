#!/usr/bin/env python3
from __future__ import annotations
import sys
from pathlib import Path as _Path
sys.path.insert(0, str(_Path(__file__).resolve().parents[1]))
import argparse, json, math
from pathlib import Path
import pandas as pd
from realtime.adaptive import FEATURE_NAMES, evaluate_gate, initial_state, update_state
from realtime.config import PROFILES
from realtime.registry import save_adaptive_artifact


def loss_rows(): return []
def row_metrics(d,pa,pp,y):
    pa=min(max(float(pa),1e-9),1-1e-9); pp=min(max(float(pp),1e-9),1-1e-9); y=int(y)
    return {'observation_date':str(d),'anchor_probability':pa,'adaptive_probability':pp,'label':y,'brier_anchor':(pa-y)**2,'brier_adaptive':(pp-y)**2,'log_anchor':-(y*math.log(pa)+(1-y)*math.log(1-pa)),'log_adaptive':-(y*math.log(pp)+(1-y)*math.log(1-pp))}

def process(df,state,settings,history):
    preds=[]
    for _,r in df.iterrows():
        features={n:float(r[n]) for n in FEATURE_NAMES}; y=int(r['target_outperform']); pa=float(r['anchor_probability'])
        state,pred=update_state(pa,features,y,state,settings); pp=float(pred['candidate_probability']); history.append(row_metrics(r['observation_date'],pa,pp,y)); preds.append(pp)
        gate=evaluate_gate(history[-max(len(history),1):],state.get('drift') or {},settings); state['gate']=gate; state['status']=gate['status']
    return state,preds

def aggregate(rows):
    if not rows:return {}
    ba=sum(r['brier_anchor'] for r in rows)/len(rows); bp=sum(r['brier_adaptive'] for r in rows)/len(rows); la=sum(r['log_anchor'] for r in rows)/len(rows); lp=sum(r['log_adaptive'] for r in rows)/len(rows)
    return {'anchor_brier':ba,'adaptive_brier':bp,'brier_improvement':ba-bp,'anchor_log_loss':la,'adaptive_log_loss':lp,'log_loss_improvement':la-lp,'observations':len(rows)}

def main():
    ap=argparse.ArgumentParser(); ap.add_argument('dataset_dir'); ap.add_argument('--profile',default='balanced',choices=PROFILES); ap.add_argument('--name',default='balanced-adaptive'); args=ap.parse_args()
    d=Path(args.dataset_dir); warm=pd.read_csv(d/'warmup.csv'); locked=pd.read_csv(d/'locked_test.csv'); settings=PROFILES[args.profile].validate(); state=initial_state(settings); history=[]
    state,_=process(warm,state,settings,history)
    warm_gate=evaluate_gate(history[-settings.online_eval_window:],state.get('drift') or {},settings); state['gate']=warm_gate; state['status']=warm_gate['status']
    warm_state=json.loads(json.dumps(state))
    locked_history=[]
    for _,r in locked.iterrows():
        features={n:float(r[n]) for n in FEATURE_NAMES}; y=int(r['target_outperform']); pa=float(r['anchor_probability'])
        state,pred=update_state(pa,features,y,state,settings); pp=float(pred['candidate_probability']); rr=row_metrics(r['observation_date'],pa,pp,y); history.append(rr); locked_history.append(rr)
        recent_dates=sorted({x['observation_date'] for x in history})[-settings.online_eval_window:]; keep=set(recent_dates); recent=[x for x in history if x['observation_date'] in keep]
        gate=evaluate_gate(recent,state.get('drift') or {},settings); state['gate']=gate; state['status']=gate['status']
    metrics=aggregate(locked_history); final_gate=state['gate']
    validation={'synthetic':True,'protocol':'predict-before-update warmup followed by locked prequential stream','profile':args.profile,'locked_metrics':metrics,'warmup_gate':warm_gate,'final_gate':final_gate,'passed':bool(final_gate.get('active')),'claims_boundary':'Software/statistical regression only; not market validation.'}
    manifest=save_adaptive_artifact('efd41fec7d9d24fd',settings,warm_state,validation,tier='fixture_only',name=args.name)
    (d/'adaptive_validation_report.json').write_text(json.dumps(validation,indent=2,sort_keys=True)+'\n')
    stream_manifest={'adaptive_id':manifest['adaptive_id'],'contract_sha256':manifest['contract_sha256'],'state_sha256':manifest['state_sha256'],'settings_fingerprint':manifest['settings_fingerprint'],'base_model_id':manifest['base_model_id'],'validation_tier':manifest['validation_tier'],'profile':args.profile}
    (d/'adaptive_stream_manifest.json').write_text(json.dumps(stream_manifest,indent=2,sort_keys=True)+'\n')
    print(json.dumps({'artifact':stream_manifest,'validation':validation},indent=2))
if __name__=='__main__': main()
