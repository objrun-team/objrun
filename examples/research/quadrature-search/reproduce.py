import csv
import hashlib
import itertools
import json
import re
from pathlib import Path
import mpmath as mp
from checker import check
from independent_check import verify

ROOT=Path(__file__).resolve().parents[3]
PREP=ROOT/'data/quadrature-search/preparation'
SOURCE=PREP/'diallo/data'
mp.mp.dps=140

def save(name, rows, source):
    path=PREP/(name+'.json')
    path.write_text(json.dumps({'domain':'prism','degree':7,'nodes':rows,'source':source},indent=2))
    report=check(path)
    report['independent']=verify(path)
    report['source_sha256']=hashlib.sha256(path.read_bytes()).hexdigest()
    (PREP/(name+'.audit.json')).write_text(json.dumps(report,indent=2))
    assert report['valid'] and report['independent']['valid'],(name,report['max_moment_error'],report['independent'].get('error'))
    print(json.dumps({'reference':name,'nodes':report['size'],'moments':report['moment_count'],'max_cartesian_error':report['max_moment_error'],'independent_error':report['independent']['max_moment_error']}))
    return rows

dw=SOURCE/'published-results/pri/expanded_hp/(degree,nodes)=(7,36).csv'
with dw.open() as f: rows=list(csv.reader(f))[1:]
save('diallo-prism-q7-n36',rows,str(dw.relative_to(PREP)))
# Reconstruct from the compact orbit listing, independently of the author's Julia expander.
mp.mp.dps=140
compact=SOURCE/'published-results/pri/compact_hp/(degree,nodes)=(7,36).txt'
lines=compact.read_text().splitlines()
counts=json.loads(lines[0]); expanded=[]; line=1
for kind,count in enumerate(counts,1):
    for unused in range(count):
        ptxt,wt=re.match(r'BigFloat\[(.*?)\]\s+(\S+)',lines[line]).groups(); line+=1
        params=[mp.mpf(s.strip()) for s in ptxt.split(',') if s.strip()]
        w=mp.mpf(wt)
        if kind in (1,2): bary=(mp.mpf(1)/3,)*3
        elif kind in (3,4): bary=(params[0],params[0],1-2*params[0])
        else: bary=(params[0],params[1],1-params[0]-params[1])
        zs=[mp.mpf(0)] if kind in (1,3,5) else [params[-1],-params[-1]]
        for b in sorted(set(itertools.permutations(bary))):
            for z in zs: expanded.append([mp.nstr(v,130) for v in (2*b[1]-1,2*b[2]-1,z,w)])
save('diallo-prism-q7-n36-reexpanded',expanded,str(compact.relative_to(PREP)))
mp.mp.dps=100
point_error=max(min(max(abs(mp.mpf(a)-mp.mpf(b)) for a,b in zip(r,s)) for s in rows) for r in expanded)
assert point_error<mp.mpf('1e-65'),point_error
# Higher-precision previous 35-node construction, in author's declared transformed frame.
mp.mp.dps=140
js=SOURCE/'jaskowiec_sukumar/cubatures_prism_sym_repository/cubature_prism_sym_p7_n35_expand.txt'
previous=[]
for line in js.read_text().splitlines():
    if not line.strip():continue
    u,v,z,w=map(mp.mpf,line.split())
    previous.append([mp.nstr(t,130) for t in (2*u-1,2*v-1,z,4*w)])
save('prior-prism-q7-n35',previous,str(js.relative_to(PREP)))
(PREP/'reproduction.json').write_text(json.dumps({'compact_vs_expanded_max_error':mp.nstr(point_error,30),'previous_mapping':'x=2u-1, y=2v-1, z=z, w=4w; matches cubaturefiling.jl get_cubature_pri_js','search_reference_policy':'Only DW36 coordinates exposed to model. Prior35 is held by controller for comparison, not search initialization.'},indent=2))
# Mutation checks exercise full moments, domain, finite-number and symmetry rejection.
bad=PREP/'negative-test.json'
for label,mutator in [
    ('weight',lambda r:r[0].__setitem__(3,'-0.1')),
    ('boundary',lambda r:r[0].__setitem__(2,'1')),
    ('nan',lambda r:r[0].__setitem__(0,'NaN')),
    ('symmetry_and_moments',lambda r:r[0].__setitem__(0,str(mp.mpf(r[0][0])+mp.mpf('1e-8')))),
]:
    changed=json.loads(json.dumps(rows));mutator(changed)
    bad.write_text(json.dumps({'domain':'prism','degree':7,'nodes':changed}))
    try: accepted=check(bad)['valid']
    except ValueError: accepted=False
    try: other_accepted=verify(bad)['valid']
    except ValueError: other_accepted=False
    assert not accepted and not other_accepted,label
print('reference reconstruction and four rejection checks passed')
