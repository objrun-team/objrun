"""Freeze the official automatic-only suite and the audited SciCode engine."""
import hashlib
import json
import os
from pathlib import Path
import shutil
import sys
import tomllib
import subprocess

REVISION = '6c6fe63a8c87f15e8fa05f3bcb549a3d44190b5d'
REPO = Path(__file__).resolve().parents[2]
WORKSPACE = REPO.parent
ROOT = WORKSPACE / 'tmp/theophyseval-20261016-v3'
ORIGIN = WORKSPACE / 'tmp/scibench-pilot-20261016-v1/package/engine'


def digest(p):
    return hashlib.sha256(p.read_bytes()).hexdigest()


def main():
    source = ROOT / 'source/tasks'
    public = ROOT / 'data/public'
    private = ROOT / 'data/private'
    public.mkdir(parents=True, exist_ok=True)
    private.mkdir(parents=True, exist_ok=True)
    catalog = []
    pins = []
    for task in sorted(source.iterdir()):
        if not task.is_dir() or task.name == 'autonomous-de':
            continue
        conf = tomllib.loads((task / 'task.toml').read_text(encoding='utf-8'))
        destination = public / task.name
        shutil.copytree(task / 'environment', destination / 'environment', dirs_exist_ok=True)
        units = []
        entries = [task / 'steps' / s['name'] for s in conf.get('steps', [])] or [task]
        for index, stage in enumerate(entries):
            spec = json.loads((stage / 'tests/grading_spec.json').read_text())
            assert spec['kind'] in {'numeric', 'sheet'}, (task.name, spec['kind'])
            unit_id = stage.name if len(entries) > 1 else task.name
            inst = (stage / 'instruction.md').read_text(encoding='utf-8')
            (destination / 'instructions').mkdir(parents=True, exist_ok=True)
            (destination / 'instructions' / (unit_id + '.md')).write_text(inst, encoding='utf-8')
            workdir = stage / 'workdir'
            if workdir.exists():
                shutil.copytree(workdir, destination / 'workdir' / unit_id, dirs_exist_ok=True)
            shutil.copytree(stage / 'tests', private / unit_id, dirs_exist_ok=True)
            units.append({'id': unit_id, 'parent': task.name, 'index': index, 'kind': spec['kind'],
                          'answer_path': 'final_answer.txt' if spec['kind'] == 'numeric' else f"problem{spec['problem']}/final_answer.txt",
                          'instruction': f'public/{task.name}/instructions/{unit_id}.md'})
        catalog.append({'id': task.name, 'units': units, 'resources': conf['environment']})
        for p in sorted(task.rglob('*')):
            if p.is_file():
                pins.append({'path': p.relative_to(ROOT / 'source').as_posix(), 'sha256': digest(p)})
    assert len(catalog) == 46 and sum(len(t['units']) for t in catalog) == 49
    (ROOT / 'data/catalog.json').write_text(json.dumps(catalog, indent=2) + '\n')
    (ROOT / 'data/source-pins.json').write_text(json.dumps({'repo': 'RameshChandra1/TheoPhysEval', 'revision': REVISION, 'excluded': ['autonomous-de'], 'files': pins}, indent=2) + '\n')
    package = ROOT / 'package'
    package.mkdir(exist_ok=True)
    for p in Path(__file__).parent.iterdir():
        if p.suffix in {'.py', '.ts', '.json'}:
            shutil.copyfile(p, package / p.name)
    if not (package / 'engine').exists():
        shutil.copytree(ORIGIN, package / 'engine', ignore=shutil.ignore_patterns('node_modules', '__pycache__', '.env', '.bun-cache'))
    modules = package / 'engine/app/node_modules'
    if not modules.exists():
        origin_modules = (ORIGIN / 'app/node_modules').resolve()
        if os.name == 'nt':
            subprocess.run(['cmd', '/c', 'mklink', '/J', str(modules), str(origin_modules)], check=True, capture_output=True)
        else:
            os.symlink(str(origin_modules), modules, target_is_directory=True)
    engine_files = []
    for p in sorted((package / 'engine').rglob('*')):
        if p.is_file() and not any(part in {'node_modules', '__pycache__', '.bun-cache'} for part in p.parts):
            engine_files.append({'path': p.relative_to(package).as_posix(), 'sha256': digest(p)})
    (ROOT / 'data/engine-origin.json').write_text(json.dumps({'origin': 'audited SciCode engine snapshot reused via SciBench stage', 'files': engine_files}, indent=2) + '\n')
    print(json.dumps({'root': str(ROOT), 'parents': len(catalog), 'units': 49, 'sourceFiles': len(pins)}))


if __name__ == '__main__':
    main()
