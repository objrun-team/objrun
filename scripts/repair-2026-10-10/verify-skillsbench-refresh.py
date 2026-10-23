"""Zero-model original-grader 0 -> 1 -> 0 control through production Bridge.

Use one fixed task/workspace/answer label. Existing images and source-pinned
descriptors are required; missing images are reported before creating resources.
"""
import base64
import hashlib
import importlib.util
import io
import json
import os
from pathlib import Path
import subprocess
import sys
import uuid
from datetime import datetime, timezone

ROOT = Path(__file__).resolve().parents[2]
SCRIPTS = ROOT / 'scripts/repair-2026-10-08'
sys.path.insert(0, str(SCRIPTS))
import skb_artifact_task_v2 as task
import skb_artifact_storage_v2 as storage
import skb_artifact_transport_v2 as transport
from openpyxl import load_workbook
spec = importlib.util.spec_from_file_location('refresh_original_stand', SCRIPTS / 'skb-artifact-stand-v2.py')
stand = importlib.util.module_from_spec(spec)
spec.loader.exec_module(stand)


def main():
    home = ROOT / 'docs/repair-2026-10-10/skillsbench-refresh' / uuid.uuid4().hex
    home.mkdir(parents=True)
    driver_snapshot = home / 'executed-driver.py'
    driver_snapshot.write_bytes(Path(__file__).read_bytes())
    descriptor_home = ROOT / 'docs/repair-2026-10-08/skillsbench-ten-takeover-v1/actual-collections/44a33604927847d7b4519c562ed41e33'
    descriptors = [task.pin(descriptor_home / (tid + '-descriptor.json')) for tid in task.TASK_IDS]
    descriptor = task.read_json(descriptors[task.TASK_IDS.index('jpg-ocr-stat')])
    image_ids = [task.read_json(descriptor[key])['imageId'] for key in ['candidateImageProofPin', 'privateRuntimeProofPin']]
    env = {**os.environ, 'DOCKER_HOST': transport.DOCKER_HOST}
    daemon = subprocess.run([str(transport.DOCKER), 'info', '--format', '{{.ServerVersion}}'], env=env, capture_output=True, timeout=20)
    probes = []
    for image in image_ids:
        completed = subprocess.run([str(transport.DOCKER), 'image', 'inspect', image, '--format', '{{.Id}}'], env=env, capture_output=True, timeout=20)
        probes.append({'imageId': image, 'present': completed.returncode == 0 and completed.stdout.decode().strip() == image, 'exitCode': completed.returncode})
    summary = {'protocol': 'skillsbench-state-refresh-control-v1', 'taskId': 'jpg-ocr-stat', 'sourcePin': task.pin(driver_snapshot), 'standSourcePin': task.pin(SCRIPTS / 'skb-artifact-stand-v2.py'), 'observedAtUtc': datetime.now(timezone.utc).isoformat(), 'daemonReady': daemon.returncode == 0, 'imageProbes': probes, 'modelCalls': 0, 'decisions': [], 'verified': False, 'scoreCertificate': False}
    def save():
        (home / 'result.json').write_bytes(task.canonical(summary))
        print(json.dumps({'result': str(home / 'result.json'), 'verified': summary['verified'], 'decisions': summary['decisions'], 'blocker': summary.get('blocker'), 'modelCalls': 0}), flush=True)
    if daemon.returncode != 0 or not all(probe['present'] for probe in probes):
        summary['blocker'] = 'docker_daemon_unavailable' if daemon.returncode != 0 else 'required_original_solver_or_private_grader_image_missing'
        save()
        return 2

    def fresh_json(name, value):
        path = home / name
        path.write_bytes(task.canonical(value))
        return task.pin(path)
    layout_pin = fresh_json('storage-descriptor.json', storage.descriptor(uuid.uuid4().hex))
    preparation = fresh_json('preparation.json', {'protocol': 'skillsbench-ten-prepared-runtime-v1', 'taskDescriptorPins': descriptors, 'storageDescriptorPin': layout_pin, 'sourcePins': [task.pin(task.__file__), task.pin(storage.__file__)]})
    initialized = subprocess.run([sys.executable, '-B', str(SCRIPTS / 'skb-artifact-D-init-v2.py'), '--preparation', preparation['path'], '--preparation-sha256', preparation['sha256']], capture_output=True, timeout=60)
    task.demand(initialized.returncode == 0, 'refresh_initialize', 'Fresh owned storage did not initialize')
    run_id = 'repair-' + datetime.now(timezone.utc).strftime('%Y-%m-%dT%H-%M-%S-000Z')
    recipe = fresh_json('recipe.json', {'family': 'skillsbench-artifact-journal-v1', 'selectedDistinctTasks': 10, 'runId': run_id, 'draftFastFirst': True, 'taskDescriptorPins': descriptors, 'storageDescriptorPin': layout_pin})
    old_token = os.environ.get('TGENGIN_GRADER_TOKEN')
    os.environ['TGENGIN_GRADER_TOKEN'] = uuid.uuid4().hex + uuid.uuid4().hex
    bridge = None
    try:
        bridge = stand.Bridge(recipe)
        place = 'skb:' + run_id + '/skillsbench/F/0/jpg-ocr-stat'
        body = {'place': place, 'said': 'same-state-refresh-answer-label'}
        oracle = ROOT / '.phase1-data/skillsbench/vendor/skillsbench/tasks/jpg-ocr-stat/verifier/stat_oracle.xlsx'
        correct = oracle.read_bytes()
        book = load_workbook(io.BytesIO(correct))
        book.active.cell(2, 3).value = 'deliberately-wrong-refresh-control'
        buffer = io.BytesIO()
        book.save(buffer)
        book.close()
        wrong = buffer.getvalue()
        for number, artifact in enumerate([wrong, correct, wrong]):
            encoded = base64.b64encode(artifact).decode()
            command = "python3 -c \"import base64,pathlib;pathlib.Path('/app/workspace/stat_ocr.xlsx').write_bytes(base64.b64decode('" + encoded + "'))\""
            bridge.call({'place': place, 'tool': 'bash', 'args': {'command': command, 'timeout_ms': 30000}})
            verified, owner = bridge.objective(body, 'verified')
            passed, passed_owner = bridge.objective(body, 'passed')
            task.demand(verified == passed and owner == passed_owner and passed['valid'], 'refresh_grade', 'Original complete grade or same-evaluation node reuse differs')
            summary['decisions'].append(int(passed['allTestsPassed']))
            summary.setdefault('steps', []).append({'index': number, 'inputArtifactSha256': hashlib.sha256(artifact).hexdigest(), 'capturePin': bridge.captures[-1]['capturePin'], 'gradeOwnerPin': owner, 'evaluation': passed})
        summary['verified'] = summary['decisions'] == [0, 1, 0] and len(bridge.grade_pins) == 3 and len({row['capturePin']['path'] for row in bridge.captures}) == 3
    except Exception as error:
        summary['blocker'] = {'type': type(error).__name__, 'kind': getattr(error, 'kind', None), 'detail': str(error)[:300]}
    finally:
        if bridge is not None:
            summary['ownedClosure'] = bridge.remove()
        if old_token is None:
            os.environ.pop('TGENGIN_GRADER_TOKEN', None)
        else:
            os.environ['TGENGIN_GRADER_TOKEN'] = old_token
    save()
    return 0 if summary['verified'] else 1


if __name__ == '__main__':
    raise SystemExit(main())
