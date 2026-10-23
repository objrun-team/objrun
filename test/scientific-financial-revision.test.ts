import{expect,test}from'bun:test';
import{readFileSync,writeFileSync}from'node:fs';
import{join,resolve}from'node:path';
import{actualPin,jsonPin}from'../scripts/benchmark-repair/paid-resource-proof-v2.ts';
import{assertOriginalAdmissionSources,auditFinancialFixture}from'../scripts/benchmark-repair/audit-scientific-financial-interruption.ts';
import{revisionFixture}from'./_financial-revision-fixture.ts';
const ROOT=resolve(import.meta.dir,'..'),meta=join(ROOT,'docs/repair-2026-10-08/campaigns/repair-2026-10-08T18-32-57-118Z'),admission=JSON.parse(readFileSync(join(meta,'paid-resource-admission.json'),'utf8')),source=JSON.parse(readFileSync(join(meta,'source.json'),'utf8')),manifest=JSON.parse(readFileSync(join(meta,'manifest.json'),'utf8')),recipe=jsonPin(manifest.paidResourceAdmission.recipePin),executed=[...source.files,...source.repairFiles].map(p=>({path:resolve(ROOT,p.path),bytes:p.bytes,sha256:p.sha256}));
test('actual original source metadata: flat81 gate is red; exact ordered intrinsic3 plus executed81/recipe multiset is green',()=>{
 expect(admission.sourcePins.length===executed.length).toBe(false);const r=assertOriginalAdmissionSources(admission.sourcePins,executed,recipe.executedSourcePins);expect(r.totalCount).toBe(84);expect(r.intrinsicCount).toBe(3);expect(r.executedCount).toBe(81);expect(r.exactMultiset).toBe(true);
});
test('missing intrinsic, wrong prefix, unexpected extra, duplicate replacement and changed bytes all reject',()=>{
 const copy=()=>structuredClone(admission.sourcePins);expect(()=>assertOriginalAdmissionSources(admission.sourcePins.slice(3),executed,recipe.executedSourcePins)).toThrow('original_source_cardinality');
 const prefix=copy();prefix[1]=prefix[0];expect(()=>assertOriginalAdmissionSources(prefix,executed,recipe.executedSourcePins)).toThrow('original_intrinsic_prefix');
 const extra=copy();extra.push(extra[3]);expect(()=>assertOriginalAdmissionSources(extra,executed,recipe.executedSourcePins)).toThrow('original_source_cardinality');
 const duplicate=copy();duplicate[4]=duplicate[3];expect(()=>assertOriginalAdmissionSources(duplicate,executed,recipe.executedSourcePins)).toThrow('original_executed_source_multiset');
 const changed=copy();changed[3].bytes++;expect(()=>assertOriginalAdmissionSources(changed,executed,recipe.executedSourcePins)).toThrow('original_executed_source_multiset');
 const badRecipe=structuredClone(recipe.executedSourcePins);badRecipe[1]=badRecipe[0];expect(()=>assertOriginalAdmissionSources(admission.sourcePins,executed,badRecipe)).toThrow('original_executed_source_multiset');
});
test('three real native F fallback gzip copies validate but only four source requests are accounted once',()=>{
 const f=revisionFixture(),r=auditFinancialFixture(f,f.out);expect(r.validated).toBe(true);expect(r.verifiedFallbackCopies).toBe(3);expect(r.fallbackCopiesChargedAgain).toBe(false);expect(r.actualForwarded).toBe(3);expect(r.rawRequestAndResponseFilesDoubleVerified).toBe(10);expect(r.financialOnly).toBe(false);expect(r.scoreCertificate).toBe(false);expect(r.originalUnknownCarryNanoCny).toBe('8392180000');
 writeFileSync(join(f.root,'revision-control-result.json'),JSON.stringify({sourcePin:actualPin(join(ROOT,'scripts/benchmark-repair/audit-scientific-financial-interruption.ts')),result:r,actualProviderCalls:0,paidLockOperations:0,DockerOperations:0,onlyFWrites:true})+'\n');
});
test('a fallback copy with corrupted CRC fails even with a refreshed declared compressed Pin',()=>{
 const f=revisionFixture(),receipt=jsonPin(f.lateProofs[0]),p=receipt.files[0].path,bytes=readFileSync(p);bytes[bytes.length-7]^=1;writeFileSync(p,bytes);receipt.files[0]=actualPin(p);writeFileSync(f.lateProofs[0].path,JSON.stringify(receipt)+'\n');f.lateProofs[0]=actualPin(f.lateProofs[0].path);expect(()=>auditFinancialFixture(f,f.out)).toThrow();
});
