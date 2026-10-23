/** Original full verification, retried once only on a read-only health TimeoutError. */
import{verifyAdoptedActivation as originalVerify}from'./unlimited-adopted-consumer.ts';
export async function readOnlyTimeoutRetry<T>(verify:()=>Promise<T>){
 for(let attempt=1;attempt<=2;attempt++){
  try{return await verify()}catch(error){
   if(!(error instanceof DOMException)||error.name!=='TimeoutError'||attempt!==1)throw error;
   process.stderr.write(JSON.stringify({protocol:'bench-readonly-health-timeout-retry-v1',attempt,maximumAttempts:2,retryOnlyReadOnlyVerification:true,originalHealthReadTimeoutMs:5000,originalPythonChildTimeoutSeconds:15,originalFailure:{name:error.name,message:error.message,code:error.code}})+'\n');
  }
 }
 throw Error('readonly_verification_unreachable');
}
export async function verifyAdoptedActivation(path:string){return readOnlyTimeoutRetry(()=>originalVerify(path));}
