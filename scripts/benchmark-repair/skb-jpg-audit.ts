import {spawnNativePython,loadNativePython} from './skb-jpg-native-python.ts';

/** Send host-only credentials through an explicitly closed asynchronous pipe. */
export async function auditJpgEvidence(input:{script:string;output:string;store:string;privateConfigs:string[];secrets:string[];timeoutMs?:number}) {
 const native=loadNativePython(),child=spawnNativePython([input.script,'--audit','--output',input.output,'--store',input.store,...input.privateConfigs.flatMap(path=>['--private-config',path])],{stdio:['pipe','ignore','pipe']});
 if(!child.stdin||child.pid===undefined)throw new Error('Evidence audit child did not start');
 child.stderr?.resume();
 await new Promise<void>((resolve,reject)=>{
  let code:number|null= null,timedOut=false,settled=false;
  const timers:ReturnType<typeof setTimeout>[]=[];
  const finish=(success:boolean,message:string)=>{if(settled)return;settled=true;for(const timer of timers)clearTimeout(timer);success?resolve():reject(new Error(message));};
  timers.push(setTimeout(()=>{timedOut=true;child.kill('SIGTERM');timers.push(setTimeout(()=>{if(child.exitCode===null&&child.signalCode===null)child.kill('SIGKILL');timers.push(setTimeout(()=>finish(false,'Evidence audit native process exit did not close within its bound'),1500));},1500));},input.timeoutMs??60000));
  child.once('error',()=>finish(false,'Evidence audit native process failed'));
  child.once('exit',value=>{code=value;});
  child.once('close',()=>finish(code===0&&!timedOut,'Evidence credential audit did not close successfully'));
  child.stdin!.on('error',()=>{});
  child.stdin!.end(JSON.stringify(input.secrets)+'\n','utf8');
 });
 return {processId:child.pid,closed:true,directChildClosed:true,nativeExecutableSha256:native.sha256};
}
