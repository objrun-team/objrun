import {checkedOutputTokens} from '../../../../benchmark-repair/campaign-contract.ts';
import {demand,hash} from '../../../../benchmark-repair/paid-resource-proof-v2.ts';
/** Same reservation as the unchanged journal, evaluated synchronously before admit. */
export function gatewayBudgetDecision(journal:any,raw:string,gatewayLimitUsd:number){
 const body=JSON.parse(raw),maxOutputTokens=checkedOutputTokens(body);demand(Array.isArray(body.messages),'recovery_request_messages');
 const requestBytes=Buffer.byteLength(raw),messagesCount=body.messages.length;
 const reservationUsd=((requestBytes+2048+messagesCount*256)*0.3+maxOutputTokens*1.2)/1e6;
 const priorSnapshot=journal.snapshot();
 demand(Number.isFinite(gatewayLimitUsd)&&gatewayLimitUsd>0&&Number.isFinite(priorSnapshot.recordedUsageUpperBoundUsd)&&Number.isFinite(priorSnapshot.reservedUpperBoundUsd),'real_recovery_gate_snapshot');
 const admitted=priorSnapshot.recordedUsageUpperBoundUsd+priorSnapshot.reservedUpperBoundUsd+reservationUsd<=gatewayLimitUsd;
 return {result:admitted?{admitted:true}:{admitted:false,reason:'recovery_task_or_parent_budget_exhausted'},priorSnapshot,gatewayLimitUsd,reservationUsd,requestSha256:hash(raw),requestBytes,maxOutputTokens,messagesCount};
}
