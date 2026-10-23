/** Original receipt and its byte-identical archive represent one fact, not two recoveries. */
import{readPinned}from'./runtime.ts';import*as prior from'./retained-invalid-original-result.ts';
export const inspectDispositionHistory=prior.inspectDispositionHistory;
export const inspectDispositionCurrentParent=prior.inspectDispositionCurrentParent;
export const allowPreservedCandidateResult=prior.allowPreservedCandidateResult;
export function allowPreservedCandidateQueueResult(key:string,r:any){const receipts=r.proofPins.filter((p:any)=>{try{return readPinned(p).protocol==='bench-actual-original-history-recovery-v1'}catch{return false}});const unique=[...new Map(receipts.map((p:any)=>[p.sha256+':'+p.bytes,p])).values()]as any[];if(unique.length!==1)throw Error('retained_invalid_unique_recovery');const receipt=readPinned(unique[0]),m=readPinned(receipt.manifestPin);if(key!==m.bench+':'+m.taskId)throw Error('retained_invalid_queue_identity');return prior.allowPreservedCandidateResult(m,r)}
