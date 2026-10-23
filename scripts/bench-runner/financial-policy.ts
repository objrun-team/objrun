import {readFileSync} from 'node:fs';
import {join} from 'node:path';
import {pin,verifyPin,demand} from './manifest.ts';
import type {Pin} from './types.ts';
const authorityPath=join(import.meta.dir,'../../docs/repair-2026-10-10/full-f-rerun/novaeve-formal-20261013/coordinator/universal-runner/user-unlimited-financial-policy-and-retrieve949f-recovery-20261015.json');
export function financialPolicy(authorityPin:Pin=pin(authorityPath)) {
 verifyPin(authorityPin);
 demand(authorityPin.sha256==='ca25d98815cf1d7c9a3a30e50f3d84962520dd57227c777fce619b71176d665b','financial_human_authority_identity');
 const a=JSON.parse(readFileSync(authorityPin.path,'utf8'));
 demand(a.protocol==='bench-explicit-human-financial-authorization-v1'&&a.financialBudgetMode==='unlimited'&&a.monetaryCeilings===null,'explicit_unlimited_financial_policy_required');
 demand(['task','attempt','batch','project','broker','lane','cash','admission','max-spend','fee-reservation monetary blocking'].every(x=>a.scope.includes(x)),'financial_authority_scope');
 return {mode:'unlimited' as const,monetaryCeilings:null,authorityPin,effectiveAtUtc:a.recordedAtUtc,preserveOriginalCashAndReservations:true,nonfinancialConstraintsUnchanged:true};
}
