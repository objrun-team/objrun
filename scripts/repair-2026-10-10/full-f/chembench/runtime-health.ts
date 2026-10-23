import type { Machine } from '../../../../test/_lib.ts';
/** A durable production submit-station fault, not a heuristic timeout. */
export async function submissionFault(engine:Machine,taskId:string){
  const result=await engine.api<{rows:any[]}>('POST','/query',{sql:`select m.unit,m.at,json_extract(m.body,'$.stuck') as fault
    from agent_bot_msg m join task_repair u on u.instance=m.instance and u.unit=m.unit
    where u.task=:task and u.cycle='submit' and m.role='system' and m.kind='inject'
    and json_valid(m.body) and json_extract(m.body,'$.stuck')='The required submit tool was not called exactly once'
    order by m.at desc limit 1`,params:{task:taskId}});
  return result.rows[0];
}
