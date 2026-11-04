"""Independent local audit and original/completed delivery; never calls a model."""
from pathlib import Path
import json
import re
from ops_recovery import LOCAL,ORIGINAL_LOCAL,REPO
from core import read,save,sha
from report_recovery import generate

def main():
    meta=read(LOCAL/'retrieval.json');root=Path(meta['fullResults']);checks=[]
    def check(name,value):checks.append({'name':name,'passed':bool(value)})
    check('recovery-archive-two-ends',meta['twoEndsSha256Verified'] and sha(meta['archive'])==meta['sha256'] and Path(meta['archive']).stat().st_size==meta['bytes'])
    check('trusted-new-authorization', (LOCAL/'authorization.json').read_bytes()==(root/'authorization.json').read_bytes() and read(root/'authorization.json')['retryUntilFirstValid'])
    parent=read(ORIGINAL_LOCAL/'retrieval.json');original_proof=read(ORIGINAL_LOCAL/'LOCAL_VERIFICATION.json')
    check('original-verified-archive-unchanged',original_proof['allPassed'] and sha(parent['archive'])==parent['sha256']==read(root/'recovery.json')['originalArchiveSha256'])
    old_inventory=read(Path(parent['fullResults'])/'outputs/canonical/file-inventory.json')
    for p in (root/'original-reference/results').glob('*/*.json'):
        rel='outputs/canonical/results/'+p.parent.name+'/'+p.name;check('original-record:'+rel,sha(p)==old_inventory[rel])
    inventory=read(root/'file-inventory-recovery.json')
    for n,(rel,h) in enumerate(inventory.items(),1):
        check('inventory:'+rel,(root/rel).is_file() and sha(root/rel)==h)
        if n%2000==0:print(json.dumps({'inventoryChecked':n,'total':len(inventory)}),flush=True)
    audit,result=generate(root,local=True);checks.extend(audit['checks'])
    server=read(root/'SUMMARY.json');check('independent-completed-stats',result['completed']['arms']==server['completed']['arms'] and result['completed']['categories']==server['completed']['categories'])
    check('independent-first-valid-provenance',result['recoverySources']==server['recoverySources'])
    for arm,g in result['fees']['allRecoveryAttempts']['byArm'].items():
        other=server['fees']['allRecoveryAttempts']['byArm'][arm];check('independent-fees:'+arm,abs(g['knownActualCostUsd']-other['knownActualCostUsd'])<1e-9 and g['unknownCostRequests']==other['unknownCostRequests'] and g['requests']==other['requests'])
    env=(REPO/'.env').read_text(encoding='utf-8-sig');m=re.search(r'^\s*(?:export\s+)?OPENROUTER_API_KEY\s*=\s*(.*?)\s*$',env,re.M);assert m
    secret=m[1].strip().strip('\"\'').encode();assert len(secret)>8;hits=[]
    for n,p in enumerate((p for p in root.rglob('*') if p.is_file()),1):
        tail=b''
        with p.open('rb') as stream:
            for chunk in iter(lambda:stream.read(1024*1024),b''):
                data=tail+chunk
                if secret in data:hits.append(p.relative_to(root).as_posix());break
                tail=data[-len(secret):]
        if n%5000==0:print(json.dumps({'credentialAbsenceFilesScanned':n}),flush=True)
    check('credential-absent',not hits)
    proof={'allPassed':all(c['passed'] for c in checks),'checkCount':len(checks),'checks':checks,'failures':[c for c in checks if not c['passed']],'archiveSha256':meta['sha256']}
    save(LOCAL/'LOCAL_VERIFICATION.json',proof)
    assert proof['allPassed'],proof['failures'][:10]
    save(LOCAL/'INDEPENDENT_SUMMARY.json',result)
    for name in ['SUMMARY.json','ORIGINAL_RESULTS.csv','COMPLETED_RESULTS.csv','REPLACEMENT_PROVENANCE.json']:(LOCAL/name).write_bytes((root/name).read_bytes())
    lines=['# LAB-Bench 原始实验与首次有效补跑结果','','原实验完整保留。仅对原 8 条基础设施异常重新给予每次 600 秒，以首次有效结果补齐；有效但答错、格式失败或正常预算耗尽均立即停止该身份。','', '|结果视图|题集|组别|通过/总数|未知|准确率范围|','|---|---|---|---:|---:|---|']
    for view in ['original','completed']:
        for category,arms in list(result[view]['categories'].items())+[('全部',result[view]['arms'])]:
            for arm,s in arms.items():lines.append(f"|{view}|{category}|{arm}|{s['passed']}/{s['tasks']}|{s['unknown']}|{s['accuracyBounds'][0]*100:.2f}%–{s['accuracyBounds'][1]*100:.2f}%|")
    lines+=['',f"共 {result['attemptCount']} 次补跑，新增声明求解预算 {result['additionalDeclaredSolveBudgetSeconds']} 秒；每次最多 3 次逻辑请求传输，全部失败与成功尝试都计入费用。逐身份来源和次数见 REPLACEMENT_PROVENANCE.json。",'','|费用范围|组别|已知实际 USD|费用未知请求|传输尝试|','|---|---|---:|---:|---:|']
    for scope,groups in [('原实验',result['fees']['original']['byArm']),('全部补跑',result['fees']['allRecoveryAttempts']['byArm']),('合计',result['fees']['combinedByArm'])]:
        for arm,g in groups.items():lines.append(f"|{scope}|{arm}|{g['knownActualCostUsd']:.9f}|{g['unknownCostRequests']}|{g['requests']}|")
    lines+=['','补齐视图是增加独立预算后的基础设施条件化补充结果，不替换原始冻结实验。完整方法有金标反馈；单次原始格式失败和截断均保留，不为答对而重试。原 3 条试跑恢复的停机计时例外仍属于原始视图；本批每次尝试独立重新授予完整 600 秒。',
            '',f"本地 {proof['checkCount']} 项核验通过；补跑归档 SHA256：{meta['sha256']}。原归档 SHA256：{parent['sha256']}。",
            '',f"完整材料：{meta['fullResults']}",f"补跑归档：{meta['archive']}",f"原始归档：{parent['archive']}"]
    (LOCAL/'RESULTS.md').write_bytes(('\n'.join(lines)+'\n').encode())
    save(LOCAL/'DELIVERY.json',{'delivered':True,'verified':True,'localChecks':proof['checkCount'],'recoveryArchive':meta,'originalArchive':parent,'firstValidCount':8,'attemptCount':result['attemptCount'],'additionalDeclaredSolveBudgetSeconds':result['additionalDeclaredSolveBudgetSeconds'],'fees':result['fees']})
    print(json.dumps({'allPassed':True,'checks':proof['checkCount'],'attempts':result['attemptCount'],'completed':result['completed']['arms'],'fees':result['fees']}),flush=True)

if __name__=='__main__':main()
