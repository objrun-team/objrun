"""Bind task-specific dependency images; never silently use a mismatched base."""
from pathlib import Path
import json, re
from docker_owned import sha


def task_packages(context,task):
    return {**context['packages'],**task.get('privatePackageOverrides',{})}


def task_private_image(context_directory,context,task,base):
    overrides=task.get('privatePackageOverrides',{})
    if not overrides:return base,None
    directory=Path(context_directory)/'task-environments'/task['taskId']
    path=directory/'image-proof.json'
    proof=json.loads(path.read_bytes())
    assert proof['protocol']=='terminal-task-private-image-v1' and proof['taskId']==task['taskId']
    assert proof['baseImage']==base and proof['packageOverrides']==overrides
    assert proof['complete'] is True and proof['buildExitCode']==0
    assert proof['dockerfileSha256']==sha(directory/'Dockerfile')
    assert re.fullmatch(r'sha256:[a-f0-9]{64}',proof['imageId'])
    return proof['imageId'],{'path':str(path),'sha256':sha(path),'imageId':proof['imageId']}
