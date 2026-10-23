import {test,expect} from 'bun:test';import {mkdtempSync,writeFileSync,readFileSync} from 'node:fs';import {tmpdir} from 'node:os';import {join,resolve} from 'node:path';import {spawnSync} from 'node:child_process';
import {pin} from './manifest.ts';import {validateNativeCheckedPin,validateNativeStageData,validateOriginalCatalogData} from './data-preflight-composed-v3.ts';
const dir=mkdtempSync(join(tmpdir(),'native-stage-data-')),file=(name:string)=>{const p=join(dir,name);writeFileSync(p,'No-Bench read-only fixture metadata.');return pin(p);},stand=file('stand.txt'),entry=file('entry.txt'),mapping=file('mapping.txt'),input=file('input.txt');
const job=()=>({protocol:'bench-pinned-native-stage-v1',modelCalls:0,mappingPin:mapping,entryPin:entry,inputPins:[input],inputFiles:[{pin:input,relative:'data/input.txt'}]});
test('original allowedEntryPins grant permission; entryMappings alone do not',()=>{
 expect(()=>validateNativeStageData(job(),{originalStandPin:stand,allowedEntryPins:[entry],entryMappings:[{pin:entry}]})).not.toThrow();
 expect(()=>validateNativeStageData(job(),{originalStandPin:stand,entryMappings:[{pin:entry}]})).toThrow('native_stage_entry_not_in_original_allowlist');
});
test('dictionary field order is irrelevant, but extra fields and noncanonical path spellings reject',()=>{
 expect(()=>validateNativeCheckedPin({sha256:entry.sha256,bytes:entry.bytes,path:entry.path})).not.toThrow();
 expect(()=>validateNativeCheckedPin({...entry,extra:true}as any)).toThrow('native_stage_pin_changed');
 if(process.platform==='win32')expect(()=>validateNativeCheckedPin({...entry,path:entry.path.replaceAll('\\','/')})).toThrow('native_stage_pin_changed');
});
test('new input paths must obey the original input jail',()=>{
 for(const relative of['../outside','/absolute','nested/../../escape','..\\outside'])expect(()=>validateNativeStageData({...job(),inputFiles:[{pin:input,relative}]},{originalStandPin:stand,allowedEntryPins:[entry]})).toThrow('native_stage_input_relative_escape');
});
test('actual original Python pin and dictionary membership produce the same positive and negative',()=>{
 const code="import sys,json;sys.path.insert(0,sys.argv[1]);from native_process import pin;x=json.loads(sys.argv[2]);a=pin(x['entryPin']['path']);assert a==x['entryPin'];assert x['entryPin'] not in [x['mapping']['originalStandPin'],*x['mapping'].get('allowedEntryPins',[])];assert x['entryPin'] in [x['mapping']['originalStandPin'],x['entryPin']];print('original_python_pin_and_membership_passed')";
 const v=spawnSync('D:/ProgramData/anaconda3/python.exe',['-c',code,import.meta.dir,JSON.stringify({entryPin:entry,mapping:{originalStandPin:stand,entryMappings:[{pin:entry}]}})],{encoding:'utf8',windowsHide:true});expect(v.status).toBe(0);expect(v.stdout).toContain('original_python_pin_and_membership_passed');
});
test('accepted catalog helper is called with the actual original metadata and rejects another task',async()=>{
 const owner=resolve(import.meta.dir,'../../docs/repair-2026-10-10/full-f-rerun/novaeve-formal-20261013/coordinator/universal-runner/parallel-owners-20261015/sb_python_kernel'),base=join(owner,'exoplanet-detection-period/formal-bundle-92638df3'),input=JSON.parse(readFileSync(join(base,'original-task-input.json'),'utf8')),manifest=JSON.parse(readFileSync(join(base,'manifest.json'),'utf8'));
 const result=await validateOriginalCatalogData(input,manifest);expect(result.passed).toBe(true);expect(result.models).toBe(0);
 await expect(validateOriginalCatalogData({...input,taskId:'different-metadata-task'},manifest)).rejects.toThrow('original_catalog_task_manifest_join');
});
