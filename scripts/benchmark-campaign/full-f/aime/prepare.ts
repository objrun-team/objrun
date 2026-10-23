import { mkdirSync, readFileSync, writeFileSync } from 'node:fs';
import { resolve, join } from 'node:path';
import { digest, fixedScientificPlan } from '../../../benchmark-repair/scientific-journal-plan.ts';
import { BENCHMARK_INFERENCE } from '../../../benchmark-repair/benchmark-inference.ts';
import { BENCHMARK_PROVIDER } from '../../../benchmark-repair/benchmark-provider.ts';
export const root = resolve(import.meta.dir, '../../../..');
export const output = join(root, 'docs/repair-2026-10-10/full-f-rerun/aime');
export function save(name: string, value: unknown) { mkdirSync(output, {recursive:true}); writeFileSync(join(output,name), JSON.stringify(value,null,2)+'\n'); }
export function prepare() {
  const campaign='repair-2026-10-10T00-00-00-001Z';
  const paired=fixedScientificPlan(root,campaign,'full',['aime']);
  const tasks=paired.tasks.filter(t=>t.arm==='F').map((t,index)=>({...t,index}));
  if(tasks.length!==60 || new Set(tasks.map(t=>t.officialId)).size!==60) throw Error('AIME denominator mismatch');
  for(const year of [2024,2025]) for(const contest of ['I','II']) for(let n=1;n<=15;n++) if(!tasks.some(t=>t.officialId===`aime-${year}-${contest}-${n}`)) throw Error('Missing official ID');
  const source=JSON.parse(readFileSync(join(root,'.phase1-data/aime/source.json'),'utf8'));
  for(const f of [...source.files,source.derivedDataset]) if(digest(readFileSync(join(root,'.phase1-data/aime',f.file)))!==f.sha256) throw Error('Dataset hash mismatch: '+f.file);
  const schedule=tasks.map(({index,officialId,promptSha256,arm})=>({index,officialId,promptSha256,arm}));
  const manifest={protocol:'aime-full-f-v1',campaign,arms:['F'],denominator:60,years:[2024,2025],tasks,scheduleSha256:digest(JSON.stringify(schedule)),datasets:paired.datasets,source,model:BENCHMARK_PROVIDER.model,provider:BENCHMARK_PROVIDER.providerSlug,allowFallbacks:false,inference:BENCHMARK_INFERENCE,seconds:600,checks:5,maxBranches:4,maxDeadSiblings:100000,noSearch:['all'],allowedTools:['submit','verify','task_tree','node_load'],workers:2,grader:'math-verify==0.9.0; parsed integer 0..999 then official verify',feedbackLevel:0,U:'Public references only; no U requests',paidAdapter:'Required shared coordinator broker; no canonical paid lock acquired by this entry'};
  save('manifest.json',manifest);
  return manifest;
}
if(import.meta.main) { const manifest=prepare(); console.log(JSON.stringify({prepared:true,denominator:manifest.denominator,scheduleSha256:manifest.scheduleSha256})); }
