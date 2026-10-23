"""Validate original guest metadata/raw CTRF and complete exact nodeid phases; exit0 alone never passes."""
import base64,hashlib,importlib.util,json
from pathlib import Path
from nodeid_phase_reporter import validate_ledger
import nodeid_phase_reporter
_original=None

def configure(original_pin):
 global _original
 p=Path(original_pin['path']);raw=p.read_bytes();assert len(raw)==original_pin['bytes'] and hashlib.sha256(raw).hexdigest()==original_pin['sha256'];spec=importlib.util.spec_from_file_location('_original_grade_contract',p);_original=importlib.util.module_from_spec(spec);spec.loader.exec_module(_original)

def validate_result(result,task_id,invocation,checker_sha,raw_ctrf):
 assert _original is not None,'original grade contract pin required'
 assert result['protocol']=='tb12-private-checker-result-v1' and result['taskId']==task_id and result['invocationId']==invocation and result['checkerSourceSha256']==checker_sha
 assert type(result['numericGuestPid']) is int and result['numericGuestPid']==1 and type(result['numericParentPid']) is int and result['numericParentPid']>=0
 assert result['exitCode'] in [0,1] and type(result['reward']) is int and result['reward']==int(result['exitCode']==0) and result['collectOnly'] is False
 assert base64.b64decode(result['ctrfRawBase64'],validate=True)==raw_ctrf and result['ctrfRawSha256']==hashlib.sha256(raw_ctrf).hexdigest() and result['ctrf']==json.loads(raw_ctrf)
 assert all(isinstance(result['privateNamespaces'][n],str) and result['privateNamespaces'][n].startswith(n+':[') for n in ['pid','mnt','net'])
 assert result['pythonExecutable'].startswith('/') and len(result['pythonExecutableSha256'])==64 and len(result['mountInfoSha256'])==64 and result['procStatus'] and result['packages'] and result['wallStop']>=result['wallStart'] and result['monotonicSeconds']>=0
 ledger_raw=base64.b64decode(result['nodeidLedgerRawBase64'],validate=True);assert len(ledger_raw)<=2*1024**2 and hashlib.sha256(ledger_raw).hexdigest()==result['nodeidLedgerRawSha256'] and json.loads(ledger_raw)==result['nodeidLedger']
 assert result['nodeidLedger']['sourceSha256']==hashlib.sha256(Path(nodeid_phase_reporter.__file__).read_bytes()).hexdigest()
 validation=validate_ledger(result['nodeidLedger'],_original.EXPECTED,result['exitCode']);return {**result,'caseLedgerValidation':validation,'rawCtrfPreserved':True,'ctrfCaseCount':len(result['ctrf']['results']['tests']),'originalExpectedCaseCount':len(_original.EXPECTED),'originalPredicatesChanged':False}
