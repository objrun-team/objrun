"""Admission list for this Bench's frozen official candidate image references."""
import json,tomllib
from pathlib import Path
from prepare import OUT,sha


def official_candidate_records():
    manifest=json.loads((OUT/'manifest.json').read_bytes())
    assert manifest['source']['commit']=='7131e4375048a0e408a8fb404b5f499d726b695b'
    assert manifest['plannedTaskRuns']==89 and len(manifest['records'])==89
    assert len({row['taskId'] for row in manifest['records']})==89
    records={}
    for row in manifest['records']:
        task_pin=next(pin for pin in row['sourceFiles'] if Path(pin['path']).name=='task.toml')
        assert sha(Path(task_pin['path']))==task_pin['sha256']
        env=tomllib.loads(Path(task_pin['path']).read_text(encoding='utf-8'))['environment']
        assert env['docker_image']==row['officialEnvironment']['docker_image']
        records[row['taskId']]=row
    return records


def candidate_image_proof(task_id):
    row=official_candidate_records()[task_id]
    directory=OUT/'private-context-v1/candidate-environments'/task_id
    path=directory/'image-proof.json';proof=json.loads(path.read_bytes())
    assert proof['protocol']=='terminal-official-candidate-image-v1' and proof['taskId']==task_id
    assert proof['complete'] and proof['officialReference']==row['officialEnvironment']['docker_image']
    assert proof['manifestSha256']==sha(OUT/'manifest.json')
    return proof,directory
