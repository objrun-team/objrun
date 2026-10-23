"""Read-only derivation from original SB command and session receipts.

No actor/process is created or killed. No resource or money is released here.
The original collector verifies command streams and fresh actor absence; engine
absence is reported honestly without inventing an original engine exit receipt.
"""
import argparse
import datetime
import hashlib
import importlib.util
import json
import os
from pathlib import Path
import urllib.request


def pin(path):
    path = Path(path).resolve()
    data = path.read_bytes()
    return dict(path=str(path), bytes=len(data), sha256=hashlib.sha256(data).hexdigest())


def read(p):
    assert pin(p['path']) == p, 'original_pin_mismatch'
    return json.loads(Path(p['path']).read_bytes())


def load_module(p, name):
    assert pin(p['path']) == p, 'source_pin_mismatch'
    spec = importlib.util.spec_from_file_location(name, p['path'])
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def exact_absent(process, incarnation_function):
    pid = process['pid']
    expected = process.get('incarnation') or process.get('ownerIncarnation') or process.get('identity', {}).get('incarnation')
    assert type(pid) is int and isinstance(expected, str) and expected, 'exact_process_identity_required'
    try:
        current = incarnation_function(pid)
    except OSError as error:
        # ERROR_INVALID_PARAMETER is the documented absence case for OpenProcess.
        # Access denied or any other observation failure is not process absence.
        assert error.errno == 87, 'exact_process_observation_unavailable'
        current = None
    assert current != expected, 'original_process_still_alive'
    return dict(pid=pid, originalIncarnation=expected, currentIncarnation=current,
                originalIdentityAbsent=True, numericPidReused=current is not None)


def validate_session(request, incarnation_function):
    result = read(request['sessionResultPin'])
    close = read(request['originalSessionClosePin'])
    stand = read(request['standClosePin'])
    stand_process = read(request['standProcessClosePin'])
    config = read(request['standConfigPin'])
    engine = read(request['engineIdentityPin'])
    prepared = read(request['enginePreparedPin'])
    closure = result['closure']
    assert prepared['taskId'] == request['taskId'], 'session_original_task_identity'
    assert engine['runId'] == request['runId'] == closure['cash']['runId'], 'session_original_run_identity'
    assert config['runId'] == request['runId'], 'stand_original_run_identity'
    assert result.get('complete') is True and result.get('state', {}).get('closed') is True, 'session_not_complete'
    assert closure['enginePid'] == engine['pid'] == prepared['enginePid'], 'engine_pid_binding'
    assert close['standClosure'] == stand == closure['standClosure'], 'stand_closure_binding'
    assert stand['pid'] == prepared['standPid'], 'stand_pid_binding'
    assert stand['closeObserved'] is True and stand['exitObserved'] is True and type(stand['exitCode']) is int, 'original_stand_not_closed'
    assert stand_process['pid'] == stand['pid'] and stand_process['identity'] == stand['identity'], 'stand_process_identity_binding'
    assert stand_process['closeObserved'] is True and stand_process['exitObserved'] is True and stand_process['exitCode'] == stand['exitCode'], 'original_stand_capture_not_closed'
    for stream in ('stdout', 'stderr'):
        assert pin(stand_process[stream]['path']) == stand_process[stream], 'original_stand_stream_hash'
    assert stand_process.get('truncated') == [False, False], 'original_stand_stream_truncated'
    assert pin(request['runtimeSourcePin']['path']) == request['runtimeSourcePin'], 'original_runtime_source_pin'
    runtime = Path(request['runtimeSourcePin']['path']).read_text(encoding='utf-8')
    assert runtime.index('await engine.stop()') < runtime.index('const closure=await session.close()'), 'original_awaited_engine_stop_order'
    for operation in ('stop', 'shutdown'):
        value = stand[operation]
        assert value['ok'] is True and value['ownedContainersRemaining'] == 0 and value['ownedNativeChildrenRemaining'] == 0, 'original_stand_owned_resources_open'
    assert closure['laneClosure']['closed'] is True and close['laneClosure']['closed'] is True, 'original_lane_open'
    assert closure['resourceReleasePermitted'] is True, 'session_release_not_permitted'
    cash_pin = closure['cashClosure']['cashPin']
    assert close['cashClosure']['cashPin'] == cash_pin, 'original_cash_binding'
    cash = read(cash_pin)
    assert cash['snapshot']['runId'] == request['runId'] and cash['snapshot']['pendingCount'] == 0 and cash['releasePermitted'] is True, 'original_cash_pending'
    assert result['state']['provider']['activeHandlers'] == 0, 'original_provider_handler_open'
    quiescence = closure['quiescence']
    assert quiescence['sealed'] is True and quiescence['outstanding'] == 0, 'original_engine_work_outstanding'
    observations = [exact_absent(stand, incarnation_function), exact_absent(engine, incarnation_function)]
    return dict(standClosure=stand, originalCashClosurePin=cash_pin,
                resourceOwnerPid=config['resourceOwnerPid'], originalStandOutput=config['output'],
                exactProcessObservations=observations,
                engineClosureMethod='Original runtime awaited engine.stop before returning session closure; registered exact identity is now absent.',
                originalEngineSeparateExitReceiptPresent=False, originalEngineExitCode=None)


def collect_original_commands(request):
    collector = request['collectorPin']
    assert collector['sha256'] == '6954ead74a4dc7d6f93ead965508d342a2d1bc72b545d5f5085cb82f1f5c4fa4', 'accepted_original_collector_required'
    module = load_module(collector, '_original_sb_native_closure_collector')
    activation = read(request['activationPin'])
    docker = activation['dockerHost']
    assert docker.startswith('tcp://127.0.0.1:'), 'original_private_docker_endpoint'
    previous = os.environ.get('DOCKER_HOST')
    os.environ['DOCKER_HOST'] = docker
    try:
        return module.collect_bounded_command_evidence(request['boundedEvidenceRoot'])
    finally:
        if previous is None:
            os.environ.pop('DOCKER_HOST', None)
        else:
            os.environ['DOCKER_HOST'] = previous


def derive(request):
    assert request['protocol'] == 'bench-original-sb-native-closure-request-v1'
    session_root = Path(request['sessionResultPin']['path']).resolve().parent
    assert Path(request['boundedEvidenceRoot']).resolve().is_relative_to(session_root), 'bounded_evidence_must_belong_to_actual_session'
    for name in ('originalSessionClosePin', 'standClosePin', 'standProcessClosePin', 'standConfigPin', 'engineIdentityPin', 'enginePreparedPin'):
        assert Path(request[name]['path']).resolve().is_relative_to(session_root), 'original_session_receipt_root_binding'
    processes = load_module(request['processesPin'], '_original_sb_native_closure_processes')
    session = validate_session(request, processes.incarnation)
    assert Path(request['boundedEvidenceRoot']).resolve().is_relative_to(Path(session['originalStandOutput']).resolve()), 'bounded_evidence_original_stand_root'
    evidence = collect_original_commands(request)
    observations = session['exactProcessObservations']
    for command in evidence['commands']:
        observations.append(exact_absent(command, processes.incarnation))
    owner = read(request['resourceOwnerPin'])
    release = read(request['resourceReleasePin'])
    assert release.get('released') is True, 'actual_resource_release_receipt_required'
    owner_inc = owner.get('ownerIncarnation') or owner.get('incarnation')
    assert type(owner['pid']) is int and isinstance(owner_inc, str), 'exact_resource_owner_required'
    assert owner['pid'] == session['resourceOwnerPid'], 'original_session_resource_owner_binding'
    assert release.get('pid') == owner['pid'] and release.get('ownerIncarnation') == owner_inc, 'exact_resource_release_binding'
    endpoint = request['brokerHealthUrl']
    assert endpoint.startswith('http://127.0.0.1:') and endpoint.endswith('/health'), 'private_broker_health_endpoint'
    with urllib.request.urlopen(endpoint, timeout=5) as response:
        health = json.load(response)
    assert health['healthy'] is True, 'broker_unhealthy'
    assert not any(x['pid'] == owner['pid'] and x.get('ownerIncarnation') == owner_inc for x in health['resourceSlots']), 'original_resource_still_held'
    return dict(protocol='bench-derived-original-native-closure-v1', artifactOrigin='derived-from-original-receipts',
                taskId=request['taskId'], runId=request['runId'],
                sourceRequest=request, sessionEvidence=session, boundedCommandEvidence=evidence,
                exactProcessObservations=observations,
                allActorsClosed=True, allNativeCommandsClosed=True,
                exactOwnedContainerApi404=evidence['actorAbsences'], originalCommands=len(evidence['commands']),
                resourceReleased=True, brokerLaneClosed=True,
                freshResourceOwnerObservation=dict(pid=owner['pid'], incarnation=owner_inc, absent=True),
                financialClosureIsSeparatelyVerifiedByOriginalAdapter=True,
                atUtc=datetime.datetime.now(datetime.timezone.utc).isoformat())


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('--request', required=True)
    parser.add_argument('--output', required=True)
    args = parser.parse_args()
    request = json.loads(Path(args.request).read_bytes())
    result = derive(request)
    result['requestPin'] = pin(args.request)
    target = Path(args.output).resolve()
    with target.open('x', encoding='utf-8', newline='\n') as stream:
        json.dump(result, stream, indent=2)
        stream.write('\n')
    print(json.dumps(dict(complete=True, outputPin=pin(target))))
