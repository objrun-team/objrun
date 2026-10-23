/** Explicit finance records; original bounded histories retain their exact replay semantics. */
import {financialPolicy} from './financial-policy.ts';
import {verifyPin,demand} from './manifest.ts';
export function unlimitedFinancialFields(originalDeclaredCapUsd:unknown=null){const p=financialPolicy();return{financialBudgetMode:p.mode,monetaryCeilings:null,financialAuthorityPin:p.authorityPin,originalDeclaredCapUsd,capUsd:null};}
export function unlimitedFinancialRecord(record:any):boolean{
 if(record?.financialBudgetMode===undefined)return false;
 demand(record.financialBudgetMode==='unlimited'&&record.monetaryCeilings===null&&record.capUsd===null&&record.financialAuthorityPin,'explicit_unlimited_record_schema');
 verifyPin(record.financialAuthorityPin);const p=financialPolicy(record.financialAuthorityPin);demand(p.mode==='unlimited','financial_record_authority');return true;
}
export function monetaryExposureAllowed(record:any,exposure:number){demand(Number.isFinite(exposure)&&exposure>=0,'financial_exposure_finite_nonnegative');return unlimitedFinancialRecord(record)||Number.isFinite(record?.capUsd)&&record.capUsd>0&&exposure<=record.capUsd+1e-9;}
