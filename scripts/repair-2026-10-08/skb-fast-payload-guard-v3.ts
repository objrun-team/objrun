/** Fail closed before external forwarding if actual host credentials enter body. */
import {hash,demand} from './paid-resource-proof-v2.ts';
export function checkFastPayload(raw:string,secrets:string[]){
 const body=JSON.parse(raw);demand(body.model==='deepseek-flash'&&body.temperature===0&&body.seed===42&&body.max_tokens===8192,'skb_fast_public_request_parameters');
 demand(Array.isArray(body.messages)&&body.messages.length>0,'skb_fast_public_messages');
 const needles=[...new Set(secrets.filter(x=>typeof x==='string'&&x.length>=6))];
 demand(needles.length>0&&!needles.some(x=>raw.includes(x)),'skb_fast_private_credential_in_model_payload');
 const allowed=new Set(['bash','read','write','edit','glob','grep','submit','verify']);
 demand((body.tools??[]).every((x:any)=>allowed.has(x.function?.name)),'skb_fast_unapproved_model_tool');
 return {protocol:'skillsbench-public-payload-guard-v3',rawRequestSha256:hash(raw),actualCredentialValuesChecked:needles.length,
   actualCredentialsSerialized:false,privateCredentialFound:false,allowedModelTools:[...allowed],
   datasetRepository:'https://github.com/benchflow-ai/skillsbench',datasetCommit:'b63b7b2850226b6aa4fb5929a8c1ac7bc4d9a6af',
   scope:'Fixed public task prompt, generic engine/tool instructions and isolated public candidate-container tool results',modelCallsByGuard:0};
}
