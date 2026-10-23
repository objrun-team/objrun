"""Shard large exclusion ledgers without changing any retained record payload."""
import argparse,json,pathlib
from export_records import JsonShards,encoded

def main():
    ap=argparse.ArgumentParser(description=__doc__);ap.add_argument('--root',type=pathlib.Path,required=True);a=ap.parse_args();root=a.root.resolve(strict=True);changed=[]
    for path in sorted((root/'reports').glob('preparation-*.json')):
        if path.stat().st_size<=8*1024*1024:continue
        report=json.loads(path.read_text(encoding='utf-8'));rows=report.get('resource_exclusions',[])
        if not rows:continue
        stream=JsonShards(root,path.stem+'-resource-exclusions')
        for row in rows:stream.write(row)
        shards=stream.finish();assert all(s['bytes']<=25*1024*1024 for s in shards)
        report['resource_exclusion_shards']=shards;report['resource_exclusion_count']=len(rows);report['resource_exclusions']=[]
        path.write_bytes(encoded(report));changed.append(dict(report=path.relative_to(root).as_posix(),rows=len(rows),shards=len(shards)))
    print(json.dumps(changed))

if __name__=='__main__':main()
