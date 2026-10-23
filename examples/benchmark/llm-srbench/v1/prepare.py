"""Pin all release rows; public training files and root-only final evaluation data."""
import hashlib,json,os,pathlib,sys
import numpy as np
import pyarrow.parquet as pq
ROOT=pathlib.Path(__file__).resolve().parents[1]
EXPECTED={'lsr_transform':111,'lsr_synth_bio_pop_growth':24,'lsr_synth_chem_react':36,'lsr_synth_matsci':25,'lsr_synth_phys_osc':44}
def sha(p):
    with p.open('rb') as f:return hashlib.file_digest(f,'sha256').hexdigest()
def write(p,v):p.parent.mkdir(parents=True,exist_ok=True);p.write_text(json.dumps(v,ensure_ascii=False,indent=2)+'\n')
def main():
    public=ROOT/'data/public';private=ROOT/'data/private';public.mkdir(parents=True,exist_ok=True);private.mkdir(parents=True,exist_ok=True);private.chmod(0o700)
    catalog=[];pins=[];ids=set();references=[];canary=[]
    for subset,count in EXPECTED.items():
        found=[]
        for p in sorted((ROOT/'data/raw'/subset).glob('*.parquet')):
            f=pq.ParquetFile(p);pins.append({'path':str(p.relative_to(ROOT)),'sha256':sha(p),'bytes':p.stat().st_size,'rows':f.metadata.num_rows})
            for batch in f.iter_batches(batch_size=1):
                for row in batch.to_pylist():
                    tid=row['instance_id'];assert tid not in ids;ids.add(tid);found.append(tid)
                    key=hashlib.sha256(tid.encode()).hexdigest()[:24]
                    X=np.asarray(row['train_input'],float);y=np.asarray(row['train_output'],float).reshape(-1)
                    assert X.ndim==2 and len(X)==len(y) and len(row['input_vars'])==X.shape[1] and len(X)>=30
                    assert np.isfinite(X).all() and np.isfinite(y).all()
                    train=public/(key+'.npz');np.savez(train,X=X,y=y);train.chmod(0o644)
                    final={};lens={'train':len(y)}
                    for src,dst in [('test','id'),('ood','ood')]:
                        if src+'_input' not in row or row[src+'_input'] is None:continue
                        a=np.asarray(row[src+'_input'],float);b=np.asarray(row[src+'_output'],float).reshape(-1)
                        assert a.ndim==2 and a.shape[1]==X.shape[1] and len(a)==len(b)>0 and np.isfinite(a).all() and np.isfinite(b).all()
                        np.savez(private/(key+'-'+dst+'.npz'),X=a,y=b);lens[dst]=len(b)
                    assert ('ood' in lens)==(subset!='lsr_transform')
                    ix=np.linspace(0,len(X)-1,30,dtype=int)
                    variables={f'x{i}':str(n) for i,n in enumerate(row['input_vars'])}
                    context={'description':row['description'],'variables':variables,'trainRows':len(y),'previewIndices':ix.tolist(),'previewX':X[ix].tolist(),'previewY':y[ix].tolist(),'trainXMin':X.min(axis=0).tolist(),'trainXMax':X.max(axis=0).tolist(),'trainXMean':X.mean(axis=0).tolist(),'trainYMean':float(y.mean()),'trainYStd':float(y.std())}
                    prompt='Discover a compact scientific equation from this context and training data preview. All candidates use the SAME deterministic training-only coefficient fitter. Submit a JSON object {"expression":"p0*x0 + p1*sin(x1)","initial":[1,1]}. Variables are x0,x1,... in the supplied mapping; optional fit parameters must be contiguous p0,p1,..., at most 16. Use arithmetic + - * / ** and functions exp,log,log10,sin,cos,tan,sinh,cosh,tanh,sqrt,abs,sign,asin,acos,atan,asinh,acosh,atanh,erf,Max,Min; constants pi,E. No Python functions, attributes, imports, lookup tables or arbitrary programs. Omit parameters when constants are known. Return exactly the JSON object. No ID/OOD test data or test feedback is available. Training success requires finite predictions on EVERY training point and NMSE<=0.01.\n'+json.dumps(context,ensure_ascii=False,separators=(',',':'))
                    catalog.append({'id':tid,'key':key,'subset':subset,'dimensions':X.shape[1],'variables':row['input_vars'],'prompt':prompt,'publicSha256':hashlib.sha256(prompt.encode()).hexdigest(),'lengths':lens,'trainSha256':sha(train)})
                    references.append({'id':tid,'key':key,'expression':row['gt_expression'],'variables':row['input_vars']})
        assert len(found)==count,(subset,len(found),count)
        canary.extend(sorted(found)[:2])
    assert len(catalog)==240 and len(canary)==10
    write(public/'catalog.json',catalog);write(private/'references.json',references)
    write(ROOT/'data/manifest.json',{'repository':'pkuHaowei/llm-srbench','revision':'f4101e201952bb35cab8332b6dcf337b6df02aa8','tasks':len(catalog),'counts':EXPECTED,'canaryIds':canary,'rawFiles':pins,'catalogSha256':sha(public/'catalog.json'),'privateSha256':[{ 'name':p.name,'sha256':sha(p)} for p in sorted(private.glob('*'))]})
    print(json.dumps({'tasks':len(catalog),'canaryIds':canary,'dataManifestSha256':sha(ROOT/'data/manifest.json')}))
if __name__=='__main__':main()
