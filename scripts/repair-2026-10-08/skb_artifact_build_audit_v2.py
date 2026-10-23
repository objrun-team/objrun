"""Replay actual image/depot/native probe joins before sealing a build catalog."""
from __future__ import annotations
import argparse
import ast
from datetime import datetime,timezone
import json
import os
from pathlib import Path
import re
import skb_artifact_task_v2 as task
import skb_artifact_storage_v2 as storage
import skb_artifact_transport_v2 as transport
import skb_artifact_native_identity_v2 as native_identity

PROTOCOL='skillsbench-actual-build-closed-catalog-v2'


def verify_snapshot_pairs(pairs):
    task.demand(isinstance(pairs,list) and pairs and len({x['originalPin']['path'] for x in pairs})==len(pairs),'build_sources','Complete unique producer sources required')
    for pair in pairs:
        task.verify_pin(pair['snapshotPin'])
        task.demand(all(pair['snapshotPin'][k]==pair['originalPin'][k] for k in ('bytes','sha256')),'build_sources','Executed producer byte snapshot changed')


def validate_depot(pin):
    depot=task.read_json(pin)
    task.demand(depot['protocol']=='skillsbench-linux-private-wheel-depot-v1' and depot['downloadComplete'] is True
                and depot['fault'] is None and depot['dependencies']==task.REQUIREMENTS and len(depot['wheels'])==21,'build_depot','Actual complete21-wheel depot required')
    for row in depot['wheels']:
        p=row['wheelPin'];task.verify_pin(p,64*1024**2)
        upstream=task.read_json(row['upstreamJsonPin'],4*1024**2)
        matches=[x for x in upstream['urls'] if x['filename']==Path(p['path']).name]
        task.demand(len(matches)==1 and matches[0]['digests']['sha256']==row['publishedSha256']==p['sha256']
                    and matches[0]['size']==p['bytes'] and matches[0]['url']==row['downloadUrl'],'build_depot_sha','Actual wheel does not join official upstream version digest')
    task.verify_pin(depot['requirementsLockPin'])
    return depot


def validate_stage(pin,run):
    value=task.read_json(pin);layout=task.read_json(run['storageDescriptorPin']);storage.validate_descriptor(layout)
    private=value['protocol']=='skillsbench-sealed-private-runtime-v1'
    tid='private-runtime' if private else value['taskId'];box=Path(pin['path']).parent
    task.demand(tid in (*task.TASK_IDS,'private-runtime') and value['actorPid']==run['actorPid'] and value['storageDescriptorPin']==run['storageDescriptorPin']
                and value['sourceSnapshots']==run['sourceSnapshots'] and value['parentActorClosureRequired'] is True,'build_stage','Exact task/build producer/storage/sources required')
    task.demand(box.name==tid and box.parent==Path(run['sourceSnapshots'][0]['snapshotPin']['path']).parent.parent,'build_stage','Stage escaped its actual owned build directory')
    verify_snapshot_pairs(value['sourceSnapshots'])
    task.verify_pin(value['buildxBinaryPin'],128*1024**2);task.verify_pin(value['dockerPluginConfigPin'])
    rows=[];observations=[]
    for serial,entry in enumerate(value['commandRecords'],1):
        record=transport.validate_command_record(entry['recordPin'],value['actorPid'],serial,entry['argv'],box,16*1024**2)
        argv=entry['argv'];task.demand(argv[0] in (str(transport.DOCKER),value['buildxBinaryPin']['path']),'build_client','Unapproved command producer')
        if argv[0]==str(transport.DOCKER):task.demand(argv[1:3]==['--host',transport.DOCKER_HOST],'build_client','Command reached another daemon')
        child=task.read_json(record['childPin'])
        observations.append(native_identity.closed_identity(record['pid'],child['atUnixMs']));rows.append((entry,record))
    def by_stdout(p):
        matches=[(a,r) for a,r in rows if r['stdoutPin']==p]
        task.demand(len(matches)==1 and matches[0][1]['exitCode']==0,'build_raw_member','Claimed raw output is not a unique successful actual command member')
        return matches[0]
    image_arg,ir=by_stdout(value['imageInspectPin']);image=task.read_json(ir['stdoutPin'])
    task.demand(image_arg['argv'][3:]==['image','inspect',value['imageId']] and isinstance(image,list) and len(image)==1
                and image[0]['Id']==value['imageId'] and image[0]['Os']=='linux' and image[0]['Architecture']=='amd64','build_image','Actual immutable inspect/image platform differs')
    package_arg,pr=by_stdout(value['installedPackagesPin']);packages=task.read_json(pr['stdoutPin'],16*1024**2)
    probe_arg,pir=by_stdout(value['probeInspectPin']);inspection=task.read_json(pir['stdoutPin'])[0]
    owner=task.read_json(value['buildActorClosurePin']);nonce=owner.get('nonce');cid=owner.get('containerID');name=owner.get('name')
    task.demand(owner['protocol']=='skillsbench-build-probe-owned-close-v1' and owner['actorPid']==value['actorPid'] and owner['imageId']==value['imageId']
                and owner['ownedClosed'] is True and owner['fault'] is None and owner['sourceSnapshots']==value['sourceSnapshots']
                and owner['commandRecords']==value['commandRecords'] and re.fullmatch('[0-9a-f]{32}',nonce or '')
                and name=='objrun-skb-build-probe-'+nonce and re.fullmatch('[0-9a-f]{64}',cid or ''),'build_probe_owner','Actual exact owned probe/nonce/closure graph differs')
    storage.validate_instance_closure(owner['leaseClosurePin'],layout,nonce,value['actorPid'],box)
    h=inspection['HostConfig'];c=inspection['Config']
    task.demand(inspection['Id']==cid and inspection['Name']=='/'+name and inspection['Image']==value['imageId']
                and c['Labels']['objrun.skb.build-probe-nonce']==nonce and c['Labels']['objrun.skb.role']=='trusted-build-probe'
                and h['ReadonlyRootfs'] is True and h['NetworkMode']=='none' and not h.get('Binds') and not h.get('Mounts')
                and h['Memory']==h['MemorySwap']==1073741824 and h['NanoCpus']==10**9 and h['CapDrop']==['ALL'] and not h['Privileged'],
                'build_probe_namespace','Actual private package probe namespace differs')
    creates=[(a,r) for a,r in rows if a['argv'][3:4]==['create'] and '--name' in a['argv'] and a['argv'][a['argv'].index('--name')+1]==name]
    removes=[(a,r) for a,r in rows if a['argv'][3:]==['rm','-f',cid]]
    absences=[(a,r) for a,r in rows if a['argv'][3:]==['container','inspect',cid] and r['exitCode']==1]
    task.demand(len(creates)==len(removes)==len(absences)==1 and creates[0][1]['exitCode']==removes[0][1]['exitCode']==0,'build_probe_lifecycle','Exact create/remove/absence chain missing')
    from skb_artifact_ram_executor_v2 import missing_target
    ar=absences[0][1]
    task.demand(missing_target(ar['exitCode'],Path(ar['stdoutPin']['path']).read_bytes(),Path(ar['stderrPin']['path']).read_bytes(),'container',cid),'build_probe_lifecycle','Exact raw post-removal missing CID diagnostic required')
    task.demand(package_arg['argv'][3:]==['start','--attach',cid],'build_package_probe','Package receipt must come from the exact attached original trusted probe')
    builder_sources=[x for x in value['sourceSnapshots'] if Path(x['originalPin']['path']).name=='skb-ten-environment-build-v1.py']
    task.demand(len(builder_sources)==1,'build_package_code','Executed builder source missing')
    tree=ast.parse(Path(builder_sources[0]['snapshotPin']['path']).read_bytes())
    functions=[x for x in tree.body if isinstance(x,ast.FunctionDef) and x.name=='installed_probe_code']
    task.demand(len(functions)==1 and not functions[0].decorator_list and all(isinstance(x.func,ast.Name) and x.func.id=='repr' for x in ast.walk(functions[0]) if isinstance(x,ast.Call)),
                'build_package_code','Only the original literal probe-code constructor may be replayed')
    scope={'__builtins__':{'repr':repr}}
    exec(compile(ast.Module(body=functions,type_ignores=[]),'<archived-trusted-probe-constructor>','exec'),scope)
    expected_code=scope['installed_probe_code'](private)
    create_args=creates[0][0]['argv']
    task.demand(create_args[-4:]==['-I','-B','-c',expected_code] and '--entrypoint' in create_args
                and create_args[create_args.index('--entrypoint')+1]==packages['pythonPath'],'build_package_code','Actual create command did not execute the exact isolated archived trusted probe')
    recipe=value.get('aptTransportVariant') if private else value['buildRecipe'].get('aptTransportVariant')
    if recipe:
        task.demand(recipe['protocol']=='skillsbench-declared-apt-transport-variant-v2' and recipe['TLSVerificationDisabled'] is False,'build_recipe','Declared HTTPS variant required')
        for k in ('originalDockerfilePin','derivedDockerfilePin','caSourcePin','caCopiedPin'):task.verify_pin(recipe[k])
        task.demand(recipe['caSourcePin']['sha256']==recipe['caCopiedPin']['sha256']=='c55b21f907f7f86d48add093552fb5651749ff5f860508ccbb423d6c1fbd80c7','build_recipe','Reviewed CA bootstrap bytes changed')
        builds=[(a,r) for a,r in rows if a['argv'][0]==value['buildxBinaryPin']['path'] and a['argv'][1:2]==['build']]
        task.demand(len(builds)==1 and builds[0][1]['exitCode']==0 and '--file' in builds[0][0]['argv']
                    and builds[0][0]['argv'][builds[0][0]['argv'].index('--file')+1]==recipe['derivedDockerfilePin']['path'],'build_recipe','Actual successful frozen recipe command required')
    else:task.demand(tid=='jpg-ocr-stat' and value['imageId']=='sha256:92892771245d31d0b1af4a0c603effbdaf02bf62c1c055081f44a462f5261ced','build_recipe','Only exact cached JPG may omit new build')
    if private:
        depot=validate_depot(value['wheelDepotManifestPin'])
        installed={re.sub('[-_.]+','-',k).lower():v for k,v in packages['installedPackages'].items()}
        task.demand(all(installed.get(x['normalizedName'])==x['version'] for x in depot['wheels'])
                    and value['dependencies']==task.REQUIREMENTS and value['pythonVersion']==packages['pythonVersion']=='3.12.3'
                    and value['pythonPath']==packages['pythonPath']=='/opt/objrun-verifier/bin/python'
                    and value['pythonSha256']==packages['pythonSha256'] and value['runnerSourcePin']['sha256']==packages['runnerSha256']
                    and value['trustedManifestSha256']==packages['trustedManifestSha256']
                    and packages['numericAbiProbe']['arraySum']==packages['numericAbiProbe']['frameSum']==3,'build_private_runtime','Actual wheel versions/interpreter/runner/manifest/ABI differ')
        files=packages['installedRuntimeFiles']
        task.demand(files and len({x['path'] for x in files})==len(files) and all(x['path'].startswith('/opt/objrun-verifier/lib/python3.12/site-packages/') and re.fullmatch('[0-9a-f]{64}',x['sha256']) for x in files),
                    'build_private_runtime','Actual private installed source/data inventory missing')
        elf=task.read_json(value['pdftotext']['elfDependencyManifestPin']);binary=packages['pdftotext']
        task.demand(binary['path']==value['pdftotext']['path']=='/usr/bin/pdftotext' and binary['sha256']==value['pdftotext']['sha256']
                    and elf['libraries']==binary['libraries'] and elf['lddRaw']==binary['lddRaw'] and value['pdftotext']['packageReceiptPin']==value['installedPackagesPin'],
                    'build_private_binary','Actual pdftotext/ELF/apt receipt joins differ')
    else:
        d=task.descriptor(tid)
        task.demand(value['taskSourcePin']==d['taskSourcePin'] and value['environmentTreeIdentity']==d['environmentTreeIdentity']
                    and value['sourceBeforeAfterEqual'] is True and value['pythonVersion']==packages['pythonVersion'],'build_original','Original source/task/package graph differs')
        task.original_sources(tid)
    return {'taskId':tid,'stagePin':pin,'actorPid':value['actorPid'],'childObservations':observations,'immutableImageId':value['imageId'],'actualNamespaceAndProbeValidated':True}


def seal(run_pin,partial=False):
    run=task.read_json(run_pin)
    expected=list(task.TASK_IDS) if partial else [*task.TASK_IDS,'private-runtime']
    task.demand(run['protocol']=='skillsbench-ten-environment-build-actual-run-v1'
                and (run['fault'] is None if not partial else run['fault']=={'kind':'build_docker_command','type':'TaskFault'})
                and [x['taskId'] for x in run['results']]==expected and run['modelCalls']==0,'build_complete','Actual fixed-order completed environment/probe results required')
    actor=native_identity.closed_identity(run['actorPid'],int(datetime.fromisoformat(run['completedAtUtc']).timestamp()*1000));layout=task.read_json(run['storageDescriptorPin']);storage.validate_descriptor(layout)
    lease=task.read_json(run['buildLeasePin'])
    task.demand(lease['held'] is False and lease['pid']==run['actorPid'] and lease['nonce']==layout['ownerNonce'] and lease['root']==str(Path(layout['storePhysical'])),'build_closed','Actual source-bound build lease still held')
    verify_snapshot_pairs(run['sourceSnapshots'])
    checks=[validate_stage(x['stagePin'],run) for x in run['results']]
    prepared=task.read_json(run['preparedRuntimePin']);depot_closure=task.read_json(prepared['depotProducerClosurePin'])
    task.demand(depot_closure['producerClosed'] is True and depot_closure['producerReceiptPin']==prepared['wheelDepotPin'],'build_depot_closed','Actual wheel depot producer closure missing')
    storage.native_actor_absent(depot_closure['producerPid'])
    value={'protocol':PROTOCOL if not partial else 'skillsbench-solver-only-build-replay-v2','buildRunPin':run_pin,'storageDescriptorPin':run['storageDescriptorPin'],'buildLeasePin':run['buildLeasePin'],
        'producerObservation':actor,'stageChecks':checks,'depotProducerClosurePin':prepared['depotProducerClosurePin'],
        'sourcePin':task.pin(__file__),'auditorPid':os.getpid(),'observedAtUtc':datetime.now(timezone.utc).isoformat(),
        'modelCalls':0,'actualTestCollections':0,'actualColdControls':0,'paidReady':False,'scoreCertificate':False,'parentAuditorClosureRequired':True}
    if partial:value.update({'actualTenSolverImagesValidated':True,'actualPrivateImageValidated':False,'BuildKitInterruptedPrivateBuildClosureProven':False})
    path=Path(run_pin['path']).parent/('solver-only-build-replay.json' if partial else 'build-closed-catalog.json')
    from skb_artifact_ram_executor_v2 import fresh
    return fresh(path,task.canonical(value),Path(layout['storePhysical']))


def main():
    p=argparse.ArgumentParser();p.add_argument('--run',type=Path,required=True);p.add_argument('--sha256',required=True);p.add_argument('--solver-only',action='store_true');a=p.parse_args()
    rp=task.pin(a.run.resolve());task.demand(rp['sha256']==a.sha256,'build_cli','Explicit completed build pin required')
    out=seal(rp,a.solver_only);print(json.dumps({'catalogPin':out,'modelCalls':0,'paidReady':False}))


if __name__=='__main__':main()
