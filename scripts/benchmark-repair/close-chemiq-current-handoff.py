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
md='ChemIQ 已按用户切换独立对话的指令停止新增工作。\n\n完成：七个新执行源+测试按SHA冻结；20pass/0fail/124断言，真实子进程exit0，0模型/HTTP服务/Docker/生产锁。F原生源码归档控制109source+4100deps通过；原科学81源未变。独立stored34审核逐个联接204HTTP记录、26PubChem+8Root构造与旧782，816keyset完整；没有把controls称正式成绩。\n\n未完成：bridge-v2只提出方案，无新v2文件、控制或运行；96条选中16的cold输入材料未生成，helper/gate均不存在，路径为null。没有未交付的半成品Bench源。旧7源仍不支持真实bridge，不能填none或假换CID。\n\n当前C约971MB不够1GiB门；52.81余额最多14.41782新envelope，未证明16F900够用，充值承诺不算到账。full816未来仍需用户专项确认、effective34extension/cold图及成本准入。旧TB USD未在legacyprior分解中，不冒称账户总额。\n\n参考路径均在state.json，包含原review/source/control/stored审核Pin。新独立对话接手前应读取这些原件，保留红/绿、lowercase driver原失败与later native recovery的不同时间证据；不改原refs/cache/论文/旧账/4unknown。\n'
md_pin=write(OUT/'README.md',md)
for p in implementation['sourcePins']:assert pin(p['path'])==p
print(json.dumps({'statePin':report,'readmePin':md_pin,'originalSevenUnchanged':True,'models':0},ensure_ascii=False))
