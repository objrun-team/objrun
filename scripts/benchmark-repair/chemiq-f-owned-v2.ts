/** Exact owned native PID/port observation; never stops an unknown process or mutates Docker. */
import { spawn } from 'node:child_process';
import { readFileSync } from 'node:fs';
import { join } from 'node:path';
import { actualPin, demand, jsonPin, same, verifyPin, type Pin } from './paid-resource-proof-v2.ts';
import { CHEMIQ_F_FAMILY, CHEMIQ_F_ROOT, chemiqOrdinary } from './chemiq-f-journal-contract-v2.ts';
import { durableChemiqJson } from './chemiq-f-paid-admission-v2.ts';

const PS = 'C:/Windows/System32/WindowsPowerShell/v1.0/powershell.exe';
export function chemiqActorCommand(pids: number[], ports: number[]) {
  demand(pids.length <= 816 && new Set(pids).size === pids.length && pids.every(x => Number.isSafeInteger(x) && x > 0 && x !== process.pid), 'chemiq_owned_pid_set');
  demand(ports.length <= 820 && new Set(ports).size === ports.length && ports.every(x => Number.isSafeInteger(x) && x > 0 && x < 65536), 'chemiq_owned_port_set');
  return `$ErrorActionPreference='Stop'; $ProgressPreference='SilentlyContinue'; [Console]::OutputEncoding=[Text.UTF8Encoding]::new($false); $rows=@(); foreach($actor in @(${pids.join(',')})){ try { $value=[System.Diagnostics.Process]::GetProcessById([int]$actor); $rows+=@{pid=[int]$actor;state='present';name=$value.ProcessName;startedAtUtc=$value.StartTime.ToUniversalTime().ToString('o')} } catch [System.ArgumentException] { $rows+=@{pid=[int]$actor;state='absent'} } catch { $rows+=@{pid=[int]$actor;state='unknown';error=$_.Exception.GetType().FullName} } }; $all=@([System.Net.NetworkInformation.IPGlobalProperties]::GetIPGlobalProperties().GetActiveTcpListeners()); $ports=@(); foreach($port in @(${ports.join(',')})){ $hits=@($all|Where-Object {$_.Port -eq $port}); $ports+=@{port=[int]$port;listening=($hits.Count -gt 0)} }; @{protocol='chemiq-f-native-owned-query-v2';queryHostPid=$PID;processes=@($rows);ports=@($ports)}|ConvertTo-Json -Depth 5 -Compress;`;
}
export function assertChemiqOwnedFrame(frame: any, pids: number[], ports: number[]) {
  demand(frame?.protocol === 'chemiq-f-native-owned-query-v2' && Number.isSafeInteger(frame.queryHostPid) && frame.queryHostPid > 0, 'chemiq_owned_native_type');
  demand(Array.isArray(frame.processes) && frame.processes.length === pids.length && new Set(frame.processes.map((r: any) => r.pid)).size === pids.length && pids.every(pid => frame.processes.some((r: any) => r.pid === pid && r.state === 'absent')), 'chemiq_owned_pid_present_or_unknown');
  demand(Array.isArray(frame.ports) && frame.ports.length === ports.length && new Set(frame.ports.map((r: any) => r.port)).size === ports.length && ports.every(port => frame.ports.some((r: any) => r.port === port && r.listening === false)), 'chemiq_owned_port_active');
}
export async function observeChemiqOwned(output: string, registrations: Pin[], extraPorts: number | number[], stage: string) {
  demand(/^[a-z-]{1,32}$/.test(stage), 'chemiq_owned_stage'); chemiqOrdinary(output, CHEMIQ_F_ROOT, true);
  const records = registrations.map(p => jsonPin(p));
  demand(records.every(r => r.protocol === 'paid-owned-process-v2' && r.family === CHEMIQ_F_FAMILY && r.runId === records[0].runId) && new Set(records.map(r => r.taskIndex)).size === records.length, 'chemiq_owned_registered_identity');
  const pids = [...new Set(records.map(r => r.pid))], ports = [...new Set([...records.map(r => new URL(r.base).port).map(Number), ...(Array.isArray(extraPorts) ? extraPorts : [extraPorts])])];
  const command = chemiqActorCommand(pids, ports), source = actualPin(import.meta.path), executable = actualPin(PS);
  const startedAtUtc = new Date().toISOString();
  const requestPin = durableChemiqJson(join(output, `owned-${stage}-request.json`), { protocol: 'chemiq-f-native-owned-request-v2', family: CHEMIQ_F_FAMILY,
    stage, command, pids, ports, hostPid: process.pid, startedAtUtc, source, executable, registrationPins: registrations, timeoutMs: 10000 });
  const env = { ...process.env }; for (const key of Object.keys(env)) if (key.toLowerCase() === 'psmodulepath') delete env[key];
  env.PSModulePath = 'C:/Windows/System32/WindowsPowerShell/v1.0/Modules';
  const result = await new Promise<{ status: number | null; stdout: string; stderr: string; timedOut: boolean }>((resolve, reject) => {
    const child = spawn(PS, ['-NoProfile', '-NonInteractive', '-Command', command], { windowsHide: true, env, stdio: ['ignore', 'pipe', 'pipe'] });
    let stdout = '', stderr = '', timedOut = false;
    const timer = setTimeout(() => { timedOut = true; child.kill('SIGKILL'); }, 10000);
    child.stdout.on('data', b => { stdout += b.toString('utf8'); if (Buffer.byteLength(stdout) > 256 * 1024) { timedOut = true; child.kill('SIGKILL'); } });
    child.stderr.on('data', b => { stderr += b.toString('utf8'); if (Buffer.byteLength(stderr) > 65536) { timedOut = true; child.kill('SIGKILL'); } });
    child.once('error', error => { clearTimeout(timer); reject(error); });
    child.once('close', status => { clearTimeout(timer); resolve({ status, stdout, stderr, timedOut }); });
  });
  const completedAtUtc = new Date().toISOString();
  // Preserve failed observations as well. They cannot mint an owned-close certificate.
  const transcriptPin = durableChemiqJson(join(output, `owned-${stage}-transcript.json`), { ...result, startedAtUtc, completedAtUtc });
  demand(result.status === 0 && !result.timedOut && !result.stderr.trim(), 'chemiq_owned_native_probe_failed');
  const parsed = JSON.parse(result.stdout.trim()); assertChemiqOwnedFrame(parsed, pids, ports); verifyPin(source); verifyPin(executable);
  return durableChemiqJson(join(output, `owned-${stage}-observation.json`), { protocol: 'chemiq-f-owned-observation-v2', family: CHEMIQ_F_FAMILY,
    stage, source, requestPin, transcriptPin, startedAtUtc, completedAtUtc, parsed, closed: true, modelCalls: 0 });
}
export function verifyChemiqOwnedObservation(pin: Pin, registrations: Pin[], extraPorts: number[]) {
  const proof = jsonPin(pin), request = jsonPin(proof.requestPin), transcript = jsonPin(proof.transcriptPin), rows = registrations.map(p => jsonPin(p));
  const pids = [...new Set(rows.map(r => r.pid))], ports = [...new Set([...rows.map(r => Number(new URL(r.base).port)), ...extraPorts])];
  demand(proof.protocol === 'chemiq-f-owned-observation-v2' && proof.family === CHEMIQ_F_FAMILY && proof.closed === true && proof.modelCalls === 0 && same(request.registrationPins, registrations) && same(request.pids, pids) && same(request.ports, ports), 'chemiq_owned_observation_binding');
  demand(request.command === chemiqActorCommand(pids, ports) && request.timeoutMs === 10000 && transcript.status === 0 && transcript.timedOut === false && !transcript.stderr.trim() && same(JSON.parse(transcript.stdout.trim()), proof.parsed), 'chemiq_owned_raw_query_binding');
  demand(Date.parse(proof.completedAtUtc) >= Date.parse(proof.startedAtUtc) && Date.parse(proof.completedAtUtc) - Date.parse(proof.startedAtUtc) <= 15000, 'chemiq_owned_query_time');
  demand(request.source.sha256 === proof.source.sha256 && proof.source.path === actualPin(import.meta.path).path, 'chemiq_owned_source'); for (const p of [proof.source, request.executable, ...registrations]) verifyPin(p);
  assertChemiqOwnedFrame(proof.parsed, pids, ports); return proof;
}
