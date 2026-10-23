/** Every real TB attempt consumes the same human-authorized 9 CNY envelope. */
import { existsSync, readFileSync, readdirSync } from "node:fs";
import { join, resolve } from "node:path";
import { actualPin, demand, jsonPin, type Pin } from "../../benchmark-repair/paid-resource-proof-v2.ts";
import { verifyCashClosure as verifyWindowCashClosure } from "../../benchmark-repair/cny-cash-shadow-v2.ts";
import { verifyCashClosure as verifyPeakCashClosure } from "./peak_cash_shadow.ts";
const ROOT=resolve(import.meta.dir,"../../..");
export function remainingTbBudget() {
  const folder=join(ROOT,"docs/repair-2026-10-09/tb12-runs-v1"),pins:Pin[]=[],runs:any[]=[];
  let consumed=0n;
  for(const child of existsSync(folder)?readdirSync(folder).sort():[]) {
    const home=join(folder,child),entry=join(home,"entry-start.json");
    if(!existsSync(entry)||jsonPin(actualPin(entry)).mode!=="run")continue;
    const closed=join(home,"entry-closed.json"),cash=join(home,"cash/cash-close.json");
    demand(existsSync(closed)&&jsonPin(actualPin(closed)).canonicalOwnerReleased===true,"tb12_previous_real_trial_not_closed");
    const cashPin=actualPin(cash),cashRecord=jsonPin(cashPin),config=jsonPin(cashRecord.configPin);
    const conservative=config.pricingMode==="published-peak-conservative-upper-bound";
    const verified=conservative?verifyPeakCashClosure(cashPin):verifyWindowCashClosure(cashPin);
    demand(verified.config.providerKind==="real-provider"&&verified.proof.releasePermitted&&verified.proof.snapshot.pendingCount===0&&verified.proof.snapshot.newUnknownCount===0,"tb12_prior_cash_not_replayed");
    const windowAmount=BigInt(verified.proof.snapshot.newKnownEstimatedNanoCny);
    let amount=0n;const seen=new Set<number>();
    for(const line of readFileSync(verified.proof.cashEventsPin.path,"utf8").trim().split("\n")) {
      if(!line)continue;const event=JSON.parse(line);if(event.kind!=="finish")continue;
      const data=event.data;demand(data.phase==="known"&&!seen.has(data.requestSeq),"tb12_prior_unique_known_finish");seen.add(data.requestSeq);
      if(!data.observedUsage){demand(data.amountNanoCny==="0","tb12_prior_missing_usage_with_amount");continue;}
      const u=data.observedUsage;amount+=BigInt(u.prompt_tokens-(u.prompt_cache_hit_tokens??0))*2000n+BigInt(u.prompt_cache_hit_tokens??0)*40n+BigInt(u.completion_tokens)*8000n;
    }
    demand(amount>=windowAmount&&(!conservative||amount===windowAmount),"tb12_prior_peak_upper_replay");consumed+=amount;
    pins.push(actualPin(entry),actualPin(closed),cashPin,verified.proof.configPin,verified.proof.cashEventsPin);
    runs.push({runId:child,publishedWindowKnownEstimatedNanoCny:windowAmount.toString(),newKnownPeakUpperNanoCny:amount.toString(),cashClosePin:cashPin});
  }
  const remaining=9_000_000_000n-consumed;demand(remaining>0n,"tb12_aggregate_human_envelope_exhausted");
  const remainingCny=String(remaining/1_000_000_000n)+"."+String(remaining%1_000_000_000n).padStart(9,"0");
  return{totalAuthorizedNanoCny:"9000000000",consumedNanoCny:consumed.toString(),remainingNanoCny:remaining.toString(),remainingCny,pins,runs,
    noPreviousFeesSubtractedFromCurrentBalanceAgain:true};
}
