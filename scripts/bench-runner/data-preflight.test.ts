import {test,expect} from 'bun:test';
import {mkdtempSync,writeFileSync,readFileSync} from 'node:fs';
import {tmpdir} from 'node:os';import {join,resolve} from 'node:path';
import {pin} from './manifest.ts';
import {canonicalFilePin,sameFilePin,validateDriverContractBinding,validatePythonMappingData,validateLauncherScope,validateCarrierFinancialJoin,validateSupplierRunId} from './data-preflight.ts';
const dir=mkdtempSync(join(tmpdir(),'bench-data-preflight-'));
const fixture=(n:string,s='print("neutral fixture")\n')=>{const p=join(dir,n);writeFileSync(p,s);return pin(p);};
const source=fixture('entry.py'),guard=fixture('guard.py'),contract=fixture('contract.json','{}');
const mapping=()=>({protocol:'bench-qualified-python-source-mapping-v1',originalStandPin:source,allowedEntryPins:[],guardPin:guard,modules:[]});
const base=()=>({adapterConfig:{driverContract:{ownedLease:true,beforeJournal:true,beforeForward:true,originalBudget:true,pin:contract}},provenance:{sourcePins:[source,contract],contractPins:[contract]}} as any);
test('original broker runId guard rejects task-name insertion and wrong bench',()=>{
 const a={runId:'repair-2026-10-13T14-36-00-486Z'};
 expect(()=>validateSupplierRunId(a.runId+'-13-1792079519',a,'skillsbench')).not.toThrow();
 expect(()=>validateSupplierRunId('repair-enterprise-1792079519',a,'skillsbench')).toThrow('invalid_bench_run_id');
 expect(()=>validateSupplierRunId(a.runId+'-14-1792079519',a,'skillsbench')).toThrow('invalid_bench_run_id');
});
test('actual adapter pre-execute contract membership rejects source-only contract',()=>{
 const m=base();expect(()=>validateDriverContractBinding(m)).not.toThrow();m.provenance.contractPins=[];
 expect(()=>validateDriverContractBinding(m)).toThrow('driver_contract_pin_required');
});
test('canonical new pin does not depend on slash spelling or object key insertion order',()=>{
 const a=canonicalFilePin(source.path),b={sha256:a.sha256,bytes:a.bytes,path:resolve(a.path).replaceAll('\\','/')};
 expect(sameFilePin(a,b)).toBe(true);expect(JSON.stringify(a)===JSON.stringify(b)).toBe(false);
 expect(sameFilePin(a,{...b,sha256:'0'.repeat(64)})).toBe(false);
});
test('duplicate originalStandPin/allowedEntryPins rejected before guard import',()=>{
 const c=mapping();expect(()=>validatePythonMappingData(c,source)).not.toThrow();c.allowedEntryPins=[source] as never[];
 expect(()=>validatePythonMappingData(c,source)).toThrow('child_entry_not_approved');
 const cp=join(dir,'duplicate-mapping.json');writeFileSync(cp,JSON.stringify(c));
 const result=Bun.spawnSync(['D:/ProgramData/anaconda3/python.exe',join(import.meta.dir,'python_child_entry.py'),'--config',cp,'--original-script',source.path],{stdout:'pipe',stderr:'pipe'});
 expect(result.exitCode).not.toBe(0);expect(result.stderr.toString()).toContain('child_entry_not_approved');
});
test('Python mapping sequential anchors and names cannot silently shadow',()=>{
 const c:any=mapping();c.modules=[{name:'example',pin:source,exactReplacements:[{from:'print("neutral fixture")',to:'print("new fixture")'}]}];
 expect(()=>validatePythonMappingData(c)).not.toThrow();c.modules[0].exactReplacements[0].from='missing literal';
 expect(()=>validatePythonMappingData(c)).toThrow('child_mapping_anchor_not_unique');c.modules=[{name:'x',pin:source},{name:'x',pin:guard}];
 expect(()=>validatePythonMappingData(c)).toThrow('duplicate_python_module_name');
});
test('launcher Python executable must be in exact source scope, not only contract scope',()=>{
 const python=fixture('python.exe','fixture executable bytes'),bootstrap=fixture('bootstrap.py'),config=fixture('mapping.json','{}'),activation=fixture('activation.json','{}');
 const stand={pythonPin:python,standEntryPin:source,pythonBootstrap:{bootstrapPin:bootstrap,configPin:config}},m=base();
 m.provenance.sourcePins=[source,bootstrap,config,activation];m.provenance.contractPins.push(python);
 expect(()=>validateLauncherScope(m,stand,activation)).toThrow('explicit_launcher_pin_not_in_scope');m.provenance.sourcePins.push(python);
 expect(()=>validateLauncherScope(m,stand,activation)).not.toThrow();
});
test('current authentic child config is joined before calling historyAdmission',()=>{
 const root=resolve(import.meta.dir,'../../docs/repair-2026-10-10/full-f-rerun/novaeve-formal-20261013/coordinator/universal-runner/provider-switch-preparation/signed-fireworks-probe-preparation-v1');
 const current=pin(join(root,'source-loader.task-route-v3.infra-signed.json'));
 const c:any={adapterConfig:{financialSourceConfigPin:current},provenance:{sourcePins:[current],contractPins:[]}};
 expect(()=>validateCarrierFinancialJoin(c,current)).not.toThrow();
 c.adapterConfig.financialSourceConfigPin=contract;expect(()=>validateCarrierFinancialJoin(c,current)).toThrow('carrier_financial_source_config_join');
 c.adapterConfig.financialSourceConfigPin=current;c.provenance.sourcePins=[];expect(()=>validateCarrierFinancialJoin(c,current)).toThrow('carrier_financial_config_not_in_scope');
});
