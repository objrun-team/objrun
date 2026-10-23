/** Real public APT transport probe from a pristine owned Docker namespace. */
import {spawnSync} from 'node:child_process';
import {strict as assert} from 'node:assert';
import {mkdirSync,readFileSync,writeFileSync} from 'node:fs';
import {join,resolve} from 'node:path';
import {actualPin,verifyPin} from '../../../repair-2026-10-08/paid-resource-proof-v2.ts';
import {acquirePreparationResource} from './preparation_resource.ts';
const root=resolve(import.meta.dir,'../../../..'),home=join(root,'docs/repair-2026-10-10/full-f-rerun/skillsbench'),read=(p:string)=>JSON.parse(readFileSync(p,'utf8'));
const output=join(home,'apt-docker-transport-controls',crypto.randomUUID());mkdirSync(output,{recursive:true});
const servicePin=read(join(home,'apt-transport-service/latest.json')).servicePin;verifyPin(servicePin);const service=read(servicePin.path);verifyPin(service.sourcePin);
const bp=read(join(home,'environment-preparation/3d-scan-calc/latest.json')).builtImagesPin;verifyPin(bp);const image=read(bp.path).candidateImageId;
let resource:Awaited<ReturnType<typeof acquirePreparationResource>>|undefined,cid:string|undefined;const commands:any[]=[];
const result:any={protocol:'skillsbench-real-docker-apt-transport-control-v1',verified:false,modelCalls:0,scoreCertificate:false,servicePin,builtImagesPin:bp,sourcePin:actualPin(import.meta.path)};
function command(argv:string[]){const r=spawnSync('D:/Program/resources/bin/docker.exe',['-H','npipe:////./pipe/dockerDesktopLinuxEngine',...argv],{windowsHide:true,encoding:'utf8',timeout:30000,maxBuffer:1024**2});const prefix=join(output,'command-'+commands.length);writeFileSync(prefix+'.stdout',r.stdout??'');writeFileSync(prefix+'.stderr',r.stderr??'');commands.push({argv,exitCode:r.status,stdoutPin:actualPin(prefix+'.stdout'),stderrPin:actualPin(prefix+'.stderr')});assert.equal(r.status,0,'owned_docker_probe_failed');return r.stdout;}
try{
 resource=await acquirePreparationResource(root);
 const python="import hashlib,json,urllib.request;u='http://deb.debian.org/debian/pool/main/n/npth/libnpth0t64_1.8-3_amd64.deb';r=urllib.request.urlopen(u,timeout=20);body=r.read(2*1024**2+1);assert len(body)<=2*1024**2 and len(body)==int(r.headers['Content-Length']);b=body[:512];print(json.dumps({'status':r.status,'prefixSha256':hashlib.sha256(b).hexdigest(),'archivePrefix':b.startswith(b'!<arch>\\n'),'bytes':len(b),'fullBodyBytes':len(body),'fullBodySha256':hashlib.sha256(body).hexdigest(),'bodyComplete':True}));r.close()";
 cid=command(['create','--read-only','--network','bridge','--cap-drop','ALL','--security-opt','no-new-privileges','--memory','256m','--memory-swap','256m','--cpus','0.25','--label','objrun.skb.role=apt-transport-probe','--label','objrun.skb.nonce='+output.split(/[\\/]/).at(-1),'-e','http_proxy=http://host.docker.internal:'+service.port,'--entrypoint','python3',image,'-I','-B','-c',python]).trim();assert(/^[0-9a-f]{64}$/.test(cid));
 const inspect=JSON.parse(command(['inspect',cid]))[0];assert.equal(inspect.Image,image);assert(inspect.HostConfig.ReadonlyRootfs&&!inspect.HostConfig.Binds?.length&&!inspect.HostConfig.Mounts?.length);
 const observed=JSON.parse(command(['start','-a',cid]));assert.equal(observed.status,200);assert.equal(observed.bytes,512);assert.equal(observed.archivePrefix,true);assert.equal(observed.bodyComplete,true);assert(observed.fullBodyBytes>=512);assert.equal(observed.prefixSha256,'b5eddca34f6626c5626284512cd95c72a567b033491e4e27ee715f0caf581f17');result.verified=true;result.observed=observed;
}catch(error){result.failure={detail:String(error)};result.resourceQueued=!resource;process.exitCode=2;}
finally{
 if(cid){try{command(['rm','-f',cid]);cid=undefined;}catch(error){result.cleanupFailure=String(error);result.verified=false;}}
 result.ownedContainersRemaining=cid?1:0;result.commands=commands;if(resource)await resource.release();
 const path=join(output,'result.json');writeFileSync(path,JSON.stringify(result,null,2)+'\n');writeFileSync(join(home,'apt-docker-transport-controls/latest.json'),JSON.stringify({resultPin:actualPin(path)})+'\n');console.log(JSON.stringify({resultPin:actualPin(path),verified:result.verified,resourceQueued:result.resourceQueued,failure:result.failure,modelCalls:0}));
}
