"""Prepare three distinct immutable namespaces for the native Wyckoff task."""
import argparse
import json
from pathlib import Path
import shutil
import uuid
from prepare import HOME,VENDOR,public,save,utc
from build_environment import DOCKER,ENV
from bounded_child import run
from code_values import TASK

def main():
    parser=argparse.ArgumentParser();parser.add_argument('--task',default=TASK);args=parser.parse_args();assert args.task==TASK
    row=json.loads((HOME/'task-descriptors'/(TASK+'.json')).read_bytes());source=VENDOR/'tasks'/TASK;before=public.tree(source)
    home=HOME/'code-environment-preparation'/TASK/uuid.uuid4().hex;home.mkdir(parents=True);serial=0;commands=[]
    def command(argv,timeout):
        nonlocal serial
        serial+=1;prefix=home/('command-%03d'%serial)
        outcome=run([DOCKER,*argv],ENV,prefix.with_suffix('.stdout'),prefix.with_suffix('.stderr'),timeout)
        pin=save(prefix.with_suffix('.json'),{'argv':[DOCKER,*argv],**outcome,'stdoutPin':public.pin(prefix.with_suffix('.stdout')),'stderrPin':public.pin(prefix.with_suffix('.stderr')),'modelCalls':0})
        commands.append(pin)
        if outcome['exitCode'] or outcome['faults']:raise RuntimeError('code environment build failed: '+pin['path'])
        return prefix.with_suffix('.stdout').read_bytes()
    result={'protocol':'skillsbench-full-f-isolated-code-images-v1','taskId':TASK,'modelCalls':0,'createdAtUtc':utc(),'imagesBuilt':False}
    try:
        tag='objrun-skb-code-pristine:'+home.name
        command(['build','--pull=false','--label','objrun.skb.role=full-f-code-pristine','-t',tag,str(source/'environment')],row['originalResources']['environment']['build_timeout_sec'])
        candidate=json.loads(command(['image','inspect',tag],30))[0]
        inputs={ '/root/cif_files/'+p.name:public.pin(p)['sha256'] for p in sorted((source/'environment').glob('*.cif'))};assert len(inputs)==11
        execution=home/'execution-context';execution.mkdir();exec_runner=Path(__file__).with_name('candidate_function_exec.py');shutil.copyfile(exec_runner,execution/exec_runner.name)
        (execution/'Dockerfile').write_text('FROM '+candidate['Id']+'\nCOPY candidate_function_exec.py /opt/objrun/candidate_function_exec.py\nENTRYPOINT ["python3","-I","-B","/opt/objrun/candidate_function_exec.py"]\n')
        exec_tag='objrun-skb-code-execution:'+home.name
        command(['build','--pull=false','--label','objrun.skb.role=full-f-untrusted-code-execution','-t',exec_tag,str(execution)],row['originalResources']['environment']['build_timeout_sec'])
        exec_image=json.loads(command(['image','inspect',exec_tag],30))[0]
        private=home/'private-context';private.mkdir();shutil.copytree(source/'verifier',private/'verifier')
        private_runner=Path(__file__).with_name('private_script_eval.py');shutil.copyfile(private_runner,private/private_runner.name)
        files=[{'path':'/verifier/'+p.relative_to(private/'verifier').as_posix(),'sha256':public.pin(p)['sha256']} for p in sorted((private/'verifier').rglob('*')) if p.is_file()]
        files.append({'path':'/opt/objrun/private_script_eval.py','sha256':public.pin(private_runner)['sha256']})
        save(private/'trusted.json',{'taskId':TASK,'publicInputs':inputs,'files':files});(private/'empty.ini').write_text('[pytest]\n')
        (private/'Dockerfile').write_text('FROM '+candidate['Id']+'\nRUN python3 -m venv --system-site-packages /opt/objrun/privatevenv && /opt/objrun/privatevenv/bin/pip install --no-cache-dir pytest==8.3.4 pytest-json-report==1.5.0\nCOPY verifier /verifier\nCOPY private_script_eval.py trusted.json empty.ini /opt/objrun/\nENV PYTEST_DISABLE_PLUGIN_AUTOLOAD=1\nENTRYPOINT ["/opt/objrun/privatevenv/bin/python","-I","-B","/opt/objrun/private_script_eval.py"]\n')
        private_tag='objrun-skb-code-private:'+home.name
        command(['build','--pull=false','--label','objrun.skb.role=full-f-trusted-native-script','-t',private_tag,str(private)],row['originalResources']['environment']['build_timeout_sec'])
        private_image=json.loads(command(['image','inspect',private_tag],30))[0]
        assert public.tree(source)==before and len({candidate['Id'],exec_image['Id'],private_image['Id']})==3
        result.update(imagesBuilt=True,candidateImageId=candidate['Id'],executionImageId=exec_image['Id'],privateImageId=private_image['Id'],publicInputs=inputs,originalResources=row['originalResources'],workingDirectory=row['workdir'],sourceTree=before,
            sourcePins=[public.pin(Path(__file__)),public.pin(exec_runner),public.pin(private_runner),public.pin(Path(__file__).with_name('code_values.py'))],namespaceSeparation=True,candidateInterpreterUsedForTrustedGrader=False,actualControlsPassed=False)
    except Exception as error:result['failure']={'type':type(error).__name__,'detail':str(error)};raise
    finally:
        result['commandPins']=commands;pin=save(home/'result.json',result,True);save(HOME/'code-environment-preparation'/TASK/'latest.json',{'builtImagesPin':pin});print(json.dumps({'builtImagesPin':pin,'imagesBuilt':result['imagesBuilt'],'modelCalls':0}))

if __name__=='__main__':main()
