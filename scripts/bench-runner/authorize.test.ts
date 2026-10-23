import { test, expect, afterEach } from 'bun:test';
import { generateKeyPairSync } from 'node:crypto';
import { mkdtempSync, writeFileSync, readFileSync, rmSync } from 'node:fs';
import { tmpdir } from 'node:os';
import { join, relative, resolve } from 'node:path';
import { pin } from './manifest.ts';
import { prepareContextDraft, loadPreparedContext } from './bindings.ts';
import { authorizeBinding } from './authorize.ts';
import type { TaskManifest, AttemptContext } from './types.ts';
const dirs: string[] = [];
afterEach(() => { for (const d of dirs.splice(0)) {
  if (relative(resolve(tmpdir()), resolve(d)).startsWith('..')) throw Error('unsafe_fixture_cleanup');
  rmSync(d, { recursive: true, force: true, maxRetries: 10, retryDelay: 50 });
} });
function setup() {
  const root = mkdtempSync(join(tmpdir(), 'bench-authority-')); dirs.push(root);
  const keys = generateKeyPairSync('ed25519', { publicKeyEncoding: { type: 'spki', format: 'pem' }, privateKeyEncoding: { type: 'pkcs8', format: 'pem' } });
  const put = (name: string, value: unknown) => { const path = join(root, name); writeFileSync(path, typeof value === 'string' ? value : JSON.stringify(value)); return pin(path); };
  const authority = put('authority.public.pem', keys.publicKey), privateKey = put('authority.private.pem', keys.privateKey);
  const evidence = put('fixture-evidence.json', { fixtureOnly: true });
  const command = [evidence.path, '{{bindings.CONTEXT}}'];
  const template = put('template.json', { taskId: 'fixture-unfinished', bench: 'terminal-bench', nonce: '{{bindings.NONCE}}', argv: command, coordinatorReviewed: false, phase: 'draft' });
  const m: TaskManifest = { schemaVersion: 1, taskId: 'fixture-unfinished', bench: 'terminal-bench', root, artifactRoot: join(root, 'runs'),
    original: { cpu: 1, memoryMb: 2048, solveSeconds: 900, gradeSeconds: 900, toolSeconds: 930, providerSeconds: 600, model: 'fixture', provider: 'fixture', reasoning: 'high', taskCapUsd: 2, priorKnownUsd: 0.2, priorUnknownUsd: 0.1 },
    provenance: { sourcePins: [evidence], contractPins: [template, authority], inventoryPin: evidence },
    history: { validResultPins: [], successfulStageProofs: {}, priorRunPins: [], stateKnown: true, originalResultRecoveryRequired: false }, stages: { solve: { kind: 'command', effect: 'read-only', timeoutSeconds: 900, command, evidencePins: [evidence] } },
    adapterConfig: { bindingSpec: { protocol: 'bench-root-data-binding-v1', authorityPin: authority, entryTemplatePin: template, inputs: {}, output: { root: join(root, 'output'), prefix: 'fixture-' }, expiresAtUtc: new Date(Date.now() + 60000).toISOString() } } };
  const manifest = put('manifest.json', m), runDir = join(root, 'attempt');
  const context = { taskId: m.taskId, bench: m.bench, attemptId: 'same-persisted-fixture', stage: 'solve', runDir, manifestPath: manifest.path, manifestPin: manifest, admissionControlPath: join(root, 'admission.json'), inventoryTask: { taskId: m.taskId, bench: m.bench, state: 'never-started', reason: 'fixture', evidencePins: [evidence], successfulStages: {}, priorRunIds: [] } } as AttemptContext;
  const draft = prepareContextDraft(m, context);
  const review = { protocol: 'bench-concrete-binding-review-v1', rootReviewed: true, inventoryReconciled: true, zeroModelChecksPassed: true, expiresAtUtc: new Date(Date.now() + 60000).toISOString(), manifestPin: manifest, requestPin: draft.requestPin, draftPin: draft.draftPin, evidencePins: [evidence] };
  return { m, context, draft, review, put, privateKey };
}
test('concrete reviewed binding uses original authority and same durable attempt; no task launch', () => {
  const f = setup(); const signed = authorizeBinding(f.put('review.json', f.review), f.privateKey.path);
  const verified = loadPreparedContext(f.m, f.context);
  expect(verified.bindings!.NONCE).toBe(f.context.attemptId);
  expect(JSON.parse(readFileSync(signed.path, 'utf8')).entry.coordinatorReviewed).toBe(true);
  expect(() => authorizeBinding(f.put('review-again.json', f.review), f.privateKey.path)).toThrow('already_signed');
});
test('missing zero-model gate or modified concrete draft cannot be authorized', () => {
  const f = setup(); expect(() => authorizeBinding(f.put('review-bad.json', { ...f.review, zeroModelChecksPassed: false }), f.privateKey.path)).toThrow('zero_model_gate');
  writeFileSync(f.draft.draftPin.path, '{}');
  expect(() => authorizeBinding(f.put('review-changed.json', f.review), f.privateKey.path)).toThrow('pin_changed');
});
