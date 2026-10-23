/** Bounded readiness wait; original remote floor/freshness is never weakened. */
import {readFileSync} from 'node:fs';import {createHash} from 'node:crypto';
export async function waitActualFreshPipelineDisk(path:string){const deadline=performance.now()+25000,attempts:any[]=[];
 while(true){let row:any;try{const raw=readFileSync(path),snapshot=JSON.parse(raw.toString('utf8')),nowMs=Date.now(),ageMs=nowMs-snapshot.observedAtMs;
  const accepted=snapshot.protocol==='novaeve-runtime-disk-v1'&&snapshot.dataRoot==='/data/wpx/tgengin/docker'&&snapshot.probeExitCode===0&&Number.isFinite(snapshot.freeBytes)&&snapshot.freeBytes>=5368709120&&Number.isFinite(ageMs)&&ageMs>=0&&ageMs<=10000;
  row={nowMs,ageMs,accepted,snapshot,actualRead:{path,bytes:raw.length,sha256:createHash('sha256').update(raw).digest('hex')}};
 }catch(error){row={nowMs:Date.now(),accepted:false,readError:String(error)}}attempts.push(row);
 if(row.accepted)return{protocol:'pipeline-v85-actual-fresh-disk-wait',waitBoundMs:25000,originalFreshnessMs:10000,originalFloorBytes:5368709120,attempts};
 if(performance.now()>=deadline){const error=Object.assign(new Error('pipeline_remote_disk_fresh_floor'),{actualDiskWaitEvidence:{protocol:'pipeline-v85-actual-fresh-disk-wait',waitBoundMs:25000,originalFreshnessMs:10000,originalFloorBytes:5368709120,attempts}});throw error}
 await Bun.sleep(250);
 }}
