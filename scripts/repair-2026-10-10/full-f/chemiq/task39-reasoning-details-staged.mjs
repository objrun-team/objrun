/** Inactive, pure request projection. No network, owners, grading, or SDK budget changes. */
import assert from 'node:assert/strict';import fs from 'node:fs';import {createHash} from 'node:crypto';
const hash=raw=>createHash('sha256').update(raw).digest('hex');
export function reasoningDetailBank(){
 const records=[];
 return {
  record(responsePin){
   const raw=fs.readFileSync(responsePin.path);assert(raw.length===responsePin.bytes&&hash(raw)===responsePin.sha256,'original response pin changed');const r=JSON.parse(raw);
   assert(/^gen-/.test(r.id)&&r.model.startsWith('deepseek/deepseek-v4.1-flash')&&!r.error&&typeof r.usage?.cost==='number');
   const m=r.choices?.[0]?.message;assert(m&&Array.isArray(m.reasoning_details)&&typeof m.reasoning==='string');assert(!records.some(v=>v.id===r.id),'generation repeated');
   assert(m.reasoning_details.every(d=>d.type==='reasoning.text'&&typeof d.text==='string'),'cannot invent encrypted or summarized reasoning');
   assert(m.reasoning_details.map(d=>d.text).join('')===m.reasoning,'reasoning text/detail mismatch');
   records.push({id:r.id,provider:r.provider,text:m.reasoning,details:structuredClone(m.reasoning_details),pin:responsePin});
  },
  project(request){
   const result=structuredClone(request),bindings=[];
   for(let index=0;index<result.messages.length;index++){
    const m=result.messages[index];if(m.role!=='assistant'||!m.reasoning_content||m.reasoning_details)continue;
    const matches=[];
    for(let start=0;start<records.length;start++){let text='';for(let end=start;end<records.length;end++){text+=records[end].text;if(text===m.reasoning_content)matches.push(records.slice(start,end+1));if(text.length>=m.reasoning_content.length)break;}}
    assert(matches.length===1,'unproven or ambiguous original reasoning continuation');
    m.reasoning_details=matches[0].flatMap(r=>structuredClone(r.details));delete m.reasoning_content;
    bindings.push({messageIndex:index,generations:matches[0].map(r=>r.id),responsePins:matches[0].map(r=>r.pin),detailCount:m.reasoning_details.length});
   }
   return{request:result,bindings};
  }
 };
}
