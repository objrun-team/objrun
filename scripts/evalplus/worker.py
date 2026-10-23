import contextlib,io,json,os,sys
from pathlib import Path
source_dir=str(Path(__file__).resolve().parent)
extras=os.environ['EP_EXTRAS']
sys.path[:0]=[extras,source_dir]
from codec import encode,decode
from sandbox import restrict
namespace={'__name__':'candidate'}
source=open(sys.argv[1],encoding='utf-8').read()
try:
    restrict(['/usr','/lib','/lib64',source_dir,extras,'/tmp/objrun-evalplus-20261012/venv'],str(Path(sys.argv[1]).parent))
except BaseException as e:
    print(json.dumps({'ready':False,'sandboxFailure':True,'errorType':type(e).__name__,'diagnostic':str(e)}),flush=True);raise SystemExit(1)
try:
    with contextlib.redirect_stdout(io.StringIO()),contextlib.redirect_stderr(io.StringIO()):
        exec(compile(source,'candidate.py','exec'),namespace)
except BaseException as e:
    print(json.dumps({'ready':False,'errorType':type(e).__name__}),flush=True);raise SystemExit(1)
print(json.dumps({'ready':True,'uid':os.getuid()}),flush=True)
for line in sys.stdin:
    try:
        q=json.loads(line)
        with contextlib.redirect_stdout(io.StringIO()),contextlib.redirect_stderr(io.StringIO()):
            result=namespace[q['function']](*decode(q['args']))
        response={'ok':True,'value':encode(result)}
    except BaseException as e: response={'ok':False,'errorType':type(e).__name__}
    print(json.dumps(response),flush=True)
