import json
from pathlib import Path
import joblib
from forecasting.registry import save_model, set_active_model, get_active_pointer

class Dummy:
    settings={}
    feature_names=['x']

def _report(t='validated_research'): return {'validation_tier':t}
def _manifest(live=True): return {'schema_version':'x','files':{},'split':{},'provenance':{'live_eligible_target':live},'target':{},'data_quality':{}}

def test_candidate_lineage_and_activation_history(tmp_path):
    m1=save_model(Dummy(),_report(),_manifest(),profile_name='m1',root=tmp_path,lineage={'parent_model_id':None})
    set_active_model(m1['model_id'],root=tmp_path)
    m2=save_model(Dummy(),_report(),_manifest(),profile_name='m2',root=tmp_path,lineage={'parent_model_id':m1['model_id']})
    # saving candidate does not change active
    assert get_active_pointer(tmp_path)['model_id']==m1['model_id']
    set_active_model(m2['model_id'],root=tmp_path)
    p=get_active_pointer(tmp_path); assert p['model_id']==m2['model_id']; assert p['previous_model_id']==m1['model_id']
    hist=json.loads((tmp_path/'activation_history.json').read_text())
    assert hist[-1]['previous_model_id']==m1['model_id'] and hist[-1]['new_model_id']==m2['model_id']
    man=json.loads((tmp_path/f"m2-{m2['model_id']}.json").read_text())
    assert man['lineage']['parent_model_id']==m1['model_id']
