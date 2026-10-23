// Pure inactive generic native-unit boundary policy; no answer extraction or operations.
export function shouldBudgetHandOff(task,nowMs){
 const created=Number(task?.created_at),seconds=Number(task?.solve_seconds);
 if(seconds!==900||!Number.isFinite(created)||!Number.isFinite(nowMs)||nowMs<created)return false;
 const remaining=created+seconds*1000-nowMs;
 return remaining>0&&remaining<=seconds*1000/4;
}
