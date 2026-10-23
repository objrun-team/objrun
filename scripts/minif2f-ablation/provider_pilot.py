"""Fresh provider pilot: share fixed dependencies, never previous model attempts."""
from pathlib import Path
import hashlib
import json
import shutil
import subprocess
import time

def prepare(project, destination, environment_file):
    project, destination, environment_file = map(Path, (project, destination, environment_file))
    assert destination.parent == project / 'pm-runtime/runs'
    assert not destination.exists(), 'Provider pilot already prepared; inspect instead of overwrite'
    baseline = destination.with_name('minif2f-pilot-20261019-v1')
    original = json.loads((baseline / 'outputs/environment.json').read_text())
    subprocess.run(['/data/ProjectManagement/.pm/bin/pm-runtime-env', str(project), destination.name,
                    str(environment_file)], cwd=project, check=True, capture_output=True, text=True)
    out = destination / 'outputs'; out.mkdir(exist_ok=True)
    (destination / 'assets').symlink_to(baseline / 'assets', target_is_directory=True)
    assets = destination / 'assets'
    for path, field in [('repl-bin', 'replSha256'), ('tools/leantar', 'leantarSha256')]:
        assert hashlib.sha256((assets / path).read_bytes()).hexdigest() == original[field]
    environment = dict(original, isolation='bubblewrap unshare-all, env -i, fresh tmpfs, readonly dependencies',
                       atUtc=time.strftime('%Y-%m-%dT%H:%M:%SZ', time.gmtime()))
    (out / 'environment.json').write_text(json.dumps(environment, indent=2) + '\n')
    shutil.copy2(baseline / 'dependency-bundle.json', destination / 'dependency-bundle.json')
    provenance = {'baselineAssetsRoot': str(baseline / 'assets'), 'dependencyBundleSha256': original['bundleSha256'],
        'newProvider': 'deepinfra/fp8', 'modelUnchanged': 'deepseek/deepseek-v4-flash-0731',
        'sameFixedValid12Tasks': True, 'previousCandidatesReused': False, 'previousGradesReused': False,
        'previousCallsOrLedgerReused': False, 'formal244Authorized': False,
        'scientificProtocol': 'medium, temperature=0, 16384 tokens, max5, 3600 seconds, $0.10 per arm-task',
        'reason': 'User selected DeepInfra after Fireworks+0731 returned HTTP404 with no generation'}
    (out / 'provider-switch.json').write_text(json.dumps(provenance, indent=2) + '\n')
    print(json.dumps({'prepared': str(destination), 'environmentFile': str(environment_file), 'previousResultsReused': False}))
