from pathlib import Path
import difflib
here=Path(__file__).parent;s=(here/'broker-delegated-v19.ts').read_text()
s=s.replace('resourceProxy?:(request:Request)=>Promise<Response>;', 'initialResources?:any[];aliasPorts?:number[];adoptionMetadata?:()=>any;adoptionResourceRelease?:(body:any)=>Promise<string>;resourceProxy?:(request:Request)=>Promise<Response>;')
s=s.replace('new Map<string,{kind:string;slug:string;pid:number;token:string;slots:number;memoryMb:number;plannedGrowthBytes:number}>()', 'new Map<string,any>((options.initialResources??[]).map(r=>[r.kind+\'/\'+r.slug+\'/\'+r.pid,{...r}]))')
s=s.replace("canonicalOwner:parent?.owned??null,parentCapUsd", "adoption:options.adoptionMetadata?.()??null,canonicalOwner:parent?.owned??null,parentCapUsd")
s=s.replace("atomicJson(healthPath,{...snapshot(),snapshotWriteFailure:snapshotWriteFailure??null});", "atomicJson(healthPath,{...snapshot(),snapshotWriteFailure:snapshotWriteFailure??null});atomicJson(join(output,'resource-pool.json'),{protocol:'novaeve-adopted-resource-pool-v46',capacity:16,rows:[...resources.values()]});")
s=s.replace("const server=Bun.serve({hostname:'127.0.0.1',port:options.port??17888,idleTimeout:255,maxRequestBodySize:4*1024**2,async fetch(request) {", "const fetchHandler=async(request:Request)=>{")
s=s.replace("if(url.pathname==='/admin/pause')", "if(url.pathname==='/adoption/resource-release'){check(options.adoptionResourceRelease,'adoption_release_unavailable');const key=await options.adoptionResourceRelease(await request.json());check(resources.get(key)?.adoptedOrphanHold===true,'not_an_adopted_orphan_resource');resources.delete(key);log({kind:'adopted-orphan-resource-closed',key});persist();return Response.json({released:true,originalBudgetReleased:false});}\n      if(url.pathname==='/admin/pause')")
s=s.replace("check(owned?.token===d.token,'resource_not_owned');", "check(owned?.token===d.token&&!owned.adoptedOrphanHold,'resource_not_owned_or_adopted_hold');")
s=s.replace("check(!held||held.slots===slots", "check(!held||!held.adoptedOrphanHold,'adopted_orphan_cannot_be_reclaimed_by_reused_pid');check(!held||held.slots===slots")
s=s.replace("  }});\n  const timer=", "  };\n  const server=Bun.serve({hostname:'127.0.0.1',port:options.port??17895,idleTimeout:255,maxRequestBodySize:4*1024**2,fetch:fetchHandler});\n  const aliasServers=(options.aliasPorts??[]).map(port=>Bun.serve({hostname:'127.0.0.1',port,idleTimeout:255,maxRequestBodySize:4*1024**2,fetch:fetchHandler}));\n  const timer=")
s=s.replace("await server.stop(true);", "await server.stop(true);for(const alias of aliasServers)await alias.stop(true);")
assert 'const fetchHandler' in s and 'aliasServers=' in s and 'initialResources?' in s
(here/'broker-adoption-v46.ts').write_text(s,encoding='utf8')
root=here.resolve().parents[4];out=root/'docs/repair-2026-10-10/full-f-rerun/novaeve-formal-20261013/coordinator/broker-adoption-v46';out.mkdir(exist_ok=True)
(out/'broker-source.diff').write_text(''.join(difflib.unified_diff((here/'broker-delegated-v19.ts').read_text().splitlines(True),s.splitlines(True),fromfile='broker-delegated-v19.ts',tofile='broker-adoption-v46.ts')),encoding='utf8')
