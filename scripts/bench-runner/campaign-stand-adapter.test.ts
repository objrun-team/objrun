import {test,expect} from 'bun:test';
import {mkdtempSync,writeFileSync,mkdirSync,readFileSync,readdirSync} from 'node:fs';
import {tmpdir} from 'node:os';import {join} from 'node:path';import {pathToFileURL} from 'node:url';
import {pin} from './manifest.ts';
import {prepareStandInjection,installStandInjection,type StandInjection} from './campaign-stand-adapter.ts';
import {injectedDriverSource,preserveModuleLocations} from './build-release.ts';
function fixture(){
 const dir=mkdtempSync(join(tmpdir(),'common-stand-'));const script=join(dir,'stand.py'),campaign=join(dir,'campaign.ts'),launcher=join(dir,'launcher.ts'),python=process.execPath;
 writeFileSync(script,'import json\nfrom helper import value\n');writeFileSync(join(dir,'helper.py'),'value=1\n');
 writeFileSync(launcher,'import { spawn } from "node:child_process";\nexport async function startStand(options:any){void options.script;const python='+JSON.stringify(python.replaceAll('\\','/'))+';const c=spawn(python,'+JSON.stringify(['-e','process.stderr.write("real failure");process.exit(3)'])+',{stdio:["ignore","pipe","pipe"]});await new Promise(r=>c.on("close",r));throw Error("original-startup-failed");}\n');
 writeFileSync(campaign,'import { startStand } from '+JSON.stringify(launcher.replaceAll('\\','/'))+';\nexport async function run(options:any){return startStand({script:join(import.meta.dir,"missing.py")});}\n');
 const observed=pin(join(import.meta.dir,'observed-spawn.ts'));
 const s:StandInjection={protocol:'bench-qualified-stand-injection-v1',campaignPin:pin(campaign),expectedExpression:'script:join(import.meta.dir,"missing.py")',standEntryPin:pin(script),launcherPin:pin(launcher),pythonPin:pin(python),observedSpawnPin:observed,launcherSpawnImport:'import { spawn } from "node:child_process";',dependencyPins:[],dependencyManifestPins:[],pythonPackages:{},pythonModules:{entry:pin(script),helper:pin(join(dir,'helper.py'))},standardLibraryModules:['json']};
 const m:any={provenance:{sourcePins:[s.campaignPin,s.standEntryPin,s.launcherPin,s.pythonPin,observed,...Object.values(s.pythonModules)]}};return {dir,s,m};
}
test('exact immutable campaign Stand injection rejects missing dependency, wrong hash and duplicate expression before effects',()=>{
 const {s,m}=fixture(),p=prepareStandInjection(m,s);expect(p.proof.replacement.count).toBe(1);expect(p.contents).toContain('script:options.standScriptPath');
 expect(()=>prepareStandInjection(m,{...s,pythonModules:{entry:s.standEntryPin}})).toThrow('local_python_import_not_exact:helper');
 expect(()=>prepareStandInjection(m,{...s,standEntryPin:{...s.standEntryPin,sha256:'0'.repeat(64)}})).toThrow();
 expect(()=>prepareStandInjection(m,{...s,expectedExpression:'script:join(import.meta.dir,"absent.py")'})).toThrow('stand_expression_must_match_exactly_once');
 expect(readFileSync(s.campaignPin.path,'utf8')).toContain(s.expectedExpression);
});
test('same prepared module executes through original startup failure and independently retains actual child exit/streams',async()=>{
 const {dir,s,m}=fixture(),p=prepareStandInjection(m,s),custody=join(dir,'custody');await installStandInjection(s,p,custody);
 const module=await import(pathToFileURL(s.campaignPin.path).href);await expect(module.run({standScriptPath:s.standEntryPin.path})).rejects.toThrow('original-startup-failed');
 const receipt=JSON.parse(readFileSync(join(custody,'1','close.json'),'utf8'));expect(receipt.exitCode).toBe(3);expect(receipt.closeObserved).toBe(true);expect(receipt.pid).toBeGreaterThan(0);expect(readFileSync(receipt.stderr.path,'utf8')).toBe('real failure');
 expect(readFileSync(s.campaignPin.path,'utf8')).toContain(s.expectedExpression);
});
test('common release delta requires exact anchors and never modifies original driver',()=>{
 const original=readFileSync(join(import.meta.dir,'terminal-driver.ts'),'utf8'),next=injectedDriverSource(original);expect(next).toContain('prepareStandInjection');expect(next).toContain('standScriptPath:d.standInjection.standEntryPin.path');expect(()=>injectedDriverSource('')).toThrow('release_anchor_not_unique');expect(readFileSync(join(import.meta.dir,'terminal-driver.ts'),'utf8')).toBe(original);
});
test('bundle module locations preserve source strings and comments',()=>{
 const source='const text="import.meta.dir"; // import.meta.url\nconst real=import.meta.url;';const out=preserveModuleLocations(source,'D:/original/source.ts');expect(out).toContain('text="import.meta.dir"');expect(out).toContain('// import.meta.url');expect(out).toContain('file:///D:/original/source.ts');
});
