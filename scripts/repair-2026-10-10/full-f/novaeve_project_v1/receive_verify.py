"""Verify staged evidence, then atomically mark it locally archived."""
import argparse
import hashlib
import json
from pathlib import Path

def main():
    parser=argparse.ArgumentParser();parser.add_argument('root',type=Path);parser.add_argument('runs',nargs='+');args=parser.parse_args()
    root=args.root.resolve();receipts=[]
    for run in args.runs:
        if '/' in run or '\\' in run or not run.startswith('smoke-'):raise ValueError('invalid_run_id')
        source=(root/(run+'.partial')).resolve();target=(root/run).resolve()
        assert source.parent==root and target.parent==root
        if not source.exists() and target.exists():source=target
        manifest=json.loads((source/'manifest.json').read_text())
        assert manifest['runId']==run
        size=0
        for item in manifest['files']:
            path=(source/item['path']).resolve()
            assert source in path.parents and path.is_file() and not path.is_symlink()
            raw=path.read_bytes();assert len(raw)==item['bytes'] and hashlib.sha256(raw).hexdigest()==item['sha256'],str(path)
            size+=len(raw)
        digest=hashlib.sha256((source/'manifest.json').read_bytes()).hexdigest()
        if source!=target:
            assert not target.exists();source.rename(target)
        receipts.append({'runId':run,'manifestSha256':digest,'verifiedFiles':len(manifest['files']),
                         'verifiedBytes':size,'localDirectory':str(target),'archivedComplete':True})
    receipt=root/'local-receipt.json';receipt.write_text(json.dumps(receipts,indent=2)+'\n')
    print(json.dumps(receipts))

if __name__=='__main__':main()
