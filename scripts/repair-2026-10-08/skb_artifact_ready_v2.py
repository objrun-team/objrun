"""Source/raw/actor-backed readiness graph; never accepts a ready boolean alone."""
from datetime import datetime
from pathlib import Path
import skb_artifact_task_v2 as task
import skb_artifact_build_audit_v2 as build_audit
import skb_artifact_native_identity_v2 as native


def validate_closed_build_proof(pin,task_id):
    proof=task.read_json(pin);stage_pin=proof.get('originStagePin');catalog_pin=proof.get('buildClosedCatalogPin')
    task.demand(stage_pin is not None and catalog_pin is not None,'build_not_closed','Closed actual build catalog and original stage required')
    stage=task.read_json(stage_pin);catalog=task.read_json(catalog_pin)
    task.demand(proof=={**stage,'originStagePin':stage_pin,'buildClosedCatalogPin':catalog_pin},'build_proof','Closed proof replaced original stage fields')
    task.demand(catalog['protocol']==build_audit.PROTOCOL and catalog['actualDistinctTaskImages']==10 and catalog['actualSealedPrivateRuntime'] is True
                and [x['taskId'] for x in catalog['stageChecks']]==[*task.TASK_IDS,'private-runtime'],'build_catalog','Exact closed10+private catalog required')
    matches=[x for x in catalog['stageChecks'] if x['taskId']==task_id]
    task.demand(len(matches)==1 and matches[0]['stagePin']==stage_pin,'build_catalog','Stage is not exact catalog member')
    run_pin=catalog['privateBuildRunPin'] if task_id=='private-runtime' else catalog['solverBuildRunPin']
    run=task.read_json(run_pin);build_audit.validate_stage(stage_pin,run)
    native.closed_identity(run['actorPid'],int(datetime.fromisoformat(run['completedAtUtc']).timestamp()*1000))
    native.closed_identity(catalog['auditorPid'],int(datetime.fromisoformat(catalog['observedAtUtc']).timestamp()*1000))
    return proof


def validate_collection(value,collection):
    from skb_artifact_grade_audit_v2 import validate_grade_report
    bootstrap_pin=collection.get('bootstrapDescriptorPin')
    task.demand(bootstrap_pin is not None,'collection_source','Actual bootstrap task descriptor required')
    bootstrap=task.read_json(bootstrap_pin)
    expected={**value,'expectedCollectionPin':None,'preparedOnly':True}
    task.demand(bootstrap==expected,'collection_source','Collection bootstrap differs from current source/task/runtime descriptor')
    replay=validate_grade_report(bootstrap_pin,collection['ownedClosurePin'],True);result=replay['result']
    task.demand(replay['owner']['mode']=='collect' and result['collectionValid'] is True and result['nodeIds']==collection['nodeIds']
                and collection['rawResultPin']==replay['owner']['resultPins']['private-result.json'],'collection_raw','Complete actual collection/raw/owned closure graph differs')
    return replay
