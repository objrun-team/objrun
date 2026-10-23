import fs from 'node:fs';import path from 'node:path';import zlib from 'node:zlib';import crypto from 'node:crypto';
const [archive,root,sha,bytes]=process.argv.slice(2);if(!archive||!root.startsWith('/tmp/objrun-tensor-framework-')||!sha||fs.existsSync(root))throw Error('fresh owned framework prefix required');
const hash=crypto.createHash('sha256');for await(const b of fs.createReadStream(archive))hash.update(b);if(hash.digest('hex')!==sha||fs.statSync(archive).size!==Number(bytes))throw Error('archive pin mismatch');
fs.mkdirSync(root,{mode:0o755});let buffer=Buffer.alloc(0),entry=null,left=0,padding=0,longName=null,longLink=null,count=0;const decoder=b=>b.toString('utf8').replace(/\0.*$/s,'');
function resolve(name){if(!name||name.startsWith('/')||name.includes('\\')||name.split('/').includes('..'))throw Error('unsafe member '+name);const dest=path.resolve(root,name);if(dest!==root&&!dest.startsWith(root+'/'))throw Error('escape');return dest;}
function parents(dest){let cur=path.dirname(dest);while(cur!==root){if(fs.existsSync(cur)&&fs.lstatSync(cur).isSymbolicLink())throw Error('symlink parent');cur=path.dirname(cur);}fs.mkdirSync(path.dirname(dest),{recursive:true});}
function finish(){if(entry.fd!==undefined)fs.closeSync(entry.fd);if(entry.special==='L')longName=decoder(Buffer.concat(entry.chunks));if(entry.special==='K')longLink=decoder(Buffer.concat(entry.chunks));entry=null;}
for await(const chunk of fs.createReadStream(archive).pipe(zlib.createGunzip())){
 buffer=Buffer.concat([buffer,chunk]);
 while(true){
  if(left){if(!buffer.length)break;const n=Math.min(left,buffer.length),part=buffer.subarray(0,n);if(entry.fd!==undefined)fs.writeSync(entry.fd,part);else if(entry.chunks)entry.chunks.push(Buffer.from(part));buffer=buffer.subarray(n);left-=n;if(!left)finish();continue;}
  if(padding){const n=Math.min(padding,buffer.length);padding-=n;buffer=buffer.subarray(n);if(padding||!buffer.length)break;}
  if(buffer.length<512)break;const h=buffer.subarray(0,512);buffer=buffer.subarray(512);if(h.every(x=>x===0))continue;
  let sum=0;for(let i=0;i<512;i++)sum+=i>=148&&i<156?32:h[i];if(sum!==parseInt(decoder(h.subarray(148,156)).trim(),8))throw Error('tar checksum');
  const type=String.fromCharCode(h[156]||48),size=parseInt(decoder(h.subarray(124,136)).trim()||'0',8),mode=parseInt(decoder(h.subarray(100,108)).trim()||'644',8)&0o777;if(!Number.isSafeInteger(size)||size<0)throw Error('size');
  entry={};if(type==='L'||type==='K'){if(size>16384)throw Error('long metadata');entry={special:type,chunks:[]};}
  else{let name=longName??decoder(h.subarray(0,100)),link=longLink??decoder(h.subarray(157,257));longName=longLink=null;const dest=resolve(name);parents(dest);
   if(type==='5'){fs.mkdirSync(dest,{recursive:true,mode});}
   else if(type==='0'){entry.fd=fs.openSync(dest,'wx',mode);}
   else if(type==='2'){const target=path.resolve(path.dirname(dest),link);if(link.startsWith('/')||link.includes('\\')||!(target===root||target.startsWith(root+'/')))throw Error('link escape');fs.symlinkSync(link,dest);}
   else if(type==='1'){const target=resolve(link);if(!fs.lstatSync(target).isFile()||fs.lstatSync(target).isSymbolicLink())throw Error('hardlink source');fs.linkSync(target,dest);}
   else throw Error('unsupported member '+type);count++;
  }left=size;padding=(512-size%512)%512;if(!left)finish();
 }
}
if(left||padding||buffer.some(x=>x!==0))throw Error('truncated archive');console.log(JSON.stringify({complete:true,memberCount:count,archiveSha256:sha,archiveBytes:Number(bytes),prefix:root,safeExtraction:true}));
