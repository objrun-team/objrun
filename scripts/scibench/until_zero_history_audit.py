"""Compare immutable archived SQLite snapshots to live historical rows, read-only."""
from pathlib import Path
import hashlib,json,sqlite3,sys,tarfile,tempfile
sha=lambda raw:hashlib.sha256(raw).hexdigest()
history=json.load(sys.stdin);checked=[]
for b in history:
 root=Path(b['root']);archive=root/(root.name+'-results.tar.gz');assert sha(archive.read_bytes())==b['archiveSha256']
 plan_path=root/'package/repair-plan.json';repair=plan_path.exists();meta=json.loads((plan_path if repair else root/'package/continuation.json').read_text());name='provenance/attempts-final.sqlite' if repair else 'provenance/global-registry-final.sqlite'
 with tarfile.open(archive) as t:raw=t.extractfile(name).read()
 assert sha((root/name).read_bytes())==sha(raw),'ImmutableRegistrySnapshotChanged'
 temporary=tempfile.TemporaryDirectory(prefix='scibench-history-audit-',dir='/var/tmp/tgengin-scibench-20261016/ops');snap_path=Path(temporary.name)/'snapshot.sqlite';snap_path.write_bytes(raw)
 snapshot=sqlite3.connect('file:'+str(snap_path)+'?mode=ro',uri=True);db=sqlite3.connect('file:'+meta['registryPath']+'?mode=ro',uri=True)
 tables=['attempts'] if repair else ['tasks','dispatch_origins']
 for table in tables:
  clause=' WHERE roundNo='+str(meta['roundNo']) if meta.get('mode')=='until_zero' else ''
  query='SELECT * FROM '+table+clause+' ORDER BY 1,2';assert list(snapshot.execute(query))==list(db.execute(query)),'HistoricalRegistryRowsChanged:'+root.name
 snapshot.close();db.close();temporary.cleanup();checked.append({'run':root.name,'snapshotSha256':sha(raw)})
print(json.dumps({'allPassed':True,'batches':checked,'historicalRowsMatchArchivedSnapshots':True,'readOnly':True}))
