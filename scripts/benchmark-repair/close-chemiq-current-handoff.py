"""F-only metadata handoff after the user's explicit move to independent benchmark chats."""
from pathlib import Path
import hashlib, json, os
ROOT=Path(__file__).resolve().parents[2]
DOC=ROOT/'docs/repair-2026-10-08'
OUT=DOC/'chemiq-f-journal-implementation-v1/handoff-2026-10-09'
def sha(p):
    h=hashlib.sha256()
    with Path(p).open('rb') as f:
        for b in iter(lambda:f.read(1024*1024),b''):h.update(b)
    return h.hexdigest()
def pin(p):
    p=Path(p).resolve();return dict(path=str(p),bytes=p.stat().st_size,sha256=sha(p))
def write(p,j):
    raw=(json.dumps(j,ensure_ascii=False,indent=2)+'\n').encode() if not isinstance(j,str) else j.encode()
    p.parent.mkdir(parents=True,exist_ok=True)
    with p.open('xb') as f:f.write(raw);f.flush();os.fsync(f.fileno())
    assert p.read_bytes()==raw;return pin(p)
implementation_path=DOC/'chemiq-f-journal-implementation-v1/review.json'
implementation=json.loads(implementation_path.read_bytes())
assert pin(implementation_path)['sha256']=='54353590357adc2438a1fc3f7019ca3cdad719dd6203fafa8e5cb20ce3821eff'
for p in implementation['sourcePins']:assert pin(p['path'])==p
stored_path=DOC/'chemiq34-independent-stored-review-v1/review.json'
assert pin(stored_path)['sha256']=='fb95c7263a76612b97a4a71190b1aebffa30e2b985a02927782fd42572c64bc0'
body={'protocol':'chemiq-independent-chat-handoff-v1','workStoppedOnParentInstruction':True,'modelCallsByThisImplementationWork':0,
 'actualProviderOrGradeExecutionByThisAgent':False,'productionLockAcquired':False,'paperModified':False,
 'completed':{'implementationReviewPin':pin(implementation_path),'controlsPin':implementation['controlPin'],'frozenSourcePins':implementation['sourcePins'],
  'frozenSevenExecutionSourcesRemainUnchanged':True,'controls':{'pass':20,'fail':0,'assertions':124,'observedChildExit':0,'httpServers':0,'docker':0,'realProvider':0},
  'sourceArchive':implementation['sourceArchiverWitness'],'sourceArchiveScope':'Actual F-only native archive control:109 source+4100 installed dependency members, no benchmark execution.',
  'originalScience81Unchanged':True,'stored34ReviewPin':pin(stored_path),'stored34Scope':'204 actual stored HTTP wires independently matched;26PubChem names+8Root constructions;782+34 exact816 keyset;controls only.'},
 'uncompleted':{'bridgeV2':{'status':'proposal_only','sourceWritten':False,'copiesOfSevenWritten':False,'newControlsRun':False,
   'proposedApproach':'Independent new version/import graph with original7+20 controls preserved; bind actual fixed bridge private service and unique127.0.0.1 port publication, readonly root/mounts, source/runtime/core-tool evidence. No widening to arbitrary bridge.'},
  'cold96':{'status':'not_generated_not_executed','expectedRequests':96,'taskCount':16,'caseKinds':['positive','wrongValue','wrongFormat'],'nodes':['parsed','correct'],
   'materialPath':None,'helperSourcePath':None,'coldGatePath':None,'realColdEngineBooted':False,
   'plannedPrivateInputs':['docs/repair-2026-10-08/legacy-chemiq-616-controls-private-references-raw-length.json','docs/repair-2026-10-08/legacy-chemiq-200-controls-private-references-raw-length.json'],
   'instruction':'Select exact16 from frozen900 readiness, preserve private positive/negative/format original inputs and hashes; never provide them to the solver or public sourceZIP; record all expected values as prospective, actual fields null until Root executes.'},
  'formalPaidReady':False,'pilot16PaidExecuted':False,'full816Executed':False,'full816UserConfirmationStillRequired':True,
  'draftInventory':{'unfinishedNewSourceFiles':[],'unfrozenActiveBenchSource':False,
   'completedAuxiliarySource':'scripts/benchmark-repair/audit-chemiq34-stored-v1.py; stored-only executed once, no grading/network.'}},
 'criticalBlockers':[
  'Frozen v1 gate demands NetworkMode none, but Root fresh exact-originalCID4c334ef1… observation found bridge and unique127.0.0.1:17918 binding. No new projectionPin was delivered before stop. v1 cannot be honestly passed with this service; requires a separately reviewed narrow new version or new profile.',
  'Root reported Cfree~971MB, below1GiB start floor. Source/dependencies must be revalidated after any independent space repair; this agent performed no further move/delete/compression.',
  'Actual supplied balance snapshot52.81 CNY leaves at most14.41782 after originalunknown8.39218+operatorheadroom30. It does not prove completion of16F900; old10NMR shape scalar900 scenario16~66.98cached/477.21nocache is nonrepresentative but exceeds that envelope. Recharge promise is not cash evidence.',
  'New34 reference extension and HTTP recovered proof remain separate from current original0d/ffda private service. Do not overwrite old refs/cache or claim effective integration merely from816 stored coverage.',
  'Current USD prior decomposition covers legacy science/JPGF, closed interrupted science74.31931532400054 once, newJPGD and ChemIQ; oldTBnginx$0.019480980 is outside that baseline and no universal newTB cross-family scanner was wired. CNYbalance reflects posted spending; neither report is invoice/FX.',
  'Run only after independent chat/source/cold/price/balance/resource/cross-family review. Same canonical wx single payer; never delete original4unknown or bypass an existing owner.'] ,
 'handoffOnly':True,'producerPin':pin(__file__)}
report=write(OUT/'state.json',body)
md='ChemIQ has stopped new work following the user instruction to switch to an independent conversation.\n\nCompleted: seven new execution sources plus tests frozen by SHA; 20pass/0fail/124 assertions, actual subprocess exit0, and 0 model/HTTP service/Docker/production-lock operations. F native source archive controls passed for 109 sources + 4100 dependencies; the original 81 scientific sources are unchanged. The independent stored34 audit joins 204 HTTP records individually, 26 PubChem + 8 Root-constructed names, and the old 782, completing the 816 keyset; controls are not called formal results.\n\nIncomplete: bridge-v2 is a proposal only, with no new v2 files, controls, or runs. Cold input materials selecting 16 of 96 records were not generated; neither helper nor gate exists, and paths are null. There are no undelivered partial benchmark sources. The old 7 sources still do not support a real bridge; do not insert none or a fake replacement CID.\n\nCurrent C drive free space is about 971MB, below the 1GiB gate. A 52.81 balance permits at most a 14.41782 new envelope, which is not proven sufficient for 16F900; a top-up promise is not received funds. Future full816 still needs specific user confirmation, effective34extension/cold graph, and cost admission. Old TB USD costs are absent from the legacyprior breakdown; do not claim an account total.\n\nAll reference paths are in state.json, including original review/source/control/stored-audit pins. A new independent conversation should read those originals before taking over, preserving red/green outcomes and the distinct temporal evidence of the original lowercase-driver failure and later native recovery. Do not change original refs/cache/paper/old accounts/4unknown.\n'
md_pin=write(OUT/'README.md',md)
for p in implementation['sourcePins']:assert pin(p['path'])==p
print(json.dumps({'statePin':report,'readmePin':md_pin,'originalSevenUnchanged':True,'models':0},ensure_ascii=False))
