from __future__ import annotations

from datetime import datetime, timezone
from hashlib import sha256
import json
from pathlib import Path
from typing import Any, Dict, List, Optional

from realtime import REALTIME_ENGINE_VERSION
from realtime.adaptive import FEATURE_NAMES, state_sha256
from realtime.config import RealtimeSettings

ROOT=Path(__file__).resolve().parents[1]/"adaptive_models"


def _contract(base_model_id:str,settings:RealtimeSettings,state:Dict[str,Any],validation:Dict[str,Any],tier:str)->Dict[str,Any]:
    s_sha=state_sha256(state)
    body={
        "base_model_id":base_model_id,
        "realtime_engine_version":REALTIME_ENGINE_VERSION,
        "settings":settings.to_dict(),
        "settings_fingerprint":settings.fingerprint(),
        "features":FEATURE_NAMES,
        "state_sha256":s_sha,
        "validation_tier":tier,
        "validation":validation,
    }
    raw=json.dumps(body,sort_keys=True,separators=(",",":"),allow_nan=False)
    c_sha=sha256(raw.encode("utf-8")).hexdigest()
    return {**body,"contract_sha256":c_sha,"adaptive_id":c_sha[:16]}


def save_adaptive_artifact(base_model_id:str,settings:RealtimeSettings,state:Dict[str,Any],validation:Dict[str,Any],tier:str="fixture_only",name:str="adaptive",root:Path=ROOT)->Dict[str,Any]:
    if tier not in {"fixture_only","rejected","validated_research","validated_market"}: raise ValueError("invalid adaptive validation tier")
    root.mkdir(parents=True,exist_ok=True)
    contract=_contract(base_model_id,settings,state,validation,tier)
    aid=contract["adaptive_id"]
    state_file=root/f"{name}-{aid}.state.json"
    manifest_file=root/f"{name}-{aid}.json"
    state_file.write_text(json.dumps(state,indent=2,sort_keys=True)+"\n",encoding="utf-8")
    manifest={**contract,"state_file":state_file.name,"created_at":datetime.now(timezone.utc).isoformat(),"name":name}
    manifest_file.write_text(json.dumps(manifest,indent=2,sort_keys=True)+"\n",encoding="utf-8")
    return manifest


def list_adaptive_manifests(root:Path=ROOT)->List[Dict[str,Any]]:
    root.mkdir(parents=True,exist_ok=True); out=[]
    for p in sorted(root.glob("*.json")):
        if p.name.endswith(".state.json"): continue
        try:
            m=json.loads(p.read_text(encoding="utf-8")); m["manifest_file"]=p.name; out.append(m)
        except Exception: pass
    return sorted(out,key=lambda m:m.get("created_at",""),reverse=True)


def load_adaptive_artifact(adaptive_id:Optional[str]=None,base_model_id:Optional[str]=None,minimum_tier:str="validated_research",root:Path=ROOT):
    rank={"fixture_only":0,"rejected":0,"validated_research":1,"validated_market":2}; req=rank.get(minimum_tier,1)
    for m in list_adaptive_manifests(root):
        if adaptive_id and m.get("adaptive_id")!=adaptive_id: continue
        if base_model_id and m.get("base_model_id")!=base_model_id: continue
        if rank.get(m.get("validation_tier"),0)<req: continue
        sf=root/m.get("state_file","")
        if not sf.exists(): continue
        try: state=json.loads(sf.read_text(encoding="utf-8"))
        except Exception: continue
        if state_sha256(state)!=m.get("state_sha256"): continue
        settings=RealtimeSettings(**m.get("settings",{})).validate()
        check=_contract(m["base_model_id"],settings,state,m.get("validation") or {},m.get("validation_tier"))
        if check["contract_sha256"]!=m.get("contract_sha256") or check["adaptive_id"]!=m.get("adaptive_id"): continue
        return state,m
    return None,None


def registry_status(root:Path=ROOT)->Dict[str,Any]:
    manifests=list_adaptive_manifests(root); usable=[m for m in manifests if m.get("validation_tier") in {"validated_research","validated_market"}]
    return {"realtime_engine_version":REALTIME_ENGINE_VERSION,"artifacts_total":len(manifests),"live_eligible_artifacts":len(usable),"active_adaptive_id":usable[0].get("adaptive_id") if usable else None,"artifacts":[{k:m.get(k) for k in ["adaptive_id","base_model_id","settings_fingerprint","validation_tier","created_at","name"]} for m in manifests[:20]]}
