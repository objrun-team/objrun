/** Preserve each actual provider response and retry missing mandatory submission. */
export async function mandatorySubmission<T extends {httpStatus:number;rawResponse:string}>(raw:string,forward:(request:string)=>Promise<T>,retryTimes:number,onRetry:(e:any)=>void){
 const initial=JSON.parse(raw),mandatory=initial.tool_choice?.type==='function'&&initial.tool_choice.function?.name==='submit'||initial.tool_choice==='auto'&&initial.tools?.length===1&&initial.tools[0]?.function?.name==='submit';
 let request=initial;
 for(let attempt=0;;attempt++){
  const reply=await forward(JSON.stringify(request));
  if(!mandatory||reply.httpStatus!==200)return reply;
  let body:any;try{body=JSON.parse(reply.rawResponse);}catch{return reply;}
  const choice=body.choices?.[0],message=choice?.message,calls=message?.tool_calls??[];
  if(choice?.finish_reason==='length'||calls.length===1&&calls[0]?.function?.name==='submit'||attempt>=retryTimes)return reply;
  onRetry({attempt:attempt+1,reason:'mandatory_submit_call_missing',generationId:body.id,originalResponseUnchanged:true});
  request={...initial,messages:[...initial.messages,...(typeof message?.content==='string'?[{role:'assistant',content:message.content}]:[]),{role:'user',content:'The previous response did not call the required submit function. Invoke the available submit tool exactly once with your final answer. A text-only response does not submit this task.'}]};
 }
}
