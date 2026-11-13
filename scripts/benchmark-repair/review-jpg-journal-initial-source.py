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
    text='Read-only review of the four newly added frozen initial JPG files and related call chains is complete; 80 execution sources and 81 protected running-scientific fingerprints actually match. Original logs and source snapshots for 7 controls / 31 assertions are saved byte-for-byte. Controls, Docker, PID/port probes, APIs, and models were not rerun here.\n\n'
    text+='One P1 was found: the ownership probe requires at least four container IDs, but valid experimental failures caused by exhausted budgets or no candidate skip final grading and may have only two cold candidates and zero/one grader instances. This condition misclassifies valid failures as infrastructure errors and retains the lock, inconsistent with branches allowed by the entry point and auditor. The implementation agent confirmed it and is rebuilding the exact set from the two actual cold candidates and real grader ownership receipts. Initial originals are retained; the new version will be reviewed separately.\n\n'
    text+='The cash chain uses original CNY prices, an explicit new budget, and peak-rate liabilities for the four earlier unknown costs. Request gzip and journal prefixes are persisted before forwarding; completion and late-arrival evidence enter an independent cash witness. JPG uses its own grading audit and financial-release graph rather than the scientific results wrapper. The private grader receives only the fixed XLSX output and grades using the original complete task image and clean interpreter. These are source-review conclusions; this round establishes no new actual container-isolation proof.\n\n'
    text+='CHECKS=6 limits only explicit model verify; automatic feedback and independent final grading count separately as physical grading. Full scope remains 87 source tasks; only jpg-ocr-stat is currently supported, and the other 86 are unsupported. Original pure controls and the old Docker mock cannot replace a complete cold U/F mock for this version. Paid admission remains false pending revision closure, actual cold validation, balance/price fingerprints near startup, and C/F space gates.\n\n'
    text+='Review artifact: '+str(report)+'; SHA '+result['sha256']+'. Original input snapshot: '+str(BASE/'inputs.json')+', SHA '+pin(BASE/'inputs.json')['sha256']+'.\n'
    md=save(DOCS/'jpg-journal-independent-source-review-initial.md',text.encode())
    print(json.dumps({'report':result,'md':md,'findings':1,'modelRequests':0,'DockerOperations':0}))

if __name__=='__main__':main()
