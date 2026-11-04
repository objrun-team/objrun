"""Protected evidence intake; primary proofs require independent host review.
Does not execute any model-provided code or accept natural-language self-certification.
"""
from pathlib import Path
import json,sys,hashlib,shutil,subprocess,datetime
PRIMARY={'proof_ge_1','proof_gt_1','counterexample'}
SECONDARY={'improved_bound','partial_lemma','obstruction'}
def sha(p):return hashlib.sha256(Path(p).read_bytes()).hexdigest()
def safe(work,name):
    p=Path(name)
    assert not p.is_absolute() and '..' not in p.parts and ':' not in str(p),'unsafe evidence path'
    actual=(work/p).resolve();assert actual.is_relative_to(work.resolve()) and actual.is_file(),'missing/outside evidence'
    return actual
def main(run,artifact,out):
    run=Path(run);work=run/'work';artifact=Path(artifact);out=Path(out)
    obj=json.loads(artifact.read_text(encoding='utf-8-sig'))
    assert isinstance(obj,dict)
    if obj.get('method')=='calibration':
        candidate=run/'baseline/prior-candidate.json';cert=out.with_suffix('.calibration-cert.json')
        p=subprocess.run([sys.executable,str(run/'checker/ball_check.py'),str(candidate),str(cert)],capture_output=True,text=True)
        report=json.loads(p.stdout);assert report['valid'] and report['improved']
        replay=subprocess.run([sys.executable,str(run/'checker/ball_replay.py'),str(cert)],capture_output=True,text=True)
        second=json.loads(replay.stdout);assert second['independent_replay_passed']
        return {'valid':True,'primary_passed':False,'calibration_only':True,'prior_bound_reproduced':True}
    kind=obj.get('claim_type');assert kind in PRIMARY|SECONDARY,'claim_type required'
    assert isinstance(obj.get('statement'),str) and obj['statement'].strip(),'statement required'
    proof=safe(work,obj['proof_path']);assert proof.stat().st_size>100,'complete derivation required'
    names=list(dict.fromkeys([obj['proof_path']]+obj.get('files',[])))
    files={name:sha(safe(work,name)) for name in names}
    assert 'candidate.json' not in names and 'manifest.json' not in names,'reserved bundle filenames'
    files['candidate.json']=sha(artifact)
    digest=hashlib.sha256(json.dumps(files,sort_keys=True,separators=(',',':')).encode()).hexdigest()
    bundle=run/'verified/bundles'/digest;bundle.mkdir(parents=True,exist_ok=True)
    for name in names:
        p=safe(work,name);target=bundle/name;target.parent.mkdir(parents=True,exist_ok=True)
        if not target.exists():shutil.copy2(p,target)
        assert sha(target)==files[name],'immutable bundle mismatch'
    if not (bundle/'candidate.json').exists():shutil.copy2(artifact,bundle/'candidate.json')
    assert sha(bundle/'candidate.json')==files['candidate.json']
    (bundle/'manifest.json').write_text(json.dumps({'files':files,'bundle_sha256':digest},indent=2))
    result={'valid':True,'primary_passed':False,'claim_type':kind,'bundle_sha256':digest,'bundle':str(bundle),'candidate_sha256':sha(artifact),'requires_host_review':kind in PRIMARY,'unproved_steps':obj.get('unproved_steps',[]),'reason':'Evidence captured; no primary theorem accepted by intake.'}
    if obj.get('method')=='ball_average_v1':
        cert=out.with_suffix('.ball-certificate.json')
        p=subprocess.run([sys.executable,str(run/'checker/ball_check.py'),str(artifact),str(cert)],capture_output=True,text=True)
        result['secondary_check']=json.loads(p.stdout)
        if result['secondary_check'].get('valid') and result['secondary_check'].get('improved'):
            q=subprocess.run([sys.executable,str(run/'checker/ball_replay.py'),str(cert)],capture_output=True,text=True)
            result['secondary_replay']=json.loads(q.stdout)
        result['reason']='Uniform bound below1 is secondary only and cannot satisfy this round primary goal.'
    receipt=run/'reviews'/(digest+'.json')
    if kind in PRIMARY and receipt.exists():
        rev=json.loads(receipt.read_text(encoding='utf-8'))
        assert rev['bundle_sha256']==digest and rev['claim_type']==kind
        assert rev['primary_passed'] is True and rev['all_quantifiers_and_boundaries_verified'] is True and rev['independent_replay_passed'] is True
        for key in ('review_report','replay_report'):
            p=safe(run/'reviews',rev[key]);assert sha(p)==rev[key+'_sha256']
        assert not obj.get('unproved_steps'),'cannot accept unresolved proof steps'
        result.update(primary_passed=True,requires_host_review=False,host_review=rev,reason='Protected independent mathematical review and replay accepted.')
    return result
if __name__=='__main__':
    try:r=main(*sys.argv[1:4])
    except Exception as e:r={'valid':False,'primary_passed':False,'reason':str(e)}
    print(json.dumps(r))
