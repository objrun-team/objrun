import json,sys,uuid,ctypes,subprocess,hashlib
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parent))
from prepare import HOME,public,save,utc
pointer=json.loads((HOME/'grader-controls/manufacturing-codebook-normalization/latest.json').read_bytes())['controlPin'];assert public.pin(Path(pointer['path']))==pointer
cold=json.loads(Path(pointer['path']).read_bytes());assert cold['controlsPassed'] and cold['ownedContainersRemaining']==0
target=Path(pointer['path']).parent/'command-012.stdout';command=json.loads(target.with_suffix('.json').read_bytes());assert command['directChildClosed'] and command['pipeReadersClosed'] and public.pin(target)==command['stdoutPin']
c=json.loads((HOME.parent/'control.json').read_bytes());h=json.loads(Path(c['broker']['healthPath']).read_bytes());assert not any(r['slug']=='skillsbench' for r in h['resourceSlots'])
assert target.resolve().is_relative_to(HOME.resolve()) and target.drive.upper()=='F:'
def allocated(p):
 hi=ctypes.c_ulong();lo=ctypes.windll.kernel32.GetCompressedFileSizeW('\\\\?\\'+str(p),ctypes.byref(hi));assert lo!=0xffffffff;return hi.value*2**32+(lo&0xffffffff)
pin=public.pin(target);st=target.stat();before=allocated(target)
p=subprocess.run(['compact.exe','/C','/I','/Q',str(target)],capture_output=True)
assert p.returncode==0 and public.pin(target)==pin and target.stat().st_ino==st.st_ino
proof={'atUtc':utc(),'originalColdControlPin':pointer,'retainedRawOracleTarPin':pin,'allocatedBefore':before,'allocatedAfter':allocated(target),'actualAllocatedBytesSaved':before-allocated(target),'fileId':st.st_ino,'models':0,'dockerCalls':0,'pathsBytesShaIdsPreserved':True,'foreignUserAssetsTouched':False}
receipt=save(HOME/'closed-codebook-oracle-compression'/uuid.uuid4().hex/'result.json',proof,True);s=json.loads((HOME/'status.json').read_bytes());s.update(closedCodebookOracleCompressionPin=receipt,updatedAtUtc=utc());save(HOME/'status.json',s);print(json.dumps({'resultPin':receipt,'actualAllocatedBytesSaved':proof['actualAllocatedBytesSaved']}))
