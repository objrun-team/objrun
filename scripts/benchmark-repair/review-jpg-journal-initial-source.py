"""F-only independent review of one immutable JPG source revision. No services."""
from pathlib import Path
import hashlib
import json
import os

ROOT=Path(__file__).resolve().parents[2]
DOCS=ROOT/'docs/repair-2026-10-08'
BASE=DOCS/'jpg-journal-independent-review-original-707be1d6'

def pin(path):
    data=path.read_bytes()
    return {'path':str(path),'bytes':len(data),'sha256':hashlib.sha256(data).hexdigest()}

def save(path,data):
    with path.open('xb') as stream:
        stream.write(data);stream.flush();os.fsync(stream.fileno())
    assert path.read_bytes()==data
    return pin(path)

def main():
    inputs=json.loads((BASE/'inputs.json').read_bytes())
    review=json.loads((BASE/'review.json').read_bytes())
    assert pin(BASE/'review.json')['sha256']=='cc9eef102bf649713412c7d96c862c2f1f7b64946cfd06816f78306cb12717fd'
    for row in inputs['copies']:
        assert pin(Path(row['snapshot']['path']))==row['snapshot']
    assert len(inputs['executionPinsObserved'])==80 and all(row['matches'] for row in inputs['executionPinsObserved'])
    assert len(inputs['scienceProtectedObserved'])==81 and all(row['matches'] for row in inputs['scienceProtectedObserved'])
    stderr=(BASE/'control.stderr.log').read_text()
    assert '7 pass' in stderr and '0 fail' in stderr and '31 expect() calls' in stderr
    campaign=BASE/'sources/scripts/benchmark-repair/skb-jpg-journal-campaign.ts'
    auditor=BASE/'sources/scripts/benchmark-repair/audit-jpg-journal-campaign.py'
    assert pin(campaign)['sha256']=='707be1d6c43f6df7d489f04a6688c5959899bc829bfec2013375b1fed47464ea'
    assert pin(auditor)['sha256']=='450097933809ebad7bd14380d388c376ce571a117b23622fe4d1c14b739acff5'
    assert "if(record.generationClassification.kind==='candidate')" in campaign.read_text()
    assert "len(ids)>=4" in auditor.read_text() and "task['generationClassification']['kind']=='experimental_failure'" in auditor.read_text()
    finding={'id':'JPG-OWNED-COUNT-1','priority':'P1','status':'confirmed_by_owner_narrow_revision_authorized',
        'file':str(ROOT/'scripts/benchmark-repair/audit-jpg-journal-campaign.py'),'line':146,
        'sourceSha256':pin(auditor)['sha256'],'relatedFiles':[{'file':str(ROOT/'scripts/benchmark-repair/skb-jpg-journal-campaign.ts'),'line':164},
            {'file':str(ROOT/'scripts/benchmark-repair/audit-jpg-journal-campaign.py'),'line':300}],
        'problem':'The owner probe assumes at least four container IDs, while a legitimate experimental_failure skips final grading. Two cold candidates and zero/one final graders with little/no feedback can yield only two/three real owned IDs. Those valid budget/no-candidate failures are rejected as owned_container_identity and cannot certify/release.',
        'requiredCorrection':'Bind both cold candidates to actual capture/removal and bridge ownership receipts, reconstruct the exact remaining IDs from real grader operation-owner receipts, reject missing/extra/duplicate/unclosed evidence; retain both arms and source87 without assuming two graders.'}
    findings=[finding]
    facts=[
        {'topic':'Cash and currency','result':'New JPG factory requires explicit fresh CNY balance/price Pins, original four unknown peak liability 8392180000 nano-CNY, CNY30 headroom and a chosen positive envelope. Same canonical wx owner nonce; old pending entries remain unknown. Peak USD report is separate from CNY shadow and neither is an invoice.','sourceLines':['jpg-paid-resource-admission-v1.ts:82-110','skb-jpg-journal-campaign.ts:102-109']},
        {'topic':'Durable provider facts','result':'Uses frozen journal139a/cash6ad/proofb1. Before-forward binds actual request gzip to the fsynced journal prefix. Normal and failed/late finish paths feed CNY witnesses; poison halts admission. Route/global provider drain precedes cash/journal close; no score/release on new unknowns.','sourceLines':['skb-jpg-journal-campaign.ts:105-109','skb-jpg-journal-campaign.ts:147-161','skb-jpg-journal-campaign.ts:191-199']},
        {'topic':'Private grading','result':'Only the fixed captured stat_ocr.xlsx crosses to a fresh private grader using the immutable full task image and clean original interpreter. Official tests/GT remain host/private; six solver tools use candidate runtime. Source-reviewed configuration, not new Docker certification.','sourceLines':['audit-jpg-journal-campaign.py:156-167','software-jpg-private-grader.py:352-392','skb-jpg-stand.py:272-280']},
        {'topic':'Model and tools','result':'Distinct U/F cold candidates, six tools, F-only verify, CHECKS6 and reuse never. CHECKS counts explicit verify; automatic feedback and independent final grades are additional physical grading. Late mutation/capture is valid budget failure. No equal-budget causal claim.','sourceLines':['skb-jpg-journal-campaign.ts:122-178','skb-jpg-contract.ts:52-59']},
        {'topic':'Family and certification','result':'JPG has its own registry/auditor/certificate and financial release acknowledgement; scientific score wrappers are not reused. Cross-family scanner rejects active science and unknown JPG scopes. Shared wx prevents concurrent paid owners. Frozen science scanner does not itself scan the JPG registry, so future launchers must explicitly call the JPG cross-family preflight.','sourceLines':['jpg-paid-resource-admission-v1.ts:39-67','jpg-paid-resource-admission-v1.ts:100-110']},
        {'topic':'Evidence and secrets','result':'Source archive references only approved public dependency members and preserves direct-source SHA/CRC. The entry scans six credential values excluding two private worker configs, gates candidate environment, probes unauthenticated/forged host tool paths, and binds the audit artifact. No new value scan or runtime probe was performed in this independent review. Full host distributions and raw Docker TAR are not newly certified.','sourceLines':['audit-jpg-journal-campaign.py:75-117','skb-jpg-journal-campaign.ts:125-138','skb-jpg-journal-campaign.ts:179-187']},
    ]
    value={'protocol':'jpg-journal-independent-source-review-v1','baselineReview':pin(BASE/'review.json'),'inputReport':pin(BASE/'inputs.json'),
        'reviewerSourcePin':pin(Path(__file__)),'pinnedInputsValid':True,'sourceBoundSpecFindings':findings,
        'standards':{'documentedHardViolationsFound':[],'scope':'Read the four new frozen files and source-bound imported paths. No broad stylistic or speculative refactors requested.'},
        'spec':{'findings':findings,'facts':facts},'sourceSnapshots':[row['snapshot'] for row in inputs['copies'] if 'canonicalBaseline' in row],
        'executionSourcePinsObserved':80,'executionSourceMismatches':[],'scienceProtectedPinsObserved':81,'scienceProtectedMismatches':[],
        'storedControls':{'pass':7,'fail':0,'assertions':31,'rerunByReviewer':False},'typecheck':review['typecheck'],
        'formalPaidReady':False,'coldDockerWorkflowReviewedForTheseSources':False,'sourceTaskCount':87,'supportedTaskIds':['jpg-ocr-stat'],'unsupportedTaskCount':86,
        'ownerRevisionInProgress':True,'limits':['Initial source review only; the fixed revision requires new source Pins, necessary controls and an independent delta review.',
            'Seven pure controls do not replace one actual cold U/F Docker mock with source/capture/namespace/cleanup/cash/six-credential evidence.',
            'No new model, balance query, Docker/PID/socket probe, production lock or migration was performed; only F review artifacts were written.',
            'Paid start needs an explicit chosen cash envelope, a fresh balance Pin, current price Pin and actual C/F free-space admission.'],
        'scope':{'onlyFWrites':True,'modelRequests':0,'networkRequests':0,'DockerOperations':0,'runtimeProbeOperations':0,'productionLocksAcquired':0,'existingSourcesModified':False}}
    report=DOCS/'jpg-journal-independent-source-review-initial.json'
    result=save(report,(json.dumps(value,ensure_ascii=False,indent=2)+'\n').encode())
    text='已对冻结的 JPG 初版四个新增文件及相关调用链完成只读审查，80 个执行源码和 81 个在跑科学保护指纹实际匹配。原 7 项控制、31 个断言的日志及源码快照已按原字节保存；本次没有重跑控制、Docker、PID/端口探测、API 或模型。\n\n'
    text+='发现一处 P1：所有权探针硬要求至少四个容器 ID，但预算耗尽或没有候选的合法实验失败会跳过终判，实际可能只有两个冷候选和零/一个判卷实例。该条件把合法失败归为基础设施错误并保留锁，与入口及审计器允许的分支不一致。实现代理已确认，正在按两个实际冷候选和真实判卷所有权收据重建精确集合；初版原件保留，新版另审。\n\n'
    text+='现金链使用 CNY 原始价格、显式新预算及旧四笔未知峰价责任；请求 gzip 和 journal 前缀先持久化再转发，完成和晚到证据进入独立现金见证。JPG 使用自己的评分审计与财务释放图，不使用科学成绩 wrapper。私有评分器只接收固定 XLSX 输出，以原始完整任务镜像和干净解释器判卷。上述是源码审查结论，本轮没有建立新的实际容器隔离证明。\n\n'
    text+='CHECKS=6 只限制模型显式 verify，自动反馈和独立终判另计物理判卷。完整口径保持 87 个源任务，当前仅支持 jpg-ocr-stat，其他 86 项未支持。原纯控制和旧 Docker mock不能替代这版完整冷 U/F mock。付费准入仍为 false，等待修订闭合、真实冷验证、临近启动的余额/价格指纹和 C/F 空间门。\n\n'
    text+='审核件：'+str(report)+'；SHA '+result['sha256']+'。原输入快照：'+str(BASE/'inputs.json')+'，SHA '+pin(BASE/'inputs.json')['sha256']+'。\n'
    md=save(DOCS/'jpg-journal-independent-source-review-initial.md',text.encode())
    print(json.dumps({'report':result,'md':md,'findings':1,'modelRequests':0,'DockerOperations':0}))

if __name__=='__main__':main()
