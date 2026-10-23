"""Seven task-specific boundaries; no readiness or score assertions."""
from pathlib import PurePosixPath

TASKS = {
 'enterprise-information-search': {'roots':['/root/answer.json'],'tree':False},
 'paratransit-routing': {'roots':['/root/report.json'],'tree':False},
 'tictoc-unnecessary-abort-detection': {'roots':['/root/unnecessary_aborts.json'],'tree':False,'score':'/verifier/score_outputs.py'},
 'quantum-numerical-simulation': {'roots':[f'/{folder}/{i}.csv' for folder in ('root','app') for i in range(1,5)],'tree':False},
 'fix-build-google-auto': {'roots':['/home/travis/build/failed'],'tree':True},
 'flink-query': {'roots':['/app/workspace'],'tree':True},
 'spring-boot-jakarta-migration': {'roots':['/workspace'],'tree':True},
}
COMMANDS = {
 'fix-build-google-auto': [('bash run_passed.sh', '/tests', None, False)],
 'flink-query': [
  ('cd /app/workspace && mvn clean package -q',None,None,True),
  ('cd /opt/flink/bin && ./flink run -t local -c clusterdata.query.LongestSessionPerJob /app/workspace/target/LongestSessionPerJob-jar-with-dependencies.jar --task_input /app/workspace/data/task_events/part-00001-of-00500.csv.gz --job_input /app/workspace/data/job_events/part-00001-of-00500.csv.gz --output /app/workspace/out.txt',None,None,True),
 ],
 'spring-boot-jakarta-migration': [
  (['bash','-c','source /root/.sdkman/bin/sdkman-init.sh && sdk use java 21.0.2-tem && mvn clean compile -q'],'/workspace',300,True),
  (['bash','-c','source /root/.sdkman/bin/sdkman-init.sh && sdk use java 21.0.2-tem && mvn test -q'],'/workspace',300,True),
 ],
}

def allowed(task,path):
 p=PurePosixPath(path)
 if not p.is_absolute() or str(p)!=path or '..' in p.parts:return False
 cfg=TASKS[task]
 return any(path==root or cfg['tree'] and path.startswith(root+'/') for root in cfg['roots'])

def limits(task,resources):
 # Original storage remains the upper bound, including complete source trees.
 storage=int(resources['environment']['storage_mb'])*1024**2
 maximum=storage if TASKS[task]['tree'] else min(storage,512*1024**2 if task=='quantum-numerical-simulation' else 8*1024**2)
 return {'maximumBytes':maximum,'maximumFiles':100000 if TASKS[task]['tree'] else len(TASKS[task]['roots'])}
