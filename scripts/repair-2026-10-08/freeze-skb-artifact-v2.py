"""Byte snapshot exact new bench, original task trees and transitive source closure."""
import argparse
import ast
import json
from pathlib import Path
import re
import uuid
import zipfile
import skb_artifact_task_v2 as task
import skb_artifact_storage_v2 as storage
from skb_artifact_ram_executor_v2 import fresh


def main():
    p=argparse.ArgumentParser();p.add_argument('--storage',type=Path,required=True);p.add_argument('--sha256',required=True);a=p.parse_args()
    lp=task.pin(a.storage.resolve());task.demand(lp['sha256']==a.sha256,'freeze_storage','Exact initialized store required');layout=task.read_json(lp);storage.validate_descriptor(layout)
    root=Path(layout['storePhysical']);home=Path(layout['directories']['source'])/('freeze-'+uuid.uuid4().hex);home.mkdir()
    scripts=Path(__file__).parent;paths={Path(__file__).resolve()}
    def visit(path):
        path=path.resolve()
        if path in paths:return
        task.demand(task.REPO in path.parents and path.is_file() and not path.is_symlink(),'freeze_path','Source escaped exact repository');paths.add(path)
        if path.suffix in ('.ts','.tsx','.js','.mjs'):
            for name in re.findall(r"(?:from\s*|import\s*\(?\s*)['\"]([^'\"]+)['\"]",path.read_text(encoding='utf8')):
                if name.startswith('.'):
                    q=path.parent/name
                    for c in (q,q.with_suffix('.ts'),q/'index.ts'):
                        if c.is_file():visit(c);break
        elif path.suffix=='.py':
            for n in ast.walk(ast.parse(path.read_bytes())):
                names=[x.name for x in n.names] if isinstance(n,ast.Import) else [n.module or ''] if isinstance(n,ast.ImportFrom) else []
                for name in names:
                    q=scripts/(name+'.py')
                    if q.is_file():visit(q)
    for q in scripts.glob('skb*'):
        if q.is_file() and q.suffix in ('.ts','.py','.json'):visit(q)
    for q in scripts.glob('audit-skb-artifact*'):visit(q)
    for q in (task.REPO/'app/src').rglob('*.ts'):visit(q)
    for q in [task.REPO/'app/package.json',task.REPO/'package.json',task.REPO/'bun.lock',task.REPO/'scripts/repair-2026-10-08/skb-jpg-native-python.json']:
        if q.is_file():visit(q)
    for tid in task.TASK_IDS:
        for pin in task.original_sources(tid):paths.add(Path(pin['path']).resolve())
    runtime=task.REPO/'examples/benchmark/terminal-bench/.runtime'
    for q in runtime.iterdir():
        if q.is_file():paths.add(q.resolve())
    # Reuse the immutable actual full node dependency inventory, verify every byte.
    dep_pin=task.pin(task.REPO/'docs/repair-2026-10-08/campaigns/repair-2026-10-08T18-32-57-118Z/frozen-source.json')
    dep=task.read_json(dep_pin,16*1024**2)
    task.demand(len(dep['dependencyFiles'])==4100,'freeze_dependencies','Original whole dependency source inventory required')
    for row in dep['dependencyFiles']:
        q=task.REPO/row['path'];pin={'path':str(q),'bytes':row['bytes'],'sha256':row['sha256']};task.verify_pin(pin,512*1024**2);paths.add(q.resolve())
    pins=[task.pin(q) for q in sorted(paths,key=lambda q:str(q).lower())]
    budget=sum(q['bytes'] for q in pins);task.demand(budget<storage.STORE_CAP//2,'freeze_cap','Source snapshot cannot consume half the owned store')
    archive=home/'frozen-source.zip'
    with zipfile.ZipFile(archive,'x',compression=zipfile.ZIP_DEFLATED,compresslevel=6) as z:
        for q in pins:
            task.verify_pin(q,512*1024**2);z.write(q['path'],str(Path(q['path']).relative_to(task.REPO)).replace('\\','/'));task.verify_pin(q,512*1024**2)
    zip_pin=task.pin(archive);task.demand(zip_pin['bytes']<storage.STORE_CAP//2,'freeze_cap','Compressed source cap exceeded')
    out=fresh(home/'frozen-source.json',task.canonical({'protocol':'skillsbench-ten-frozen-executable-source-v2','sourcePins':pins,'archivePin':zip_pin,
        'originalDependencyInventoryPin':dep_pin,'sourceBeforeAfterEqual':True,'modelCalls':0,'paidLockAcquired':False,'sourcePin':task.pin(__file__)}),root)
    print(json.dumps({'freezePin':out,'sourceFiles':len(pins),'rawSourceBytes':budget,'archiveBytes':zip_pin['bytes'],'modelCalls':0}),flush=True)


if __name__=='__main__':main()
