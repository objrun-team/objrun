"""Record the actual native Python process, then run a frozen script in-place."""
from __future__ import annotations
import argparse
import hashlib
import json
import os
from pathlib import Path
import runpy
import sys
import time


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--receipt', type=Path, required=True)
    parser.add_argument('--nonce', required=True)
    parser.add_argument('--home', type=Path, required=True)
    parser.add_argument('--script', type=Path, required=True)
    parser.add_argument('arguments', nargs=argparse.REMAINDER)
    args = parser.parse_args()
    if len(args.nonce) != 64 or any(c not in '0123456789abcdef' for c in args.nonce):
        raise RuntimeError('Invalid lifecycle nonce')
    receipt, home = args.receipt.resolve(), args.home.resolve()
    part = receipt.with_name(receipt.name + '.part')
    if receipt.parent != home or not home.is_dir() or receipt.exists() or part.exists():
        raise RuntimeError('Fresh owned lifecycle receipt is required')
    executable = Path(sys.executable).resolve()
    identity = {
        'protocol': 'jpg-native-python-service-lifecycle-v2',
        'pid': os.getpid(), 'parentPid': os.getppid(),
        'executable': str(executable),
        'executableSha256': hashlib.sha256(executable.read_bytes()).hexdigest(),
        'home': str(home), 'nonce': args.nonce,
        'startedAtUnixMs': int(time.time() * 1000), 'pythonVersion': sys.version,
        'sameProcessExecution': True,
    }
    raw = (json.dumps(identity, indent=2) + '\n').encode('utf-8')
    with part.open('xb') as handle:
        handle.write(raw)
        handle.flush()
        os.fsync(handle.fileno())
    if part.read_bytes() != raw:
        raise RuntimeError('Lifecycle receipt readback mismatch')
    # A reader cannot observe a half-written JSON receipt. Failure preserves
    # this owned part and stops startup; it is never silently adopted/deleted.
    part.rename(receipt)
    os.environ['OBJRUN_JPG_LIFECYCLE_NONCE'] = args.nonce
    arguments = args.arguments[1:] if args.arguments[:1] == ['--'] else args.arguments
    sys.argv = [str(args.script.resolve()), *arguments]
    runpy.run_path(str(args.script.resolve()), run_name='__main__')


if __name__ == '__main__':
    main()
