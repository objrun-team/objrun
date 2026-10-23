"""Owned native parent for the independent RAM scorer. No import-time run."""
from __future__ import annotations
import hashlib
import importlib.util
import json
import os
from pathlib import Path
import re
import stat
import subprocess
import sys
import time

ROOT=Path(__file__).resolve().parents[2]

def require(value,message):
    if not value:raise RuntimeError(message)
def sha(path):
    h=hashlib.sha256()
    with Path(path).open('rb')as f:
        while block:=f.read(65536):h.update(block)
    return h.hexdigest()
def pin(path):return{'path':str(Path(path).absolute()),'bytes':Path(path).stat().st_size,'sha256':sha(path)}
def verify(p):
    path=Path(p['path']);s=path.lstat();require(stat.S_ISREG(s.st_mode)and s.st_nlink==1 and not getattr(s,'st_file_attributes',0)&0x400,'RAM_parent_pin_regular')
    require(s.st_size==p['bytes']and sha(path)==p['sha256'],'RAM_parent_pin_changed');return path
def load(name,path):
    spec=importlib.util.spec_from_file_location(name,path);m=importlib.util.module_from_spec(spec);spec.loader.exec_module(m);return m
def save(path,value):
    raw=(json.dumps(value,indent=2)+'\n').encode()
    with path.open('xb')as f:require(f.write(raw)==len(raw),'RAM_parent_short_write');f.flush();os.fsync(f.fileno())
    require(path.read_bytes()==raw,'RAM_parent_readback');return pin(path)

def supervise_owned_child(argv,env,folder,intent_value,absence_probe,resource_probe,deadline=650,intent_writer=save):
    """Only a child returned by this exact Popen can be signalled or waited.

    The production caller fixes argv, D namespace and650s. Small F controls
    exercise the same exit/handle/stdio path with harmless native children.
    """
    require(isinstance(deadline,(int,float))and 0<deadline<=650,'RAM_parent_deadline')
    out_path=folder.parent/('cli-'+folder.name+'-stdout.bin');err_path=folder.parent/('cli-'+folder.name+'-stderr.bin')
    intent=folder.parent/('cli-'+folder.name+'-intent.json');receipt=folder.parent/('cli-'+folder.name+'.json');started=time.monotonic();failure=None;child=None;handle_closed=False;exit_code=None
    with out_path.open('xb')as stdout,err_path.open('xb')as stderr:
        try:
            child=subprocess.Popen(argv,env=env,stdin=subprocess.DEVNULL,stdout=stdout,stderr=stderr,creationflags=(subprocess.CREATE_NO_WINDOW if os.name=='nt'else 0))
            intent_writer(intent,{'protocol':'jpg-D-owned-grade-child-intent-v1',**intent_value,'processId':child.pid,'parentPid':os.getpid(),'operationOutput':str(folder),'argvSha256':hashlib.sha256(json.dumps(argv).encode()).hexdigest(),'startedAtUnixMs':int(time.time()*1000)})
            while child.poll()is None:
                require(time.monotonic()-started<=deadline,'RAM_parent_operational_timeout')
                require(os.fstat(stdout.fileno()).st_size<=1024**2 and os.fstat(stderr.fileno()).st_size<=1024**2,'RAM_parent_stdout_stderr_bound')
                require(resource_probe(),'RAM_parent_physical_resource_guard');time.sleep(.025)
        except BaseException as error:failure=type(error).__name__+':'+str(error)
        finally:
            if child is not None:
                if child.poll()is None:child.kill()
                exit_code=child.wait(timeout=10)
                if os.name=='nt':child._handle.Close();handle_closed=True
            stdout.flush();os.fsync(stdout.fileno());stderr.flush();os.fsync(stderr.fileno())
    require(child is not None,'RAM_parent_spawn_failure_no_actor')
    # Even after wait+owned HANDLE Close, Windows can briefly retain an exited
    # process object. Do not signal a PID again; wait only for strict absence.
    absence_observations=[];until=time.monotonic()+2
    while True:
        try:
            actual_absence=absence_probe(child.pid);absence_observations.append({'absent':True});break
        except BaseException as error:
            absence_observations.append({'absent':False,'kind':getattr(error,'kind',type(error).__name__)})
            if getattr(error,'kind',None)!='actor_not_absent'or time.monotonic()>=until:raise
            time.sleep(.025)
    info={'protocol':'jpg-D-owned-grade-child-close-v1','processId':child.pid,'parentPid':os.getpid(),'operationOutput':str(folder),'phase':intent_value['phase'],'intentPin':pin(intent)if intent.is_file()else None,'exitCode':exit_code,
        'directChildExited':exit_code is not None,'directChildClosed':stdout.closed and stderr.closed and handle_closed,'nativeProcessHandleClosed':handle_closed,'actualPidAbsence':actual_absence,'postCloseAbsenceObservations':absence_observations,
        'stdoutPin':pin(out_path),'stderrPin':pin(err_path),'durationMs':round((time.monotonic()-started)*1000),'failureType':failure,'modelCalls':0,'scoreCertificate':False}
    save(receipt,info);return info

def run_capture_cli(recipe,capture,folder,phase='final'):
    s=recipe['DStorage'];storage=load('jpg_D_parent_storage',verify(s['storageSourcePin']));d=json.loads(verify(s['descriptorPin']).read_bytes());storage.validate_descriptor(d)
    folder=Path(folder).absolute();require(folder.parent==Path(d['directories']['private-logs'])and re.fullmatch('grade-[a-f0-9]{32}',folder.name)and not folder.exists(),'RAM_parent_new_output')
    storage.ordinary(folder.parent,Path('D:/'));require(phase in('feedback','final'),'RAM_parent_phase')
    profile=json.loads(verify(recipe['approvedNativeProfile']).read_bytes());exe=Path(profile['executable']);require(sha(exe)==profile['sha256']and Path(sys.executable).resolve()==exe.resolve(),'RAM_parent_native_python_identity')
    executor=verify(s['executorSourcePin']);require(executor==ROOT/'scripts/benchmark-repair/jpg_private_ram_executor.py','RAM_parent_exact_executor')
    recipe_path=Path(recipe['output'])/'recipe.json';recipe_pin=pin(recipe_path);require(json.loads(verify(recipe_pin).read_bytes())==recipe,'RAM_parent_runtime_recipe')
    capture_pin=pin(capture['captureReceiptPath']);actual=json.loads(verify(capture_pin).read_bytes());require(all(capture[k]==v for k,v in actual.items()),'RAM_parent_fixed_capture')
    argv=[str(exe),'-B','-X','utf8',str(executor),'--grade','--phase',phase,'--capture-receipt',capture_pin['path'],'--capture-receipt-sha256',capture_pin['sha256'],
        '--descriptor',s['descriptorPin']['path'],'--descriptor-sha256',s['descriptorPin']['sha256'],'--ram-plan',s['ramPlanPin']['path'],'--ram-plan-sha256',s['ramPlanPin']['sha256'],
        '--recipe',recipe_pin['path'],'--recipe-sha256',recipe_pin['sha256'],'--namespace-proof',s['namespaceProofPin']['path'],'--namespace-proof-sha256',s['namespaceProofPin']['sha256'],
        '--docker-client-sha256',s['dockerClientPin']['sha256'],'--output',str(folder)]
    env=storage.native_environment(d,os.environ)
    info=supervise_owned_child(argv,env,folder,{'phase':phase,'recipePin':recipe_pin,'captureReceiptPin':capture_pin,'executorSourcePin':s['executorSourcePin']},storage.native_actor_absent,
        lambda:storage.assess_resources(d,{k:storage.shutil.disk_usage(k+':/').free for k in('C','D','F')},False,0)['admitted'],deadline=650)
    module=load('jpg_D_parent_executor',executor)
    if info['failureType'] or info['exitCode']!=0:
        module.recover_owned_after_child_exit(folder,info['processId'],recipe)
        raise RuntimeError('RAM_scorer_failed_owned_evidence_preserved_no_score')
    require(info['stdoutPin']['bytes']<=1024**2 and info['stderrPin']['bytes']<=1024**2,'RAM_parent_closed_output_boundary')
    result_pin=pin(folder/'report.json');module.validate_grade_report(recipe,result_pin)
    return json.loads(verify(result_pin).read_bytes())
