// HumanEval Bench response validation; the native runtime remains unchanged.
export async function submitResponse(body:any, invoke:(request:any,attempt:number)=>Promise<any>){
  const first=await invoke(body,0);
  const tools=body.tools??[];
  const handIn=tools.length===1&&tools[0]?.type==='function'&&tools[0]?.function?.name==='submit';
  if(!handIn||first.status!==200||first.receipt?.fault&&first.receipt.fault!=='MissingOrInvalidOpenRouterUsdCost')return first;
  let response:any;
  try{response=JSON.parse(first.raw);}catch{return first;}
  const choice=response.choices?.[0];
  const calls=choice?.message?.tool_calls??[];
  if(choice?.finish_reason==='length'||calls.length===1&&calls[0]?.function?.name==='submit')return first;
  // Format repair is another real model request. Never convert ordinary text or
  // an earlier verify argument into a tool call on the model's behalf.
  const request={...body,messages:[...(body.messages??[]),{role:'user',content:'Your preceding response did not invoke the submit tool and was not handed in. This is the hand-in station. Invoke the available submit tool exactly once with your complete Python code in the answer argument. Earlier submit attempts that were not executed do not complete this hand-in. A plain text or code-block response is rejected by the runtime.'}]};
  return invoke(request,1);
}
