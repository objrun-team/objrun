import { test, expect, afterEach } from 'bun:test';
import { mkdtempSync, writeFileSync, mkdirSync, rmSync, readFileSync } from 'node:fs';
import { tmpdir } from 'node:os';
import { join, resolve, relative } from 'node:path';
import { pin } from './manifest.ts';
import { retainValidResult } from './retention.ts';
import type { TaskManifest, AttemptContext, StageResult } from './types.ts';
const directories: string[] = [];
afterEach(() => { for (const d of directories.splice(0)) {
  const checked = relative(resolve(tmpdir()), resolve(d));
  if (!checked || checked.startsWith('..')) throw Error('unsafe_fixture_cleanup');
  rmSync(d, { recursive: true, force: true, maxRetries: 10, retryDelay: 50 });
} });
function fixture() {
  const root = mkdtempSync(join(tmpdir(), 'bench-retention-')); directories.push(root);
  const runDir = join(root, 'runs', 'fixture-attempt'); mkdirSync(runDir, { recursive: true });
  const original = join(root, 'original-verdict.json');
  writeFileSync(original, JSON.stringify({ fixtureOnly: true, acceptance: { valid: true, passed: false } }));
  const manifestPath = join(root, 'manifest.json'); writeFileSync(manifestPath, JSON.stringify({ fixtureOnly: true }));
  const custody = join(runDir, 'archived-result.json'); writeFileSync(custody, JSON.stringify({ fixtureOnly: true, originalPin: pin(original) }));
  const m = { root, bench: 'terminal-bench', taskId: 'unfinished-fixture', original: { priorKnownUsd: 0.12, priorUnknownUsd: 0.1 },
    adapterConfig: { retainedRegistryDirectory: join(root, 'valid-completions') } } as unknown as TaskManifest;
  const c = { runDir, attemptId: 'fixture-attempt', manifestPin: pin(manifestPath) } as AttemptContext;
  const r: StageResult = { status: 'valid', proofPins: [pin(original)], nativeClosed: true, financialClosed: true,
    candidateOrSubmissionPresent: true, validResult: { passed: false, outcome: 'wrong', proofPin: pin(original) } };
  return { root, m, c, r, original };
}
test('retains valid wrong once with original costs and immutable custody; no retry promotion', () => {
  const { m, c, r } = fixture(); const result = retainValidResult(m, c, r)!;
  const record = JSON.parse(readFileSync(result.path, 'utf8'));
  expect(record.valid).toBe(true); expect(record.passed).toBe(false); expect(record.rerunForbidden).toBe(true);
  expect(record.originalConstraints.priorUnknownUsd).toBe(0.1);
  expect(retainValidResult(m, c, r)).toEqual(result);
});
test('unclosed finance/native cannot publish a valid registry row', () => {
  const { m, c, r } = fixture();
  expect(() => retainValidResult(m, c, { ...r, financialClosed: false })).toThrow('exact_closure');
  expect(() => retainValidResult(m, c, { ...r, nativeClosed: false })).toThrow('exact_closure');
});
test('original artifact mutation and conflicting verdict never overwrite retained proof', () => {
  const { m, c, r, original } = fixture(); retainValidResult(m, c, r);
  expect(() => retainValidResult(m, c, { ...r, validResult: { ...r.validResult!, passed: true } })).toThrow('conflict');
  writeFileSync(original, '{"changed":true}');
  expect(() => retainValidResult(m, c, r)).toThrow('pin_changed');
});
