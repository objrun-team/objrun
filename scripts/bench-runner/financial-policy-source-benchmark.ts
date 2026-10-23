/** Exact original Terminal Bench cash projection; other paths keep the accepted composite. */
import{join}from'node:path';
import{unlimitedFinancialSource as prior}from'./financial-policy-source-composite.ts';
const helper=JSON.stringify(join(import.meta.dir,'financial-policy-runtime.ts'));
function one(s:string,a:string,b:string){if(s.split(a).length!==2)throw Error('benchmark_cash_exact_anchor:'+a);return s.replace(a,b)}
export function unlimitedFinancialSource(path:string,s:string){
 if(path.replaceAll('\\','/').endsWith('/terminal-bench/benchmark-usd-cash.ts')){
 s='import {unlimitedFinancialFields,unlimitedFinancialRecord,monetaryExposureAllowed} from '+helper+';\n'+s;
  s=one(s,'currency: "USD", configPin: this.configPin,','currency: "USD", ...unlimitedFinancialFields(this.config.originalDeclaredCapUsd), configPin: this.configPin,');
  s=one(s,'Number.isFinite(this.capUsd) && this.capUsd > 0 && config.capUsd <= this.capUsd','unlimitedFinancialRecord(config) && (options.providerKind === "local-mock" || unlimitedFinancialRecord(admission))');
  s=one(s,'providerKind: options.providerKind, capUsd: this.capUsd,','providerKind: options.providerKind, ...unlimitedFinancialFields((admission as any)?.originalDeclaredCapUsd ?? config.originalDeclaredCapUsd),');
  s=one(s,'capUsd: this.capUsd, billedUsd: known,','...unlimitedFinancialFields(this.config.originalDeclaredCapUsd), billedUsd: known,');
  s=one(s,'if (phase === "unknown") this.poison("usd_unknown_charge");','if (phase === "unknown") this.poison("usd_unknown_charge");');
  s=one(s,'remainingUsd: this.capUsd - known - pending - unknown','remainingUsd: null');
  s=one(s,'this.snapshot().exposureUpperBoundUsd + reservationUsd <= this.capUsd + 1e-9','monetaryExposureAllowed(this.config,this.snapshot().exposureUpperBoundUsd + reservationUsd)');
  s=one(s,'if (this.snapshot().exposureUpperBoundUsd > this.capUsd + 1e-9)','if (!monetaryExposureAllowed(this.config,this.snapshot().exposureUpperBoundUsd))');
  s=one(s,'Number.isFinite(config.capUsd) && config.capUsd > 0','(unlimitedFinancialRecord(config)||Number.isFinite(config.capUsd) && config.capUsd > 0)');
  s=one(s,'journalConfig.capUsd <= config.capUsd','(unlimitedFinancialRecord(config)?unlimitedFinancialRecord(journalConfig):journalConfig.capUsd <= config.capUsd)');
  s=one(s,'known + unknown + pending + ticket.reservationUsd <= config.capUsd + 1e-9','monetaryExposureAllowed(config,known + unknown + pending + ticket.reservationUsd)');
  s=one(s,'Math.abs(proof.snapshot.remainingUsd - config.capUsd + known + unknown) < 1e-9','(unlimitedFinancialRecord(config)?proof.snapshot.remainingUsd===null:Math.abs(proof.snapshot.remainingUsd - config.capUsd + known + unknown) < 1e-9)');
  s=one(s,'known + unknown > config.capUsd + 1e-9','!monetaryExposureAllowed(config,known + unknown)');
 return s;
 }
 let result=prior(path,s);
 if(['signed-owned-operation.ts','signed-owned-asset.ts','terminal-driver.ts'].includes(path.replaceAll('\\','/').split('/').pop()!)){
 result=one(result,JSON.stringify(join(import.meta.dir,'financial-policy-loader-composite.ts')),JSON.stringify(join(import.meta.dir,'financial-policy-loader-benchmark.ts')));
 }
 return result;
}
