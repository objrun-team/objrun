"""Portable public framework install; original candidate image remains the base."""
import os,json,time,hashlib
from pathlib import Path
from bootstrap import ROOT
from tensor_protocol import read
from runtime_transport import copy_runtime_asset

def pin(p):
 p=Path(p);h=hashlib.sha256()
 with p.open('rb') as f:
  for b in iter(lambda:f.read(1024**2),b''):h.update(b)
 return {'path':str(p.resolve()),'bytes':p.stat().st_size,'sha256':h.hexdigest()}
def install(native,cid,output):
 output=Path(output);output.mkdir(parents=True,exist_ok=True);base=ROOT/'docs/repair-2026-10-10/full-f-rerun/novaeve-formal-20261013/group-04';prov=json.loads((base/'adapter_1/versions/tensor-v1/public-framework-provenance.json').read_bytes());archive=prov['archivePin'];assert pin(archive['path'])==archive;overlay=base/'adapter_3/versions/pipeline-v2/pipeline-public-overlay-gnu.tgz';overlaypin=pin(overlay);assert overlaypin['sha256']=='b4ad41298302de7865f2d4cac99d996156f5222fc515d2b1177703c6c6c625a0';actor=native.assert_actor(cid);labels={k:actor['Labels'][k] for k in ('objrun.tb12.owner','objrun.tb12.role','objrun.tb12.native-source')};native.guard();record={'baseFrameworkPin':archive,'overlayPin':overlaypin}
 record['frameworkCopy']=copy_runtime_asset(archive['path'],cid,'/tmp/public-framework.tgz',labels,output/'framework-cache',lease_pid=int(os.environ['NOVAEVE_RESOURCE_PARENT_PID']))
 extractor=Path(__file__).with_name('safe_framework_extract.mjs');native.checked(['cp',str(extractor),cid+':/tmp/safe_framework_extract.mjs'],timeout=60);prefix='/tmp/objrun-tensor-framework-'+native.nonce
 record['frameworkExtraction']=native.execute(cid,['/bin/sh','-c','LD_LIBRARY_PATH=/rt-lib /rt-node /tmp/safe_framework_extract.mjs /tmp/public-framework.tgz '+prefix+' '+archive['sha256']+' '+str(archive['bytes'])],timeout=180)
 native.guard();native.assert_actor(cid);record['overlayCopy']=native.checked(['cp',str(overlay),cid+':/tmp/public-overlay.tgz'],timeout=180)
 overlayprefix=prefix+'-overlay';record['overlayExtraction']=native.execute(cid,['/bin/sh','-c','LD_LIBRARY_PATH=/rt-lib /rt-node /tmp/safe_framework_extract.mjs /tmp/public-overlay.tgz '+overlayprefix+' '+overlaypin['sha256']+' '+str(overlaypin['bytes'])],timeout=180)
 record['combine']=native.execute(cid,['/bin/sh','-c','LD_LIBRARY_PATH=/rt-lib /rt-node -e '+"'const f=require(\"fs\");f.cpSync(\""+overlayprefix+'/opt/checker\",\"'+prefix+'/opt/checker\",{recursive:true,force:true});'+'\''],timeout=120);record['prefix']=prefix;record['privatePathsAbsentByProvenance']=True
 record['imports']=native.execute(cid,[prefix+'/run-python','-c','import torch,transformers,json;from transformers import LlamaConfig,LlamaForCausalLM,LlamaModel;assert torch.__version__=="2.7.0+cpu" and transformers.__version__=="4.55.0";print(json.dumps({"torch":torch.__version__,"transformers":transformers.__version__}))'],timeout=60)
 (output/'portable-framework.json').write_text(json.dumps(record,indent=2));return prefix,record
