"""WX leaves-first publication only after Root review; dry-run is virtual. No signing or dispatch."""
import argparse,json,hashlib,sys
from pathlib import Path
ROOT=Path('F:/git/TgEngin-handoff-2026-10-07/TgEngin');D=ROOT/'docs/repair-2026-10-10/full-f-rerun/novaeve-formal-20261013/group-04/adapter_3/versions/pipeline-formal-successor-wx-v142';HOME=D.parents[3]
read=lambda p:json.loads(virtual[str(Path(p).resolve())].decode() if str(Path(p).resolve()) in virtual else Path(p).read_text(encoding='utf8'))
virtual={}
def pin(p):
 p=Path(p).resolve();b=virtual.get(str(p),None)
 if b is None:b=p.read_bytes()
 return dict(path=str(p),bytes=len(b),sha256=hashlib.sha256(b).hexdigest())
def wx(p,x):
 p=Path(p).resolve();assert not p.exists() and str(p) not in virtual,'WX publication collision';b=(json.dumps(x,indent=2)+'\n').encode()
 if args.dry_run:virtual[str(p)]=b;return
 p.parent.mkdir(parents=True,exist_ok=True)
 with p.open('xb') as f:f.write(b)
a=argparse.ArgumentParser();a.add_argument('--dry-run',action='store_true');a.add_argument('--root-review-completed',action='store_true');a.add_argument('--virtual-disposition-stdin',action='store_true');a.add_argument('--raw-root-disposition',required=True);a.add_argument('--draft',default=str(D/'entry.json'));a.add_argument('--fresh-history',required=True);a.add_argument('--history-root-review',required=True);args=a.parse_args()
assert args.dry_run or args.root_review_completed,'Root actual review required; no publication'
if args.virtual_disposition_stdin:
 assert args.dry_run and not args.root_review_completed,'virtual input can never make actual reviewed files'
 bundle=json.load(sys.stdin);assert bundle['dryRun'] is True and bundle['signed'] is False
 for item in bundle['virtualArtifacts']:
  body=item['body'];body['rootReviewed']=True
  if body.get('protocol')=='pipeline-root-independent-fresh-formal-disposition-v130':body['allowFreshFormalAttempt']=True
  virtual[str(Path(item['path']).resolve())]=(json.dumps(body,indent=2)+'\n').encode()
 # Rejoin the preview-only normalized pin after virtual flags; never write either leaf.
 raw=read(args.raw_root_disposition);normalpath=raw['mailboxDockerProbePin']['path'];raw['mailboxDockerProbePin']=pin(normalpath);virtual[str(Path(args.raw_root_disposition).resolve())]=(json.dumps(raw,indent=2)+'\n').encode()

e=read(args.draft);raw=read(args.raw_root_disposition);assert raw['rootReviewed'] and raw['raw127Nonce']=='pipeline_raw127_e9a0986d70f3427f90f7158543a2f0e1' and raw['originalFinalCandidateAbsent'] and not raw['rawResultIsFormalTaskResult'] and raw['allowFreshFormalAttempt'],'Root actual raw127 closure and separate fresh-attempt disposition required'
for k in ['rawGradePin','rawClosurePin','mailboxDockerProbePin']:assert pin(raw[k]['path'])==raw[k]
probe=read(raw['mailboxDockerProbePin']['path']);assert probe['actualDocker'] is True and probe['passed'] is True and probe['allOwnedActorsClosed'] is True and probe['modelCalls']==0 and probe['newPaidRequests']==0,'Root actual Docker probe pass and exact owned closure required'
closed=read(raw['rawClosurePin']['path']);assert closed['protocol']=='novaeve-pipeline-original-raw-regrade-closure-v128' and closed['nonce']==raw['raw127Nonce'] and closed['rawOnly'] and closed['formalValid'] is False and closed['formalPromotionForbidden'] and closed['allExactActorsApi404'] and closed['allExactProcessesAbsent'] and closed['allNativeCommandsClosed'] and closed['resourceReleased'] and closed['modelCalls']==0 and closed['newPaidRequests']==0 and closed['rawGradePin']==raw['rawGradePin'],'actual incomplete raw harness closure, no invented valid result'
e.update(raw127GradePin=raw['rawGradePin'],raw127ClosurePin=raw['rawClosurePin'],raw127RootDispositionPin=pin(args.raw_root_disposition),raw127DependencyReady=True,allowNewAttemptAfterClosedNativeFailure=True,mailboxDockerProbePin=raw['mailboxDockerProbePin'])
rawpins=[e['raw127GradePin'],e['raw127ClosurePin'],e['raw127RootDispositionPin'],e['mailboxDockerProbePin']];e['sourcePins'] += rawpins
assert e['requiredHistoryUnknownCount']==44 and e['latestRootHistoryReady'] is True,'Latest44 consumer not qualified; Root flags cannot override missing history';fresh=read(args.fresh_history);assert fresh['rootReviewed'] and fresh['unknownCount']>=e['requiredHistoryUnknownCount'] and fresh['incrementalOnly'] and fresh['old42FullReplayNotRepeated'],'Root latest44 reviewed history not published'
review=read(args.history_root_review);assert review['unknownCount']==fresh['unknownCount'],'Root review joins latest history';assert pin(args.fresh_history)==e['historyCarryPolicy']['accountHistoryFreshUnionPin'] and pin(args.history_root_review)==e['historyCarryPolicy']['rootReviewPin'],'Actual reviewed44 SHA/source binding required';assert pin(fresh['producerPin']['path'])==fresh['producerPin'] and fresh['baselinePin']==e['historyCarryPolicy']['currentAccountHistoryPin'],'Actual latest producer/baseline pin required'
for p in e['sourcePins']+[e['readinessPin'],e['taskPlanPin'],e['priorRunClosurePin'],e['taskCashCarryPin'],e['successfulPrefixClosedPin'],e['successfulPrefixSignedEntryPin']]:assert pin(p['path'])==p,'Frozen input changed'
out=HOME/'coordinator'/('pipeline-formal-successor-wx-v142-'+e['nonce']);segment=D/'root-reviewed'/e['nonce']
wx(segment/'source-manifest.final.json',{'sealed':True,'sourcePins':e['sourcePins'],'actualRaw127DependencyPins':rawpins});e['sourceManifestPin']=pin(segment/'source-manifest.final.json')
policy=e['historyCarryPolicy'];policy.update(accountHistoryFreshUnionPin=pin(args.fresh_history),rootReviewPin=pin(args.history_root_review),currentAccountHistoryPin=fresh['baselinePin'],reviewedFreshHistoryProducerPin=fresh['producerPin']);e.update(historyCarryPolicy=policy,rootReviewed=True,coordinatorReviewed=True,allowPaid=True,formalReady=True,readyForRootReview=True,allowNewAttemptAfterClosedTransportFailure=True,neverReplayOriginalWire=True,latestRootHistoryReady=True,phase='ready',blockReasons=[])
ready=read(e['readinessPin']['path']);ready['sourceManifestPin']=e['sourceManifestPin'];ready['taskEvidencePins'] += rawpins;ready['taskEvidencePins'] += [pin(args.fresh_history),pin(args.history_root_review)];wx(segment/'readiness.json',ready);plan=read(e['taskPlanPin']['path']);plan['jobs'][0]['readinessPin']=pin(segment/'readiness.json');wx(segment/'task-plan.json',plan)
e['readinessPin']=pin(segment/'readiness.json');e['taskPlanPin']=pin(segment/'task-plan.json');e['argv'][4:6]=[str(segment/'readiness.json'),str(segment/'task-plan.json')];runtime=out/'worker-runtime-policy.root-reviewed.json';authpath=out/'authorization.root-reviewed.json';e['argv'][6]=str(authpath);e['env']['NOVAEVE_PIPELINE_RUNTIME_ENTRY']=str(runtime);e['rootAuthorizationPublicationPath']=str(authpath);e['sourcePins'] += [pin(args.fresh_history),pin(args.history_root_review),pin(segment/'readiness.json'),pin(segment/'task-plan.json')]
# Runtime policy is a separate signed-body dependency, avoiding an auth/body hash cycle.
wx(runtime,e);auth=read(D/'root-authorization.template.json');auth.update(rootReviewed=True,allowPaid=True,rootOnlyDispatch=True,narrowCompositeApproved=True,productionAuditContractReviewed=True,allowNewAttemptAfterClosedTransportFailure=True,allowNewAttemptAfterClosedNativeFailure=True,neverReplayOriginalWire=True,entryPin=pin(runtime),sourceManifestPin=e['sourceManifestPin'],qualificationPin=e['qualificationPin'],readinessPin=pin(segment/'readiness.json'),taskPlanPin=pin(segment/'task-plan.json'),runtimeBindingPins=e['sourcePins']);wx(authpath,auth)
e['authorizationPin']=pin(authpath);e['runtimeRootEntryBinding']=pin(runtime);e['sourcePins'] += [pin(runtime),pin(authpath)];wx(out/'entry.reviewed-body-for-root-signing.json',e)
bun='C:/Users/y1252/AppData/Roaming/npm/node_modules/bun/bin/bun.exe';signer=ROOT/'scripts/benchmark-campaign/full-f/novaeve_formal_v1/coordinator/review-authority-pipeline-formal-v89.ts';signed=HOME/'coordinator/inbox-pipeline-formal-v89/formal'/(e['nonce']+'.json');result={'dryRun':args.dry_run,'virtualRootReviewOnly':args.virtual_disposition_stdin,'actualReviewedBodyPin':pin(out/'entry.reviewed-body-for-root-signing.json'),'actualAuthorizationPin':pin(authpath),'runtimePolicyPin':pin(runtime),'signCommand':[bun,'--smol',str(signer),'--sign',str(out/'entry.reviewed-body-for-root-signing.json')],'actualSignerOutputPath':str(signed),'validateCommand':[bun,'--smol',e['runnerPin']['path'],'--validate',str(signed)],'launchCommand':[bun,'--smol',e['runnerPin']['path'],'--run',str(signed)],'launchEnv':e['env'],'cwd':str(ROOT),'signingExecuted':False,'modelCalls':0,'resourceActions':0,'nativeActions':0};wx(out/'ROOT-ACTUAL-PUBLICATION.json',result);print(json.dumps(result))
