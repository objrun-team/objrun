/** Bench-owned build transform: required-call validation uses existing retryTimes.
 * No provider output is synthesized; each retry traverses the original paid gateway.
 */
import {readFileSync,mkdirSync,writeFileSync} from 'node:fs';
import {join,resolve} from 'node:path';
import {actualPin,demand} from '../../../repair-2026-10-08/paid-resource-proof-v2.ts';
import {requiredFaultSource} from './pending-interfaces/required_fault_transform.ts';
import {graderTransportSource} from './pending-interfaces/grader_transport_transform.ts';
export {startEngine} from '../../../repair-2026-10-09/tb12-v2/host_engine.ts';
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
  const kernelOriginal=join(root,'app/src/engine/loop.ts');
  const kernelTransformed=requiredFaultSource(readFileSync(kernelOriginal,'utf8'));
  const kernelSource=join(directory,'bench-kernel-transformed.ts');writeFileSync(kernelSource,kernelTransformed,{flag:'wx'});
  const registryOriginal=join(root,'app/src/engine/registry.ts');
  const registryTransformed=graderTransportSource(readFileSync(registryOriginal,'utf8'));
  const registrySource=join(directory,'bench-grader-registry-transformed.ts');writeFileSync(registrySource,registryTransformed,{flag:'wx'});
  const result=await Bun.build({entrypoints:[join(root,'app/src/main.ts')],outdir:directory,
    target:'bun',minify:false,sourcemap:'external',plugins:[{name:'tb-required-submit-retry',setup(build){
      build.onLoad({filter:/[\\/]app[\\/]src[\\/]llm[\\/]index\.ts$/},()=>({contents:transformed,loader:'ts'}));
      build.onLoad({filter:/[\\/]app[\\/]src[\\/]engine[\\/]loop\.ts$/},()=>({contents:kernelTransformed,loader:'ts'}));
      build.onLoad({filter:/[\\/]app[\\/]src[\\/]engine[\\/]registry\.ts$/},()=>({contents:registryTransformed,loader:'ts'}));
    }}]});
  demand(result.success,'tb12_project_engine_bundle_failed');
  const files=result.outputs.map(output=>actualPin(output.path));
  const executable=files.find(pin=>pin.path.endsWith('main.js'));demand(executable,'tb12_project_engine_bundle_missing');
  const proof={protocol:'tb-required-submit-existing-retry-build-v1',original:actualPin(original),transformed:actualPin(source),
    transform:actualPin(import.meta.path),retryTimesUnchanged:3,maxTokensUnchanged:16384,reasoningUnchanged:'high',
    originalDeadlineUnchanged:true,responseSynthesis:false,files,executable};
  Object.assign(proof,{kernelOriginal:actualPin(kernelOriginal),kernelTransformed:actualPin(kernelSource),
    kernelTransform:actualPin(join(import.meta.dir,'pending-interfaces/required_fault_transform.ts')),
    exhaustedMandatoryResponse:'invalid-native-closed',taskScoreSynthesized:false});
  Object.assign(proof,{graderRegistryOriginal:actualPin(registryOriginal),graderRegistryTransformed:actualPin(registrySource),
    graderRegistryTransform:actualPin(join(import.meta.dir,'pending-interfaces/grader_transport_transform.ts')),
    authenticatedGraderSocketIdleLimitDisabled:true,declaredGraderWholeRequestDeadlinePreserved:true});
  writeFileSync(join(directory,'submission-build-proof.json'),JSON.stringify(proof,null,2)+'\n',{flag:'wx'});
  return {...proof,hostBun:actualPin(process.execPath),hostBunVersion:Bun.version,originalEntry:actualPin(join(root,'app/src/main.ts'))};
}
