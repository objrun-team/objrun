import {gunzipSync} from 'node:zlib';
import {createHash} from 'node:crypto';
/** Hardlink only attested immutable original image pool parts. Never candidates,
 * grader/cash records, or editable code. Preserve the existing custody schema.
 */
import {copyFileSync,existsSync,mkdirSync,readFileSync,linkSync,lstatSync,realpathSync} from 'node:fs';
import {basename,dirname,join,resolve} from 'node:path';
import {actualPin,demand,jsonPin,same,verifyPin,type Pin} from '../../../benchmark-repair/paid-resource-proof-v2.ts';
import {durable} from '../../../terminal-bench-repair/tb12-v2/paid_admission.ts';
export {executedSources} from '../../../terminal-bench-repair/tb12-v2/freeze_sources.ts';
const root=resolve(import.meta.dir,'../../../..'),home=join(root,'docs/repair-2026-10-10/full-f-rerun/terminal-bench');
const poolBase=join(home,'private-context-v1/immutable-official-image-gzip-parts');
export function immutableImagePartEligible(pin:Pin):boolean{
 const path=resolve(pin.path),parent=dirname(path);
 if(dirname(parent)!==poolBase||!/^[a-f0-9]{64}$/.test(basename(parent))||!/^part-[0-9]{4}-[a-f0-9]{64}\.bin\.gz$/.test(basename(path)))return false;
 demand(!lstatSync(path).isSymbolicLink()&&realpathSync(path)===path,'image_pool_scope');
 const record=JSON.parse(readFileSync(join(parent,'pool-manifest.json'),'utf8'));
 demand(record.complete===true&&record.purpose==='immutable_original_official_image_export_gzip_parts'&&record.concatenatedSha256===basename(parent),'image_pool_purpose');
 const nativePin=record.originalNativeImportProofPin;verifyPin(nativePin);
 demand(resolve(nativePin.path)===join(home,'private-context-v1/official-build-pov-ray-blobs/import-proof.json'),'image_pool_native_proof_scope');
 const native=jsonPin(nativePin);
 demand(native.complete&&native.actualDockerImportValidated&&native.actualConfigSha256MatchesSource&&native.actualRootFSDiffIdsMatchSource&&native.actualPlatformAndExecutionConfigMatchSource,'image_pool_native_identity');
 demand(native.exportedDockerArchivePin.sha256===record.concatenatedSha256&&native.exportedDockerArchivePin.bytes===record.concatenatedBytes,'image_pool_original_export');
 demand(record.orderedPartPins.some((p:Pin)=>same(p,pin))&&pin.bytes<=128*1024**2,'image_pool_part_attestation');
 verifyPin(pin);
 const decoded=record.decodedPartProofs.find((row:any)=>row.compressedPartSha256===pin.sha256);
 demand(decoded&&decoded.decodedBytes<=64*1024**2,'image_pool_decoded_bound');
 const raw=gunzipSync(readFileSync(path),{maxOutputLength:64*1024**2});
 demand(raw.length===decoded.decodedBytes&&createHash('sha256').update(raw).digest('hex')===decoded.decodedSha256,'image_pool_decoded_sha');
 return true;
}
export function snapshotSources(output:string,pins:readonly Pin[]){
 const folder=join(output,'source-snapshots');mkdirSync(folder,{recursive:true});const links:any[]=[];
 const files=pins.map(originalPin=>{
  verifyPin(originalPin);const path=join(folder,originalPin.sha256+'-'+basename(originalPin.path));
  if(!existsSync(path)){
   if(immutableImagePartEligible(originalPin)){linkSync(originalPin.path,path);links.push({originalPin,path,kind:'immutable_image_hardlink'});}
   else copyFileSync(originalPin.path,path);
  }
  const snapshotPin=actualPin(path);demand(snapshotPin.sha256===originalPin.sha256,'tb12_source_snapshot_changed');return{originalPin,snapshotPin};
 });
 const target=join(folder,'manifest.json');
 if(existsSync(target)){const pin=actualPin(target);demand(same(jsonPin(pin).files,files),'tb12_source_snapshot_reuse_changed');return pin;}
 durable(join(folder,'immutable-image-custody.json'),{protocol:'terminal-immutable-original-image-custody-v1',links,mutableEvidenceHardlinked:false});
 return durable(target,{protocol:'tb12-matching-executed-source-snapshots-v1',files});
}
