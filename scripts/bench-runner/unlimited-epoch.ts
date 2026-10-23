/** Terminal-driver activated return contract backed by the actual current executor. */
import {readFileSync} from 'node:fs';
import {resolve} from 'node:path';
import {verifyAdoptedActivation} from './unlimited-adopted-consumer.ts';
import {unlimitedFinancialRecord} from './financial-policy-runtime.ts';
export async function activated(path:string){
 const adopted=await verifyAdoptedActivation(path),activation=JSON.parse(readFileSync(path,'utf8'));
 if(!unlimitedFinancialRecord(activation.financialPolicy)||activation.dockerHost!=='tcp://127.0.0.1:18750'||activation.network?.gateway!=='172.30.89.1'||activation.network?.proxy!=='http://172.30.89.1:10809'||resolve(activation.controlPath)!==resolve(activation.brokerControlPath))throw Error('actual_unlimited_activation_native_scope');
 return {activation,connection:adopted.connection,adopted};
}
