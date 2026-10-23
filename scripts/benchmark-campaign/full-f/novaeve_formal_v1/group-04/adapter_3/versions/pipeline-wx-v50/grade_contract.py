"""Validate real guest grading fields without supplying placeholder values."""
import hashlib,json,base64
from pathlib import Path
EXPECTED={'test_pipeline_parallel_exists','test_no_hooks_in_pipeline_parallel','test_pipeline_parallel[1]','test_pipeline_parallel[2]'}
def validate_result(result,task_id,invocation,checker_sha,raw_ctrf):
 assert result['protocol']=='tb12-private-checker-result-v1' and result['taskId']==task_id and result['invocationId']==invocation and result['checkerSourceSha256']==checker_sha
 assert type(result['numericGuestPid']) is int and result['numericGuestPid']==1 and type(result['numericParentPid']) is int and result['numericParentPid']>=0
 assert result['exitCode'] in [0,1] and type(result['reward']) is int and result['reward']==int(result['exitCode']==0) and result['collectOnly'] is False
 assert base64.b64decode(result['ctrfRawBase64'],validate=True)==raw_ctrf
 assert result['ctrfRawSha256']==hashlib.sha256(raw_ctrf).hexdigest() and result['ctrf']==json.loads(raw_ctrf)
 tests=result['ctrf']['results']['tests'];assert len(tests)==4 and {x['name'].split('::')[-1] for x in tests}==EXPECTED
 assert all(isinstance(result['privateNamespaces'][n],str) and result['privateNamespaces'][n].startswith(n+':[') for n in ['pid','mnt','net'])
 assert result['pythonExecutable'].startswith('/') and len(result['pythonExecutableSha256'])==64 and len(result['mountInfoSha256'])==64 and result['procStatus'] and result['packages'] and result['wallStop']>=result['wallStart'] and result['monotonicSeconds']>=0
 return result
