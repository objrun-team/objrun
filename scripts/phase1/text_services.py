"""Start only the small, owned text graders; reuse the existing scientific image."""
import argparse
import json
import hashlib
from pathlib import Path
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[2]
PORTS = {'gpqa':17903, 'cmt':17901, 'aime':17905, 'chembench':17906, 'chemiq':17907, 'atmossci-bench':17924, 'lab-bench':17925}
ENV_NAMES = {'gpqa':'TGENGIN_GPQA_HOME', 'cmt':'TGENGIN_CMT_HOME', 'aime':'TGENGIN_AIME_HOME', 'chembench':'TGENGIN_CHB_HOME', 'chemiq':'TGENGIN_CHEMIQ_HOME', 'lab-bench':'TGENGIN_LAB_HOME', 'atmossci-bench':'TGENGIN_ATMOS_HOME'}
IMAGE = 'objrun-scicode:phase1'

def command(slug, action):
    file = 'grader.py' if slug == 'cmt' else 'stand.py'
    owned = 'objrun-phase1-' + slug
    argv = ['docker', 'run', '--read-only', '--cap-drop', 'ALL', '--security-opt', 'no-new-privileges', '--memory', '1g', '--cpus', '2', '--pids-limit', '128', '--tmpfs', '/tmp:rw,nosuid,size=128m']
    if action == 'start': argv += ['-d', '--name', owned, '-p', f'127.0.0.1:{PORTS[slug]}:{PORTS[slug]}']
    else: argv += ['--rm', '--network', 'none']
    for source, target in [(ROOT / f'examples/benchmark/{slug}/{file}', f'/app/{slug}/{file}'), (ROOT / 'examples/benchmark/_lib/gradelib.py', '/app/_lib/gradelib.py'), (ROOT / f'.phase1-data/{slug}', '/oracle'), (ROOT / '.phase1-data/python-extras', '/extras')]:
        argv += ['--mount', f'type=bind,source={source},target={target},readonly']
    argv += ['-e', ENV_NAMES[slug] + '=/oracle', '-e', 'PYTHONPATH=/extras', '-e', 'PYTHONDONTWRITEBYTECODE=1', '-e', 'MPLCONFIGDIR=/tmp/matplotlib']
    argv += [IMAGE, 'python', f'/app/{slug}/{file}']
    argv += ['--port', str(PORTS[slug]), '--bind', '0.0.0.0'] if action == 'start' and slug in ['aime','chembench','chemiq'] else ['--port', str(PORTS[slug])] if action == 'start' else ['--selftest']
    if slug in ['gpqa','aime','chembench','chemiq']: argv += ['--level', '0']
    return argv

def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('action', choices=['start','selftest','stop'])
    ap.add_argument('benchmarks', nargs='+', choices=list(PORTS))
    args = ap.parse_args()
    failures = []
    for slug in args.benchmarks:
        if args.action == 'stop':
            result = subprocess.run(['docker','rm','-f','objrun-phase1-' + slug], capture_output=True, text=True, encoding='utf-8')
        else:
            result = subprocess.run(command(slug, args.action), capture_output=True, text=True, encoding='utf-8', timeout=300)
        if args.action == 'selftest':
            output = ROOT / f'docs/phase1/{slug}-selfcheck.json'
            try: detail = json.loads(result.stdout)
            except ValueError:
                private = ROOT / f'.phase1-data/selfchecks/{slug}.log'
                private.parent.mkdir(parents=True,exist_ok=True)
                private.write_text(result.stdout + '\n' + result.stderr,encoding='utf-8')
                detail = {'privateLog':str(private),'logSha256':hashlib.sha256(private.read_bytes()).hexdigest()}
            output.write_text(json.dumps({'benchmark':slug,'image':IMAGE,'allPassed':result.returncode==0,'returncode':result.returncode,'details':detail}, indent=2) + '\n',encoding='utf-8')
        print(json.dumps({'benchmark':slug,'action':args.action,'returncode':result.returncode,'output':result.stdout[-1200:] if args.action!='selftest' else 'Private raw self-check log; see sanitized evidence JSON','error':result.stderr[-1000:] if result.returncode else ''}), flush=True)
        if result.returncode: failures.append(slug)
    return 1 if failures else 0

if __name__ == '__main__': sys.exit(main())
