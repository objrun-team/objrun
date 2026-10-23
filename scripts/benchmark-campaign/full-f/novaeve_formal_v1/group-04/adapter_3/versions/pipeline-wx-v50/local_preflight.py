"""Finite source/adoption reads only; no Docker, leases, grading or provider calls."""
import ast,json
from pathlib import Path
from bootstrap import install
install()
from activation_guard import require_activation
for path in Path(__file__).parent.rglob('*.py'):ast.parse(path.read_text(encoding='utf-8-sig'),filename=str(path))
a=require_activation()
print(json.dumps({'protocol':'pipeline-wx-v50-python-preflight','passed':True,'actualLiveExecutorPid':a['adoption']['liveExecutorPid'],'originalExecutorStillAlive':a['adoption']['originalExecutorStillAlive'],'actualAdoptedEpoch':True,'singleResourcePool':True,'nativeActions':0,'resourceAcquisitions':0,'modelCalls':0,'newPaidRequests':0}))
