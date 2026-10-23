import {join}from'node:path';
const helper=JSON.stringify(join(import.meta.dir,'financial-policy-runtime.ts'));
function one(s:string,a:string,b:string){if(s.split(a).length!==2)throw Error('unlimited_financial_anchor_not_unique:'+a);return s.replace(a,b)}
export function unlimitedFinancialSource(path:string,s:string){
 const name=path.replaceAll('\\','/').split('/').pop();
 if(!['digitalocean-journal.ts','supplier-journal.ts','digitalocean-usd-cash.ts','supplier-usd-cash.ts','recording_digitalocean_cash.ts','gateway_budget_gate_v4.ts','gateway_budget_gate_v7.ts','skillsbench-single-task-session.ts','skillsbench-single-task-fee.ts','signed-owned-operation.ts','signed-owned-asset.ts','shared-admission.ts','supplier-shared-admission.ts','broker-adoption-v76.ts','nonblocking-history-policy.ts','manifest.ts','terminal-driver.ts','relative-qualified-source.ts','qualified-source-mappings.ts','qualified-driver-interfaces.ts','account-history-fresh-chain-consumer-v102.ts','original-history.ts','index.ts'].includes(name!))return s;
 if(name==='index.ts'&&!path.replaceAll('\\','/').endsWith('/adapters/index.ts'))return s;
 s='import {unlimitedFinancialFields,unlimitedFinancialRecord,monetaryExposureAllowed} from '+helper+';\n'+s;
 if(name==='index.ts'&&path.replaceAll('\\','/').endsWith('/adapters/index.ts')){
  s=one(s,'o.priorKnownUsd + o.priorUnknownUsd <= o.taskCapUsd','(unlimitedFinancialRecord(m.adapterConfig.financialPolicy)||o.priorKnownUsd + o.priorUnknownUsd <= o.taskCapUsd)');
  s=one(s,"requireTrue((!runId||cash.config.runId===runId)&&(cap===undefined||cash.config.capUsd<=cap),'original_cash_run_cap_identity');","requireTrue(!runId||cash.config.runId===runId,'original_cash_run_identity');unlimitedFinancialFields();");
  s=one(s,'const proofs: Pin[] = [r.taskPin,r.summaryPin,r.financialClosurePin,r.nativeClosurePin];','const proofs: Pin[] = [r.taskPin,r.summaryPin,r.financialClosurePin,r.nativeClosurePin,unlimitedFinancialFields().financialAuthorityPin];');
 }else if(name==='manifest.ts'){
  s=one(s,'o.priorKnownUsd+o.priorUnknownUsd<=o.taskCapUsd',"unlimitedFinancialRecord(m.adapterConfig?.financialPolicy)");
 }else if(name==='original-history.ts'){
  s=one(s,"need(original.capUsd===m.original.taskCapUsd,'original_task_cap_config');","need(unlimitedFinancialRecord(m.adapterConfig.financialPolicy),'original_task_explicit_unlimited_policy');");
  s=one(s,"cash.config.capUsd<=m.original.taskCapUsd+1e-9&&journal.valid","journal.valid");
 }else if(name==='account-history-fresh-chain-consumer-v102.ts'){
  const start='export async function verifyFreshHistoryActualParentV102(contract:any,actualLanePin?:any){';if(s.split(start).length!==2)throw Error('financial_fresh_history_anchor');
  s='import {verifyUnlimitedFreshHistory} from '+JSON.stringify(join(import.meta.dir,'unlimited-fresh-history.ts'))+';\n'+s.slice(0,s.indexOf(start))+start+'return verifyUnlimitedFreshHistory(verifyFreshHistoryChainV102(contract),contract,actualLanePin);}\n';
 }else if(name==='nonblocking-history-policy.ts'){
  s=one(s,"demand(Number.isFinite(a.maximumNewSpendUsd)&&a.maximumNewSpendUsd>0&&a.maximumNewSpendUsd<=a.taskCapUsd-f.verifiedKnownUsd-f.verifiedUnknownReservationUsd+1e-9,'root_new_allocation_within_task_ceiling');","demand(unlimitedFinancialRecord(a.financialPolicy)&&unlimitedFinancialRecord(m.adapterConfig.financialPolicy)&&same(a.financialPolicy,m.adapterConfig.financialPolicy)&&a.maximumNewSpendUsd===null,'explicit_unlimited_task_and_parent_admission');");
 }else if(name==='terminal-driver.ts'){
  s='import {installUnlimitedFinancialLoader} from '+JSON.stringify(join(import.meta.dir,'financial-policy-loader.ts'))+';\n'+s;
  s=one(s,'const api=await importsFor(d),ready=readPinned(d.readinessPin);',"const financialSourceConfigPin=m.adapterConfig.financialSourceConfigPin as any;checkPin(financialSourceConfigPin);demand(m.provenance.sourcePins.some(p=>p.path===financialSourceConfigPin.path&&p.sha256===financialSourceConfigPin.sha256&&p.bytes===financialSourceConfigPin.bytes),'actual_child_financial_source_config_bound');installUnlimitedFinancialLoader(financialSourceConfigPin.path);const api=await importsFor(d),ready=readPinned(d.readinessPin);");
  s=one(s,'cash.proof.snapshot.pendingCount===0&&cash.config.capUsd<=m.original.taskCapUsd','cash.proof.snapshot.pendingCount===0');
  s=one(s,"demand(history.remainingUsd>0,'original_task_budget_exhausted');","demand(unlimitedFinancialRecord(m.adapterConfig.financialPolicy),'explicit_unlimited_task_policy_required');");
  s=one(s,"maximum=Math.min(history.remainingUsd,lane.capUsd,fresh.maximumAdditionalSpendUsd)","maximum=null");
  s=one(s,"demand(maximum>0,'actual_parent_and_original_task_budget_exhausted');","demand(unlimitedFinancialRecord(lane)&&fresh.financialBudgetMode==='unlimited'&&fresh.maximumAdditionalSpendUsd===null,'actual_unlimited_parent_and_original_task_policy');");
  s=one(s,"return Math.min(history.remainingUsd,lane.capUsd,h.maximumAdditionalSpendUsd);","demand(h.financialBudgetMode==='unlimited'&&h.maximumAdditionalSpendUsd===null,'actual_unlimited_fresh_history');return null;");
 }else if(name==='relative-qualified-source.ts'||name==='qualified-source-mappings.ts'){
  s=one(s,'Number.isFinite(benchMaximum)&&benchMaximum>0','benchMaximum===null');
  s=one(s,'benchSnapshot.recordedUsageUpperBoundUsd+benchSnapshot.reservedUpperBoundUsd+benchReservation<=benchMaximum+1e-9','benchMaximum===null');
 }else if(name==='qualified-driver-interfaces.ts'){
  s=one(s,"need(Number.isFinite(max)&&max>0,'qualified_current_parent_budget_exhausted');","need(max===null,'qualified_explicit_unlimited_parent_policy');");
  s=one(s,'gatewayBudgetDecision(journal,wire,Math.min(budget.newAttemptMaxSpendUsd,await options.benchBeforeJournalGuard()))','gatewayBudgetDecision(journal,wire,await options.benchBeforeJournalGuard())');
 }else if(name==='signed-owned-operation.ts'||name==='signed-owned-asset.ts'){
  const loader=JSON.stringify(join(import.meta.dir,'financial-policy-loader.ts'));
  s=one(s,'argv=[process.execPath,import.meta.path,path,sha,out]','argv=[process.execPath,'+loader+',p.financialSourceConfigPin.path,import.meta.path,path,sha,out]');
  s=one(s,"const inner=process.env.BENCH_ATTEMPT_ID===p.formalParent.attemptId", "verifyPin(p.financialSourceConfigPin);demand(unlimitedFinancialRecord(p.financialPolicy),'explicit_owned_parent_child_financial_policy');const actualFinancialManifest=JSON.parse(readFileSync(p.formalParent.manifestPin.path,'utf8'));demand(JSON.stringify(actualFinancialManifest.adapterConfig.financialSourceConfigPin)===JSON.stringify(p.financialSourceConfigPin)&&unlimitedFinancialRecord(actualFinancialManifest.adapterConfig.financialPolicy),'same_actual_owned_manifest_financial_policy');const inner=process.env.BENCH_ATTEMPT_ID===p.formalParent.attemptId");
 }else if(name==='skillsbench-single-task-session.ts'){
  s=one(s,"h.adoption?.protocol==='novaeve-truthful-broker-price-renewal-v1'","h.adoption?.protocol==='bench-truthful-unlimited-financial-adoption-v1'&&unlimitedFinancialRecord(h)");
 }else if(name==='skillsbench-single-task-fee.ts'){
  s=one(s,"Number.isFinite(maximum)&&maximum>0","maximum===null&&unlimitedFinancialRecord(input.admission)");
 }else if(name==='gateway_budget_gate_v4.ts'||name==='gateway_budget_gate_v7.ts'){
  s=one(s,'Number.isFinite(gatewayLimitUsd)&&gatewayLimitUsd>0','gatewayLimitUsd===null&&unlimitedFinancialRecord(priorSnapshot)');
  s=one(s,'priorSnapshot.recordedUsageUpperBoundUsd+priorSnapshot.reservedUpperBoundUsd+reservationUsd<=gatewayLimitUsd','monetaryExposureAllowed(priorSnapshot,priorSnapshot.recordedUsageUpperBoundUsd+priorSnapshot.reservedUpperBoundUsd+reservationUsd)');
 }else if(name==='broker-adoption-v76.ts'){
  s=one(s,"const capUsd=Math.floor(owner.capUsd*BENCH_WEIGHTS[data.slug]!/(HEAVY.has(data.slug)?Math.min(options.perBenchHeavySlots??16,8):1)*1e6)/1e6;check(capUsd>0,'empty_lane_budget');","const capUsd=null;check(unlimitedFinancialRecord(owner),'explicit_unlimited_parent_required');");
  s=one(s,"check([...lane.cashStates].reduce((n,[seq,s])=>n+(s.phase==='pending'?Math.max(s.ticket.reservationUsd,lane.provisionalCosts.get(seq)??0):s.amount),0)<=lane.admission.capUsd+1e-9,'lane_exposure_exceeded_cap');","check(monetaryExposureAllowed(lane.admission,[...lane.cashStates].reduce((n,[seq,s])=>n+(s.phase==='pending'?Math.max(s.ticket.reservationUsd,lane.provisionalCosts.get(seq)??0):s.amount),0)),'lane_exposure_exceeded_cap');");
  s=one(s,"protocol:'full-f-shared-lane-v1',runId:lane.runId,capUsd:lane.admission.capUsd,","protocol:'full-f-shared-lane-v1',runId:lane.runId,...unlimitedFinancialFields(lane.admission.originalDeclaredCapUsd),");
  s=one(s,"protocol:'full-f-broker-status-v1',localMock:","protocol:'full-f-broker-status-v1',...unlimitedFinancialFields(options.initialParent?.originalDeclaredCapUsd),localMock:");
  s=one(s,"commonSources.push(actualPin(join(resolve(import.meta.dir,'../../shared'),'atomic-state.ts')));","commonSources.push(actualPin(join(resolve(import.meta.dir,'../../shared'),'atomic-state.ts')));commonSources.push(unlimitedFinancialFields().financialAuthorityPin);");
 }else if(name==='shared-admission.ts'||name==='supplier-shared-admission.ts'){
  s=one(s,"join(root,'docs/repair-2026-10-10/full-f-rerun/control.json')","join(root,'docs/repair-2026-10-10/full-f-rerun/novaeve-formal-20261013/broker/control-unlimited-financial.private.json')");
  s=one(s,"const laneProof=jsonPin(claim.proofPin);","check(unlimitedFinancialRecord(claim)&&unlimitedFinancialRecord(parent),'shared_explicit_unlimited_parent_claim');const laneProof=jsonPin(claim.proofPin);check(unlimitedFinancialRecord(laneProof),'shared_explicit_unlimited_lane_proof');");
  s=one(s,"runId:input.runId,capUsd:claim.capUsd,","runId:input.runId,...unlimitedFinancialFields(claim.originalDeclaredCapUsd),");
 }else if(name!.endsWith('journal.ts')){
  s=one(s,'campaign: this.config.campaign, capUsd: this.config.capUsd,','campaign: this.config.campaign, ...unlimitedFinancialFields(this.config.originalDeclaredCapUsd),');
  s=one(s,'finite(config.capUsd) && config.capUsd > 0','(unlimitedFinancialRecord(config)||finite(config.capUsd) && config.capUsd > 0)');
  s=one(s,'config.priorCampaignCostUpperBoundUsd + spent + reserveOf(active) + e.record.reservationUsd! <= config.capUsd + EPS','monetaryExposureAllowed(config,config.priorCampaignCostUpperBoundUsd + spent + reserveOf(active) + e.record.reservationUsd!)');
  s=one(s,'config.priorCampaignCostUpperBoundUsd + spent <= config.capUsd + EPS','monetaryExposureAllowed(config,config.priorCampaignCostUpperBoundUsd + spent)');
  s=one(s,'finite(options.capUsd) && options.capUsd > 0','(options.capUsd===null||finite(options.capUsd) && options.capUsd > 0)');
  s=one(s,'campaign: options.campaign, capUsd: options.capUsd,','campaign: options.campaign, ...unlimitedFinancialFields(options.capUsd),');
  s=one(s,'this.config.priorCampaignCostUpperBoundUsd + this.spent + reserveOf(this.active) + values.reservationUsd > this.config.capUsd','!monetaryExposureAllowed(this.config,this.config.priorCampaignCostUpperBoundUsd + this.spent + reserveOf(this.active) + values.reservationUsd)');
  s=one(s,'this.config.priorCampaignCostUpperBoundUsd + this.spent + reserveOf(this.active) > this.config.capUsd + EPS','!monetaryExposureAllowed(this.config,this.config.priorCampaignCostUpperBoundUsd + this.spent + reserveOf(this.active))');
  s=one(s,'capUsd: config.capUsd, priorCampaignCostUpperBoundUsd:', 'capUsd: config.capUsd, ...(unlimitedFinancialRecord(config)?unlimitedFinancialFields(config.originalDeclaredCapUsd):{}), priorCampaignCostUpperBoundUsd:');
 }else{
  s=one(s,'currency: "USD", configPin: this.configPin,','currency: "USD", ...unlimitedFinancialFields(this.config.originalDeclaredCapUsd), configPin: this.configPin,');
  s=one(s,'Number.isFinite(this.capUsd) && this.capUsd > 0 && config.capUsd <= this.capUsd','unlimitedFinancialRecord(config) && (options.providerKind === "local-mock" || unlimitedFinancialRecord(admission))');
  s=one(s,'providerKind: options.providerKind, capUsd: this.capUsd,','providerKind: options.providerKind, ...unlimitedFinancialFields((admission as any)?.originalDeclaredCapUsd ?? config.originalDeclaredCapUsd),');
  s=one(s,'capUsd: this.capUsd, billedUsd: known,','...unlimitedFinancialFields(this.config.originalDeclaredCapUsd), billedUsd: known,');
  s=one(s,'if (phase === "unknown") this.poison("usd_unknown_charge");','if (phase === "unknown") this.poison("usd_unknown_charge");');
  if(name!=='recording_digitalocean_cash.ts')s=one(s,'!this.closed && !this.poisonReason','!this.closed && (!this.poisonReason || unlimitedFinancialRecord(this.config) && this.poisonReason === "usd_unknown_charge")');
  s=one(s,'remainingUsd: this.capUsd - known - pending - unknown','remainingUsd: null');
  s=one(s,'this.snapshot().exposureUpperBoundUsd + reservationUsd <= this.capUsd + 1e-9','monetaryExposureAllowed(this.config,this.snapshot().exposureUpperBoundUsd + reservationUsd)');
  s=one(s,'if (this.snapshot().exposureUpperBoundUsd > this.capUsd + 1e-9)','if (!monetaryExposureAllowed(this.config,this.snapshot().exposureUpperBoundUsd))');
  s=one(s,'Number.isFinite(config.capUsd) && config.capUsd > 0','(unlimitedFinancialRecord(config)||Number.isFinite(config.capUsd) && config.capUsd > 0)');
  s=one(s,'journalConfig.capUsd <= config.capUsd','(unlimitedFinancialRecord(config)?unlimitedFinancialRecord(journalConfig):journalConfig.capUsd <= config.capUsd)');
  s=one(s,'known + unknown + pending + ticket.reservationUsd <= config.capUsd + 1e-9','monetaryExposureAllowed(config,known + unknown + pending + ticket.reservationUsd)');
  s=one(s,'Math.abs(proof.snapshot.remainingUsd - config.capUsd + known + unknown) < 1e-9','(unlimitedFinancialRecord(config)?proof.snapshot.remainingUsd===null:Math.abs(proof.snapshot.remainingUsd - config.capUsd + known + unknown) < 1e-9)');
  s=one(s,'known + unknown > config.capUsd + 1e-9','!monetaryExposureAllowed(config,known + unknown)');
 }
 return s;
}
