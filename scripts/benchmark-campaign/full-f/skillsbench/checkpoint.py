"""Reconcile preparation facts while preserving actual F/financial progress."""
import json
from pathlib import Path
from prepare import HOME,public,save,utc

def main():
    status=json.loads((HOME/'status.json').read_bytes());prepared=[]
    for path in sorted((HOME/'grader-controls').glob('*/latest.json')):
        pin=json.loads(path.read_bytes())['controlPin']
        if public.pin(Path(pin['path']))!=pin:raise ValueError('control evidence changed')
        control=json.loads(Path(pin['path']).read_bytes())
        if not control.get('controlsPassed'):continue
        built_pin=control['builtImagesPin'];built=json.loads(Path(built_pin['path']).read_bytes())
        if public.pin(Path(built_pin['path']))!=built_pin:raise ValueError('build evidence changed')
        runner=built['privateRunnerSourcePin']
        if public.pin(Path(runner['path']))!=runner:continue
        current=json.loads((HOME/'environment-preparation'/control['taskId']/'latest.json').read_bytes())['builtImagesPin']
        if current!=built_pin:continue
        prepared.append({'taskId':control['taskId'],'controlPin':pin,'decisions':control['decisions']})
    policies=json.loads((HOME/'artifact-policy-inventory.json').read_bytes())
    control=json.loads((HOME.parent/'control.json').read_bytes())
    broker=json.loads(Path(control['broker']['healthPath']).read_bytes());owner=broker.get('resources',{}).get('heavy-container')
    safe_owner={'slug':owner['slug'],'pid':owner['pid']} if owner else None
    status.update(preparedTaskCount=len(prepared),preparedTaskControls=prepared,
        artifactPolicies={'reviewed':policies['reviewedPolicyCount'],'pending':policies['policiesPending'],'inventory':str(HOME/'artifact-policy-inventory.json')},
        sharedResourceObservation={'observedAtUtc':broker['atUtc'],'brokerHealthy':broker['healthy'],'heavyOwner':safe_owner},
        paidForwardingAllowed=bool(control['paidReady'] and broker['healthy']),
        updatedAtUtc=utc())
    refresh_path=HOME/'state-refresh-controls/latest.json'
    refresh_current=False
    if refresh_path.exists():
        result_pin=json.loads(refresh_path.read_bytes())['resultPin'];result=json.loads(Path(result_pin['path']).read_bytes())
        source_pins=result.get('sourcePins',[])
        refresh_current=bool(result.get('verified') and source_pins and all(public.pin(Path(p['path']))==p for p in source_pins))
    status['sameRunRefreshCurrentSourceVerified']=refresh_current
    if refresh_current:status['sameRunRefresh']={'verified':True,'resultPin':result_pin,'decisions':[s['reward'] for s in result['steps']],'scoreCertificate':False}
    resume_path=HOME/'resume-controls/latest.json'
    if resume_path.exists():
        resume_pin=json.loads(resume_path.read_bytes())['resultPin'];resume=json.loads(Path(resume_pin['path']).read_bytes())
        status['resumePlanningControls']={'verified':resume['verified'] and all(public.pin(Path(p['path']))==p for p in resume['sourcePins']),
            'resultPin':resume_pin,'cases':len(resume['cases']),'fullFinancialLifecycleValidated':False,'modelRequests':0}
    if not broker['healthy']:status['paidHold']={'reason':'shared_broker_not_healthy','action':'Do not acquire a paid lane or dispatch; coordinator is reconciling unsettled lane costs. Continue only independent zero-model preparation.'}
    else:status.pop('paidHold',None)
    status['costPolicy']=control.get('costPolicy',{'mode':'strict'})
    status['recordingCash']={'implemented':True,'validated':False,'sourcePin':public.pin(Path(__file__).with_name('recording_usd_cash.ts')),
        'scope':'Unknown receipts/reservations and poisoned flag retained; financial-only poison permits continuation. Original shared cash-close verifier, real journal bindings and admission caps unchanged. Full financial lifecycle controls pending.'}
    cash_test=HOME/'recording-cash-controls/latest.json'
    if cash_test.exists():
        cp=json.loads(cash_test.read_bytes())['resultPin'];cr=json.loads(Path(cp['path']).read_bytes())
        status['recordingCash']['offlineControls']={'resultPin':cp,'verified':bool(cr.get('verified') and public.pin(Path(cp['path']))==cp and all(public.pin(Path(p['path']))==p for p in cr['sourcePins'])),
            'cases':cr.get('cases',[]),'modelRequests':0,'fullPaidLifecycleValidated':False,'scope':cr['scope']}
    segment_test=HOME/'segment-boundary-controls/latest.json'
    if segment_test.exists():
        qp=json.loads(segment_test.read_bytes())['resultPin'];qr=json.loads(Path(qp['path']).read_bytes())
        status['segmentBoundaryControls']={'resultPin':qp,'verified':bool(qr.get('verified') and public.pin(Path(qp['path']))==qp and all(public.pin(Path(p['path']))==p for p in qr['sourcePins'])),
            'cases':qr['cases'],'modelRequests':0,'fullPaidLifecycleValidated':False,'scope':qr['scope']}
    code_path=HOME/'code-value-controls/latest.json'
    if code_path.exists():
        code_pin=json.loads(code_path.read_bytes())['resultPin'];code=json.loads(Path(code_pin['path']).read_bytes())
        status['codeIsolationPrototype']={'taskId':'crystallographic-wyckoff-position-analysis','implemented':True,
            'boundaryControlsVerified':code['verified'] and all(public.pin(Path(p['path']))==p for p in code['sourcePins']),
            'boundaryControlPin':code_pin,'cases':len(code['cases']),'actualCodeExecutionControlsPassed':False,'runtimeIntegrated':False,
            'scope':'Single-source function-return prototype; original native script and zero pytest collection retained. Candidate dependency/helper-file parity remains pending.'}
        native_path=HOME/'code-grader-controls/crystallographic-wyckoff-position-analysis/latest.json'
        if native_path.exists():
            native_pin=json.loads(native_path.read_bytes())['controlPin'];native=json.loads(Path(native_pin['path']).read_bytes())
            native_build_pin=native['builtImagesPin'];native_build=json.loads(Path(native_build_pin['path']).read_bytes())
            current=native.get('controlsPassed') and public.pin(Path(native_pin['path']))==native_pin and public.pin(Path(native_build_pin['path']))==native_build_pin and native.get('ownedContainersRemaining')==0
            current=current and all(public.pin(Path(p['path']))==p for p in native_build.get('sourcePins',[])+native.get('sourcePins',[]))
            status['codeIsolationPrototype'].update(actualCodeExecutionControlsPassed=bool(current),actualControlPin=native_pin,
                actualPytestCollection=native.get('actualPytestCollection'),nativeCaseCount=native.get('nativeCaseCount'),decisions=native.get('decisions'),failure=native.get('failure'))
        status['codeIsolationPrototype']['candidateEnvironmentAdapter']={'implemented':True,'actualControlsPassed':False,'runtimeIntegrated':False,
            'sourcePins':[public.pin(Path(__file__).with_name(n)) for n in ('candidate_snapshot_exec.py','snapshot_function_adapter.py')],
            'scope':'Candidate filesystem/helpers/dependencies retained only in untrusted execution snapshot; private grader remains immutable; combined original verifier deadline and owned-image cleanup implemented but actual controls pending.'}
        status['codeIsolationPrototype']['runtimeIntegrationImplemented']=True
        status['codeIsolationPrototype']['runtimeIntegrationValidated']=False
        integration_path=HOME/'native-snapshot-refresh-controls/latest.json'
        if integration_path.exists():
            ip=json.loads(integration_path.read_bytes())['resultPin'];ir=json.loads(Path(ip['path']).read_bytes())
            verified=bool(ir.get('verified') and ir.get('ownedResourcesRemaining')==0 and public.pin(Path(ip['path']))==ip and all(public.pin(Path(p['path']))==p for p in ir.get('sourcePins',[])))
            status['codeIsolationPrototype']['candidateEnvironmentAdapter'].update(actualControlsPassed=verified,runtimeIntegrated=verified,
                resultPin=ip,decisions=[s['reward'] for s in ir.get('steps',[])],ownedResourcesRemaining=ir.get('ownedResourcesRemaining'),
                candidateEnvironmentParityVerified=bool(verified and ir.get('candidateEnvironmentParityVerified')),
                originalVerifierBudgetVerified=bool(verified and ir.get('originalVerifierBudgetVerified')),
                storageBudgetParityVerified=bool(verified and ir.get('storageBudgetParityVerified')),failure=ir.get('failure'),
                scope='Actual missing/helper/installed-dependency same-run refresh controls; immutable private grader receives JSON only. Streaming source budget verified='+str(bool(verified and ir.get('storageBudgetParityVerified'))))
            status['codeIsolationPrototype']['runtimeIntegrationValidated']=verified
        recoveries=[]
        for recovery in sorted((HOME/'native-snapshot-refresh-controls').glob('*/cleanup-recovery.json')):
            recovered=json.loads(recovery.read_bytes())
            recoveries.append({'recoveryPin':public.pin(recovery),'sourceResultPin':recovered.get('sourceResultPin'),
                'removed':recovered.get('removed'),'ownerLabelMatched':recovered.get('ownerLabelMatched')})
        status['codeIsolationPrototype']['cleanupRecoveries']=recoveries
    native_count=int(status.get('codeIsolationPrototype',{}).get('actualCodeExecutionControlsPassed',False))
    status.update(preparedDataTaskCount=len(prepared),actualNativeControlTaskCount=native_count,actualGraderControlTaskCount=len(prepared)+native_count)
    bounds_path=HOME/'capture-bound-controls/latest.json'
    if bounds_path.exists():
        bound_pin=json.loads(bounds_path.read_bytes())['resultPin'];bounds=json.loads(Path(bound_pin['path']).read_bytes())
        status['captureBoundControls']={'resultPin':bound_pin,'verified':bounds['verified'] and public.pin(Path(bounds['sourcePin']['path']))==bounds['sourcePin'],'modelCalls':0}
    streams_path=HOME/'stream-digest-controls/latest.json'
    if streams_path.exists():
        sp=json.loads(streams_path.read_bytes())['resultPin'];sr=json.loads(Path(sp['path']).read_bytes())
        status['streamDigestControls']={'resultPin':sp,'verified':bool(sr.get('verified') and public.pin(Path(sp['path']))==sp and all(public.pin(Path(p['path']))==p for p in sr['sourcePins'])),
            'cases':len(sr.get('cases',[])),'realGraderExecuted':False,'modelCalls':0}
    multi_prepared=[]
    for row in prepared:
        c=json.loads(Path(row['controlPin']['path']).read_bytes())
        b=json.loads(Path(c['builtImagesPin']['path']).read_bytes())
        if Path(b['privateRunnerSourcePin']['path']).name=='private_eval_multi.py':multi_prepared.append(row['taskId'])
    status['multiReplay']={'implemented':True,'actualControlsPassed':bool(multi_prepared),'preparedTaskIds':multi_prepared}
    status['remainingImplementation']=[str(policies['policiesPending'])+' additional artifact/execution policies',
        str(87-len(prepared)-native_count)+' additional actual private grader/dependency/collection controls',
        'actual multi replay and source-pinned current bridge refresh controls',
        'isolated candidate-code execution prototype actual controls, dependency/helper parity and runtime integration','full runtime financial/lifecycle and resume controls']
    review=HOME/'policy-review-next.json'
    if review.exists():status['nextPolicyReviews']={'evidencePin':public.pin(review),'taskCount':len(json.loads(review.read_bytes())['rows']),'privateGraderReady':False}
    status['nextAction']='Check current-source native streaming and data refresh receipts; keep failures and exact-owner cleanup evidence. Continue original task controls; bike private build failed on Debian502 and now has bounded timeout receipts/apt retries/force-rm without changing original task build deadline. Remaining policies/environments and full financial/lifecycle validation are still required before full87 dispatch. Claim shared slot once and queue on409. Cost policy record_and_continue preserves unknown evidence without fee-review pauses.'
    campaign=HOME/'reviewed-preparation-campaign/latest.json'
    if campaign.exists():
        qp=json.loads(campaign.read_bytes())['statePin']
        if public.pin(Path(qp['path']))==qp:
            queue=json.loads(Path(qp['path']).read_bytes())
            status['preparationQueueObservation']={'statePin':qp,'pid':queue['pid'],'phase':queue['phase'],'attemptCount':len(queue['attempts']),'modelCalls':0}
            recovered=status.get('preparationCampaign',{}).get('interruptionRecoveryPin')
            if recovered and public.pin(Path(recovered['path']))==recovered:
                proof=json.loads(Path(recovered['path']).read_bytes())
                if proof.get('originalChildDead') and proof.get('resourceReleased'):
                    status['preparationQueueObservation'].update(phase='interrupted_recovered',recoveryPin=recovered,active=False)
            elif queue['phase']=='running':status['nextAction']='Inspect saved reviewed preparation queue PID '+str(queue['pid'])+' before starting another worker. While alive, preserve its pinned preparation sources/inventory and let its sequential original task controls proceed; continue only independent adapter work. It claims once per task and exits on409, retains failures, and does not create paid lanes or formal F results. Native streaming/current data refresh and offline cash controls have separate receipts; full87 and paid financial lifecycle remain incomplete. Stop requests must use targeted stop-request.json at a task boundary; do not terminate the parent process while a child owns the slot.'
    service=HOME/'apt-transport-service/latest.json'
    if service.exists():
        ap=json.loads(service.read_bytes())['servicePin'];ar=json.loads(Path(ap['path']).read_bytes())
        status['aptTransport']={'servicePin':ap,'pid':ar['pid'],'modelCalls':0,'sourceCurrent':public.pin(Path(ar['sourcePin']['path']))==ar['sourcePin'],'realDockerVerified':False}
        dp=HOME/'apt-docker-transport-controls/latest.json'
        if dp.exists():
            pin=json.loads(dp.read_bytes())['resultPin'];tested=json.loads(Path(pin['path']).read_bytes())
            valid=bool(tested.get('verified') and tested.get('ownedContainersRemaining')==0 and tested['servicePin']==ap and public.pin(Path(tested['sourcePin']['path']))==tested['sourcePin'])
            status['aptTransport'].update(realDockerVerified=valid,dockerControlPin=pin,resourceQueued=tested.get('resourceQueued',False))
        if not status['aptTransport']['realDockerVerified']:
            status['nextAction']='Own interrupted court build was recovered and original resource released; parent queue58628 is dead. Inspect current shared owner. When free, run verify_apt_docker.ts once; on409 queue without repeated contention. Docker-to-host official APT transport must really pass before its temporary build arguments or a new reviewed queue are enabled. Then resume prepare_reviewed.ts with frozen sources; targeted stop-request.json must drain at task boundaries. Isolated Excel builder/private CSV assertion adapter and11 local boundary controls are implemented but need real images/collection/empty-oracle-wrong and runtime integration. Full87 and paid lifecycle remain pending; feesunknown do not block continuation.'
    excel=HOME/'excel-conversion-protocol-controls/latest.json'
    if excel.exists():
        ep=json.loads(excel.read_bytes())['resultPin'];er=json.loads(Path(ep['path']).read_bytes())
        status['excelConversionAdapter']={'taskIds':['weighted-gdp-calc','reserves-at-risk-calc','shock-analysis-demand'],'implemented':True,
            'boundaryControlsPin':ep,'boundaryControlsVerified':bool(er.get('verified') and all(public.pin(Path(p['path']))==p for p in er['sourcePins'])),
            'boundaryCases':len(er['cases']),'actualConverterControlsPassed':False,'runtimeIntegrated':False,'modelCalls':0,
            'sourcePins':[public.pin(Path(__file__).with_name(n)) for n in ('excel_conversion_protocol.py','pristine_excel_conversion.py','build_excel_conversion.py','excel_controls.py','prepare_excel.ts')]}
    hold_path=HOME/'coordination-hold.json'
    if hold_path.exists():
        hold=json.loads(hold_path.read_bytes());replacement=bool(control['paidReady'] and (control['broker']['pid']!=hold['brokerPid'] or control['broker']['runId']!=hold['brokerRunId']))
        status['resourceCoordinationHold']={'evidencePin':public.pin(hold_path),'active':not hold.get('releasedAtUtc') and not replacement,'replacementPublishedReady':replacement}
        if status['resourceCoordinationHold']['active']:
            status['nextAction']='Coordinator broker replacement hold: existing PID50372 may finish and release through its captured old connection. Do not acquire any new resource or paid lane. Keep active build/control sources frozen; continue only work without containers. After a published replacement broker identity and paidReady=true, inspect owned processes and claim the shared slot once.'
            if status.get('codePreparation',{}).get('stage')=='actual_native_controls_complete' and safe_owner is None:
                status['nextAction']='Native Wyckoff cold controls completed; old PID50372 exited and heavy resource released. Wait for replacement control without claiming resources/paid lanes. Current Stand/runtime native integration is implemented but unvalidated; after coordination resumes, run true missing/helper/dependency/same-run snapshot controls and current-source data bridge refresh. Original storage/capture parity and financial/lifecycle checks remain required before full87 dispatch.'
    status['lastHeartbeat']={'atUtc':utc(),'phase':status['phase'],'preparedTaskCount':len(prepared),'modelRequests':status['modelRequests'],'costUsd':status['costUsd'],
        'newWork':[str(len(prepared))+' actual source-current empty/oracle/wrong controls',str(policies['reviewedPolicyCount'])+' explicit single/multi/directory policies',
            'Current bridge refresh verified='+str(refresh_current),'Resume planning controls added; actual cash/lifecycle integration remains unvalidated']}
    status['heartbeat'].update(costPolicy='record_and_continue',feeReviewBlocksExecution=False)
    # Control receipts are never promoted into F completed/scored totals.
    save(HOME/'status.json',status)
    print(json.dumps({'phase':status['phase'],'preparedTaskCount':len(prepared),'completed':status['completed'],
        'modelRequests':status['modelRequests'],'costUsd':status['costUsd'],'policyCount':policies['reviewedPolicyCount'],'heavyOwner':safe_owner}))

if __name__=='__main__':main()
