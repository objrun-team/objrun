import {generateKeyPairSync,sign,verify} from 'node:crypto';
import {readFileSync,writeFileSync,existsSync,mkdirSync} from 'node:fs';
import {join,resolve} from 'node:path';
export const base=join(resolve(import.meta.dir,'../../../../..'),'docs/repair-2026-10-10/full-f-rerun/novaeve-formal-20261013/coordinator');
export const authorityPath=join(base,'review-authority.public.pem');
export function verifyRootEntry(envelope:any,publicKey=readFileSync(authorityPath,'utf8')){
 if(envelope.protocol!=='novaeve-root-signed-entry-v4'||!envelope.entry||typeof envelope.signature!=='string'||!verify(null,Buffer.from(JSON.stringify(envelope.entry)),publicKey,Buffer.from(envelope.signature,'base64')))throw Error('root_review_signature_invalid');
 if(envelope.entry.coordinatorReviewed!==true)throw Error('root_review_required');return envelope.entry;
}
if(import.meta.main){
 mkdirSync(base,{recursive:true});const mode=process.argv[2],privatePath=join(base,'review-authority.private.pem');
 if(mode==='--init'){
  if(existsSync(privatePath)||existsSync(authorityPath))throw Error('review_authority_already_exists');
  const pair=generateKeyPairSync('ed25519',{publicKeyEncoding:{type:'spki',format:'pem'},privateKeyEncoding:{type:'pkcs8',format:'pem'}});
  writeFileSync(privatePath,pair.privateKey,{flag:'wx',mode:0o600});writeFileSync(authorityPath,pair.publicKey,{flag:'wx',mode:0o600});
  console.log(JSON.stringify({created:true,publicKeyPath:authorityPath,secretsPrinted:false}));
 }else if(mode==='--sign'){
  const draft=JSON.parse(readFileSync(resolve(process.argv[3]),'utf8'));if(draft.blockReasons?.length||!['formal','preparation'].includes(draft.queueClass)||!draft.nonce)throw Error('root_must_review_concrete_unblocked_entry');
  const entry={...draft,coordinatorReviewed:true,phase:draft.queueClass==='formal'?'ready':'preparation_approved'};
  const signature=sign(null,Buffer.from(JSON.stringify(entry)),readFileSync(privatePath,'utf8')).toString('base64');
  const directory=join(base,'inbox',entry.queueClass);mkdirSync(directory,{recursive:true});
  const path=join(directory,entry.nonce+'.json');writeFileSync(path,JSON.stringify({protocol:'novaeve-root-signed-entry-v4',entry,signature},null,2)+'\n',{flag:'wx',mode:0o600});
  console.log(JSON.stringify({signed:true,path,taskId:entry.taskId,queueClass:entry.queueClass}));
 }else throw Error('root uses --init or --sign reviewedDraftPath');
}
