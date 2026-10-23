/** Keep the exact historical 42→43→44 verifier; project only the actual new parent. */
import {fixedFreshHistoryContractV102,verifyFreshHistoryChainV102} from '../repair-2026-10-10/full-f/novaeve_formal_v1/coordinator/account-history-fresh-chain-consumer-v102.ts';
import {verifyUnlimitedFreshHistory} from './unlimited-fresh-history.ts';
export {fixedFreshHistoryContractV102};
export async function verifyFreshHistoryActualParentV102(contract:any,actualLanePin?:any){
 return verifyUnlimitedFreshHistory(verifyFreshHistoryChainV102(contract),contract,actualLanePin);
}
