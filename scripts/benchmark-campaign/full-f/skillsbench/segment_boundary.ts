/** Close a stopped proxy segment before another task, retaining every receipt. */
export function taskSegmentBoundary(state:{provider:{stopReason?:string;journal?:{stopReason?:string};anomalies?:number};cash:{newUnknownCount:number;pendingCount:number}}){
 const reason=state.provider.stopReason??state.provider.journal?.stopReason;
 // An unknown invoice is an accounting observation. Only a proxy/journal
 // that already refuses admissions requires a new authenticated segment.
 return reason?{closeSegment:true,reason,unknownCount:state.cash.newUnknownCount,action:'close_and_continue_unfinished' as const}:
  {closeSegment:false,unknownCount:state.cash.newUnknownCount,action:'continue_current_segment' as const};
}
