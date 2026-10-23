/** Preserve both original read-only APIs; retry only the already accepted health TimeoutError once. */
import {verifyAdoptedConnection as originalConnection} from './unlimited-adopted-consumer.ts';
import {readOnlyTimeoutRetry} from './unlimited-readonly-guard-retry.ts';
export {assertPriceRenewalSnapshot} from './unlimited-adopted-consumer.ts';
export {verifyAdoptedActivation} from './unlimited-readonly-guard-retry.ts';
export function verifyAdoptedConnection(connection:any,initialPublication=false){
 return readOnlyTimeoutRetry(()=>originalConnection(connection,initialPublication));
}
