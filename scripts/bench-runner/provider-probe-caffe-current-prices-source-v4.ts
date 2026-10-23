/** Preparation only: exact observed Wafer endpoint, preserving ordinary Fireworks. */
import {scopedTaskTransportSource} from './provider-probe-scoped-transport-source-v3.ts';
const responseSha='d946fea13ea64c4e8d1d0db9120333e5ed2f81263eba1f289b3af21594d7da54';
function one(s:string,a:string,b:string){if(s.split(a).length!==2)throw Error('caffe_probe_exact_anchor:'+a);return s.replace(a,b)}
export function currentProbeSource(path:string,raw:string){
 let s=scopedTaskTransportSource(path,raw);const n=path.replaceAll('\\','/').split('/').pop();
 if(n==='chembench-supplier-profiles.ts')s=one(s,"wafer:make('wafer','Wafer',.049)","wafer:make('wafer','Wafer',.05)");
 if(n==='supplier-usd-cash.ts'){
  const anchor='  const raw = jsonPin(data.originalResponsePin);';
  s=one(s,anchor,anchor+`\n  if(providerSlug==='wafer')demand(data.canonicalModel==='deepseek/deepseek-v4.1-flash-20260910'&&data.endpointTag==='wafer/mxfp4'&&data.originalResponsePin.sha256==='${responseSha}'&&same(data.peakRates,{input:.1,cachedInput:.05,output:.65}),'probe_current_wafer_official_snapshot');`);
  s=one(s,'row.tag === providerSlug',"row.tag === (providerSlug==='wafer'?'wafer/mxfp4':providerSlug)");
 }
 if(n==='start-unlimited-broker.ts')s=one(s,"from'./provider-probe-scoped-transport-loader-v3.ts'","from'./provider-probe-caffe-current-prices-loader-v4.ts'");
 return s;
}
