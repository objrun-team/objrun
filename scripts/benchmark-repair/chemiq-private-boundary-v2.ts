/** The original private bridge service is accepted only with this exact measured boundary. */
import { join } from 'node:path';
import { demand, jsonPin, same, verifyPin } from './paid-resource-proof-v2.ts';
import { verifyChemiqOwnedObservation } from './chemiq-f-owned-v2.ts';
export const CHEMIQ_PRIVATE_CID = '4c334ef1f093e82cf9e26ec06aaf0edd09385212c249e42b9ee7f7b8aae73153';
export const CHEMIQ_PRIVATE_IMAGE = 'sha256:adccbc2412fe240d3bba28a81e136d2e816a28b003263a2f1738098a67cbfbba';
export const CHEMIQ_SOLVER_TOOLS = ['node_load', 'submit', 'task_tree', 'verify'];
const normalize = (path: string) => path.replaceAll('\\', '/').toLowerCase();
const empty = (value: any) => value == null || Array.isArray(value) && value.length === 0;
export function assertChemiqPrivateBridgeObservation(frame: any, root: string) {
  demand(frame?.protocol === 'chemiq-private-inspect-observation-v2' && frame.modelCalls === 0 && frame.containerId === CHEMIQ_PRIVATE_CID && frame.nonpublicEnvironmentValuesRedacted === true, 'chemiq_bridge_observation_type');
  const r = frame.inspect, h = r?.HostConfig;
  demand(r?.Id === CHEMIQ_PRIVATE_CID && r.Image === CHEMIQ_PRIVATE_IMAGE && r.State?.Running === true && h?.NetworkMode === 'bridge', 'chemiq_bridge_exact_original_identity');
  demand(r.Path === 'python' && same(r.Args, ['/app/chemiq/stand.py', '--port', '17918', '--bind', '0.0.0.0', '--level', '0']), 'chemiq_bridge_daemon_command');
  demand(h.ReadonlyRootfs === true && h.Privileged === false && h.PidMode === '' && h.IpcMode === 'private' && h.UTSMode === '' && h.UsernsMode === '', 'chemiq_bridge_namespaces');
  demand(empty(h.CapAdd) && same(h.CapDrop, ['ALL']) && same(h.SecurityOpt, ['no-new-privileges']) && empty(h.Devices) && empty(h.DeviceRequests) && empty(h.VolumesFrom), 'chemiq_bridge_privilege_or_device');
  demand(h.Memory === 1073741824 && h.MemorySwap === 2147483648 && h.NanoCpus === 2000000000 && h.PidsLimit === 128 && same(h.Tmpfs, {'/tmp': 'rw,nosuid,size=128m'}), 'chemiq_bridge_resource_bounds');
  const ports = {'17918/tcp': [{HostIp: '127.0.0.1', HostPort: '17918'}]};
  demand(same(h.PortBindings, ports) && same(r.NetworkSettings?.Ports, ports) && h.PublishAllPorts === false && same(Object.keys(r.NetworkSettings?.Networks ?? {}), ['bridge']), 'chemiq_bridge_unique_loopback_port');
  const mounts = [
    [join(root, 'examples/benchmark/chemiq/stand.py'), '/app/chemiq/stand.py', false],
    [join(root, '.phase1-data/chemiq'), '/oracle', false],
    [join(root, '.phase1-data/python-extras'), '/extras', false],
    [join(root, 'docs/repair-2026-10-08/legacy-opsin-bridge'), '/opsin-jobs', true],
  ];
  demand(Array.isArray(r.Mounts) && r.Mounts.length === mounts.length, 'chemiq_bridge_mount_count');
  for (const [source, destination, rw] of mounts) {
    const found = r.Mounts.filter((m: any) => m.Destination === destination);
    demand(found.length === 1 && found[0].Type === 'bind' && normalize(found[0].Source) === normalize(String(source)) && found[0].RW === rw, 'chemiq_bridge_exact_mount');
  }
  demand(!r.Mounts.some((m: any) => /docker\.sock|\/proc|\/sys|\/dev/.test(m.Destination)), 'chemiq_bridge_host_device_mount');
  return frame;
}
export function assertChemiqSolverColdObservation(frame: any) {
  demand(frame?.protocol === 'chemiq-solver-cold-observation-v2' && frame.validated === true && frame.modelCalls === 0 && frame.remoteProviderRequests === 0 && frame.fixtureOnly === false && frame.nativeEngineStarted === true, 'chemiq_solver_cold_type');
  demand(same(frame.allowedTools, CHEMIQ_SOLVER_TOOLS) && Array.isArray(frame.toolRows) && frame.toolRows.every((r: any) => Number(r.usable) === (CHEMIQ_SOLVER_TOOLS.includes(r.name) ? 1 : 0)), 'chemiq_solver_tool_flags');
  const required = ['read', 'write', 'edit', 'glob', 'grep', 'bash', 'python_exec'];
  demand(required.every(name => frame.toolRows.some((r: any) => r.name === name && Number(r.usable) === 0)), 'chemiq_solver_disabled_tool_missing');
  demand(required.every(name => frame.rejectedCalls.some((r: any) => r.name === name && r.value?.error === `${name} is registered but usable = 0, so it was not run`)), 'chemiq_solver_actual_refusal_missing');
  demand(frame.closed === true && frame.enginePid > 0 && frame.enginePort > 0 && frame.stopReturned === true && frame.closedObservationPin && frame.taskDatabasePin && frame.toolUnitSourcePin, 'chemiq_solver_owned_close_missing');
  for (const p of [frame.closedObservationPin, frame.registrationPin, frame.taskDatabasePin, frame.toolUnitSourcePin]) verifyPin(p);
  const registered=jsonPin(frame.registrationPin);
  demand(registered.pid===frame.enginePid && Number(new URL(registered.base).port)===frame.enginePort && registered.family===frame.family && registered.runId===frame.runId, 'chemiq_solver_registration_binding');
  const close = verifyChemiqOwnedObservation(frame.closedObservationPin,[frame.registrationPin],[frame.localProviderPort]);
  demand(close.closed === true && close.parsed.processes.some((r: any) => r.pid === frame.enginePid && r.state === 'absent') && close.parsed.ports.some((r: any) => r.port === frame.enginePort && r.listening === false), 'chemiq_solver_owned_close_actual');
  return frame;
}
