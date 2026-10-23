/** One Python owner's read-only stdio channel. No scheduler, mutations, or cached decisions. */
import{readFileSync}from'node:fs';import{resolve,join}from'node:path';import{pathToFileURL}from'node:url';import{createHash,verify,createHmac,timingSafeEqual}from'node:crypto';import{createInterface}from'node:readline';
const sha=(b:Buffer)=>createHash('sha256').update(b).digest('hex');
function demand(ok:any,code:string):asserts ok{if(!ok)throw Error(code)}
function pinned(p:any){const b=readFileSync(p.path);demand(b.length===p.bytes&&sha(b)===p.sha256,'persistent_guard_pin_changed:'+p.path);return b}
const mappingPath=resolve(process.env.NOVAEVE_PYTHON_MAPPING_CONFIG!),mappingSha=process.env.NOVAEVE_PYTHON_MAPPING_SHA256!,secret=process.env.NOVAEVE_GUARD_CHANNEL_SECRET!;
demand(/^[a-f0-9]{64}$/.test(mappingSha)&&/^[a-f0-9]{64}$/.test(secret),'persistent_guard_explicit_binding');
const initialMapping=readFileSync(mappingPath);demand(sha(initialMapping)===mappingSha,'persistent_guard_mapping_changed');
const mapping=JSON.parse(initialMapping.toString()),contract=mapping.adoptedGuardCapture,channel=contract.persistentReadonlyChannel;
demand(channel.protocol==='bench-persistent-readonly-guard-channel-v1'&&channel.originalBridgePin.sha256==='86420ff8d6058ada967a50c07587f825fe720795615c67f806d4addd269e7bb8','persistent_guard_exact_original_bridge');
const root=resolve(contract.root),home=join(root,'docs/repair-2026-10-10/full-f-rerun/novaeve-formal-20261013'),activation=resolve(process.argv[2]);
demand(activation===resolve(home,'activation-unlimited-financial.json')&&resolve(channel.serverPin.path)===resolve(import.meta.path),'persistent_guard_canonical_source');
function fullSources(){
 const raw=readFileSync(mappingPath);demand(sha(raw)===mappingSha&&raw.equals(initialMapping),'persistent_guard_mapping_changed');
 for(const p of[contract.bridgePin,channel.originalBridgePin,channel.serverPin,channel.clientPin,channel.loaderPin,channel.sourceConfigPin,channel.activationPin])pinned(p);
 demand(resolve(channel.activationPin.path)===activation,'persistent_guard_activation_path');
 const a=JSON.parse(pinned(channel.activationPin).toString());demand(resolve(a.sourceLoaderPin.path)===resolve(channel.sourceConfigPin.path)&&a.sourceLoaderPin.bytes===channel.sourceConfigPin.bytes&&a.sourceLoaderPin.sha256===channel.sourceConfigPin.sha256,'persistent_guard_current_config_binding');
 const e=JSON.parse(pinned(channel.sourceConfigPin).toString()),c=e.config,key=pinned(c.authorityPublicPin);
 demand(sha(key)==='ed4e7676d5c78e04d328dbca6ff1666a496ef6d2f2e213925dc870384983ca98'&&e.protocol==='bench-signed-financial-source-config-v1'&&verify(null,Buffer.from(JSON.stringify(c)),key,Buffer.from(e.signature,'base64')),'persistent_guard_signed_config');
 demand(c.financialBudgetMode==='unlimited'&&c.monetaryCeilings===null&&sha(pinned(c.financialAuthorityPin))==='ca25d98815cf1d7c9a3a30e50f3d84962520dd57227c777fce619b71176d665b'&&sha(pinned(c.providerProbeHumanAuthorityPin))==='430a105d94afce428ddd4fa9e5d31b67589e91a22b84aecc665ebe3ef686d48e'&&c.providerProbeOnly===true,'persistent_guard_original_authority');
 for(const p of c.sourcePins)pinned(p);for(const a of c.moduleAliases??[]){pinned(a.fromPin);pinned(a.toPin)}
 return a;
}
pinned(contract.bunPin);fullSources();
const loader=await import(pathToFileURL(channel.loaderPin.path).href);loader.installUnlimitedFinancialLoader(channel.sourceConfigPin.path);
const {actualPin}=await import(pathToFileURL(join(root,'scripts/benchmark-repair/paid-resource-proof-v2.ts')).href),{verifyAdoptedActivation}=await import(pathToFileURL(join(root,'scripts/bench-runner/unlimited-readonly-guard-retry.ts')).href),{processIncarnation}=await import(pathToFileURL(join(root,'scripts/benchmark-campaign/full-f/novaeve_formal_v1/broker/process-incarnation-v70.ts')).href);
const parentPid=process.ppid,parentIncarnation=processIncarnation(parentPid),seenNonces=new Set<string>();let sequence=0;
function requestBinding(r:any){
 const {auth,...body}=r;const mac=createHmac('sha256',secret).update(JSON.stringify(body)).digest();demand(typeof auth==='string'&&/^[a-f0-9]{64}$/.test(auth)&&timingSafeEqual(mac,Buffer.from(auth,'hex')),'persistent_guard_request_auth');
 demand(body.protocol==='bench-persistent-readonly-guard-request-v1'&&body.op==='verify'&&body.sequence===sequence+1&&Number.isSafeInteger(body.sequence)&&body.sequence<=65536,'persistent_guard_sequence');
 demand(typeof body.nonce==='string'&&/^[a-f0-9]{32}$/.test(body.nonce)&&!seenNonces.has(body.nonce),'persistent_guard_fresh_nonce');
 demand(body.callerPid===parentPid&&body.callerIncarnation===parentIncarnation&&processIncarnation(parentPid)===parentIncarnation,'persistent_guard_parent_identity');
 demand(body.mappingSha256===mappingSha&&resolve(body.activationPath)===activation,'persistent_guard_request_source');
 demand(Number.isSafeInteger(body.deadlineUnixMs)&&Date.now()<body.deadlineUnixMs&&body.deadlineUnixMs-Date.now()<=15000,'persistent_guard_request_expired');
 sequence=body.sequence;seenNonces.add(body.nonce);return body;
}
console.log(JSON.stringify({protocol:'bench-persistent-readonly-guard-ready-v1',pid:process.pid,incarnation:processIncarnation(process.pid),parentPid,parentIncarnation,mappingSha256:mappingSha,modelCalls:0}));
for await(const line of createInterface({input:process.stdin,crlfDelay:Infinity})){
 if(Buffer.byteLength(line)>16384)throw Error('persistent_guard_request_size');
 let r:any,b:any;const start=performance.now();
 try{
  r=JSON.parse(line);b=requestBinding(r);const beforeSources=performance.now(),a=fullSources(),afterSources=performance.now();
  // This is the unchanged original verifier, including fresh 5s reads and timeout-only retry.
  const result=await verifyAdoptedActivation(activation),h=result.health,afterOriginal=performance.now();
  demand(h.localMock===false&&h.atUtc&&Date.now()-Date.parse(h.atUtc)>=0&&Date.now()-Date.parse(h.atUtc)<=30000,'fresh_real_broker_snapshot_required');
  demand(Date.now()<b.deadlineUnixMs&&processIncarnation(parentPid)===parentIncarnation,'persistent_guard_request_expired');
  const token=process.env.NOVAEVE_RESOURCE_TOKEN,ownerMatches=(r:any)=>{try{return !r.adoptedOrphanHold&&!r.inheritedResourceHold&&r.ownerIncarnation===processIncarnation(r.pid)}catch{return false}};
  const value={protocol:'novaeve-redacted-python-consumer-bridge-v81',checkedAtUtc:new Date().toISOString(),activationPin:actualPin(activation),controlPin:a.controlPin,brokerPid:h.pid,brokerRunId:h.runId,endpoint:result.connection.endpoint,healthy:true,adoption:h.adoption,allocation:h.allocation,financialBudgetMode:'unlimited',monetaryCeilings:null,financialAuthorityPin:a.financialPolicy.financialAuthorityPin,availableResourceSlots:h.availableResourceSlots,resourceSlots:h.resourceSlots.map((r:any)=>({kind:r.kind,slug:r.slug,pid:r.pid,slots:r.slots,memoryMb:r.memoryMb,plannedGrowthBytes:r.plannedGrowthBytes,adoptedOrphanHold:r.adoptedOrphanHold??false,inheritedResourceHold:r.inheritedResourceHold??false,ownerIncarnation:r.ownerIncarnation??null,ownerIncarnationMatches:ownerMatches(r),resourceTokenSha256:typeof r.token==='string'?sha(Buffer.from(r.token)):null,tokenMatches:!!token&&r.token===token})),dockerHost:a.dockerHost,dataRoot:a.dataRoot,remoteDiskObservationPath:a.remoteDiskObservationPath,modelCalls:0,secretsPrinted:false};
  console.log(JSON.stringify({protocol:'bench-persistent-readonly-guard-response-v1',sequence:b.sequence,nonce:b.nonce,ok:true,value,elapsedMs:performance.now()-start,phaseMs:{fullSources:afterSources-beforeSources,originalVerifier:afterOriginal-afterSources,result:performance.now()-afterOriginal},freshOriginalVerification:true}));
 }catch(error:any){
  console.log(JSON.stringify({protocol:'bench-persistent-readonly-guard-response-v1',sequence:b?.sequence??r?.sequence??null,nonce:b?.nonce??r?.nonce??null,ok:false,error:{name:error?.name??'Error',message:String(error?.message??error)},elapsedMs:performance.now()-start}));
  // Failed request admission consumes no sequence; a verified request failure does.
 }
}
