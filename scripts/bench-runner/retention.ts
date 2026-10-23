import { createHash } from 'node:crypto';
import { existsSync, mkdirSync, readFileSync, writeFileSync } from 'node:fs';
import { isAbsolute, join, relative, resolve } from 'node:path';
import type { AttemptContext, Pin, StageResult, TaskManifest } from './types.ts';
import { demand, pin, verifyPin } from './manifest.ts';

/** Publish only an adapter-verified original verdict after exact cash/native closure. */
export function retainValidResult(m: TaskManifest, c: AttemptContext, r: StageResult): Pin | undefined {
  if (r.status !== 'valid') return;
  demand(r.validResult && r.nativeClosed && r.financialClosed, 'retain_requires_original_valid_and_exact_closure');
  const configured = m.adapterConfig.retainedRegistryDirectory;
  demand(typeof configured === 'string' && isAbsolute(configured), 'retained_registry_directory_required');
  const directory = resolve(configured), within = relative(m.root, directory);
  demand(within && !within.startsWith('..') && !isAbsolute(within), 'registry_must_be_inside_reviewed_workspace');
  verifyPin(c.manifestPin); verifyPin(r.validResult.proofPin);
  for (const p of r.proofPins) verifyPin(p);
  const custody = pin(join(c.runDir, 'archived-result.json'));
  const key = createHash('sha256').update(m.bench + ':' + m.taskId).digest('hex');
  const attempt = createHash('sha256').update(c.attemptId).digest('hex').slice(0, 20);
  const record = {
    protocol: 'novaeve-universal-retained-valid-v1', taskId: m.taskId, bench: m.bench,
    valid: true, rerunForbidden: true, passed: r.validResult.passed, outcome: r.validResult.outcome,
    taskPin: r.validResult.proofPin, proofPin: custody, manifestPin: c.manifestPin,
    originalConstraints: m.original, originalProofPins: r.proofPins,
    nativeClosed: true, financialClosed: true, attemptId: c.attemptId,
    scoreClassificationSource: 'original-contract-and-original-candidate-artifacts',
    noNewGradeOrModelForRetention: true,
  };
  mkdirSync(directory, { recursive: true });
  const path = join(directory, 'universal-' + key + '-' + attempt + '.json');
  if (existsSync(path)) {
    demand(JSON.stringify(JSON.parse(readFileSync(path, 'utf8'))) === JSON.stringify(record), 'retained_result_conflict');
  } else writeFileSync(path, JSON.stringify(record, null, 2) + '\n', { flag: 'wx', mode: 0o600 });
  return pin(path);
}
