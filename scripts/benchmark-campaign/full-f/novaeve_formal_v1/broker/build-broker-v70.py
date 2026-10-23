from pathlib import Path
p=Path(__file__).parent;s=(p/'broker-adoption-v48.ts').read_text()
s=s.replace('resourceProxy?:(request:Request)=>Promise<Response>;','resourceProxy?:(request:Request)=>Promise<Response>;')
needle="if(HEAVY.has(data.slug)&&!lanes.has(data.runId))check([...resources.values()].some(r=>r.kind==='heavy-container'&&r.slug===data.slug&&!r.adoptedOrphanHold),'heavy_container_slot_required_before_lane');"
replacement="""let claimedResource:any;
        if(HEAVY.has(data.slug)&&!lanes.has(data.runId)){
          check(data.ownedResource&&Number.isSafeInteger(data.ownedResource.pid)&&typeof data.ownedResource.token==='string','exact_owned_resource_pid_token_required');
          const key='heavy-container/'+data.slug+'/'+data.ownedResource.pid;claimedResource=resources.get(key);
          check(claimedResource&&!claimedResource.adoptedOrphanHold&&!claimedResource.inheritedResourceHold&&claimedResource.token===data.ownedResource.token,'exact_new_owned_resource_required');
          check(![...lanes.values()].some((l:any)=>!l.closed&&l.resourceBinding?.key===key),'owned_resource_already_has_live_lane');
          try{process.kill(data.ownedResource.pid,0)}catch{throw Error('exact_resource_owner_not_live')}
        }"""
assert needle in s;s=s.replace(needle,replacement)
old="if(HEAVY.has(data.slug))check([...lanes.values()].filter(l=>l.slug===data.slug&&!l.closed).length<[...resources.values()].filter(r=>r.kind==='heavy-container'&&r.slug===data.slug&&!r.adoptedOrphanHold).reduce((n,r)=>n+r.slots,0),'independent_heavy_container_slot_required_before_lane');"
assert s.count(old)==2;s=s.replace(old,"if(HEAVY.has(data.slug))check(claimedResource&&!claimedResource.adoptedOrphanHold&&!claimedResource.inheritedResourceHold,'exact_new_resource_remains_eligible');")
s=s.replace('registeredProcesses:[]};lanes.set(data.runId,lane);',"registeredProcesses:[],resourceBinding:claimedResource?{key:'heavy-container/'+data.slug+'/'+data.ownedResource.pid,pid:data.ownedResource.pid,tokenSha256:hash(data.ownedResource.token)}:undefined} as any;lanes.set(data.runId,lane);")
s=s.replace('registeredProcesses:Pin[]};','registeredProcesses:Pin[];resourceBinding?:{key:string;pid:number;tokenSha256:string}};')
s=s.replace('novaeve-adopted-resource-pool-v48','novaeve-adopted-resource-pool-v70')
(p/'broker-adoption-v70.ts').open('x').write(s)
