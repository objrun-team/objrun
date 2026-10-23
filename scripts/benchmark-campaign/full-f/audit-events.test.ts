import {test,expect} from 'bun:test';
import {auditProviderFlights} from './audit-events.ts';
const dispatch=(runId:string,requestSeq:number,requestSha256:string)=>({kind:'dispatch',slug:'chembench',runId,requestSeq,requestSha256});
const response=(runId:string,requestSeq:number,sha256:string)=>({kind:'response',runId,requestSeq,responsePin:{sha256}});
const result=(runId:string,rawSha256:string,sha256:string)=>({kind:'forward-result',runId,rawSha256,responsePin:{sha256},providerAttempted:true});
test('incomplete upstream flight ends before a restarted lane uses its slots',()=>{
  const audit=auditProviderFlights([dispatch('old',41,'A'),result('old','A','local503'),dispatch('new',0,'B'),dispatch('new',1,'C')]);
  expect(audit.peakPerBench).toBe(2);expect(audit.peakRequests).toBe(2);expect(audit.incompleteFlightsEnded).toBe(1);
  expect(audit.remainingFlights).toBe(2);expect(audit.duplicateDispatch).toBe(false);
});
test('a complete result does not end a different live request with identical input',()=>{
  const audit=auditProviderFlights([dispatch('r',0,'A'),dispatch('r',1,'A'),response('r',0,'X'),result('r','A','X'),dispatch('r',2,'B')]);
  expect(audit.peakPerBench).toBe(2);expect(audit.remainingFlights).toBe(2);expect(audit.incompleteFlightsEnded).toBe(0);
});
test('ambiguous incomplete results retain conservative counts and expose uncertainty',()=>{
  const audit=auditProviderFlights([dispatch('r',0,'A'),dispatch('r',1,'A'),result('r','A','error')]);
  expect(audit.remainingFlights).toBe(2);expect(audit.ambiguousForwardResults).toBe(1);
});
