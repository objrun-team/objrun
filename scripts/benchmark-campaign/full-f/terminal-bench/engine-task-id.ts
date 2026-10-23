import {createHash} from 'node:crypto';
/** Engine path parameters are bounded; original task IDs remain in all metadata. */
export function engineTaskId(runId:string,arm:'F',officialTaskId:string):string {
  if(!runId||arm!=='F'||!officialTaskId)throw Error('terminal_engine_task_id_input');
  return 'tb12-'+createHash('sha256').update(JSON.stringify([runId,arm,officialTaskId])).digest('hex').slice(0,32);
}
