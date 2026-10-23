"""Explicit zero-provider fresh D initialization. Importing this file is inert."""
from __future__ import annotations
import argparse
import hashlib
import importlib.util
import json
import os
from pathlib import Path
import shutil
import stat
import sys
import time

ROOT=Path(__file__).resolve().parents[2]
PROTOCOL='jpg-D-store-initialization-v1'

def require(value,message):
    if not value:raise RuntimeError(message)
def sha(path):
    h=hashlib.sha256()
    with Path(path).open('rb')as f:
        while block:=f.read(65536):h.update(block)
    return h.hexdigest()
def pin(path):return{'path':str(Path(path).absolute()),'bytes':Path(path).stat().st_size,'sha256':sha(path)}
def verify(p):
    f=Path(p['path']);s=f.lstat();require(stat.S_ISREG(s.st_mode)and s.st_nlink==1 and not getattr(s,'st_file_attributes',0)&0x400,'initialization_pin_regular')
    require(s.st_size==p['bytes']and sha(f)==p['sha256'],'initialization_pin_changed');return f
def read(path):return json.loads(Path(path).read_text(encoding='utf-8'))
def module(path):
    spec=importlib.util.spec_from_file_location('jpg_D_storage_initializer',path);m=importlib.util.module_from_spec(spec);spec.loader.exec_module(m);return m
def save(path,value):
    raw=(json.dumps(value,indent=2)+'\n').encode()
    with path.open('xb')as f:require(f.write(raw)==len(raw),'initialization_short_write');f.flush();os.fsync(f.fileno())
    require(path.read_bytes()==raw,'initialization_readback');return pin(path)

def prepare_materials(nonce,namespace_proof=None):
    """F-only material creation; merely naming D paths never creates them."""
    require(isinstance(nonce,str)and __import__('re').fullmatch('[0-9a-f]{32}',nonce),'material_nonce')
    sources={
        'storageSourcePin':('jpg_d_storage_profile.py','0d0b20832d60248605a3e0314aa5e029091c536dc6f80e3bccf5623da1f18c17'),
        'ramSourcePin':('jpg_private_ram_profile.py','00a9f978b9e2ae90d912a7bd48bc522107c6c0db50a6a6c91df5b800df122ee3'),
        'executorSourcePin':('jpg_private_ram_executor.py','c00404ce4700a1702572f1960877ca7ff178b12dd35e01ead356064d469a5e59'),
        'storageModulePin':('jpg-d-storage-profile.ts','afbfb9d71fcc0652acb96bbfe72c05c8ae9889821127a1bceab158fbd202c7cc')}
    pins={}
    for key,(name,want)in sources.items():
        p=pin(ROOT/'scripts/repair-2026-10-08'/name);require(p['sha256']==want,'material_reviewed_source_changed');verify(p);pins[key]=p
    review=pin(ROOT/'docs/repair-2026-10-08/jpg-D-storage-private-ram-review-r1.json');require(review['sha256']=='2e4fa6841bf562da743150c127a2343c97c6267e17b5de8147c740c97b133d8f','material_review_changed')
    reviewed=read(verify(review));base=read(verify(reviewed['baseReviewPin']));client=base['dockerClientPin'];verify(client)
    storage=module(verify(pins['storageSourcePin']));ram_path=verify(pins['ramSourcePin']);spec=importlib.util.spec_from_file_location('jpg_D_material_ram',ram_path);ram=importlib.util.module_from_spec(spec);spec.loader.exec_module(ram)
    folder=ROOT/'docs/repair-2026-10-08/jpg-D-storage-preparations'/nonce
    require(not os.path.lexists(folder),'material_refuses_existing_F_output');folder.parent.mkdir(parents=True,exist_ok=True)
    current=folder.parent
    while True:
        z=current.lstat();require(stat.S_ISDIR(z.st_mode)and not getattr(z,'st_file_attributes',0)&0x400,'material_F_ancestor_reparse')
        if current==ROOT:break
        current=current.parent;require(ROOT==current or ROOT in current.parents,'material_F_root_escape')
    folder.mkdir(exist_ok=False);descriptor=save(folder/'descriptor.json',storage.descriptor(nonce));plan=save(folder/'ram-plan.json',ram.plan(nonce))
    bundle={**pins,'descriptorPin':descriptor,'ramPlanPin':plan,'profileReviewPin':review,'dockerClientPin':client}
    if namespace_proof is not None:bundle['namespaceProofPin']=pin(namespace_proof);verify(bundle['namespaceProofPin'])
    result=save(folder/'storage-bundle.json',bundle)
    proof=save(folder/'preparation.json',{'protocol':'jpg-D-storage-material-preparation-v1','nonce':nonce,'bundlePin':result,'initializerSourcePin':pin(__file__),'modelCalls':0,'DockerOperations':0,'DWrites':0,'locksAcquired':0,'paidReady':False,'minimumTrialDistinctTasks':10,'benchmarkTrialRequirementMet':False})
    return{'storageBundlePin':result,'preparationPin':proof,'modelCalls':0,'DWrites':0,'paidReady':False}

def initialize(recipe_path):
    recipe_pin=pin(recipe_path);r=read(verify(recipe_pin));require(r['protocol']=='jpg-D-journal-recipe-v1'and r['family']=='jpg-journal-v1','initialization_recipe_family')
    storage=module(verify(r['DStorage']['storageSourcePin']));d=read(verify(r['DStorage']['descriptorPin']));storage.validate_descriptor(d)
    require(Path(r['store'])==Path(d['storePhysical'])and Path(r['output'])==Path(d['directories']['taskmeta']),'initialization_exact_stage')
    for p in r['sourcePins']:verify(p)
    require(any(p['path']==str(Path(__file__).absolute())and p['sha256']==sha(__file__)for p in r['sourcePins']),'initialization_executed_source_missing')
    free={k:shutil.disk_usage(k+':/').free for k in('C','D','F')};resources=storage.assess_resources(d,free,False,0,initial=True)
    require(resources['admitted'],'initialization_resource_guard')
    root=Path(d['storePhysical']);storage.ordinary(root.parent,Path('D:/'))
    require(not os.path.lexists(root),'initialization_refuses_existing_root');root.mkdir(exist_ok=False)
    for directory in d['directories'].values():Path(directory).mkdir(exist_ok=False)
    # A separate fixed setup lease avoids consuming the runtime/instance names.
    lease=storage.NativeStorageLease(root,d['ownerNonce']);lease.path=root/'leases/setup.lock'
    with lease:
        lease.assert_owned();storage.ordinary(root,Path('D:/'))
        before={'protocol':PROTOCOL+'-intent','family':'jpg-journal-v1','runId':r['runId'],'ownerNonce':d['ownerNonce'],'creatorPid':os.getpid(),
            'descriptorPin':r['DStorage']['descriptorPin'],'sourcePins':r['sourcePins'],'recipePin':recipe_pin,'storeLogical':d['storeLogical'],'storePhysical':d['storePhysical'],
            'directories':d['directories'],'modelCalls':0,'providerForwarded':0,'DockerOperations':0,'canonicalPaidLockAcquired':False,'scoreCertificate':False}
        intent=save(root/'taskmeta/initial-store-intent.json',before)
    final_lease=pin(lease.path);closed=read(verify(final_lease));require(closed['held']is False and closed['root']==str(root)and closed['nonce']==d['ownerNonce']and closed['pid']==os.getpid(),'initialization_setup_lease_unclosed')
    result={**before,'protocol':PROTOCOL,'intentPin':intent,'setupClosedLeasePin':final_lease,'setupNativeHandleClosed':True,'initializationSourcePin':pin(__file__),
        'initializedAtUnixMs':int(time.time()*1000),'resourceObservation':resources,'freshRootCreated':True,'actualDirectoryIdentityVerified':True,
        'allowedPreRunWrites':['bun-cache/**','python-cache/**','tmp/**'],'preRunRawJournalSqliteAndRegistryMustRemainAbsent':True,'paidReady':False,'validated':True}
    return save(root/'taskmeta/initial-store.json',result)

if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('--recipe',type=Path);p.add_argument('--prepare-materials',action='store_true');p.add_argument('--nonce');p.add_argument('--namespace-proof',type=Path);a=p.parse_args()
    if a.prepare_materials:require(a.recipe is None,'material_no_D_initialization');result=prepare_materials(a.nonce,a.namespace_proof)
    else:
        require(a.recipe is not None and a.nonce is None and a.namespace_proof is None,'initialization_explicit_recipe');result={'protocol':PROTOCOL,'initializationPin':initialize(a.recipe),'modelCalls':0,'DockerOperations':0,'paidReady':False}
    print(json.dumps(result))
