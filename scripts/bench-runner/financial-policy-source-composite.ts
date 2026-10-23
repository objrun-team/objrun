/** Compose the monetary projection with the existing qualified source hook. */
import {join}from'node:path';
import {unlimitedFinancialSource as original}from'./financial-policy-source.ts';
const oldLoader=JSON.stringify(join(import.meta.dir,'financial-policy-loader.ts')),newLoader=JSON.stringify(join(import.meta.dir,'financial-policy-loader-composite.ts'));
export function unlimitedFinancialSource(path:string,text:string){
 let source=original(path,text),name=path.replaceAll('\\','/').split('/').pop();
 if(['signed-owned-operation.ts','signed-owned-asset.ts','terminal-driver.ts'].includes(name!)){
  if(source.split(oldLoader).length!==2)throw Error('composite_explicit_child_loader_anchor');source=source.replace(oldLoader,newLoader);
 }
 if(name==='qualified-mapped-interfaces.ts'){
  const anchor="need(Number.isFinite(max)&&max>0,'qualified_current_parent_budget_exhausted');";
  if(source.split(anchor).length!==2)throw Error('composite_qualified_budget_callback_anchor');source=source.replace(anchor,"need(max===null,'qualified_explicit_unlimited_parent_policy');");
  const expression='gatewayBudgetDecision(journal,wire,Math.min(budget.newAttemptMaxSpendUsd,await options.benchBeforeJournalGuard()))';
  if(source.split(expression).length!==2)throw Error('composite_qualified_beforejournal_anchor');source=source.replace(expression,'gatewayBudgetDecision(journal,wire,await options.benchBeforeJournalGuard())');
 }
 return source;
}
