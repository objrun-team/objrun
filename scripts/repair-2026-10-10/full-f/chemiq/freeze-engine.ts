/** Bench-owned build transform: required-call validation uses existing retryTimes.
 * No provider output is synthesized; each retry traverses the original paid gateway.
 */
import {readFileSync,mkdirSync,writeFileSync} from 'node:fs';
import {join,resolve} from 'node:path';
import {actualPin,demand} from '../../../repair-2026-10-08/paid-resource-proof-v2.ts';

const root=resolve(import.meta.dir,'../../../..');
export function submissionRetrySource(source:string) {
  const target='return await generateText({';
  demand(source.split(target).length===2,'submission_transform_generateText_shape');
  source=source.replace(target,'const submittedResult = await generateText({');
  const boundary='abortSignal: wall.signal,\n              });';
  demand(source.split(boundary).length===2,'submission_transform_boundary_shape');
  source=source.replace(boundary,boundary+`
              if (officialOpenRouter && u.mustCall && submittedResult.finishReason !== "length" &&
                  (submittedResult.toolCalls.length !== 1 || submittedResult.toolCalls[0]?.toolName !== u.mustCall)) {
                const missing = new Error("The required " + u.mustCall + " tool was not called exactly once");
                missing.name = "RequiredToolCallMissing";
                throw missing;
              }
              return submittedResult;`);
  const retry='if (!listed(e, retryOn)) throw e;';
  demand(source.split(retry).length===2,'submission_transform_retry_shape');
  return source.replace(retry,'if (!(e instanceof Error && e.name === "RequiredToolCallMissing") && !listed(e, retryOn)) throw e;');
}
export async function freezeEngine(directory:string) {
  mkdirSync(directory,{recursive:true});
  const original=join(root,'app/src/llm/index.ts');
  const transformed=submissionRetrySource(readFileSync(original,'utf8'));
  const source=join(directory,'bench-llm-transformed.ts');writeFileSync(source,transformed,{flag:'wx'});
  const result=await Bun.build({entrypoints:[join(root,'app/src/main.ts')],outdir:directory,
    target:'bun',minify:false,sourcemap:'external',plugins:[{name:'chemiq-required-submit-retry',setup(build){
      build.onLoad({filter:/[\\/]app[\\/]src[\\/]llm[\\/]index\.ts$/},()=>({contents:transformed,loader:'ts'}));
    }}]});
  demand(result.success,'chemiq_project_engine_bundle_failed');
  const files=result.outputs.map(output=>actualPin(output.path));
  const executable=files.find(pin=>pin.path.endsWith('main.js'));demand(executable,'chemiq_project_engine_bundle_missing');
  const proof={protocol:'chemiq-required-submit-existing-retry-build-v1',original:actualPin(original),transformed:actualPin(source),
    transform:actualPin(import.meta.path),retryTimesUnchanged:3,maxTokensUnchanged:16384,reasoningUnchanged:'high',
    originalDeadlineUnchanged:true,responseSynthesis:false,files,executable};
  writeFileSync(join(directory,'submission-build-proof.json'),JSON.stringify(proof,null,2)+'\n',{flag:'wx'});
  return {...proof,hostBun:actualPin(process.execPath),hostBunVersion:Bun.version,originalEntry:actualPin(join(root,'app/src/main.ts'))};
}
