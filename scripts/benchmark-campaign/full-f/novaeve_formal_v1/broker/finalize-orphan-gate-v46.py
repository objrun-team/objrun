from pathlib import Path
p=Path(__file__).parent
f=p/'broker-adoption-v46.ts';s=f.read_text();s=s.replace("r.kind==='heavy-container'&&r.slug===data.slug","r.kind==='heavy-container'&&r.slug===data.slug&&!r.adoptedOrphanHold");f.write_text(s)
f=p/'check-http-adoption-v46.ts';s=f.read_text();needle="const claim=await(await fetch"
insert="const orphanClaim=await fetch(b.connection.endpoint+'/lane/claim',{method:'POST',headers,body:JSON.stringify({slug:'skillsbench',runId:laneId,output,sourcePins:[actualPin(import.meta.path)]})});if(orphanClaim.ok)throw Error('orphan_hold_borrowed_for_new_lane');const acquired=await fetch(b.aliasEndpoints[0]+'/resource/acquire',{method:'POST',headers,body:JSON.stringify({kind:'heavy-container',slug:'skillsbench',pid:process.pid,slots:1,memoryMb:4096,plannedGrowthBytes:0})});if(!acquired.ok)throw Error('alias_resource_acquire_failed');\n"
s=s.replace(needle,insert+needle).replace('status.resourceSlots.length!==1','status.resourceSlots.length!==2').replace('actualSharedResourceMap:true','actualSharedResourceMap:true,orphanOnlyClaimRefused:true,aliasResourceAcquiredBeforeClaim:true');f.write_text(s)
