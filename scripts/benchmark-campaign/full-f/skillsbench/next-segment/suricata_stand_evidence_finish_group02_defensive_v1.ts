/** Source and receipt validation only. No benchmark, Docker, network, or model actions. */
export function validateSuricataStandEvidence(proof:any,built:any,cold:any,route:any,expected:any[],io:any){
 const demand=(ok:any,why:string)=>{if(!ok)throw Error(why);};
 const same=(a:any,b:any)=>JSON.stringify(a)===JSON.stringify(b);
 demand(proof.taskStandControlsPin,'suricata_actual_stand_evidence_required');io.verifyPin(proof.taskStandControlsPin);const stand=io.jsonPin(proof.taskStandControlsPin);
 demand(stand.protocol==='skillsbench-suricata-real-stand-controls-v2'&&stand.taskId==='suricata-custom-exfil'&&stand.verified===true&&stand.modelCalls===0,'suricata_actual_stand_controls_required');
 demand(stand.ownedContainersRemaining===0&&stand.privateNamespacesVerified===true&&stand.originalVerifierBudgetVerified===true,'suricata_stand_namespace_or_cleanup_missing');
 demand(same(stand.workerRoute,route)&&same(stand.builtImagesPin,proof.builtImagesPin)&&same(stand.controlPin,proof.controlPin),'suricata_stand_worker_or_cold_join_drift');
 for(const pin of stand.sourcePins??[])io.verifyPin(pin);
 demand(expected.every(pin=>(stand.sourcePins??[]).some((p:any)=>same(p,pin))),'suricata_stand_exact_source_pins_required');
 for(const tool of ['bash','read','write','edit','glob','grep','verify','submit'])demand(Number.isInteger(stand.toolCalls?.[tool])&&stand.toolCalls[tool]>0,'suricata_stand_missing_tool:'+tool);
 demand(stand.steps?.length===3&&same(stand.steps.map((s:any)=>s.reward),[0,1,0]),'suricata_stand_original_controls_required');
 const collection=io.jsonPin(cold.collectionPin);demand(collection.complete===true&&collection.suricataSeparateSandbox===true&&collection.nodeIds.length===12,'suricata_original_collection_required');
 const seen=new Set();
 for(const step of stand.steps){
  io.verifyPin(step.gradeOwnerPin);demand(!seen.has(step.gradeOwnerPin.path),'suricata_distinct_grade_receipts_required');seen.add(step.gradeOwnerPin.path);
  const grade=io.jsonPin(step.gradeOwnerPin),result=grade.result;
  demand(same(grade.builtImagesPin,proof.builtImagesPin)&&same(grade.controlPin,proof.controlPin),'suricata_grade_cold_join_drift');
  demand(result.complete===true&&result.reward===step.reward&&same(result.nodeIds,collection.nodeIds)&&result.candidateExecutablesUsed===false&&result.candidateSnapshotUsed===false&&result.suricataSeparateSandbox===true,'suricata_original_stand_grade_required');
  io.verifyPin(result.suricataOwnerClosurePin);const closure=io.jsonPin(result.suricataOwnerClosurePin);
  demand(closure.completed===true&&closure.ownedContainersRemaining===0&&closure.directChildClosed===true&&closure.pipeReadersClosed===true&&closure.cleanupErrors.length===0&&closure.originalVerifierDeadlinePreserved===true,'suricata_native_owner_cleanup_required');
  demand(closure.privateImageId===built.privateImageId&&closure.sandboxImageId===built.sandboxImageId,'suricata_native_namespace_image_drift');
 }
 return stand;
}
