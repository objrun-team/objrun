"""Fresh authorized test244 run, gated on completed pilot delivery and controls."""
import json
import os
from pathlib import Path
import sys
from lean_worker import Grader, digest, save
from transport import Transport
from scheduler import Scheduler

def main(root):
    root=Path(root).resolve();os.chdir(root)
    cfg=json.loads((root/'package/experiment.json').read_text())
    assert cfg['scope']=='test244-formal' and cfg['formalAuthorized'] is True and not cfg.get('controlOnly')
    fixed={'model':'deepseek/deepseek-v4-flash-0731','providerTag':'deepinfra/fp8','provider':'DeepInfra',
        'modelConcurrency':16,'graderConcurrency':4,'requestSpacingSeconds':0,'maxAttempts':5,
        'perTaskSeconds':3600,'perTaskDollarCap':.10,'batchDollarCap':48.80,'expectedRecords':488,
        'maxTokens':16384,'reasoningEffort':'medium','temperature':0,'maxTransportAttempts':3,
        'transportBackoffSeconds':20,'compileTimeoutSeconds':300,'workerMemoryGiB':12}
    assert all(cfg[k]==v for k,v in fixed.items()),'UnauthorizedProtocolChange'
    catalog=json.loads((root/'data/public-test.json').read_text())
    manifest=json.loads((root/'data/catalog-manifest.json').read_text())
    assert len(catalog)==cfg['taskCount']==244 and all(t['split']=='test' for t in catalog)
    assert len({t['id'] for t in catalog})==244 and manifest['publicTestSha256']==digest((root/'data/public-test.json').read_bytes())
    assert manifest['revision']=='5def318348521dfc34875045a9ecddf729a2b49f'
    assert not list((root/'outputs/calls').rglob('dispatch.json')) and not list((root/'outputs/results').glob('*/*.json'))
    controls=json.loads((root/'outputs/controls.json').read_text())
    assert controls['allPassed'] and controls['modelCalls']==0
    required=['actual_loopback_http_shared_16_and_immediate_refill_without_waiting_for_lean',
              'concurrent_shared_cap_and_unknown_reservations',
              'four_real_lean_workers_original_sandbox_and_resources']
    assert all(any(c['name']==name and c['passed'] for c in controls['checks']) for name in required)
    gate_path=root/'outputs/pilot-delivery-gate.json'
    gate=json.loads(gate_path.read_text())
    for k in ['humanAuthorized','pilotCompleted','fullLogsReturnedToLocal','archiveSha256Verified',
              'protocolAndIntegrityChecksPassed','credentialsAbsent','unknownExpensesConservativelyReserved']:
        assert gate[k] is True,'PilotGate:'+k
    pins={str(p.relative_to(root)):digest(p.read_bytes()) for d in ['package','vendor','data'] for p in (root/d).iterdir() if p.is_file()}
    assert pins==controls['sourcePins'],'SourceChangedAfterControls'
    gate_sha=digest(gate_path.read_bytes())
    save(root/'outputs/source-pins.json',pins);save(root/'outputs/gate-pin.json',{'sha256':gate_sha})
    def frozen():
        assert all(digest((root/p).read_bytes())==h for p,h in pins.items()),'FrozenSourceChanged'
        assert digest(gate_path.read_bytes())==gate_sha,'DeliveryGateChanged'
    transport=Transport(root,cfg,os.environ['OPENROUTER_API_KEY'])
    save(root/'outputs/admission.json',transport.preflight())
    environment=json.loads((root/'outputs/environment.json').read_text())
    grader=Grader(root,cfg,digest(json.dumps(environment,sort_keys=True)))
    assert grader.identity==controls['graderIdentity']
    Scheduler(root,cfg,catalog,transport,grader,frozen).run()
    import report
    report.finish(root)

if __name__=='__main__':main(sys.argv[1])
