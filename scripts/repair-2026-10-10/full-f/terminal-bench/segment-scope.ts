/** A ready subset never changes the frozen full denominator. */
export function segmentScope(planned:string[],ready:string[]){
  if(planned.length!==89||new Set(planned).size!==89)throw new Error('Full Terminal-Bench plan must retain 89 unique tasks');
  if(!ready.length||new Set(ready).size!==ready.length||ready.some(id=>!planned.includes(id)))
    throw new Error('Ready segment must be a nonempty unique subset of the full plan');
  return {plannedTaskRuns:89,taskIds:[...planned],executingTaskIds:[...ready],pendingPreparationTaskIds:planned.filter(id=>!ready.includes(id))};
}
