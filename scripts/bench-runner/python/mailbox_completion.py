"""Classify only an exact owned checker clean completion; never turn transport faults into missing mail."""
import base64, hashlib, importlib.util, json, os, re
from pathlib import Path
_original=None

def configure(original_pin):
 global _original
 path=Path(original_pin['path']);raw=path.read_bytes();assert len(raw)==original_pin['bytes'] and hashlib.sha256(raw).hexdigest()==original_pin['sha256']
 spec=importlib.util.spec_from_file_location('_qualified_original_mailbox',path);module=importlib.util.module_from_spec(spec);spec.loader.exec_module(module);_original=module

def _original_module():
 if _original is None:configure(json.loads(os.environ['BENCH_MAILBOX_ORIGINAL_PIN']))
 return _original

def _stream(receipt,name):
 item=receipt[name];raw=Path(item['path']).read_bytes();assert item.get('bytesObserved',len(raw))==item.get('bytesStored',item.get('bytes'));assert len(raw)==item.get('bytesStored',item.get('bytes')) and hashlib.sha256(raw).hexdigest()==item['sha256'];return raw.decode('utf-8')

def classify_checker_completion(native,checker,receipt):
 assert re.fullmatch(r'[0-9a-f]{64}',checker),'exact checker CID required'
 if receipt.get('exitCode')==0:return None
 assert type(receipt.get('exitCode')) is int,'unknown mailbox command exit'
 assert receipt.get('closeObserved') is True and receipt.get('exitObserved',True) is True and not any(receipt.get(k) for k in ['timedOut','overflow','captureFaults','spawnFault','signal']),'unclosed or faulty mailbox command'
 argv=receipt['argv'];pos=argv.index('exec');assert argv[pos+1]==checker,'mailbox failed command CID mismatch'
 assert _stream(receipt,'stdout')=='','completion error unexpectedly has stdout'
 assert _stream(receipt,'stderr').strip()=='Error response from daemon: container '+checker+' is not running','not an exact checker-completion error'
 actual=native.assert_actor(checker);state=actual['State'];assert actual['Id']==checker and state['Status']=='exited' and state['Running'] is False and type(state['ExitCode']) is int and state['ExitCode']==0 and state['OOMKilled'] is False and not state.get('Error'),'checker is not cleanly completed'
 return {'protocol':'bench-owned-checker-completion-v1','classification':'checker-completed','checkerCid':checker,'originalCommandReceipt':receipt,'ownedInspect':actual,'missing':False,'gradePassed':None,'receiptFabricated':False}

def capture_request(native,checker,name,output,remain):
 original=_original_module();assert re.fullmatch(r'[0-9]+-1\.request\.json',name)
 receipt=native.command(['exec',checker,'/opt/checker/bin/python','-c',original.READ_CODE,name,'/tmp/pipeline-mailbox'],timeout=original._timeout(remain),stdout_limit=4*((original.LIMIT+2)//3)+8192)
 if receipt.get('exitCode')!=0:
  classified=classify_checker_completion(native,checker,receipt);remain();return None,classified
 class ReplayOne:
  def __getattr__(self,key):return getattr(native,key)
  def command(self,argv,**kwargs):return receipt
 return original.capture_request(ReplayOne(),checker,name,output,remain)

def deliver_response(*args,**kwargs):return _original_module().deliver_response(*args,**kwargs)
