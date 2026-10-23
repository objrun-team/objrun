from pathlib import Path
p=Path(__file__).parent
s=(p/'check-delegated-v19.ts').read_text(encoding='utf-8')
s=s.replace("'./broker-delegated-v19.ts'","'./broker-adoption-v46.ts'").replace('broker-recovery-v19-fixtures','broker-adoption-v46-fixtures')
s=s.replace("const originalResources:any[]=[{kind:'heavy-container',slug:'skillsbench',pid:1,slots:8,memoryMb:4096,plannedGrowthBytes:0,token:'fixture-only'}];","const originalResources:any[]=[{kind:'heavy-container',slug:'skillsbench',pid:1,slots:8,memoryMb:4096,plannedGrowthBytes:0,token:'fixture-only',adoptedOrphanHold:true}];")
a=s.index('const originalPool=Bun.serve(');b=s.index('const parent:any=',a);s=s[:a]+s[b:]
a=s.index('externalResources:()=>originalResources');b=s.index('transport:async',a)
s=s[:a]+"initialResources:originalResources,aliasPorts:[0],beforeAccept:()=>{if(!externalHealthy)throw Error('fixture_execution_health_guard');},externalHealth:()=>({healthy:externalHealthy}),"+s[b:]
s=s.replace('resourceProxyCalls!==1','resourceProxyCalls!==0').replace('actualUpstreamResourceHTTP:true','actualSharedResourceMap:true')
s=s.replace("await b.server.stop(true);await originalPool.stop(true);process.exit(0);","await b.server.stop(true);process.exit(0);")
s=s.replace("protocol:'novaeve-delegated-v19-synthetic-http-drill'","protocol:'novaeve-adoption-v46-synthetic-http-drill'")
(p/'check-http-adoption-v46.ts').write_text(s,encoding='utf-8')
