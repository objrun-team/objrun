"""Immutable no-verifier conversion image entry point; never use model packages."""
import base64
import hashlib
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys

def main():
    assert sys.flags.isolated and sys.dont_write_bytecode
    config=json.loads(Path('/opt/objrun/converter.json').read_bytes())
    for pin in config['sourcePins']:assert hashlib.sha256(Path(pin['path']).read_bytes()).hexdigest()==pin['sha256']
    sys.path.insert(0,'/opt/objrun')
    from excel_conversion_protocol import PROTOCOL,PROFILES,MAXIMUM_BYTES,MAXIMUM_FILES,decode
    task=config['taskId'];profile=PROFILES[task]
    assert config['profile']==profile and os.getcwd()==config['workingDirectory']
    assert not Path('/verifier').exists() and not Path('/oracle').exists()
    shutil.copytree('/opt/objrun/public-fixtures',config['fixtureDestination'],dirs_exist_ok=True)
    raw=sys.stdin.buffer.read(12*1024**2+1);assert len(raw)<=12*1024**2
    incoming=json.loads(raw);assert set(incoming)=={'artifacts'} and len(incoming['artifacts'])<=1
    workbook=Path(profile['workbook'])
    for row in incoming['artifacts']:
        assert set(row)=={'path','base64','sha256'} and row['path']==str(workbook)
        body=base64.b64decode(row['base64'],validate=True);assert len(body)<=MAXIMUM_BYTES and hashlib.sha256(body).hexdigest()==row['sha256']
        assert not workbook.is_symlink();workbook.write_bytes(body)
    source_sha=hashlib.sha256(workbook.read_bytes()).hexdigest() if workbook.exists() else hashlib.sha256(b'').hexdigest()
    binary=Path('/usr/bin/ssconvert');binary_sha=hashlib.sha256(binary.read_bytes()).hexdigest();assert binary_sha==config['converterSha256']
    # Existing fixture CSV is never accepted as a new conversion result.
    for file in Path(profile['csvPrefix']).parent.glob('sheet.csv.*'):
        assert file.is_file() and not file.is_symlink();file.unlink()
    code=0
    if workbook.exists():
        # Same argv as the original test.sh, with no shell/model executable.
        outcome=subprocess.run([str(binary),'-S',str(workbook),profile['csvPrefix']],stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL,timeout=config['originalVerifierSeconds'])
        code=outcome.returncode
        assert hashlib.sha256(workbook.read_bytes()).hexdigest()==source_sha
    rows=[];total=0
    for file in sorted(Path(profile['csvPrefix']).parent.glob('sheet.csv.*')):
        assert file.is_file() and not file.is_symlink();assert file.stat().st_size<=MAXIMUM_BYTES
        body=file.read_bytes();total+=len(body);assert total<=MAXIMUM_BYTES and len(rows)<MAXIMUM_FILES
        rows.append({'path':str(file),'base64':base64.b64encode(body).decode(),'sha256':hashlib.sha256(body).hexdigest()})
    value={'protocol':PROTOCOL,'taskId':task,'sourceSha256':source_sha,'sourceExists':workbook.exists(),'converterExitCode':code,'converterSha256':binary_sha,'derivedCsv':rows}
    encoded=json.dumps(value,separators=(',',':')).encode();decode(encoded,task,source_sha)
    assert hashlib.sha256(binary.read_bytes()).hexdigest()==binary_sha
    print(encoded.decode())

if __name__=='__main__':main()
