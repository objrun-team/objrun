"""Pure original-resource public solver plan and exact frozen six-tool assets."""
from pathlib import Path
import re
import skb_artifact_task_v2 as task

ASSETS=task.REPO/'examples/benchmark/terminal-bench/.runtime'
TOOLS={'bash','read','write','edit','glob','grep'}
PROTOCOL='skillsbench-task-solver-plan-v2'
TARGETS={'node':'/rt-node','runtime.mjs':'/rt-runtime.mjs','libstdc++.so.6':'/rt-lib/libstdc++.so.6','libgcc_s.so.1':'/rt-lib/libgcc_s.so.1'}


def runtime_manifest():
    pin=task.pin(ASSETS/'manifest.json');value=task.read_json(pin)
    task.demand(set(value['tools'])==TOOLS and set(value['assets'])==set(TARGETS),'solver_six','Exact frozen six-tool manifest required')
    assets=[];sources=[]
    for name,sha in value['assets'].items():
        p=task.pin(ASSETS/name);task.demand(p['sha256']==sha,'solver_asset','Original six-tool binary/library/bundle changed');assets.append({'sourcePin':p,'containerPath':TARGETS[name]})
    for name,sha in value['frozenSources'].items():
        p=task.pin(task.REPO/name);task.demand(p['sha256']==sha,'solver_core','Original executor core source changed');sources.append(p)
    return {'manifestPin':pin,'assets':assets,'frozenSourcePins':sources,'toolNames':sorted(TOOLS),'bootstrapPolicy':'Exact same copied six-tool assets as frozen JPG bridge; no candidate program enters host/private grader'}


def plan(descriptor,nonce):
    task.validate_descriptor(descriptor)
    task.demand(re.fullmatch('[0-9a-f]{32}',nonce or ''),'solver_nonce','Fresh exact instance nonce required')
    image=task.read_json(descriptor['candidateImageProofPin'])['imageId'];e=descriptor['originalResources']['environment'];memory=e['memory_mb']*1024**2
    name='objrun-skb-solver-'+nonce;cwd='/app/workspace' if descriptor['taskId']=='jpg-ocr-stat' else '/root'
    argv=['create','--name',name,'--pull','never','--label','objrun.skb.task-id='+descriptor['taskId'],'--label','objrun.skb.instance-nonce='+nonce,
        '--label','objrun.skb.role=solver','--network','bridge','--log-driver','none','--memory',str(memory),'--memory-swap',str(memory),
        '--cpus',str(e['cpus']),'--cap-drop','ALL','--security-opt','no-new-privileges','--workdir',cwd,'--entrypoint','/bin/bash',image,'-c','exec sleep infinity']
    return {'protocol':PROTOCOL,'taskId':descriptor['taskId'],'instanceNonce':nonce,'name':name,'imageId':image,'createArgv':argv,
        'cpus':e['cpus'],'memoryBytes':memory,'agentSeconds':descriptor['originalResources']['agent']['timeout_sec'],
        'verifierSeconds':descriptor['originalResources']['verifier']['timeout_sec'],'solverWritableMaximumBytes':descriptor['solverWritableBudgetBytes'],
        'workingDirectory':cwd,'originalPublicNetworkMode':e['network_mode'],'actualDockerNetworkMode':'bridge','hostBinds':[],
        'kernelWorkspaceQuotaCertified':False,'runtime':runtime_manifest(),'sourcePin':task.pin(__file__),'modelCalls':0,'actualReady':False}


# Trusted fixed wrapper starts the frozen MCP runtime for one request, waits for
# its actual response and closes that exact child. Candidate args are JSON data.
ONE_TOOL_WRAPPER=r"""const fs=require('node:fs'),crypto=require('node:crypto'),cp=require('node:child_process');
const [file,want,limit]=process.argv.slice(1),raw=fs.readFileSync(file);
if(crypto.createHash('sha256').update(raw).digest('hex')!==want)throw Error('tool request SHA differs');
const input=JSON.parse(raw);fs.unlinkSync(file);
const child=cp.spawn('/rt-node',['/rt-runtime.mjs'],{env:{...process.env,LD_LIBRARY_PATH:'/rt-lib'},stdio:['pipe','pipe','pipe']});
let buffered='',done=false,errorBytes=0;const end=setTimeout(()=>finish({isError:true,content:[{type:'text',text:'tool deadline exceeded'}]},1),Number(limit));
function finish(result,status){if(done)return;done=true;clearTimeout(end);child.kill('SIGKILL');child.once('close',()=>{fs.writeSync(1,JSON.stringify(result)+'\n');process.exit(status)});}
child.stderr.on('data',b=>{errorBytes+=b.length;if(errorBytes>262144)finish({isError:true,content:[{type:'text',text:'runtime stderr limit exceeded'}]},1)});
child.on('error',()=>finish({isError:true,content:[{type:'text',text:'frozen tool runtime spawn failed'}]},1));
child.stdout.on('data',b=>{buffered+=b.toString();if(Buffer.byteLength(buffered)>8388608){finish({isError:true,content:[{type:'text',text:'tool result limit exceeded'}]},1);return;}
let i;while((i=buffered.indexOf('\n'))>=0){const line=buffered.slice(0,i);buffered=buffered.slice(i+1);if(!line)continue;const msg=JSON.parse(line);
if(msg.id===1){if(msg.error){finish({isError:true,content:[{type:'text',text:'initialize failed'}]},1);return;}child.stdin.write(JSON.stringify({jsonrpc:'2.0',id:2,method:'tools/call',params:{name:input.tool,arguments:input.args}})+'\n');}
if(msg.id===2)finish(msg.result??{isError:true,content:[{type:'text',text:'tool RPC failed'}]},0);}});
child.once('close',()=>{if(!done){clearTimeout(end);fs.writeSync(1,JSON.stringify({isError:true,content:[{type:'text',text:'runtime exited without a response'}]})+'\n');process.exit(1)}});
child.stdin.write(JSON.stringify({jsonrpc:'2.0',id:1,method:'initialize',params:{protocolVersion:'2026-07-28'}})+'\n');
"""
