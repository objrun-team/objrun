"""No Bench content: exercise the original runtime ship branch and cleanup."""
import argparse
import json
from pathlib import Path
import time

from docker_owned import OwnedDocker
import runtime_transport_circuit_drained_20261013_next as runtime


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--output', required=True)
    parser.add_argument('--base-image', required=True)
    args = parser.parse_args()
    out = Path(args.output)
    out.mkdir(parents=True, exist_ok=False)
    native = OwnedDocker(out / 'native')
    complete = False
    shipment = None
    begin = time.monotonic()
    try:
        staged = runtime.stage_runtime(out / 'runtime')
        cid, initial, created = native.create('neutral-runtime-batch', args.base_image,
            '/bin/sh', ['-c', 'mkdir -p /app && exec sleep 300'], network='none', memory_mb=2048, cpus=1)
        native.start(cid)
        shipment = runtime.ship_runtime(native, cid, staged)
        elapsed = time.monotonic() - begin
        assert elapsed < 120, 'original_up_120_second_budget_not_met'
        assert shipment['batchShipment']['guestFullHashVerified'] is True
        assert shipment['numericPidAndClockCalibration']['measuredBeforeAnyModel'] is True
        complete = True
    finally:
        for actor, role, name in native.open_actors():
            native.remove(actor)
        native.close()
    (out / 'result.json').write_text(json.dumps({
        'complete': complete, 'neutralContentOnly': True,
        'runtimeBatchAccepted': complete, 'originalUpSeconds': 120,
        'createStartAndShipmentSeconds': elapsed, 'shipment': shipment,
        'modelCalls': 0, 'gradeCalls': 0, 'referenceCalls': 0,
    }, indent=2) + '\n')


if __name__ == '__main__':
    main()
