"""Copy only the host-owned SQLite engine state; no candidate code execution."""
import sqlite3,sys,time
from pathlib import Path
from prepare import HOME
source=Path(sys.argv[1]).resolve();target=Path(sys.argv[2]).resolve()
assert (HOME/'runs').resolve() in source.parents and (HOME/'runs').resolve() in target.parents
assert source.name=='h2h.sqlite' and source.is_file() and not source.is_symlink()
assert target.name=='interrupted-engine.sqlite' and not target.exists()
began=time.monotonic()
def progress(status,remaining,total):
    if time.monotonic()-began>20:
        raise TimeoutError('bounded_sqlite_engine_backup_timeout')
with sqlite3.connect('file:'+source.as_posix()+'?mode=ro',uri=True,timeout=5) as original:
    with sqlite3.connect(target,timeout=5) as backup:
        original.backup(backup,pages=128,progress=progress,sleep=0.1)
        assert backup.execute('pragma integrity_check').fetchone()[0]=='ok'
