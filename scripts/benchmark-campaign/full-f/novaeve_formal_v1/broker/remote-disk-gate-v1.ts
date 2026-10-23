import {readFileSync} from 'node:fs';
import {evaluateDockerDisk} from '../../shared/actual-physical-disk-floor.next.ts';
export function verifyRemoteDisk(path:string) {
 const d=JSON.parse(readFileSync(path,'utf8'));
 if(!(d.protocol==='novaeve-runtime-disk-v1'&&d.dataRoot==='/data/wpx/tgengin/docker'||d.protocol==='novaeve-docker-storage-observation-v1'&&d.dockerRootDir==='/data/wpx/tgengin/docker'&&d.probeExitCode===0))throw Error('remote_disk_scope_invalid');
 const gate=evaluateDockerDisk({drive:'E:',driveType:3,freeBytes:d.freeBytes??d.availableBytes,observedAtMs:d.observedAtMs??Date.parse(d.observedAtUtc)},{nowMs:Date.now(),expectedDrive:'E:'});
 if(!gate.admissible)throw Error(gate.reason);
 return gate;
}
