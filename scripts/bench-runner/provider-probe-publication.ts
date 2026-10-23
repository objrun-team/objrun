/** Publish only an already healthy, uniquely adopted same-pool executor. */
import{readFileSync,writeFileSync,renameSync}from'node:fs';import{join,resolve}from'node:path';
import{actualPin,jsonPin,demand,verifyPin,same}from'../repair-2026-10-08/paid-resource-proof-v2.ts';
import{verifyAdoptedConnection}from'./unlimited-adopted-consumer.ts';
import{unlimitedFinancialFields}from'./financial-policy-runtime.ts';
export async function publishProviderSuccessor(signedPlanPin:any){
 verifyPin(signedPlanPin);const envelope=jsonPin(signedPlanPin),p=envelope.plan;
 demand(p.preparationOnly===false&&p.sharedPool===16&&p.allResourceHoldsAdoptedWithoutRelease===true,'final_same_pool_publication_only');
 const connection=jsonPin(actualPin(join(p.directory,'connection.private.json'))),v=await verifyAdoptedConnection(connection,true);
 demand(v.health.activeRequests===0&&v.health.queuedRequests===0&&same(v.health.adoption.signedAdoptionPlanPin,signedPlanPin),'fresh_exact_successor_zero_request_publication');
 const home=resolve(import.meta.dir,'../../docs/repair-2026-10-10/full-f-rerun/novaeve-formal-20261013'),cp=join(home,'broker/control-unlimited-financial.private.json'),ap=join(home,'activation-unlimited-financial.json');
 demand(actualPin(cp).sha256===p.oldControlPin.sha256&&actualPin(ap).sha256===p.oldActivationPin.sha256,'publication_compare_and_swap_original_bytes');
 const oldControl=jsonPin(p.oldControlPin),oldActivation=jsonPin(p.oldActivationPin),financial=unlimitedFinancialFields(p.originalCapUsd);
 const maintenance={fullChainAccepted:false,formalDispatchBlockedPendingActualAcceptance:true,modelRequests:0,providerProbeOnly:true};
 const control={...oldControl,updatedAtUtc:new Date().toISOString(),broker:connection,adoption:v.health.adoption,previousAdoption:oldControl.adoption,originalControlPin:p.oldControlPin,financialPolicy:financial,financialBudgetMode:'unlimited',monetaryCeilings:null,financialMaintenance:maintenance};
 const ct=cp+'.'+p.nonce+'.pending';writeFileSync(ct,JSON.stringify(control,null,2)+'\n',{flag:'wx',mode:0o600});renameSync(ct,cp);
 const activation={...oldActivation,atUtc:new Date().toISOString(),controlPath:cp,brokerControlPath:cp,controlPin:actualPin(cp),adoption:v.health.adoption,previousAdoption:oldActivation.adoption,originalActivationPin:p.oldActivationPin,consumerGuardPin:actualPin(join(import.meta.dir,'unlimited-adopted-consumer.ts')),sourceLoaderPin:p.sourceLoaderPin,financialPolicy:financial,financialBudgetMode:'unlimited',monetaryCeilings:null,financialMaintenance:maintenance};
 const at=ap+'.'+p.nonce+'.pending';writeFileSync(at,JSON.stringify(activation,null,2)+'\n',{flag:'wx'});renameSync(at,ap);
 return{activationPin:actualPin(ap),controlPin:actualPin(cp),pid:connection.pid,allResourceHoldsUnmodified:true,formalReady:false};
}
