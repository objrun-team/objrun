"""Native interactive ScienceWorld episodes; only observations enter the agent context."""
import argparse
import hashlib
from http.server import BaseHTTPRequestHandler,HTTPServer
import json
import os
from pathlib import Path
import sys
import types
ROOT=Path(__file__).resolve().parents[3]
HOME=ROOT/'.phase1-data/scienceworld'
VENDOR=HOME/'vendor/ScienceWorld'
sys.path[:0]=[str(ROOT/'.phase1-data/host-extras'),str(VENDOR)]
version=types.ModuleType('scienceworld.version'); version.__version__='source-e8216d60'
sys.modules['scienceworld.version']=version
tmp=HOME/'tmp'; tmp.mkdir(exist_ok=True)
os.environ['TMP']=os.environ['TEMP']=str(tmp)
os.environ['JAVA_TOOL_OPTIONS']='-Xmx512m -Djava.io.tmpdir='+str(tmp).replace('\\','/')
from scienceworld import ScienceWorldEnv
SOURCE=json.loads((HOME/'source.json').read_text(encoding='utf-8'))
EPISODES=SOURCE['selectedEpisodes']
BOOK={f"scienceworld-{row['task']}-{row['variation']}":row for row in EPISODES}
world=ScienceWorldEnv(envStepLimit=100)
CURRENT=None
TRACE=[]
INITIAL=None

class Handler(BaseHTTPRequestHandler):
    def log_message(self,*_): pass
    def send(self,obj,status=200):
        raw=json.dumps(obj).encode()
        self.send_response(status); self.send_header('content-type','application/json'); self.send_header('content-length',str(len(raw))); self.end_headers(); self.wfile.write(raw)
    def do_GET(self):
        if self.path=='/health': self.send({'ok':True,'tasks':len(BOOK),'variant':'native test variations, no simplifications'})
        elif self.path.startswith('/problems'): self.send([dict(row,id=tid) for tid,row in BOOK.items()])
        else: self.send({'error':'not found'},404)
    def do_POST(self):
        global CURRENT,TRACE,INITIAL
        try:
            body=json.loads(self.rfile.read(int(self.headers.get('content-length',0))))
            if self.path=='/prepare':
                row=BOOK[body['id']]
                world.load(row['task'],row['variation'],'',generateGoldPath=False)
                observation,info=world.reset()
                CURRENT=body['task']; TRACE=[]
                INITIAL=hashlib.sha256(json.dumps(world.getObjectTree(),sort_keys=True).encode()).hexdigest()
                prompt=world.get_task_description()+'\n\nInitial observation:\n'+observation+'\n\nInteract using world_action, one natural-language simulator action per call. Typical commands include look around, inventory, open door to ROOM, go to ROOM, pick up ITEM, put ITEM in CONTAINER, activate ITEM, deactivate ITEM, focus on ITEM, wait, and use ITEM on ITEM. Follow simulator observations. The episode allows 100 actions and 120 seconds of preparation time. When finished, submit a nonempty label for the completed episode. Native score, rewards and hidden gold actions are not provided.'
                self.send({'prompt':prompt,'initialStateSha256':INITIAL}); return
            if self.path=='/action':
                if not CURRENT or not str(body.get('instance','')).startswith(CURRENT+'#'): self.send({'error':'wrong active episode'},403); return
                if len(TRACE)>=100: self.send({'observation':'Episode action limit reached. Submit the current episode.'}); return
                action=str(body.get('args',{}).get('action',''))
                if len(action)>500: self.send({'error':'action too long'},422); return
                observation,reward,done,info=world.step(action)
                TRACE.append({'action':action,'observation':observation,'score':info['score'],'nativeDone':done})
                self.send({'observation':observation}); return
            if self.path in ['/parsed','/passed','/accept']:
                inp=body.get('input',{}); task=inp.get('task',{})
                if task.get('id')!=CURRENT: self.send({'error':'episode identity mismatch'},422); return
                candidate=inp.get('result'); text=candidate.get('body') if isinstance(candidate,dict) else candidate
                if text is None: text=task.get('result','')
                if self.path=='/parsed': self.send({'value':bool(text)}); return
                passed=bool(text) and bool(TRACE) and TRACE[-1]['score']==100
                if self.path=='/passed': self.send({'value':passed}); return
                self.send({'valid':True,'passed':passed,'score':TRACE[-1]['score'] if TRACE else 0,'actions':len(TRACE),'initialStateSha256':INITIAL,'trace':TRACE,'finalStateSha256':hashlib.sha256(json.dumps(world.getObjectTree(),sort_keys=True).encode()).hexdigest()}); return
            self.send({'error':'not found'},404)
        except Exception as error: self.send({'valid':False,'outcome':'grader_error','errorType':type(error).__name__},503)

if __name__=='__main__':
    ap=argparse.ArgumentParser(); ap.add_argument('--port',type=int,default=17930); args=ap.parse_args()
    print(json.dumps({'listening':args.port,'tasks':len(BOOK)}),flush=True)
    try: HTTPServer(('127.0.0.1',args.port),Handler).serve_forever()
    finally: world.close()
