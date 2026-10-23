"""Fresh, coordinator-observed remote daemon storage; never local drive substitution."""
import json
import time
from pathlib import Path

def remote_disk(root):
    path = Path(root) / 'docs/repair-2026-10-10/full-f-rerun/novaeve-formal-20261013/broker/remote-disk.json'
    value = json.loads(path.read_bytes())
    assert value['protocol'] == 'novaeve-runtime-disk-v1'
    assert value['dataRoot'] == '/data/wpx/tgengin/docker'
    age = int(time.time() * 1000) - value['observedAtMs']
    assert 0 <= age <= 30000, 'Remote physical disk observation stale'
    assert isinstance(value['freeBytes'], int) and not isinstance(value['freeBytes'], bool)
    assert value['freeBytes'] >= 5 * 1024**3, 'Remote physical disk below original 5GiB floor'
    return {'sourcePath': str(path), 'daemonEndpoint': 'tcp://127.0.0.1:18750', **value}
