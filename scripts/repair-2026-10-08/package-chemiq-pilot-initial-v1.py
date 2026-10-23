"""Initial real-pilot ZIP. Reuses V5 filesystem guards; does not run models or certification audits."""
from datetime import datetime, timezone
import gzip
import hashlib
import importlib.util
import io
import json
import os
from pathlib import Path
import zipfile

ROOT=Path(__file__).resolve().parents[2]
DOC=ROOT/'docs/repair-2026-10-08'
HOME=DOC/'chemiq-f-journal-implementation-v3'
RUN='repair-2026-10-09T12-21-50-354Z'
OLD='repair-2026-10-09T09-40-03-707Z'
OUTPUT=DOC/'chemiq-f-journal-campaigns-v3'/RUN
spec=importlib.util.spec_from_file_location('chemiq_existing_packager_v5',ROOT/'scripts/repair-2026-10-08/package-chemiq-pilot-v5.py')
existing=importlib.util.module_from_spec(spec);spec.loader.exec_module(existing)

VERIFY=r'''"""Offline ZIP integrity check only; no model, grader, network or SQLite access."""
import argparse, hashlib, json, pathlib, zipfile
def verify(path):
    with zipfile.ZipFile(path) as bundle:
        names=bundle.namelist()
        assert len(names)==len(set(names)), 'Duplicate ZIP member'
        assert all(not n.startswith(('/', '\\')) and '..' not in pathlib.PurePosixPath(n).parts for n in names), 'Unsafe ZIP member'
        manifest=json.loads(bundle.read('package-manifest.json'))
        records=manifest['members']
        assert set(names)=={r['member'] for r in records}|{'package-manifest.json'}, 'Member set mismatch'
        for record in records:
            raw=bundle.read(record['member'])
            assert len(raw)==record['bytes'] and hashlib.sha256(raw).hexdigest()==record['sha256'], 'Changed member: '+record['member']
        summary=json.loads(bundle.read('summary.json'))
        assert summary['executionCompletedTasks']==16 and summary['finalGradePassedTasks']==16
        assert summary['originalScoreCertificateValid'] is False and summary['recoveredPilotValidated'] is False
        assert summary['full816Executed'] is False
    digest=hashlib.sha256()
    with pathlib.Path(path).open('rb') as stream:
        for block in iter(lambda:stream.read(1024*1024),b''):digest.update(block)
    return {'verified':True,'memberCount':len(names),'bytes':pathlib.Path(path).stat().st_size,'sha256':digest.hexdigest(),'modelCalls':0,'graderCalls':0,'certificationReplayed':False}
if __name__=='__main__':
    parser=argparse.ArgumentParser();parser.add_argument('archive');args=parser.parse_args()
    print(json.dumps(verify(args.archive),ensure_ascii=False))
'''

def encoded(value):return (json.dumps(value,ensure_ascii=False,indent=2)+'\n').encode('utf-8')
def main():
    initial=HOME/'initial-delivery-v1'/RUN
    summary=json.loads((initial/'chemiq-pilot16-initial-results.json').read_bytes())
    assert summary['runId']==RUN and summary['executionCompletedTasks']==16 and summary['finalGradePassedTasks']==16
    assert summary['originalScoreCertificateValid'] is False and summary['recoveredPilotValidated'] is False
    manifest=json.loads((OUTPUT/'manifest.json').read_bytes());recipe=json.loads(Path(manifest['recipePin']['path']).read_bytes())
    gate=json.loads(Path(recipe['runtimeGate']['path']).read_bytes());provenance=json.loads((DOC/'chemiq-nextwave-grader-provenance.json').read_bytes())
    target=HOME/'pilot-packages'/(RUN+'-initial-v1');target.mkdir(parents=True,exist_ok=False)
    archive=target/'ChemIQ-pilot16-F900-initial-results.zip'
    items={};generated={}
    def add(member,path):
        path=existing.ordinary(Path(path).resolve())
        assert member not in items and member not in generated
        assert path.name.lower()!='.env' and path.suffix.lower() not in {'.key','.pem'}, 'Credential file prohibited'
        items[member]=path
    def folder(label,path):
        for p in sorted(Path(path).rglob('*')):
            if p.is_file():add(label+'/'+p.relative_to(path).as_posix(),p)
    folder('tasks/run-records',OUTPUT)
    folder('raw/owned-model-store',Path(recipe['store']))
    folder('source/paid-preparation',Path(manifest['recipePin']['path']).parent)
    folder('provenance/cold-runtime-controls',Path(recipe['runtimeGate']['path']).parent)
    folder('provenance/cold-materials',Path(gate['materialPin']['path']).parent)
    folder('provenance/source-review-07',HOME/'source-review-07')
    folder('provenance/completed-task-and-runtime-error-reviews',HOME/'independent-v3-runtime-abort-review-v1')
    folder('provenance/recovery-observation-not-certified',HOME/'independent-v3-closed-runtime-recovery-v1'/RUN)
    folder('provenance/recovery-source-review-pending',HOME/'independent-v3-closed-runtime-recovery-source-review-v1')
    folder('failed-attempts/'+OLD+'/records',DOC/'chemiq-f-journal-campaigns-v2'/OLD)
    folder('failed-attempts/'+OLD+'/raw-store',ROOT/'.phase1-data/chemiq-f-journal-v2'/OLD)
    folder('failed-attempts/'+OLD+'/financial-recovery',DOC/'chemiq-f-financial-recoveries-v2'/OLD)
    add('summary.json',initial/'chemiq-pilot16-initial-results.json')
    add('results.zh.txt',initial/'chemiq-pilot16-initial-results.zh.txt')
    add('selection.json',Path(manifest['recipePin']['path']).parent/'public-tasks.json')
    add('provenance/frozen-grader-provenance.json',DOC/'chemiq-nextwave-grader-provenance.json')
    add('source/dependencies/opsin-cli-2.8.0-jar-with-dependencies.jar',Path(provenance['opsin_jar']['path']))
    for label,pin in [('account-balance',recipe['balance']),('official-prices',recipe['prices']),('available-models',recipe['modelAvailability'])]:
        add('provenance/provider-observations/'+label+'.json',pin['path'])
    prices=json.loads(Path(recipe['prices']['path']).read_bytes());add('provenance/provider-observations/official-pricing.html',prices['officialResponsePin']['path'])
    recovery=json.loads((HOME/'independent-v3-closed-runtime-recovery-v1'/RUN/'recovery-observation.json').read_bytes())
    for label in ('inspectPin','bridgePin','resourcePin'):add('provenance/recovery-native-inputs/'+label+'.json',recovery[label]['path'])
    for name in ['package-chemiq-pilot-v5.py','package-chemiq-pilot-initial-v1.py','chemiq-v3-shutdown-native-diagnostic-01.ts','chemiq-v3-closed-runtime-recovery-v1.ts']:
        add('source/packaging-and-recovery-helpers/'+name,ROOT/'scripts/repair-2026-10-08'/name)
    counts={'taskRecords':len(list(OUTPUT.glob('task-*.json'))),'taskTraces':len(list(OUTPUT.glob('trace-*.jsonl'))),'rawModelRequests':len(list(Path(recipe['store']).glob('provider-*-request.json.gz'))),'rawModelResponses':len(list(Path(recipe['store']).glob('provider-*-response.json.gz')))}
    assert counts=={'taskRecords':16,'taskTraces':16,'rawModelRequests':46,'rawModelResponses':46}
    generated['README.md']=('''# ChemIQ 16题 F900 试跑初版结果包

固定16题已实际执行并完成最终评分，16题均通过。每题时间预算900秒，F臂、4并发；46次真实模型请求。此包是初版实际结果，原V3关闭证书仍为runtime-abort／score=false，不能视为全部认证完成，也不能外推816题。

| 项目 | 结果 |
| --- | ---: |
| 计划／已执行／已最终评分 | 16／16／16 |
| 最终评分通过／失败／未完成 | 16／0／0 |
| 有效生成 | 16 |
| 真实模型请求 | 46 |
| 实际物理评分回执／独立最终回执 | 106／32 |
| 本轮新增费用估算 | 0.20077968元 |

运行参数、逐题答案、官方索引和ID见summary.json；逐题中文表见results.zh.txt。此前失败轮费用估算5.32224116元另列，两个轮次未拼题或混合计分。费用是按usage与官方费率计算的估算，不是账单。

## 已完成与待补

16题候选、900秒期限、完整轨迹、32份最终parsed／correct原始回执、46次请求usage与现金链已经独立核验；131个实际源码文件及冻结归档成员匹配。原关闭检查只留下SystemError名称，具体错误码和失败子命令未知，因此原失败证书、摘要和记录全部保留。补充的完整原运行时审计、17个本轮进程和18个端口消失观察已通过，原文件前后哈希一致。

独立恢复证书尚未签发；恢复helper的桥进程／磁盘字段完整谓词补齐审阅仍为pending。本包不修改原失败状态、不冒充冻结V3成绩证书。包本身仅完成一次离线成员完整性核对，未新增重复双轴审阅。816题未启动。

## 文件布局

- tasks/run-records：16份实际任务记录、完整trace、候选答案、最终评分和原关闭／费用证据。
- raw/owned-model-store：46对模型原始gzip请求／响应、完整usage事件与现金账本、实际评分请求／响应／回执、16个停止后的DB／WAL／SHM以及本轮冻结源码ZIP。
- source：实际付费配方／配置／源码清单及已有源码快照、打包器与恢复观察源码、固定OPSIN依赖。完整源码和Node依赖实物位于raw/owned-model-store/frozen-source.zip；公开评分源码另在该store的grader-provenance内。
- provenance：冷评分控制、私有评分器环境和依赖清单、已有独立审阅、尚未认证的恢复观察。
- failed-attempts：此前失败／中断轮的真实任务、轨迹、模型原始请求响应、现金与精确锁释放证据；不计入本轮16题。

原始证据保留其采集时的绝对路径；文件实物均按上述成员目录收入ZIP。package-manifest.json可按sourcePath查找对应成员。指向其他Bench、操作系统解释器或容器镜像的历史引用不代表其已装入本包；Bun、Python、Java等外部执行器仅提供现有版本／哈希清单，Docker镜像未导出。

## 离线核验

从ZIP取出verify-package.py，执行`python verify-package.py <本ZIP路径>`。它核对完整成员集合、CRC、大小与SHA256，不访问模型、评分服务、网络或SQLite。package-manifest.json列出除清单自身以外的所有成员；清单自身和ZIP的哈希记录在外置package-receipt.json。ZIP内package-receipt.json为打包过程收据，ZIP最终哈希仅在外置收据记录，避免循环哈希。

不包含.env、鉴权header、私钥或API key实值。本包写入时扫描当前实际provider key，包括gzip和嵌套ZIP展开；本轮原封存secret-audit另证明当时使用的provider／grader两值扫描通过。此前轮的grader临时token已不可得，因此不声称对其重新完成实值扫描。
''').encode('utf-8')
    generated['verify-package.py']=VERIFY.encode('utf-8')
    generated['package-receipt.json']=encoded({'protocol':'chemiq-pilot16-initial-package-internal-receipt-v1','runId':RUN,'deliveryStage':'initial-real-results','executedTasks':16,'finalPassedTasks':16,'failedTasks':0,'uncompletedTasks':0,'actualPayloadCounts':counts,'originalScoreCertificateValid':False,'recoveredPilotValidated':False,'modelCallsByPackager':0,'graderCallsByPackager':0,'manifestMember':'package-manifest.json','finalArchiveHashInExternalReceipt':True,'recoveryCertification':'pending','newIndependentPackageReview':'pending'})
    env_file=(ROOT/'.env').read_text(encoding='utf-8-sig');secret=None
    for line in env_file.splitlines():
        if line.startswith('DEEPSEEK_API_KEY='):secret=line.split('=',1)[1].strip().strip('"\'').encode('utf-8')
    assert secret and len(secret)>=16,'Provider secret unavailable for safe packaging'
    scanned=0;expanded=0
    def scan(raw,member,depth=0):
        nonlocal scanned,expanded
        scanned+=1;assert secret not in raw,'Sensitive credential found in '+member
        assert depth<5,'Unexpected nested archive depth'
        if raw.startswith(b'\x1f\x8b'):
            expanded+=1;scan(gzip.decompress(raw),member+'::gzip',depth+1)
        elif raw.startswith(b'PK\x03\x04'):
            with zipfile.ZipFile(io.BytesIO(raw)) as nested:
                for info in nested.infolist():
                    if not info.is_dir():expanded+=1;scan(nested.read(info),member+'::'+info.filename,depth+1)
    member_records=[]
    with archive.open('xb') as destination:
        with zipfile.ZipFile(destination,'w',compression=zipfile.ZIP_DEFLATED,compresslevel=3) as bundle:
            for member,path in sorted(items.items()):
                raw=path.read_bytes();scan(raw,member);bundle.writestr(member,raw)
                member_records.append({'member':member,'bytes':len(raw),'sha256':hashlib.sha256(raw).hexdigest(),'sourcePath':str(path)})
            for member,raw in generated.items():
                scan(raw,member);bundle.writestr(member,raw);member_records.append({'member':member,'bytes':len(raw),'sha256':hashlib.sha256(raw).hexdigest(),'generated':True})
            manifest_bytes=encoded({'protocol':'chemiq-pilot16-initial-package-manifest-v1','runId':RUN,'members':member_records,'memberCountExcludingManifest':len(member_records),'excludedSelfMember':'package-manifest.json','initialResultsOnly':True,'originalScoreCertificateValid':False,'recoveredPilotValidated':False,'full816Executed':False})
            bundle.writestr('package-manifest.json',manifest_bytes)
        destination.flush();os.fsync(destination.fileno())
    namespace={};exec(compile(VERIFY,'verify-package.py','exec'),namespace);verification=namespace['verify'](archive)
    receipt={'protocol':'chemiq-pilot16-initial-package-receipt-v1','runId':RUN,'createdAtUtc':datetime.now(timezone.utc).isoformat(),'archive':{'path':str(archive),'bytes':verification['bytes'],'sha256':verification['sha256']},'memberCount':verification['memberCount'],'manifestSha256':hashlib.sha256(manifest_bytes).hexdigest(),'zipCrcAndMemberHashesVerified':True,'verificationPasses':1,'actualPayloadCounts':counts,'credentialScan':{'actualProviderValuesChecked':1,'checkedPayloads':scanned,'expandedPayloads':expanded,'findings':0,'originalPaidRunTwoValueAuditIncluded':True,'oldGraderSecretRescanClaimed':False},'originalScoreCertificateValid':False,'recoveredPilotValidated':False,'full816Executed':False,'modelCallsByPackager':0,'graderCallsByPackager':0,'packagerSourcePin':{'path':str(Path(__file__).resolve()),'bytes':Path(__file__).stat().st_size,'sha256':hashlib.sha256(Path(__file__).read_bytes()).hexdigest()},'pending':['independent recovery certificate','new independent final-package review']}
    proof=target/'package-receipt.json'
    with proof.open('x',encoding='utf-8') as stream:json.dump(receipt,stream,ensure_ascii=False,indent=2);stream.write('\n');stream.flush();os.fsync(stream.fileno())
    print(json.dumps({'archive':receipt['archive'],'receiptPath':str(proof),'memberCount':verification['memberCount'],'verificationPasses':1,'providerCredentialFindings':0,'modelCalls':0,'graderCalls':0},ensure_ascii=False))
if __name__=='__main__':main()
