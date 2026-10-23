import {expect,test} from 'bun:test';
import {mkdirSync,readFileSync,symlinkSync,writeFileSync} from 'node:fs';
import {randomBytes} from 'node:crypto';
import {execFileSync} from 'node:child_process';
import {join,resolve} from 'node:path';
import {actualPin} from '../scripts/repair-2026-10-08/paid-resource-proof-v2.ts';
import {loadNativePython} from '../scripts/repair-2026-10-08/skb-jpg-native-python.ts';
import {createJpgOwnedFlushFixture} from '../scripts/repair-2026-10-08/skb-jpg-journal-campaign.ts';
const ROOT=resolve(import.meta.dir,'..'),AUDIT=join(ROOT,'scripts/repair-2026-10-08/audit-jpg-journal-campaign.py');
test('new Bun source flushes only its own new regular output with r+ and preserves actual bytes/SHA',()=>{
  const scope=createJpgOwnedFlushFixture(),path=join(scope.root,'owned.txt'),raw=Buffer.from('harmless owned fixture\n');writeFileSync(path,raw);const before=actualPin(path),after=scope.flush(path);
  expect(before.sha256).toBe(after.sha256);expect(before.bytes).toBe(after.bytes);expect(readFileSync(path).equals(raw)).toBe(true);writeFileSync(join(scope.root,'result.json'),JSON.stringify({before,after,sourcePin:actualPin(join(ROOT,'scripts/repair-2026-10-08/skb-jpg-journal-campaign.ts')),fsyncReturned:true,modelCalls:0,DockerOperations:0})+'\n');scope.close();
});
test('Bun rejects original source, directory and actual junction before acquiring write access',()=>{
  const scope=createJpgOwnedFlushFixture(),source=actualPin(AUDIT),target=join(scope.root,'target');mkdirSync(target);const file=join(target,'owned.txt');writeFileSync(file,'public own fixture');const link=join(scope.root,'junction');symlinkSync(target,link,'junction');
  expect(()=>scope.flush(AUDIT)).toThrow('jpg_flush_not_self_owned');expect(()=>scope.flush(target)).toThrow('jpg_flush_regular_file');expect(()=>scope.flush(join(link,'owned.txt'))).toThrow('jpg_flush_reparse');expect(actualPin(AUDIT).sha256).toBe(source.sha256);scope.close();
});
const program=String.raw`import importlib.util,json,sys,subprocess
from pathlib import Path
s=importlib.util.spec_from_file_location('current_flush',sys.argv[1]);m=importlib.util.module_from_spec(s);s.loader.exec_module(m)
root=m.create_owned_flush_fixture();path=root/'own.txt';data=b'harmless own fixture\n';path.write_bytes(data);before=m.pin(path);count=m.flush_tree(root);after=m.pin(path)
outside=m.pin(Path(sys.argv[1]));foreign=None
try:m.flush_tree(Path(sys.argv[1]).parent)
except Exception as e:foreign=str(e)
target=root/'target';target.mkdir();(target/'own.txt').write_bytes(data);link=root/'junction'
r=subprocess.run([sys.argv[2],'-e',"import{symlinkSync}from'node:fs';symlinkSync(process.argv[1],process.argv[2],'junction')",str(target),str(link)],capture_output=True)
if r.returncode:raise RuntimeError('bounded F junction fixture could not be created')
reparse=None
try:m.flush_tree(root)
except Exception as e:reparse=str(e)
result={'sourcePin':m.pin(Path(sys.argv[1])),'before':before,'after':after,'bytesUnchanged':path.read_bytes()==data,'fsyncReturnedCount':count,'foreignError':foreign,'junctionError':reparse,'outsideSourceUnchanged':m.pin(Path(sys.argv[1]))==outside,'modelCalls':0,'DockerOperations':0,'onlyFWrites':True}
m.save(root/'result.json',result);print(json.dumps(result))
`;
test('actual native Python source uses r+b fsync on own output, preserves SHA and rejects original/junction paths',()=>{
  const dir=join(ROOT,'.scratch/jpg-fsync-owned-controls','harness-'+randomBytes(8).toString('hex'));mkdirSync(dir,{recursive:true});const script=join(dir,'fixture.py');writeFileSync(script,program);
  const out=execFileSync(loadNativePython().executable,['-B','-X','utf8',script,AUDIT,process.execPath],{windowsHide:true,encoding:'utf8',timeout:20000}),value=JSON.parse(out);
  expect(value.fsyncReturnedCount).toBe(1);expect(value.before.sha256).toBe(value.after.sha256);expect(value.before.bytes).toBe(value.after.bytes);expect(value.bytesUnchanged).toBe(true);expect(value.foreignError).toBe('flush_not_self_owned');expect(value.junctionError).toBe('flush_reparse');expect(value.outsideSourceUnchanged).toBe(true);
});
