"""New, remaining-only serial phase. Prepared materials authorize no decoder.

Only an actual, separately pinned3927 recovery graph admits Run. The original
batch061 is not repaired into a64-object success, and its expired dispatch
window is not reused. Each child is the unchanged reviewed fast-v2 producer.
"""
import argparse
import ctypes
import hashlib
import importlib.util
import json
import os
from pathlib import Path
import re
import shutil
import stat
import subprocess
import threading
import time
from datetime import datetime, timezone

PROTOCOL = 'minif2f-remaining-only-serial-v1'
FAST = 'bounded-official-cache-unpack-v2-archive-dot-prefix'
RECOVERY = 'minif2f-fast-nonzero-recovery-v1'
START, TOTAL, LEFT, BATCH, PHASES, DISPATCH_SECONDS = 3927, 5826, 1899, 64, 30, 21600
FAST_SHA = 'ef0ddf5d708f6507d256af7a3c77e68c71a1eb7adda79ab7a7f19e9a246fbc09'
FAST_PS_SHA = '76485ca8d248947da978ef0a8e1070879da59ef8d3490e8a2eb56af57a5823ce'
RECOVERY_SHA = '398ea83a829e1362ee976d179b6152a8dc6879c97b11ca801f50d8149c83f9f4'
ACQUISITION_SHA = '24f91e9a9790a0d14a94e6e5f530af0fa51c8823203a94eae5d68f9cd026a368'
REPO = Path(__file__).resolve().parents[2]
ROOT = Path('E:/objrun-experiment-cache/01a119ed-fdf7-7c32-b323-de9bab1290b6/minif2f-v415')
AUDIT = ROOT / 'audit'
DOCS = REPO / 'docs/repair-2026-10-08'
RUNTIME_BYTES, F_MIN, E_MIN, E_CAP = 4 * 1024**2, 1024**3, 3 * 1024**3, 14 * 1024**3
STDOUT_LIMIT, STDERR_LIMIT, MAX_JSON, MAX_LINE = 65536, 16384, 32768, 16384
GRAPH_FIELDS = ('recoveryReviewPin', 'recoveryReceiptSnapshotPin', 'baselineSnapshotPin',
                'baselineCommitSnapshotPin', 'finalEnvelopeSnapshotPin',
                'checkClosedRecordPin', 'originalFastGatePin')


class Fault(RuntimeError):
    def __init__(self, kind, detail): super().__init__(detail); self.kind = kind


def need(value, kind, detail):
    if not value: raise Fault(kind, detail)


def now(): return datetime.now(timezone.utc).isoformat()
def digest(data): return hashlib.sha256(data).hexdigest()
def encoded(value): return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(',', ':')).encode() + b'\n'


def ordinary(path, boundary):
    p, b = Path(os.path.abspath(path)), Path(os.path.abspath(boundary))
    need(p == b or b in p.parents, 'containment', 'Path escapes the exact ordinary root')
    while True:
        z = p.lstat()
        need(stat.S_ISDIR(z.st_mode) and not getattr(z, 'st_file_attributes', 0) & 0x400,
             'ancestor', 'An ancestor is not an ordinary directory')
        if p == b: break
        p = p.parent


def regular(path):
    p = Path(path); ordinary(p.parent, ROOT if ROOT in p.parents else REPO)
    z = p.lstat()
    need(stat.S_ISREG(z.st_mode) and not getattr(z, 'st_file_attributes', 0) & 0x400,
         'nonregular', 'Expected an ordinary regular file')
    return z


def pin(path):
    p = Path(path); z = regular(p)
    with p.open('rb') as f: h = hashlib.file_digest(f, 'sha256').hexdigest()
    need(regular(p).st_size == z.st_size, 'concurrent_change', 'File length changed during its fingerprint')
    return {'path': str(p), 'bytes': z.st_size, 'sha256': h}


def verify_pin(p, f_only=True):
    need(isinstance(p, dict) and type(p.get('bytes')) is int and 0 <= p['bytes'] <= 16 * 1024**2 and
         isinstance(p.get('sha256'), str) and re.fullmatch('[0-9a-f]{64}', p['sha256']),
         'pin_schema', 'Missing, unbounded or malformed actual Pin')
    path = Path(p['path'])
    if f_only: ordinary(path.parent, REPO)
    actual = pin(path)
    need(actual['bytes'] == p['bytes'] and actual['sha256'] == p['sha256'], 'pin_changed', 'Pinned original bytes changed')
    return actual


def same_bytes(a, b): return a['bytes'] == b['bytes'] and a['sha256'] == b['sha256']


def json_file(path, maximum=MAX_JSON):
    z = regular(path); need(z.st_size <= maximum, 'json_bound', 'Metadata exceeds its fixed bound')
    with Path(path).open('rb') as f: raw = f.read(maximum + 1)
    need(len(raw) == z.st_size, 'concurrent_change', 'Metadata length changed while reading')
    try: value = json.loads(raw)
    except (ValueError, UnicodeError) as e: raise Fault('metadata_json', 'Metadata JSON is invalid') from e
    need(isinstance(value, dict), 'metadata_schema', 'Metadata must be an object')
    return value, raw


def sources(review):
    need(isinstance(review.get('sourcePins'), list), 'source_schema', 'No frozen source Pins')
    found = {}
    for p in review['sourcePins']:
        verify_pin(p); found[Path(p['path']).resolve()] = p['sha256']
    fixed = {Path(__file__).resolve(): pin(__file__)['sha256'],
        REPO / 'scripts/repair-2026-10-08/minif2f_fast_unpack_v2.py': FAST_SHA,
        REPO / 'scripts/repair-2026-10-08/minif2f_fast_unpack_v2.ps1': FAST_PS_SHA,
        REPO / 'scripts/repair-2026-10-08/minif2f_fast_nonzero_recovery.py': RECOVERY_SHA}
    need(all(found.get(p.resolve()) == h for p, h in fixed.items()),
         'source_scope', 'The new entry and exact unchanged producer/recovery sources must all be reviewed')


def load_review(path, expected):
    p = pin(path); need(p['sha256'] == expected, 'review_changed', 'Review identity differs')
    review, _ = json_file(path, 128 * 1024)
    need(review.get('protocol') == PROTOCOL and review.get('initialPrefix') == START and
         review.get('objects') == TOTAL and review.get('remainingObjects') == LEFT and
         review.get('maximumBatchCount') == BATCH and review.get('maximumBatches') == PHASES and
         review.get('maximumNextDispatchElapsedSeconds') == DISPATCH_SECONDS and
         review.get('newIndependentDispatchWindow') is True and
         review.get('oldBatch061Closed') is False and review.get('oldSerialSourceModified') is False and
         review.get('nativeV3GraphAutomaticallyAccepted') is False and
         re.fullmatch('[0-9a-f]{32}', review.get('serialNonce', '')),
         'review_scope', 'Review is not this fixed remaining-only new phase')
    sources(review); review['_actual_review_pin'] = p
    return review


def reviewed_module(name, relative, expected):
    path = REPO / relative
    need(pin(path)['sha256'] == expected, 'source_changed', 'Frozen imported source changed')
    spec = importlib.util.spec_from_file_location(name, path)
    m = importlib.util.module_from_spec(spec); spec.loader.exec_module(m)
    return m


def graph(review):
    g = review.get('actual_recovery_graph')
    need(isinstance(g, dict) and set(g) == set(GRAPH_FIELDS), 'prepared_only',
         'Prepared review has no actual separately closed3927 recovery graph')
    values = {}
    for name in GRAPH_FIELDS:
        verify_pin(g[name]); values[name] = json_file(g[name]['path'], 128 * 1024)[0]
    receipt, base = values['recoveryReceiptSnapshotPin'], values['baselineSnapshotPin']
    commit, envelope = values['baselineCommitSnapshotPin'], values['finalEnvelopeSnapshotPin']
    check, fg = values['checkClosedRecordPin'], values['originalFastGatePin']
    need(receipt.get('protocol') == RECOVERY and receipt.get('closed') is True and
         receipt.get('state') == 'recovery_closed' and receipt.get('nativeLeaseHandlesClosed') is True and
         receipt.get('processed_prefix') == START and receipt.get('recovery_objects') == 21 and
         receipt.get('base_prefix') == 3906 and receipt.get('original_requested_count') == 64 and
         receipt.get('original_batch_closed') is False and receipt.get('original_batch_exit_fabricated') is False and
         receipt.get('decoded_objects') == 0 and receipt.get('cache_unpack_complete') is False and
         receipt.get('source_sha256') == RECOVERY_SHA and receipt.get('source_before') == receipt.get('source_after') and
         all(receipt.get(k) is False for k in ('controls_executed', 'decoder_executed', 'public_get', 'llm_called', 'candidate_run')),
         'recovery_graph', 'Actual recovery cannot certify an original64 batch, decoder or complete cache')
    need(base.get('protocol') == FAST and base.get('recovery_protocol') == RECOVERY and
         base.get('state') == 'recovery_closed' and base.get('validated') is True and
         base.get('processed_prefix') == START and base.get('prefix_before') == 3906 and
         base.get('requested_count') == 0 and base.get('original_batch_closed') is False and
         base.get('reviewed_script_sha256') == RECOVERY_SHA and base.get('original_producer_sha256') == FAST_SHA and
         base.get('cache_unpack_complete') is False and base.get('lease_handle_closed') is True and
         base.get('receipts_sha256') == receipt.get('receipts_sha256') and
         base.get('commits_sha256') == receipt.get('commits_sha256') and
         same_bytes(base['recovery_receipt_pin'], g['recoveryReceiptSnapshotPin']) and
         base.get('source_before') == receipt.get('source_before') == base.get('source_after') and
         base.get('input_provenance') == receipt.get('input_provenance'),
         'recovery_graph', 'Exact new3927 baseline or its raw source graph differs')
    need(commit.get('protocol') == RECOVERY and commit.get('nonce') == receipt.get('nonce') and
         commit.get('source_sha256') == RECOVERY_SHA and commit.get('baseline_fsync_returned') is True and
         commit.get('all_native_exclusion_handles_closed') is True and
         same_bytes(commit['baseline_pin'], g['baselineSnapshotPin']) and
         same_bytes(commit['recovery_receipt_pin'], g['recoveryReceiptSnapshotPin']) and
         envelope.get('protocol') == RECOVERY and envelope.get('nonce') == receipt.get('nonce') and
         envelope.get('source_sha256') == RECOVERY_SHA and
         same_bytes(envelope['baseline_commit_pin'], g['baselineCommitSnapshotPin']) and
         type(envelope.get('final_allocation_upper_bound')) is int and envelope['final_allocation_upper_bound'] <= E_CAP,
         'recovery_graph', 'Actual fsync/closed-handle/baseline-envelope witnesses differ')
    need(check.get('protocol') == RECOVERY and check.get('validated') is True and
         check.get('processed_prefix') == START and check.get('actual_restore_pid_absent') is True and
         check.get('historical_actors_absent') is True and check.get('exact_historical_container_absent') is True and
         check.get('all_native_handles_reopened_and_closed') is True and check.get('original64_batch_closed') is False and
         check.get('full5826_closed') is False and same_bytes(check['receipt_pin'], g['recoveryReceiptSnapshotPin']) and
         same_bytes(check['baseline_pin'], g['baselineSnapshotPin']),
         'recovery_graph', 'Separate actual CheckClosed after the restorer exit is required')
    need(fg.get('protocol') == FAST and fg.get('gate_passed') is True and fg.get('objects') == TOTAL and
         fg.get('verified_prefix') == START and fg.get('input_provenance') == receipt.get('input_provenance') and
         all(fg.get(k) is False for k in ('e_write', 'public_get', 'candidate_run', 'llm_called')),
         'original_gate', 'An actual unchanged fast Gate at3927 is required')
    need(same_bytes(receipt['actual_review_pin'], g['recoveryReviewPin']),
         'recovery_graph', 'The snapshot does not bind the actual separately reviewed recovery')
    # F copies represent historical E roles by byte identity, not by pretending
    # that copied F paths are the original E paths. Original graph Pins stay intact.
    for name in ('recovery_receipt_pin', 'baseline_pin'):
        expected = AUDIT / ('cache-fast-nonzero-recovery.json' if name == 'recovery_receipt_pin' else 'cache-fast-progress.json')
        p = base[name] if name == 'recovery_receipt_pin' else commit[name]
        need(Path(p['path']).resolve() == expected.resolve(), 'graph_role', 'A historical role is not the exact canonical E path')
    return g, values


def free_space(reservation=0):
    need(shutil.disk_usage(REPO).free >= F_MIN + reservation, 'F_reserve', 'F must retain at least1GiB plus the remaining audit reservation')


def admission(review):
    sources(review); g, values = graph(review); free_space(RUNTIME_BYTES)
    recovery = reviewed_module('remaining_reviewed_recovery', 'scripts/repair-2026-10-08/minif2f_fast_nonzero_recovery.py', RECOVERY_SHA)
    rr = recovery.load_review(g['recoveryReviewPin']['path'], g['recoveryReviewPin']['sha256'])
    # This performs actual full current output/source/provenance checks and
    # actual native actors/three exclusive handle reopens, once before phase1.
    current = recovery.check_closed(rr)
    need(same_bytes(current['receipt_pin'], g['recoveryReceiptSnapshotPin']) and
         same_bytes(current['baseline_pin'], g['baselineSnapshotPin']), 'startup_changed', 'Current recovery differs from the immutable actual F graph')
    for name, relative in [('baselineCommitSnapshotPin', 'cache-fast-nonzero-baseline-commit.json'),
                           ('finalEnvelopeSnapshotPin', 'cache-fast-nonzero-final-envelope.json')]:
        need(same_bytes(pin(AUDIT / relative), g[name]), 'startup_changed', 'A mandatory actual witness changed')
    fast = reviewed_module('remaining_reviewed_fast', 'scripts/repair-2026-10-08/minif2f_fast_unpack_v2.py', FAST_SHA)
    helper = fast.load_helper(REPO)
    records, provenance = fast.inputs(REPO, ROOT, helper)
    need(len(records) == TOTAL and provenance == values['recoveryReceiptSnapshotPin']['input_provenance'], 'startup_changed', 'Frozen5826 acquisition identity differs')
    sources(review); graph(review); free_space(RUNTIME_BYTES)
    return {'recovery': recovery, 'records': records, 'source': values['recoveryReceiptSnapshotPin']['source_after'],
            'provenance': provenance, 'actualCheckClosed': current, 'graphPins': g}


def gate(review):
    a = admission(review)
    return {'protocol': PROTOCOL, 'state': 'readonly_gate_passed', 'validated': True,
        'review_pin': review['_actual_review_pin'], 'driver_source_sha256': pin(__file__)['sha256'],
        'serial_nonce': review['serialNonce'], 'initial_prefix': START, 'objects': TOTAL, 'remaining_objects': LEFT,
        'maximum_batches': PHASES, 'maximum_next_dispatch_elapsed_seconds': DISPATCH_SECONDS,
        'actual_recovery_graph': a['graphPins'], 'actual_check_closed': a['actualCheckClosed'],
        'source': a['source'], 'input_provenance': a['provenance'], 'recorded_at_utc': now(),
        'decoder_executed': False, 'e_write': False, 'public_get': False, 'llm_called': False,
        'old_original_batch061_closed': False, 'full5826_closed': False, 'native_v3_admitted': False}


def authorize(review, gate_pin, root_review_pin):
    verify_pin(gate_pin); verify_pin(root_review_pin)
    g, _ = json_file(gate_pin['path']); peer, _ = json_file(root_review_pin['path'])
    need(g.get('protocol') == PROTOCOL and g.get('validated') is True and g.get('state') == 'readonly_gate_passed' and
         g.get('serial_nonce') == review['serialNonce'] and g.get('driver_source_sha256') == pin(__file__)['sha256'] and
         g.get('review_pin') == review['_actual_review_pin'] and g.get('initial_prefix') == START and
         g.get('remaining_objects') == LEFT and g.get('actual_recovery_graph') == review.get('actual_recovery_graph'),
         'gate_binding', 'New Root admission must bind the exact actual readonly Gate')
    need(peer.get('protocol') == PROTOCOL + '-root-reviewed' and peer.get('allow_run') is True and
         peer.get('driver_source_sha256') == pin(__file__)['sha256'] and peer.get('gate_sha256') == gate_pin['sha256'] and
         peer.get('review_sha256') == review['_actual_review_pin']['sha256'] and
         peer.get('serial_nonce') == review['serialNonce'] and peer.get('initial_prefix') == START and
         peer.get('remaining_objects') == LEFT and peer.get('maximum_next_dispatch_elapsed_seconds') == DISPATCH_SECONDS and
         peer.get('new_independent_dispatch_window') is True and peer.get('native_lean_authorized') is False,
         'root_review', 'An exact separately reviewed new6h remaining-only phase is required')
    age = (datetime.now(timezone.utc) - datetime.fromisoformat(g['recorded_at_utc'])).total_seconds()
    need(0 <= age <= 600, 'gate_stale', 'New admission Gate is older than10minutes')
    return g


def native_env():
    ps = Path(os.environ.get('SystemRoot', 'C:/Windows')) / 'System32/WindowsPowerShell/v1.0/powershell.exe'
    env = dict(os.environ); env['PSModulePath'] = os.pathsep.join([str(ps.parent / 'Modules'),
        str(Path(os.environ.get('ProgramFiles', 'C:/Program Files')) / 'WindowsPowerShell/Modules')])
    return ps, env


def actual_absence(pid, cid):
    need(type(pid) is int and pid > 0 and isinstance(cid, str) and re.fullmatch('[0-9a-f]{64}', cid),
         'owner_schema', 'Actual child PID and exact CID must be valid')
    ps, env = native_env()
    code = "$ErrorActionPreference='Stop';$p=Get-CimInstance Win32_Process -Filter 'ProcessId=" + str(pid) + "' -ErrorAction Stop;[pscustomobject]@{pid=" + str(pid) + ";present=($null -ne $p)}|ConvertTo-Json -Compress"
    p = subprocess.run([str(ps), '-NoProfile', '-NonInteractive', '-Command', code], capture_output=True, timeout=30, env=env)
    need(p.returncode == 0 and len(p.stdout) <= 8192 and len(p.stderr) <= 8192, 'pid_query', 'Native exact-PID query failed')
    z = json.loads(p.stdout.decode('utf-8-sig'))
    need(z.get('pid') == pid and z.get('present') is False, 'actor_present', 'Actual child PID is still present')
    c = subprocess.run(['docker', 'inspect', '--type', 'container', '--format', '{{.Id}}', cid], capture_output=True, timeout=30)
    error = c.stderr.decode('utf-8', errors='replace')
    need(c.returncode != 0 and len(c.stdout) <= 8192 and len(c.stderr) <= 8192 and
         'no such' in error.casefold() and cid in error, 'container_present', 'Exact child container absence was not established')
    return {'pid': pid, 'actual_pid_absent': True, 'container_id': cid, 'actual_container_absent': True,
        'observed_at_utc': now(), 'pid_stdout_sha256': digest(p.stdout), 'pid_stderr_sha256': digest(p.stderr),
        'daemon_stdout_sha256': digest(c.stdout), 'daemon_stderr_sha256': digest(c.stderr)}


def raw_journals(prefix, records, expected_receipts, expected_commits):
    rp, cp = AUDIT / 'cache-unpacked.jsonl', AUDIT / 'cache-fast-commits.jsonl'
    before = (regular(rp).st_size, regular(cp).st_size); rh, ch = hashlib.sha256(), hashlib.sha256()
    end, used = 0, set()
    with rp.open('rb') as rf, cp.open('rb') as cf:
        for index in range(prefix):
            r, c = rf.readline(MAX_LINE + 1), cf.readline(MAX_LINE + 1)
            need(r.endswith(b'\n') and c.endswith(b'\n') and len(r) <= MAX_LINE and len(c) <= MAX_LINE,
                 'journal_tail', 'Committed journal has an incomplete or oversized line')
            try: row, commit = json.loads(r), json.loads(c)
            except (ValueError, UnicodeError) as e: raise Fault('journal_json', 'Actual committed journal is invalid') from e
            source = records[index]; end += len(r); rh.update(r); ch.update(c)
            need(row.get('protocol') == FAST and row.get('ltar') == source['ltar'] and
                 row.get('source_sha256') == source['sha256'] and row.get('source_bytes') == source['bytes'] and
                 row.get('source_url') == source['url'] and row.get('outputs_fsynced') is True and
                 commit.get('protocol') == FAST and commit.get('ltar') == row['ltar'] and
                 commit.get('receipt_end') == end and commit.get('receipt_line_sha256') == digest(r) and
                 commit.get('receipt_fsync_returned') is True and isinstance(row.get('files'), list) and 0 < len(row['files']) <= 8,
                 'journal_link', 'Source/order/fsync/offset/hash of the complete commit chain differs')
            for f in row['files']:
                path = f.get('path'); parts = path.split('/') if isinstance(path, str) else []
                roots = ('.lake/build/',) + tuple('.lake/packages/' + q + '/.lake/build/' for q in
                    ('plausible', 'LeanSearchClient', 'importGraph', 'proofwidgets', 'aesop', 'Qq', 'batteries', 'Cli'))
                need(parts and not any(p in ('', '.', '..') for p in parts) and '\\' not in path and ':' not in path and
                     len(parts) <= 16 and len(path.encode()) <= 256 and path.startswith(roots) and
                     not any(ord(x) < 32 or ord(x) == 127 for x in path) and path.casefold() not in used and
                     type(f.get('bytes')) is int and 0 <= f['bytes'] <= 64 * 1024**2 and
                     re.fullmatch('[0-9a-f]{64}', f.get('sha256', '')), 'output_schema', 'Output metadata is outside the original nine-tree limits')
                used.add(path.casefold())
        need(not rf.read(1) and not cf.read(1), 'journal_count', 'Unexpected extra receipt or commit')
    need((regular(rp).st_size, regular(cp).st_size) == before and rh.hexdigest() == expected_receipts and
         ch.hexdigest() == expected_commits, 'journal_changed', 'Current raw journals differ from the closed phase')
    return {'receipt_rows': prefix, 'commit_rows': prefix, 'output_records': len(used),
            'receipts_sha256': rh.hexdigest(), 'commits_sha256': ch.hexdigest()}


def closed_state(review, admission_result, prefix, before=None, count=None):
    sources(review); free_space(); g, _ = graph(review)
    # Historical immutable F evidence remains bound, but mutable current fast
    # baseline/lease are deliberately checked against this new child phase.
    need(same_bytes(pin(AUDIT / 'cache-fast-nonzero-recovery.json'), g['recoveryReceiptSnapshotPin']) and
         pin(AUDIT / 'public-cache-acquisition.lock')['sha256'] == ACQUISITION_SHA,
         'history_changed', 'Recovery receipt or original complete acquisition marker changed')
    paths = [AUDIT / x for x in ('cache-fast-progress.json', 'cache-fast-unpack.lock', 'cache-fast-container.json')]
    initial_pins = [pin(p) for p in paths]
    p, praw = json_file(paths[0]); lease, lraw = json_file(paths[1]); owner, oraw = json_file(paths[2])
    need(p.get('protocol') == FAST and p.get('state') == 'batch_closed' and p.get('validated') is True and
         p.get('processed_prefix') == prefix and p.get('reviewed_script_sha256') == FAST_SHA and
         p.get('source_before') == p.get('source_after') == admission_result['source'] and
         p.get('input_provenance') == admission_result['provenance'] and p.get('lease_handle_closed') is True and
         p.get('original_acquisition_lease_sha256') == ACQUISITION_SHA and
         p.get('cache_unpack_complete') is (prefix == TOTAL) and
         all(p.get(k) is False for k in ('controls_executed', 'candidate_run', 'llm_called', 'public_get')) and
         type(p.get('final_envelope')) is int and p['final_envelope'] <= E_CAP and
         type(p.get('ledger_peak')) is int and p['ledger_peak'] <= E_CAP,
         'phase_not_closed', 'Actual unchanged producer has not closed this precise prefix/source/resource phase')
    if before is not None:
        need(p.get('prefix_before') == before and p.get('requested_count') == count and prefix == before + count,
             'phase_range', 'Actual phase does not match its single ordered dispatch')
    need(lease.get('held') is False and lease.get('outcome') == 'batch_closed' and lease.get('stage') == FAST and
         initial_pins[1]['sha256'] == p.get('fast_lease_release_sha256') and owner.get('state') == 'removed' and
         owner.get('container_id') == p.get('worker', {}).get('container_id') and not (AUDIT / 'cache-fast-item.json').exists(),
         'phase_owner', 'A pending item or unclosed/changed owner lease remains')
    journals = raw_journals(prefix, admission_result['records'], p['receipts_sha256'], p['commits_sha256'])
    absence = actual_absence(lease['pid'], owner['container_id'])
    need([pin(x) for x in paths] == initial_pins, 'phase_changed', 'Metadata changed during its closure/absence observation')
    sources(review); free_space()
    return {'progress': p, 'absence': absence, 'journal_chain': journals, 'metadata_pins': initial_pins,
            'metadata_raw': [praw, lraw, oraw]}


def schedule(prefix, ordinal, elapsed):
    need(type(prefix) is int and type(ordinal) is int and 1 <= ordinal <= PHASES and
         prefix == START + min((ordinal - 1) * BATCH, LEFT) and START <= prefix < TOTAL,
         'dispatch_order', 'Only the fixed1899 ordered remaining objects may be dispatched')
    need(0 <= elapsed < DISPATCH_SECONDS, 'next_dispatch_limit', 'The new six-hour next-dispatch window has ended')
    return min(BATCH, TOTAL - prefix)


class Budget:
    """Only new F records; conservative4096 allocation and a fixed4MiB cap."""
    def __init__(self, output, limit=RUNTIME_BYTES): self.output, self.limit, self.allocated, self.lock = Path(output), limit, 16384, threading.RLock()
    def reserve(self, amount):
        with self.lock:
            units = max(4096, ((amount + 4095) // 4096) * 4096)
            need(self.allocated + units <= self.limit, 'audit_capacity', 'New F evidence exhausted its fixed allocation reservation')
            free_space(units); self.allocated += units
    def write(self, name, raw, maximum=MAX_JSON):
        need(Path(name).name == name and 0 <= len(raw) <= maximum, 'audit_bound', 'New audit record has an invalid name/size')
        ordinary(self.output, REPO); self.reserve(len(raw)); p = self.output / name
        with p.open('xb') as f: f.write(raw); f.flush(); os.fsync(f.fileno())
        need(p.read_bytes() == raw, 'audit_readback', 'New F evidence differs after fsync/readback')
        return pin(p)
    def save(self, name, value): return self.write(name, encoded(value))


def capture_child(command, output, ordinal, budget, env):
    """Drain both full streams, hash all bytes, store only the bounded prefix.

    Any IO/limit failure is reported after the original child exits. We never
    kill just its wrapper and then pretend the owned decoder was closed.
    """
    results = {}; sinks = {}
    for key, limit in (('stdout', STDOUT_LIMIT), ('stderr', STDERR_LIMIT)):
        budget.reserve(limit); path = output / (f'batch-{ordinal:03d}-{key}.log')
        sinks[key] = (path.open('xb'), path, limit)
    try:
        proc = subprocess.Popen(command, cwd=REPO, env=env, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
    except BaseException:
        for f, _, _ in sinks.values(): f.close()
        raise
    def drain(key, pipe):
        f, path, limit = sinks[key]; h = hashlib.sha256(); total = stored = 0; fault = None; synced = False
        try:
            while True:
                chunk = pipe.read(8192)
                if not chunk: break
                h.update(chunk); total += len(chunk)
                if fault is None and stored < limit:
                    try:
                        part = chunk[:limit - stored]; free_space(len(part) + 4096); f.write(part); stored += len(part)
                    except BaseException as e: fault = type(e).__name__
            try: f.flush(); os.fsync(f.fileno()); synced = True
            except BaseException as e: fault = fault or type(e).__name__
        except BaseException as e: fault = fault or type(e).__name__
        finally: pipe.close(); f.close()
        results[key] = {'bytes': total, 'sha256': h.hexdigest(), 'stored_bytes': stored,
            'truncated': total > limit, 'fsync_returned': synced, 'capture_fault': fault, 'pin': pin(path)}
    threads = [threading.Thread(target=drain, args=(key, getattr(proc, key))) for key in ('stdout', 'stderr')]
    for t in threads: t.start()
    returncode = proc.wait()
    for t in threads: t.join()
    need(set(results) == {'stdout', 'stderr'}, 'capture_missing', 'A full stream observer failed')
    return {'wrapper_pid': proc.pid, 'exit_code': returncode, 'streams': results}


def require_capture(result):
    need(result.get('exit_code') == 0 and all(z.get('fsync_returned') is True and z.get('truncated') is False and
         z.get('capture_fault') is None and z.get('stored_bytes') == z.get('bytes') for z in result['streams'].values()),
         'child_failed', 'Child exit or bounded durable streams are invalid; no retry or next dispatch')


def run(review, gate_pin, root_review_pin):
    need(os.name == 'nt', 'platform', 'Actual Windows host required')
    authorize(review, gate_pin, root_review_pin); a = admission(review)
    authorize(review, gate_pin, root_review_pin)  # Recheck TTL after the heavy actual check.
    output = DOCS / ('minif2f-remaining-runtime-' + review['serialNonce'])
    ordinary(output.parent, REPO); free_space(RUNTIME_BYTES); output.mkdir(exist_ok=False)
    budget = Budget(output); r = a['recovery']; own = None; failure = None; complete = False; prefix = START
    lease_path = DOCS / 'minif2f-remaining-serial-admission.lock'
    started, wall_started = time.monotonic(), now(); ps, env = native_env()
    try:
        own = r.WinFile(lease_path, fresh=True).__enter__()
        own.write({'protocol': PROTOCOL, 'held': True, 'pid': os.getpid(), 'nonce': review['serialNonce'],
                   'review_sha256': review['_actual_review_pin']['sha256'], 'started_at_utc': wall_started})
        owner = budget.save('owner.json', {'protocol': PROTOCOL, 'pid': os.getpid(), 'nonce': review['serialNonce'],
            'started_at_utc': wall_started, 'initial_prefix': START, 'objects': TOTAL, 'remaining_objects': LEFT,
            'maximum_next_dispatch_elapsed_seconds': DISPATCH_SECONDS, 'new_independent_dispatch_window': True,
            'review_pin': review['_actual_review_pin'], 'gate_pin': gate_pin, 'root_review_pin': root_review_pin,
            'driver_source_pin': pin(__file__), 'actual_recovery_graph': a['graphPins'],
            'actual_initial_check_closed': a['actualCheckClosed'], 'F_audit_reservation': RUNTIME_BYTES,
            'old_original_batch061_closed': False, 'old_serial_source_modified': False,
            'network_requests_by_coordinator': 0, 'model_calls': 0, 'native_lean_executed': False})
        print(json.dumps({'runtime_directory': str(output), 'owner_pin': owner, 'initial_prefix': START}), flush=True)
        prior = None
        for ordinal in range(1, PHASES + 1):
            sources(review); graph(review); free_space(128 * 1024)
            if prior is not None: prior = closed_state(review, a, prefix)
            count = schedule(prefix, ordinal, time.monotonic() - started)
            dispatch = budget.save(f'batch-{ordinal:03d}-dispatch.json', {'protocol': PROTOCOL,
                'ordinal': ordinal, 'prefix_before': prefix, 'requested_count': count,
                'serial_nonce': review['serialNonce'], 'driver_source_sha256': pin(__file__)['sha256'],
                'producer_source_sha256': FAST_SHA, 'wrapper_source_sha256': FAST_PS_SHA,
                'prior_progress_pin': pin(AUDIT / 'cache-fast-progress.json'),
                'actual_prior_closure': a['actualCheckClosed'] if prior is None else prior['absence'],
                'elapsed_next_dispatch_seconds': time.monotonic() - started, 'recorded_at_utc': now()})
            # Deadline is checked again after the durable intent. An unlaunched
            # intent remains evidence; it is never automatically redispatched.
            schedule(prefix, ordinal, time.monotonic() - started)
            sources(review); free_space(128 * 1024)
            result = capture_child([str(ps), '-NoProfile', '-NonInteractive', '-File',
                str(REPO / 'scripts/repair-2026-10-08/minif2f_fast_unpack_v2.ps1'),
                '-Stage', 'Batch', '-Count', str(count), '-ReviewedPythonSha256', FAST_SHA],
                output, ordinal, budget, env)
            exit_pin = budget.save(f'batch-{ordinal:03d}-exit.json', {'protocol': PROTOCOL,
                'dispatch_pin': dispatch, 'result': result, 'recorded_at_utc': now()})
            require_capture(result); sources(review)
            prior = closed_state(review, a, prefix + count, prefix, count)
            snapshots = []
            for name, raw in zip(('progress', 'lease', 'owner'), prior['metadata_raw']):
                snapshots.append(budget.write(f'batch-{ordinal:03d}-{name}.json', raw))
            closed = budget.save(f'batch-{ordinal:03d}-closed.json', {'protocol': PROTOCOL,
                'ordinal': ordinal, 'processed_prefix': prefix + count, 'requested_count': count,
                'dispatch_pin': dispatch, 'exit_pin': exit_pin, 'snapshots': snapshots,
                'actual_owned_absence': prior['absence'], 'actual_journal_chain': prior['journal_chain'],
                'producer_verified_source_unchanged': True, 'producer_whole_outputs_verified': True,
                'independent_new_decoder_execution': False, 'native_lean_executed': False, 'model_calls': 0})
            prefix += count
            print(json.dumps({'closed_prefix': prefix, 'objects': TOTAL, 'batch': ordinal, 'closed_pin': closed}), flush=True)
        need(prefix == TOTAL and prior['progress']['cache_unpack_complete'] is True, 'incomplete', 'The1899 remaining objects did not all close')
        sources(review); graph(review); free_space()
        budget.save('awaiting-owner-release.json', {'protocol': PROTOCOL, 'completed': False,
            'processed_prefix': prefix, 'awaiting_native_serial_handle_release': True,
            'elapsed_seconds': time.monotonic() - started})
        own.write({'protocol': PROTOCOL, 'held': False, 'pid': os.getpid(), 'nonce': review['serialNonce'],
                   'outcome': 'dispatch_complete', 'processed_prefix': prefix, 'closed_at_utc': now()})
        complete = True
    except BaseException as e:
        failure = e
        if own is not None and own.stream is not None:
            try: own.write({'protocol': PROTOCOL, 'held': False, 'pid': os.getpid(), 'nonce': review['serialNonce'],
                'outcome': 'infrastructure_invalid', 'processed_prefix_last_confirmed': prefix,
                'error_type': getattr(e, 'kind', type(e).__name__), 'closed_at_utc': now()})
            except BaseException: pass
        try: budget.save('failure.json', {'protocol': PROTOCOL, 'completed': False,
            'last_confirmed_prefix': prefix, 'error_type': getattr(e, 'kind', type(e).__name__),
            'error': str(e), 'automatic_retry': False, 'decoder_cleanup_performed': False,
            'model_calls': 0, 'native_lean_executed': False})
        except BaseException: pass
        raise
    finally:
        if own is not None: own.close()
    need(complete and failure is None, 'incomplete', 'Serial phase has no complete closure')
    with r.WinFile(lease_path) as h:
        marker = json.loads(h.raw())
        need(marker.get('held') is False and marker.get('nonce') == review['serialNonce'] and
             marker.get('outcome') == 'dispatch_complete', 'serial_lease', 'Actual exclusive serial lease reopen differs')
    sources(review); final = closed_state(review, a, TOTAL); graph(review); free_space()
    final_pin = budget.save('dispatch-complete.json', {'protocol': PROTOCOL + '-closed',
        'completed': True, 'producer_closed_prefix': TOTAL, 'initial_prefix': START, 'objects_dispatched': LEFT,
        'closed_batches': PHASES, 'actual_recovery_graph': a['graphPins'], 'review_pin': review['_actual_review_pin'],
        'root_review_pin': root_review_pin, 'gate_pin': gate_pin, 'serial_lease_pin': pin(lease_path),
        'native_serial_handle_closed_and_reopened': True, 'coordinator_process_absence_certified': False,
        'final_progress_pin': pin(AUDIT / 'cache-fast-progress.json'), 'actual_owned_absence': final['absence'],
        'actual_journal_chain': final['journal_chain'], 'driver_source_pin': pin(__file__),
        'elapsed_seconds': time.monotonic() - started, 'next_dispatch_limit_seconds': DISPATCH_SECONDS,
        'next_dispatch_window_reset': False, 'F_allocated_reservation_used': budget.allocated,
        'model_calls': 0, 'network_requests_by_coordinator': 0, 'native_lean_executed': False,
        'old_original_batch061_closed': False, 'independent_whole_output_audit_still_required': True,
        'native_v3_admitted': False, 'original_candidate_verdicts_certified': False})
    return {'protocol': PROTOCOL, 'completed': True, 'pin': final_pin, 'runtime_directory': str(output)}


def main():
    p = argparse.ArgumentParser(); p.add_argument('--stage', choices=['Gate', 'Run'], required=True)
    p.add_argument('--review', required=True); p.add_argument('--review-sha', required=True)
    p.add_argument('--gate'); p.add_argument('--gate-sha'); p.add_argument('--root-review'); p.add_argument('--root-review-sha')
    a = p.parse_args(); review = load_review(a.review, a.review_sha)
    if a.stage == 'Gate': result = gate(review)
    else:
        need(all((a.gate, a.gate_sha, a.root_review, a.root_review_sha)), 'prepared_only', 'Run requires its actual Gate and separate Root review')
        gp, rp = pin(a.gate), pin(a.root_review)
        need(gp['sha256'] == a.gate_sha and rp['sha256'] == a.root_review_sha, 'admission_changed', 'Actual admission bytes changed')
        result = run(review, gp, rp)
    print(json.dumps(result, ensure_ascii=False))


if __name__ == '__main__':
    try: main()
    except BaseException as e:
        import sys
        print(json.dumps({'protocol': PROTOCOL, 'completed': False, 'error_type': getattr(e, 'kind', type(e).__name__),
            'error': str(e), 'automatic_retry': False, 'public_get': False, 'llm_called': False,
            'native_lean_executed': False, 'full5826_closed': False}), file=sys.stderr)
        raise SystemExit(1)
