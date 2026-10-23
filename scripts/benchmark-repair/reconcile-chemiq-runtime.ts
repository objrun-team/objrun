// Repeat only the frozen public-runtime identity audit. Never a model or grader call.
import { createHash } from 'node:crypto';
import { mkdirSync, readFileSync, writeFileSync } from 'node:fs';
import { resolve, join } from 'node:path';
import { loadChemiqProvenance } from './chemiq-nextwave-contract.ts';

const root = resolve(import.meta.dir, '../..');
const run = process.argv[2];
if (run !== 'repair-2026-10-08T10-25-57-408Z') throw new Error('Only the declared interrupted ChemIQ shutdown may be reconciled');
const directory = join(root, 'docs/repair-2026-10-08/campaigns', run);
const summary = JSON.parse(readFileSync(join(directory, 'summary.json'), 'utf8'));
const ledger = JSON.parse(readFileSync(join(directory, 'api-ledger.json'), 'utf8'));
const source = JSON.parse(readFileSync(join(directory, 'source.json'), 'utf8'));
const manifest = JSON.parse(readFileSync(join(directory, 'manifest.json'), 'utf8'));
if (manifest.benchmarks.join(',') !== 'chemiq' || summary.completed !== false || ledger.fatal !== 'spawnSync docker ETIMEDOUT') throw new Error('The original interruption differs; preserve it for review');
if (Math.abs(ledger.reservedUpperBoundUsd) > 1e-9 || Object.values(ledger.pending).some(value => value !== 0) || ledger.calls.some((call: { finishedAt?: string; fault?: string }) => !call.finishedAt || call.fault)) throw new Error('Unsettled API receipts block reconciliation');
if (summary.records.length !== summary.plannedTaskRuns || summary.records.some((row: { acceptance: { valid: boolean; passed: boolean } }) => row.acceptance.valid !== true || typeof row.acceptance.passed !== 'boolean')) throw new Error('Final fixed-candidate grading is incomplete');
const expected = source.repairFiles.find((file: {path: string}) => file.path.endsWith('/chemiq-nextwave-contract.ts'));
const sha = (path: string) => createHash('sha256').update(readFileSync(path)).digest('hex');
if (!expected || sha(join(root, expected.path)) !== expected.sha256) throw new Error('Original runtime audit contract changed');
const stamp = new Date().toISOString().replace(/[:.]/g, '-');
const store = join('C:/Users/y1252/.codex/visualizations/2026/10/08/01a119ed-fdf7-7c32-b323-de9bab1290b6', 'experiment-audits', run, stamp);
mkdirSync(store, { recursive: true });
const invocation = { run, attemptedAt: new Date().toISOString(), originalCompleted: false, originalFatal: ledger.fatal, contractSha256: expected.sha256, originalSummarySha256: sha(join(directory, 'summary.json')), originalLedgerSha256: sha(join(directory, 'api-ledger.json')), modelCalls: 0, candidateGraderCalls: 0, originalArtifactsModified: false, limitation: 'This is a later runtime identity observation; the original failed shutdown and all raw artifacts are preserved.' };
try {
  const proof = loadChemiqProvenance(root, store);
  const observed = proof.audit('shutdown');
  if (sha(join(root, expected.path)) !== expected.sha256) throw new Error('Runtime audit contract changed during reconciliation');
  const result = { ...invocation, valid: true, observedAt: observed.observedAt, runtimeAudit: join(store, 'grader-provenance/chemiq/shutdown-runtime-audit.json') };
  writeFileSync(join(store, 'invocation.json'), JSON.stringify(result, null, 2) + '\n');
  console.log(JSON.stringify(result));
} catch (error) {
  const result = { ...invocation, valid: false, fault: error instanceof Error ? error.message : String(error), auditStore: store };
  writeFileSync(join(store, 'invocation.json'), JSON.stringify(result, null, 2) + '\n');
  console.log(JSON.stringify(result));
  process.exitCode = 1;
}
