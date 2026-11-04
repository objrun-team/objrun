"""Read-only original-batch drain and freeze checks; touches no foreign process."""
from pathlib import Path
import hashlib
import json
import os
import shutil

def guard(original, archive_sha):
    root=Path(original); out=root/'outputs/canonical'
    read=lambda p:json.loads(p.read_text())
    s=read(out/'status.json')
    assert s['stage'] in {'complete','complete_with_exceptions'} and not s['active'] and not s['activeApiRequests']
    assert len(list((out/'results').glob('*/*.json')))==200
    assert len(list((out/'final-results').glob('*/*.json')))==200
    assert read(out/'AUDIT.json')['allPassed']
    live=[]
    for p in Path('/proc').glob('[0-9]*/cmdline'):
        try:
            if str(root).encode() in p.read_bytes():live.append(int(p.parent.name))
        except (OSError,ProcessLookupError):pass
    assert not live, 'OriginalOwnedProcessesStillLive:'+str(live)
    unresolved=[str(p.relative_to(root)) for p in (out/'calls').glob('**/dispatch.json') if not p.with_name('receipt.json').exists()]
    pending=[str(p.relative_to(root)) for p in (out/'jobs').glob('*/*.json') if not (out/'judgments'/p.parent.name/p.name).exists()]
    assert not unresolved and not pending, 'OriginalPaidQueueNotDrained'
    archive=root/(root.name+'-results.tar.gz')
    assert hashlib.sha256(archive.read_bytes()).hexdigest()==archive_sha
    for rel,sha in read(out/'source-pins.json')['files'].items():
        assert hashlib.sha256((root/rel).read_bytes()).hexdigest()==sha, 'OriginalSourceChanged:'+rel
    return {'originalProcessIdsLive':live,'unresolvedDispatches':unresolved,'pendingJobs':pending,
            'originalArchiveSha256':archive_sha,'originalStage':s['stage']}

def resources():
    cpu=os.cpu_count();load=os.getloadavg()[0]
    mem=int(next(x.split()[1] for x in Path('/proc/meminfo').read_text().splitlines() if x.startswith('MemAvailable:')))*1024
    disk=shutil.disk_usage('/var/tmp').free
    result={'cpus':cpu,'load1':load,'availableMemoryBytes':mem,'freeDiskBytes':disk}
    assert mem>8*1024**3 and disk>3*1024**3 and load<cpu*.95, 'InsufficientResourceHeadroom:'+str(result)
    return result
