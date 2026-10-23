import { copyFileSync, existsSync, mkdirSync, readdirSync, readFileSync } from "node:fs";
import { basename, dirname, join, resolve } from "node:path";
import { actualPin, demand, jsonPin, same, verifyPin, type Pin } from "../../benchmark-repair/paid-resource-proof-v2.ts";
import { durable } from "./paid_admission.ts";
const ROOT=resolve(import.meta.dir,"../../..");
export function executedSources():Pin[] {
  const found=new Set<string>();
  const add=(path:string)=>{
    path=resolve(path);if(found.has(path))return;demand(existsSync(path),"tb12_source_dependency_missing");found.add(path);
    if(path.endsWith(".ts"))for(const match of readFileSync(path,"utf8").matchAll(/(?:from\s*|import\s*\(|import\s*)["'](\.[^"']+)["']/g)) {
      const source=resolve(dirname(path),match[1]);
      const target=[source,source+".ts",join(source,"index.ts")].find(existsSync);
      demand(target,"tb12_transitive_source_missing");add(target!);
    }
  };
  for(const entry of readdirSync(import.meta.dir))if(/\.(ts|py)$/.test(entry))add(join(import.meta.dir,entry));
  const walk=(folder:string)=>{for(const entry of readdirSync(folder,{withFileTypes:true})) {
    if(entry.isDirectory())walk(join(folder,entry.name));else if(entry.name.endsWith(".ts"))add(join(folder,entry.name));
  }};walk(join(ROOT,"app/src"));
  for(const name of ["isolated_verifier.py","nginx_client.py"])add(join(ROOT,"examples/benchmark/terminal-bench",name));
  return [...found].sort().map(actualPin);
}
export function snapshotSources(output:string,pins:readonly Pin[]) {
  const folder=join(output,"source-snapshots");mkdirSync(folder,{recursive:true});
  const files=pins.map(originalPin=>{
    verifyPin(originalPin);const path=join(folder,originalPin.sha256+"-"+basename(originalPin.path));
    if(!existsSync(path))copyFileSync(originalPin.path,path);const snapshotPin=actualPin(path);
    demand(snapshotPin.sha256===originalPin.sha256,"tb12_source_snapshot_changed");return{originalPin,snapshotPin};
  });
  const target=join(folder,"manifest.json");
  if(existsSync(target)){const pin=actualPin(target);demand(same(jsonPin(pin).files,files),"tb12_source_snapshot_reuse_changed");return pin;}
  return durable(target,{protocol:"tb12-matching-executed-source-snapshots-v1",files});
}
