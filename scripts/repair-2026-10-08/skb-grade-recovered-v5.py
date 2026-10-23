"""Grade existing stopped artifacts with original private verifier; model calls zero."""
import json,os,subprocess,sys,time,uuid
from pathlib import Path
import skb_artifact_task_v2 as task
import skb_artifact_ram_executor_v2 as grader
r=json.loads(Path(sys.argv[1]).read_text());layout=task.read_json(r['storageDescriptorPin']);root=Path(layout['storePhysical']);output=Path(r['output']);prior=task.read_json(r['priorRecipePin']);env=os.environ.copy();env.update(layout['nativeEnvironment'])
for i in range(1,16):
    record=task.read_json(r['reuseGenerationPins'][i]);cp=record['artifactCapture']['capturePin'];dp=record['taskDescriptorPin'];lp=r['storageDescriptorPin'];script=Path(__file__).with_name('skb_artifact_ram_executor_v2.py')
    argv=['D:/ProgramData/anaconda3/python.exe','-B','-X','utf8',str(script),'--task-descriptor',dp['path'],'--task-descriptor-sha256',dp['sha256'],'--storage-descriptor',lp['path'],'--storage-descriptor-sha256',lp['sha256'],'--mode','grade','--capture',cp['path'],'--capture-sha256',cp['sha256']]
    started=int(time.time()*1000);child=subprocess.Popen(argv,env=env,stdout=subprocess.PIPE,stderr=subprocess.PIPE,creationflags=subprocess.CREATE_NO_WINDOW)
    try:out,err=child.communicate(timeout=record['verifierSeconds']+120);timed=False
    except subprocess.TimeoutExpired:child.kill();out,err=child.communicate();timed=True
    caller=grader.fresh(output/('offline-grade-caller-'+str(i)+'.json'),task.canonical({'argv':argv,'childPid':child.pid,'parentPid':os.getpid(),'startedAtUnixMs':started,'finishedAtUnixMs':int(time.time()*1000),'exitCode':child.returncode,'timedOut':timed,'directChildClosed':True,'stdout':out.decode(),'stderr':err.decode(),'modelCalls':0}),root)
    lines=[json.loads(x) for x in out.decode().splitlines() if x.startswith('{')];op=lines[0].get('gradeOwnerPin') if lines else None;owner=task.read_json(op) if op else None;result=task.read_json(owner['resultPins']['private-result.json']) if owner and owner.get('resultPins') else None;e=result.get('evaluation') if result else None
    record.update(finalGradeCallerPin=caller,finalGradeOwnerPin=op,finalEvaluation=e,finalGradeStartedAfterGenerationClosed=False,finalGradeFromInterruptedRun=True)
    if not e:record['finalGradeFault']={'exitCode':child.returncode,'timedOut':timed,'ownerFault':owner.get('fault') if owner else None}
    grader.fresh(output/('recovered-task-'+str(i)+'.json'),task.canonical(record),root)
    if e:grader.fresh(output/('recovered-stage-grade-'+str(i)+'.json'),task.canonical({'taskDescriptorPin':dp,'capturePin':cp,'gradeOwnerPin':op,'callerPin':caller,'evaluation':e,'modelCalls':0,'generationInterrupted':record.get('state')=='interrupted'}),root)
    print(json.dumps({'index':i,'task':record['officialId'],'arm':record['arm'],'reward':e.get('officialReward') if e else None,'valid':e.get('valid') if e else None,'modelCalls':0}),flush=True)
