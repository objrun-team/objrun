import {readFileSync} from 'node:fs';
import {join} from 'node:path';
import {ROOT} from './common.ts';

export const toolSpecs=[
 {name:'compute',description:'Run bash in your isolated Linux scientific workspace. Use Python/scripts, files, curl and public literature. The workspace and /output persist within this task. No benchmark answer keys are available.',parameters:{type:'object',properties:{command:{type:'string'},timeout:{type:'integer'}},required:['command','timeout'],additionalProperties:false}},
 {name:'snapshot',description:'Freeze all current /output artifacts and return their immutable candidate identifier. Call this after writing the required output files, then pass the exact identifier to submit or verify.',parameters:{type:'object',properties:{},required:[],additionalProperties:false}}
];
export const submission={name:'submit',description:'Deliver an immutable artifact candidate returned by snapshot. This finishes the current stage.',parameters:{type:'object',properties:{answer:{type:'string'}},required:['answer'],additionalProperties:false}};
export const protocol='\nUse compute for all bash, Python, files and public literature. Follow the official output paths exactly. This is one complete tool-assisted attempt, not one model message. After writing the outputs, call snapshot and use its exact candidate identifier as the answer in submit. Do not merely state an answer in chat. Do not access benchmark-specific answers, grader files, host resources, or other runs. The /output and /workspace contain only your current task and any actual preceding-stage artifacts.';

export async function bridge(op:string,data:any={}){
 const config=JSON.parse(readFileSync(join(ROOT,'outputs/bridge.json'),'utf8'));
 const r=await fetch(config.url+'/'+op,{method:'POST',headers:{'content-type':'application/json','x-tpe-token':config.token},body:JSON.stringify(data),timeout:false,signal:AbortSignal.timeout(op==='create'?900000:op==='compute'?110000:180000)} as any);
 const value:any=await r.json();if(!r.ok)throw Error('Bridge:'+op+':'+(value.errorType??r.status));return value;
}
