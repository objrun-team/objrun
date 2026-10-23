"""Plan F-only or explicitly copy a single closed real nginx U/F trial to fresh D.

No model, Docker, SQLite, network, config/env read, original modification, move,
delete or junction. Derive a TB-only ZIP from the original frozen archive.
"""
import argparse
import datetime as dt
import hashlib
import json
import os
from pathlib import Path, PurePosixPath
import re
import shutil
import stat
import uuid
import zipfile

ROOT = Path(__file__).resolve().parents[2]
RUN = 'tb-nginx-2026-10-08T10-47-06-544Z'
THREAD = '01a119ed-fdf7-7c32-b323-de9bab1290b6'
META = ROOT/'docs/repair-2026-10-08/campaigns'/RUN
STORE = ROOT/'.phase1-data/repair'/RUN
AUDIT = ROOT/'docs/repair-2026-10-08/tb-pilot-independent-audit'/RUN
DOC = ROOT/'docs/repair-2026-10-08/tb-real-nginx-handoff-v1'
OWNER = Path('D:/objrun-experiment-stores')/THREAD/'trial-packages'
MAX_PACKAGE = 512*1024**2
RESERVE_D = RESERVE_F = 1024**3
MAX_F_EVIDENCE = 1024**2
TASK = ROOT/'.phase1-data/terminal-bench/vendor/terminal-bench-2-1/tasks/nginx-request-logging'
METADATA = {'manifest.json','summary.json','task-0.json','task-1.json','api-ledger.json','tool-ledger.json',
            'quiescence-0.json','quiescence-1.json','terminal-bench-public-tasks.json','analysis.json'}
REPAIR = {'tb-nginx-campaign.ts','tb-nginx-contract.ts','tb-engine.ts','tb-tool-gateway.ts',
          'campaign-contract.ts','paid-campaign-lock.ts','freeze-tb-source.py'}
GRADER = {'stand.py','isolated_verifier.py','nginx_client.py','prepare_runtime.py','prepare_verifier_dependencies.py','objective.ts'}
SUSPICIOUS = re.compile(rb'(?:sk-[A-Za-z0-9_-]{24,}|(?:Bearer|X-ObjRun-Grader-Token:)\s+[A-Za-z0-9_-]{24,})')

def need(ok,message):
    if not ok:
        raise RuntimeError(message)

def sha(raw):
    return hashlib.sha256(raw).hexdigest()

def ordinary(path,file=False):
    p = Path(path).absolute()
    need(p.resolve() == p,'reparse_or_noncanonical_physical_path')
    for at in (p,*p.parents):
        s = at.lstat()
        need(not at.is_symlink() and not getattr(s,'st_file_attributes',0)&0x400,'reparse_path')
        need(stat.S_ISREG(s.st_mode) if at == p and file else stat.S_ISDIR(s.st_mode),'nonordinary_path')
    return p

def pin(path):
    p = Path(path).absolute()
    raw_path = p.resolve()
    ordinary(raw_path,file=True)
    before = raw_path.stat()
    h,n = hashlib.sha256(),0
    with raw_path.open('rb') as f:
        while chunk := f.read(1024**2):
            h.update(chunk);n += len(chunk)
    after = raw_path.stat()
    need((before.st_dev,before.st_ino,before.st_mtime_ns,before.st_size) ==
         (after.st_dev,after.st_ino,after.st_mtime_ns,after.st_size) and n == before.st_size,'input_changed_while_hashing')
    return dict(path=str(p),resolvedPath=str(raw_path),bytes=n,sha256=h.hexdigest())

def verify(p):
    need(pin(p['path']) == p,'input_pin_changed')

def rel(value):
    p = PurePosixPath(value)
    need(value and str(p) == value and not p.is_absolute() and '..' not in p.parts and '\\' not in value,'noncanonical_relative_member')
    need(not any(x == '.env' or x == 'config.yaml' or x.endswith(('.sqlite','.sqlite-wal','.sqlite-shm')) for x in p.parts),'private_member_forbidden')
    return p

def selected(name):
    rel(name)
    return (name.startswith('app/src/') or name.startswith('app/node_modules/') or name.startswith('artifacts/')
            or name in {'app/package.json','app/bun.lock','app/tsconfig.json','test/_lib.ts','scripts/phase1/source-snapshot.ts'}
            or name.startswith('scripts/repair-2026-10-08/') and PurePosixPath(name).name in REPAIR
            or name.startswith('examples/benchmark/terminal-bench/') and PurePosixPath(name).name in GRADER
            or name == 'examples/benchmark/_lib/grader_status.py')

def load(path):
    return json.loads(Path(path).read_bytes())

def new_dirs(path):
    p = Path(path).absolute(); ancestor=p
    while not ancestor.exists():
        ancestor=ancestor.parent
    ordinary(ancestor);p.mkdir(parents=True,exist_ok=True);ordinary(p)

def save_new(path, value, maximum=MAX_F_EVIDENCE):
    raw = value.encode() if isinstance(value,str) else (json.dumps(value,ensure_ascii=False,separators=(',',':'))+'\n').encode()
    need(len(raw) <= maximum,'new_evidence_size_bound')
    new_dirs(path.parent)
    with path.open('xb') as f:
        f.write(raw);f.flush();os.fsync(f.fileno())
    need(path.read_bytes() == raw,'new_evidence_readback')
    return pin(path)

def add_file(out,source,target,expected=None):
    rel(target);p=pin(source)
    if expected:
        need(p['bytes'] == expected['bytes'] and p['sha256'] == expected['sha256'],'independent_audit_inventory_changed')
    out.append(dict(source=p,target=target))

def README(plan):
    facts=plan['facts']
    return f'''# Terminal-Bench nginx 真实 U/F 试跑日志包

run: {RUN}；开始 UTC {facts['createdAt']}；2026-10-08 的真实模型请求，不是 local mock。
仅 nginx-request-logging，一冷候选/臂，U→F 串行，原任务来源 89、支持 1、其他 88 未运行；不外推旧 94.4% 或全量成绩。

| 臂 | 真实 API | 显式 verify | runtime 自动判卷 | 独立终判 | 有效官方测试 | 最终 |
|---|---:|---:|---:|---:|---:|---|
| U | 13 | 0 | 0 | 1 | 8/8 | passed |
| F | 14 | 0 | 2 | 1 | 8/8，每次4份中属于该臂的3份 | passed |

模型别名 deepseek-flash，provider https://api.deepseek.com，temperature0、seed42、reasoning none、max_tokens8192；别名/seed不固定 provider checkpoint。每臂agent900s，官方verifier900s，CHECKS4 是 ObjRun 配置，F 本次没有显式 verify。manifest 模板 independentRReplicas5 不代表本次运行 R：实际只有 U/F 两臂。

全部27回执 reported usage：prompt119887 / completion5392 / cache-hit78080 / uncached41807。原冻结USD峰价 input0.3/cache0.006/output1.2 perM；U $0.009403188，F $0.010077792，合计$0.019480980，为估算，不是发票/CNY汇率。保留54份原request/response gzip、API ledger及其pending/reserve闭合。

30份工具回执中4份HTTP500（每臂2）完整保留；U/F各在首次submit后还有1次模型请求，最终candidate选择/原trace与seal/drain时间都在task与quiescence证据中。API封口不证明容器后台服务不再写；本任务保留live nginx服务。private grader有独立PID/mount、固定原镜像解释器、无候选测试注入；仅本nginx协议的证据，不是通用隔离认证。

运行image与registry digest、Node22.22.2 executor image、实际Linux node/libgcc/libstdc++/runtime.mjs SHA都在metadata/manifest.json和source/selected-source-index.json。固定private Python3.13.7来自原image，uv0.9.5、pytest8.4.1、requests2.32.4、ctrf0.3.5及完整wheels/manifest在source/tb-frozen-source.zip。官方task/test原文和oracle仅此nginx任务在official-task/。此前cold curl失败属于较早基础设施无效，不是本次模型0分；本次v2 preseed的真实8测试输出放在raw/stand/logs。

目录：metadata/含两任务的完整answer/units/trace、预算/结果/API与工具账；raw/provider-*.json.gz、raw/tool-receipts/、raw/stand/logs/；audit/为原49项独立报告的完整字节引用；source/为此TB所需原ZIP成员的导出；official-task/只含nginx。原source.json/full frozen ZIP含其他benchmark修复源码，故不直接混装；本filtered ZIP为显式派生，不冒充原archive SHA或原完整sourceExecutionDigest。

隐私：不复制任何.env、worker/config.yaml、SQLite/WAL/SHM或真实凭据。原49报告精确验证4个当时仍可读的host控制值，0命中；stand/gateway header、broker和provider API key当时未可重扫，不能扩大为六值证书。新打包器仅对公开wire/log检查疑似长Bearer/sk字段；它不读取凭据。保留该边界，若敏感格式命中则停止并留owned partial。

离线复核：在本包根用 `python verification/verify-package.py`。只读本包文件SHA、selected ZIP逐member SHA/CRC；不会联网、评分、创建容器或调用模型。原49报告包含原SQLite验证的结果引用，但数据库因为私密字段未交付，离线脚本不重复其SQL部分。

复现一次新实验需独立新准入与冻结：从source/tb-frozen-source.zip取原core/runner/TB grader与公开依赖；按selected-source-index中的artifact映射还原runtime/.verifier-deps/官方文件，使用manifest固定镜像ID/registry digest、fresh token与冷候选，六工具经过鉴权gateway，seal/drain后原官方8条终判。原运行可写512MiB/stream1MiB，与官方10GiB storage不同，必须同行说明；不能直接在旧run目录续跑，也不能把旧fee guard或本日志包当新付费授权。本包不含镜像本体，不自动pull/build，默认只有离线复核。

独立成绩范围：U/F各1个真实任务通过；未声明等预算因果效应、全89完整或泛化隔离。原基准94.4%旧数据来源问题不由本试跑修复为同一个分数。
'''

VERIFIER = '''"""Offline SHA/ZIP CRC verifier. No model/network/SQLite/Docker."""
import hashlib,json
from pathlib import Path
import zipfile
ROOT=Path(__file__).resolve().parents[1]
def h(p):
    a=hashlib.sha256()
    with p.open('rb') as f:
        while c:=f.read(1024**2):a.update(c)
    return a.hexdigest()
m=json.loads((ROOT/'package-manifest.json').read_bytes())
for p in m['files']:
    f=ROOT/p['path'];assert f.is_file() and not f.is_symlink() and f.stat().st_size==p['bytes'] and h(f)==p['sha256'],p['path']
i=json.loads((ROOT/'source/selected-source-index.json').read_bytes())
with zipfile.ZipFile(ROOT/'source/tb-frozen-source.zip') as z:
    assert set(z.namelist())=={p[0] for p in i['members']}
    for name,size,want in i['members']:
        a=hashlib.sha256();n=0
        with z.open(name) as f:
            while c:=f.read(1024**2):a.update(c);n+=len(c)
        assert n==size and a.hexdigest()==want,name
print(json.dumps({'verified':True,'files':len(m['files']),'sourceMembers':len(i['members']),'modelCalls':0,'graderCalls':0}))
'''

def make_plan():
    new_dirs(DOC)
    need(shutil.disk_usage(ROOT).free >= RESERVE_F+MAX_F_EVIDENCE,'F_floor_before_plan')
    audit=load(AUDIT/'audit.json');summary=load(META/'summary.json');manifest=load(META/'manifest.json');frozen=load(META/'frozen-source.json')
    need(audit['run']==RUN and audit['passedAllAvailableChecks'] and summary['completed'] and summary['plannedTaskRuns']==summary['recordedTaskRuns']==2,'closed_real_trial_required')
    need(manifest['benchmarks']==['terminal-bench'] and manifest['datasets']['terminal-bench']['selectedTaskIds']==['nginx-request-logging'],'one_benchmark_one_task')
    direct=[];meta_index={p['path']:p for p in audit['metadataInventory']};raw_index={p['path']:p for p in audit['rawInventory']}
    for name in sorted(METADATA):
        add_file(direct,META/name,'metadata/'+name,meta_index[name])
    for path in sorted(AUDIT.iterdir()):
        if path.is_file() and path.suffix in ('.json','.md'):
            add_file(direct,path,'audit/'+path.name)
    for name,p in sorted(raw_index.items()):
        if re.fullmatch(r'provider-\d+-(request|response)\.json\.gz',name) or name.startswith('tool-receipts/') or name.startswith('stand/logs/') or name=='stand.log':
            add_file(direct,STORE/name,'raw/'+name,p)
    for path in sorted(TASK.rglob('*')):
        if path.is_file():
            add_file(direct,path,'official-task/'+path.relative_to(TASK).as_posix())
    archive=pin(STORE/'frozen-source.zip')
    need(archive['sha256']==frozen['archiveSha256'] and archive['bytes']==frozen['archiveBytes'],'original_archive_pin')
    members=[];excluded=0
    with zipfile.ZipFile(archive['path']) as z:
        need(len(z.namelist())==len(set(z.namelist())),'duplicate_archive_member')
        for info in z.infolist():
            if not selected(info.filename):
                excluded+=1;continue
            h,n=hashlib.sha256(),0
            with z.open(info) as f:
                while chunk:=f.read(1024**2):
                    h.update(chunk);n+=len(chunk)
            need(n==info.file_size,'archive_member_size')
            members.append([info.filename,n,h.hexdigest()])
    verify(archive)
    for p in direct:
        verify(p['source'])
    official_runs=audit['officialRuns']
    need(len(official_runs)==4 and all(p['validSavedOfficialEvidence'] for p in official_runs),'four_valid_saved_grades')
    plan=dict(protocol='terminal-bench-real-trial-package-plan-v1',run=RUN,plannedAtUtc=dt.datetime.now(dt.timezone.utc).isoformat(),
        writerPin=pin(__file__),sourceArchive=archive,directFiles=direct,zipMemberColumns=['path','bytes','sha256'],zipMembers=members,
        excludedArchiveSourceMemberCount=excluded,archiveIsDerived=True,otherBenchmarkDataIncluded=False,
        originalSourceMetadataReference=pin(META/'source.json'),originalFullFreezeMetadataReference=pin(META/'frozen-source.json'),
        sourceArtifacts=frozen['artifacts'],independent49AuditPin=pin(AUDIT/'audit.json'),
        sourceTaskCount=89,selectedTaskCount=1,arms=['U','F'],realModelCalls=27,localMockCalls=0,
        facts={'createdAt':manifest['createdAt'],'model':manifest['model'],'usage':audit['usage'],'costUsd':audit['computedCostUsd'],
               'arms':[dict(arm=p['arm'],apiCalls=p['apiCalls'],explicitVerify=p['modelExplicitVerifyCalls'],autoGrades=p['runtimeGradedEvents'],costUsd=p['computedCostUsd']) for p in audit['arms']],
               'physicalGrades':4,'officialTestsEach':8,'HTTP500ToolReceipts':4,'historicalKnownSecretScanValues':audit['secretScan']['knownValues']},
        projectedPublicCopyBytes=sum(p['source']['bytes'] for p in direct),selectedZipExpandedBytes=sum(p[1] for p in members),
        safePackageUpperBytes=sum(p['source']['bytes'] for p in direct)+sum(p[1] for p in members)+4*1024**2,
        proposedTarget=str(OWNER/('terminal-bench-nginx-real-uf-'+uuid.uuid4().hex)),maximumPackageBytes=MAX_PACKAGE,
        reserveDBytes=RESERVE_D,agentProductionPackageCreated=False,modelsRequestedByPlanner=0,DProductionWrites=0,
        packageExclusions=['worker-U/**','worker-F/**','.env','config.yaml','all SQLite/WAL/SHM','other benchmark-specific source/experiment logs','entire original ZIP'],
        limitations=audit['limitations'],secretScanBoundary=audit['secretScan'])
    need(plan['safePackageUpperBytes']<=MAX_PACKAGE,'512MiB_package_upper')
    result=save_new(DOC/'plan.json',plan)
    save_new(DOC/'README.proposed.md',README(plan))
    print(json.dumps({'plan':result,'directFiles':len(direct),'zipMembers':len(members),'safePackageUpperBytes':plan['safePackageUpperBytes'],'proposedTarget':plan['proposedTarget']}))

def copy_file(source,target,expected):
    ordinary(target.parent);before=pin(source);need(before==expected,'copy_before_pin')
    h,n=hashlib.sha256(),0
    with Path(before['resolvedPath']).open('rb') as a,target.open('xb') as b:
        while chunk:=a.read(1024**2):
            b.write(chunk);h.update(chunk);n+=len(chunk)
        b.flush();os.fsync(b.fileno())
    need(n==before['bytes'] and h.hexdigest()==before['sha256'],'copied_bytes')
    out=pin(target);need(out['bytes']==n and out['sha256']==h.hexdigest(),'copy_readback')
    verify(before);return out

def apply(plan_path,plan_sha,target,source_sha):
    pp=pin(plan_path);need(pp['sha256']==plan_sha and pin(__file__)['sha256']==source_sha,'explicit_reviewed_source_and_plan')
    need(Path(plan_path).resolve()==DOC/'plan.json','exact_plan_scope')
    p=load(plan_path);need(p['protocol']=='terminal-bench-real-trial-package-plan-v1' and p['writerPin']==pin(__file__),'plan_writer_changed')
    target=Path(target).absolute()
    need(str(target)==p['proposedTarget'] and target.parent==OWNER and re.fullmatch(r'terminal-bench-nginx-real-uf-[a-f0-9]{32}',target.name) and not target.exists(),'exact_fresh_D_target')
    ancestor=OWNER
    while not ancestor.exists():ancestor=ancestor.parent
    ordinary(ancestor);need(shutil.disk_usage(ancestor).free>=RESERVE_D+p['safePackageUpperBytes'],'D_package_envelope')
    before=[pp,pin(__file__),p['sourceArchive'],p['originalSourceMetadataReference'],p['originalFullFreezeMetadataReference'],p['independent49AuditPin'],*[x['source'] for x in p['directFiles']]]
    for value in before:verify(value)
    new_dirs(OWNER);target.mkdir(exist_ok=False);ordinary(target)
    written=[];success=False
    try:
        for item in p['directFiles']:
            destination=target/rel(item['target']);new_dirs(destination.parent)
            need(destination.is_relative_to(target),'target_escape')
            need(shutil.disk_usage(OWNER).free>=RESERVE_D+item['source']['bytes'],'D_before_file')
            # Only public logs/wire are checked for credential-shaped strings; do not read private keys.
            raw=Path(item['source']['resolvedPath']).read_bytes()
            if item['target'].endswith('.gz'):
                import gzip
                raw=gzip.decompress(raw)
            need(not SUSPICIOUS.search(raw),'public_evidence_potential_credential_stop')
            written.append(copy_file(Path(item['source']['path']),destination,item['source']))
        new_dirs(target/'source');new_zip=target/'source/tb-frozen-source.zip'
        with zipfile.ZipFile(p['sourceArchive']['path']) as z,zipfile.ZipFile(new_zip,'x',compression=zipfile.ZIP_DEFLATED,compresslevel=6) as out:
            for name,size,want in p['zipMembers']:
                rel(name);h,n=hashlib.sha256(),0
                with z.open(name) as a,out.open(name,'w') as b:
                    while chunk:=a.read(1024**2):
                        b.write(chunk);h.update(chunk);n+=len(chunk)
                need(n==size and h.hexdigest()==want,'source_member_changed')
                need(shutil.disk_usage(OWNER).free>=RESERVE_D,'D_during_archive')
        with new_zip.open('r+b') as f:f.flush();os.fsync(f.fileno())
        with zipfile.ZipFile(new_zip) as z:
            need(z.testzip() is None,'new_zip_crc')
        written.append(pin(new_zip))
        save_new(target/'source/selected-source-index.json',dict(protocol='tb-selected-original-archive-members-v1',run=RUN,members=p['zipMembers'],
            originalArchivePin=p['sourceArchive'],originalExecutionDigest='4121528abc77d10e47488063af9474c307ebbdbdaab867a86b3ffaba6acc46c6',
            derived=True,sourceArtifacts=p['sourceArtifacts']),maximum=MAX_F_EVIDENCE)
        save_new(target/'README.md',README(p));new_dirs(target/'verification');save_new(target/'verification/verify-package.py',VERIFIER)
        for value in before:verify(value)
        inventory=[dict(path=v.relative_to(target).as_posix(),bytes=v.stat().st_size,sha256=pin(v)['sha256']) for v in sorted(target.rglob('*')) if v.is_file()]
        need(sum(v['bytes'] for v in inventory)<=MAX_PACKAGE,'actual_package_size_bound')
        manifest=save_new(target/'package-manifest.json',dict(protocol='terminal-bench-real-trial-handoff-package-v1',run=RUN,
            sourcePlanPin=pp,writerPin=pin(__file__),target=str(target),files=inventory,
            originalBeforeAfterPinsUnchanged=True,modelCalls=0,graderCalls=0,DockerMutations=0,originalsModified=False,
            realTrialRuns=2,full89ScoreCertificate=False,credentialsReadByPackager=False))
        success=True
        evidence=save_new(DOC/('apply-'+uuid.uuid4().hex+'.json'),dict(protocol='tb-real-trial-package-copy-receipt-v1',validated=True,
            packageManifest=manifest,actualBytes=sum(v['bytes'] for v in inventory)+manifest['bytes'],files=len(inventory)+1,
            currentOriginalPinsUnchanged=before,DProductionCopyCreated=True,originalsModified=False,modelCalls=0,graderCalls=0))
        print(json.dumps({'receipt':evidence,'manifest':manifest,'target':str(target)}))
    except Exception as e:
        evidence=save_new(DOC/('invalid-'+uuid.uuid4().hex+'.json'),dict(protocol='tb-real-trial-package-copy-invalid-v1',validated=False,
            target=str(target),ownedPartialPreserved=True,completed=False,error=type(e).__name__+':'+str(e),originalsModified=False,
            modelCalls=0,graderCalls=0,newCopies=written))
        print(json.dumps({'invalid':evidence}));raise
    return success

if __name__=='__main__':
    parser=argparse.ArgumentParser();parser.add_argument('--mode',choices=['plan','apply'],default='plan')
    parser.add_argument('--plan',type=Path);parser.add_argument('--plan-sha');parser.add_argument('--source-sha');parser.add_argument('--target',type=Path)
    args=parser.parse_args()
    if args.mode=='plan':make_plan()
    else:
        need(all((args.plan,args.plan_sha,args.source_sha,args.target)),'explicit_apply_arguments')
        apply(args.plan,args.plan_sha,args.target,args.source_sha)
