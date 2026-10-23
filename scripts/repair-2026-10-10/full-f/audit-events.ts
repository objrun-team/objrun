/** Read-only reconstruction of provider flights, including incomplete responses. */
export function auditProviderFlights(events:any[]) {
  const dispatchRows=new Map<string,any>(),completeBodies=new Set<string>();
  const key=(event:any)=>`${event.runId}/${event.requestSeq}`;
  for(const event of events)if(event.kind==='dispatch')dispatchRows.set(key(event),event);
  for(const event of events)if(event.kind==='response'){
    const dispatch=dispatchRows.get(key(event));
    if(dispatch&&event.responsePin)completeBodies.add(`${event.runId}/${dispatch.requestSha256}/${event.responsePin.sha256}`);
  }
  const active=new Map<string,string>(),dispatches=new Set<string>();
  let peakRequests=0,peakPerBench=0,duplicateDispatch=false,incompleteFlightsEnded=0,ambiguousForwardResults=0;
  for(const event of events){
    if(event.kind==='dispatch'){
      const id=key(event);if(dispatches.has(id))duplicateDispatch=true;
      dispatches.add(id);active.set(id,event.slug);peakRequests=Math.max(peakRequests,active.size);
      for(const slug of new Set(active.values()))peakPerBench=Math.max(peakPerBench,[...active.values()].filter(value=>value===slug).length);
    }else if(event.kind==='response')active.delete(key(event));
    else if(event.kind==='forward-result'&&event.providerAttempted===true){
      // Complete native responses already ended their flight. A result for that
      // response must not remove a different pending call with identical input.
      if(completeBodies.has(`${event.runId}/${event.rawSha256}/${event.responsePin?.sha256}`))continue;
      const candidates=[...active.keys()].filter(id=>{
        const dispatch=dispatchRows.get(id);return dispatch.runId===event.runId&&dispatch.requestSha256===event.rawSha256;
      });
      if(candidates.length===1){active.delete(candidates[0]!);incompleteFlightsEnded++;}
      else if(candidates.length>1)ambiguousForwardResults++;
    }
  }
  return{peakRequests,peakPerBench,duplicateDispatch,incompleteFlightsEnded,ambiguousForwardResults,remainingFlights:active.size};
}
