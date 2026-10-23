import {join,resolve} from 'node:path';
import {spawn} from 'node:child_process';
import {atomicStateJson} from '../../shared/atomic-state.ts';
const root=resolve(import.meta.dir,'../../../../..');
const path=join(root,'docs/repair-2026-10-10/full-f-rerun/novaeve-formal-20261013/broker/remote-disk.json');
const mode=process.argv[2];
if(!['--check','--once','--watch'].includes(mode??''))throw Error('use --check, --once or --watch');
export function parseFree(stdout:string){const lines=stdout.trim().split(/\r?\n/);const n=Number(lines.at(-1)?.trim());if(!Number.isSafeInteger(n)||n<0)throw Error('invalid_remote_df');return n;}
async function refresh(){
 const info:any=await(await fetch('http://127.0.0.1:18750/info',{signal:AbortSignal.timeout(5000)})).json();
 if(info.DockerRootDir!=='/data/wpx/tgengin/docker')throw Error('remote_docker_root_changed');
 const startedAt=Date.now();
 const stdout=await new Promise<string>((accept,reject)=>{
  const child=spawn('C:/Windows/System32/OpenSSH/ssh.exe',['-T','-o','BatchMode=yes','-o','ConnectTimeout=8','-o','ClearAllForwardings=yes','novaeve',"df -B1 --output=avail /data/wpx/tgengin/docker"],{windowsHide:true,stdio:['ignore','pipe','pipe']});
  let out='';child.stdout.on('data',b=>out+=b.toString());child.stderr.resume();
  const timer=setTimeout(()=>{child.kill();reject(Error('remote_df_timeout'));},12000);
  child.on('error',e=>{clearTimeout(timer);reject(e);});child.on('exit',code=>{clearTimeout(timer);if(code===0)accept(out);else reject(Error('remote_df_failed'));});
 });
 // Timestamp begins before measurement so network delay never extends freshness.
 const value={protocol:'novaeve-runtime-disk-v1',dataRoot:info.DockerRootDir,freeBytes:parseFree(stdout),observedAtMs:startedAt,observedAtUtc:new Date(startedAt).toISOString(),dockerHost:'tcp://127.0.0.1:18750',probeExitCode:0};
 atomicStateJson(path,value);console.log(JSON.stringify({refreshed:true,freeGiB:value.freeBytes/1024**3,observedAtUtc:value.observedAtUtc,modelCalls:0}));
}
if(mode==='--check'){if(parseFree('Avail\n197568495616\n')!==197568495616)throw Error('df_parser');let refused=false;try{parseFree('bad');}catch{refused=true;}if(!refused)throw Error('df_parser_accepts_bad_data');console.log(JSON.stringify({parserChecked:true,networkCalls:0,modelCalls:0}));}
else do{try{await refresh();}catch(e){console.error(JSON.stringify({refreshed:false,reason:e instanceof Error?e.message:'refresh_failed',staleGateRetained:true}));if(mode==='--once')process.exitCode=1;}if(mode==='--watch')await Bun.sleep(1000);}while(mode==='--watch');
