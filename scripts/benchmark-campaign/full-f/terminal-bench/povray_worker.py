"""Original renderer operations chained without any private test/assertion source."""
from pathlib import Path
import time
from artifacts import capture_file

RENDER=['/usr/local/bin/povray','+L/app/povray-2.2/povdoc/include','+I/app/deps/illum1.pov',
        '+O/app/illum1.tga','+FT','+W640','+H480','+A0.1','+V','-P']
CONVERT=['convert','/app/illum1.tga','/app/illum1.png']
VERSION=['/usr/local/bin/povray','-h']


def povray_worker(native,candidate,task,deadline,output):
    source=native.assert_actor(candidate);assert source['State']['Paused']
    image,commit=native.commit(candidate,'untrusted-povray');rows=[];receipts=[];files=[]
    output=Path(output);output.mkdir(parents=True,exist_ok=False)
    render_exists=False
    for index,(argv,cwd) in enumerate([(RENDER,'/app'),(CONVERT,None),(VERSION,None)]):
        if argv==CONVERT and not render_exists:continue
        remaining=deadline-time.monotonic()
        if remaining<=0:raise TimeoutError('Official POV-Ray verifier deadline exhausted')
        cid,initial,create=native.create('untrusted-povray-'+str(index),image,argv[0],argv[1:],network='none',
            memory_mb=task['officialEnvironment']['memory_mb'],cpus=task['officialEnvironment']['cpus'],cwd='/app')
        start=native.command(['start','-a',cid],timeout=remaining,stdout_limit=2*1024**2)
        final=native.assert_actor(cid);exception=None
        startup_error=final['State'].get('Error','')
        missing='executable file not found' in startup_error or ('stat '+argv[0]+': no such file or directory') in startup_error
        if final['State']['Status']=='created' and missing:
            exception='FileNotFoundError'
        else:assert final['State']['Status']=='exited'
        captures=[];next_commit=None
        if exception is None:
            if argv in (RENDER,CONVERT):
                path='/app/illum1.tga' if argv==RENDER else '/app/illum1.png'
                captures.append(capture_file(native,cid,path,16*1024**2,output/str(index)))
                captures[-1]['sourceCid']=cid;files.extend(captures)
                if argv==RENDER:render_exists=captures[-1]['exists']
            image,next_commit=native.commit(cid,'untrusted-povray-chain-'+str(index))
        rows.append({'argv':argv,'cwd':cwd,'timeout':None,'exitCode':final['State']['ExitCode'],
                     'stdout':Path(start['stdout']['path']).read_bytes().decode('utf-8'),
                     'stderr':Path(start['stderr']['path']).read_bytes().decode('utf-8'),'exception':exception})
        removal,absence=native.remove(cid)
        receipts.append({'cid':cid,'initial':initial,'create':create,'start':start,'final':final,'captures':captures,
                         'nextImage':image,'nextCommit':next_commit,'sourceState':source,'initialCommit':commit,
                         'removal':removal,'absence':absence})
    return {'protocol':'terminal-povray-cli-data-v1','rows':rows},receipts,files
