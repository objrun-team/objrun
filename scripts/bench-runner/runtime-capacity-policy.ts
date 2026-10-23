/** One signed capacity policy shared by original queue and broker. */
import{readFileSync}from'node:fs';import{verify}from'node:crypto';
import{verifyPin,demand}from'./manifest.ts';import type{Pin}from'./types.ts';
const AUTHORITY_PUBLIC_SHA='ed4e7676d5c78e04d328dbca6ff1666a496ef6d2f2e213925dc870384983ca98';
const HUMAN_AUTHORITY_SHA='430a105d94afce428ddd4fa9e5d31b67589e91a22b84aecc665ebe3ef686d48e';
export function verifyRuntimeCapacityPolicy(policyPin:Pin){
 verifyPin(policyPin);const e=JSON.parse(readFileSync(policyPin.path,'utf8')),p=e.policy;
 demand(e.protocol==='bench-signed-runtime-capacity-policy-v1'&&p?.protocol==='bench-runtime-capacity-policy-v1','runtime_capacity_policy_protocol');
 verifyPin(e.authorityPublicPin);demand(e.authorityPublicPin.sha256===AUTHORITY_PUBLIC_SHA,'runtime_capacity_original_authority_public');
 demand(verify(null,Buffer.from(JSON.stringify(p)),readFileSync(e.authorityPublicPin.path),Buffer.from(e.signature??'','base64')),'runtime_capacity_policy_signature');
 verifyPin(p.authorityPin);demand(p.authorityPin.sha256===HUMAN_AUTHORITY_SHA,'runtime_capacity_exact_human_authority');const h=JSON.parse(readFileSync(p.authorityPin.path,'utf8'));
 demand(h.protocol==='bench-human-provider-failover-and-concurrency-authority-v1'&&h.maximumActualSolvers===48&&h.capacity?.maximum===48&&h.capacity.noOversubscription===true&&h.historyAndLocksPreserved===true&&h.controlledHandoff.immutableInflightSignedSources===true,'runtime_capacity_original_user_scope');
 demand(p.maximumActualSolvers===48&&p.maximumPreparation===4&&p.physicalCpuCapacity===192&&p.aggregateMemoryMb===262144&&p.previousMaximumActualSolvers===16&&p.noOversubscription===true&&p.oldHoldsAndFinancialRowsPreserved===true,'runtime_capacity_exact_original_limits');
 const now=Date.now();demand(Number.isFinite(Date.parse(p.validFromUtc))&&Date.parse(p.validFromUtc)<=now&&Date.parse(p.expiresAtUtc)>now&&p.expiresAtUtc==='2026-10-15T16:00:00Z','runtime_capacity_policy_validity');
 return Object.freeze({...p,verifiedPolicyPin:policyPin});
}
