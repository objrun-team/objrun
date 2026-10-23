import {readFileSync} from 'node:fs';import {verify,createHash} from 'node:crypto';
function need(v:unknown,c:string):asserts v{if(!v)throw Error(c)}
function read(p:any){const b=readFileSync(p.path);need(b.length===p.bytes&&createHash('sha256').update(b).digest('hex')===p.sha256,'legacy_cpu_evidence_pin');return JSON.parse(b.toString());}
export function projectLegacyResourceCpu(rows:any[],evidencePin:any){
 const e=read(evidencePin);need(e.protocol==='old-retained-holds-original-signed-cpu-metadata-v1','exact_original_signed_cpu_metadata');
 const seen=new Set();for(const r of e.rows){need(!seen.has(r.pid),'duplicate_legacy_cpu_owner');seen.add(r.pid);const original=rows.find(q=>q.pid===r.pid&&q.ownerIncarnation===r.ownerIncarnation);need(original,'legacy_cpu_exact_existing_owner');
 const p=read(r.signedPlanPin),lease=read(r.originalLeaseReceiptPin);read(r.signatureVerificationPin);need(r.originalAuthorityPin.sha256==='ed4e7676d5c78e04d328dbca6ff1666a496ef6d2f2e213925dc870384983ca98','legacy_cpu_original_authority');const key=readFileSync(r.originalAuthorityPin.path);need(key.length===r.originalAuthorityPin.bytes&&createHash('sha256').update(key).digest('hex')===r.originalAuthorityPin.sha256,'legacy_cpu_public_pin');
 need(verify(null,Buffer.from(JSON.stringify(p.plan)),key,Buffer.from(p.signature,'base64')),'legacy_cpu_original_signature');
 need(p.plan.resource.cpu===r.cpu&&p.plan.resource.memoryMb===original.memoryMb&&p.plan.resource.slots===original.slots&&p.plan.resource.growthBytes===original.plannedGrowthBytes&&lease.pid===original.pid&&lease.ownerIncarnation===original.ownerIncarnation&&lease.memoryMb===original.memoryMb,'legacy_cpu_signed_resource_and_original_lease');
 need(Number.isSafeInteger(r.cpu)&&r.cpu>0,'legacy_cpu_exact_positive');}
 return rows.map(original=>{const r=e.rows.find(q=>q.pid===original.pid&&q.ownerIncarnation===original.ownerIncarnation);return r?{...original,cpu:r.cpu,cpuMetadataEvidencePin:evidencePin,cpuOriginallyUnrecorded:original.cpu==null}: {...original,cpu:original.cpu??null};});
}
