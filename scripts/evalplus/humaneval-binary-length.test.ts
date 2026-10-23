import { test, expect } from 'bun:test';
import { readFileSync } from 'node:fs';
import { join, resolve } from 'node:path';
import { recoverEmptyLengthCompletion } from './humaneval-binary-length.ts';
import { runBinaryTask } from './humaneval-binary-policy.ts';
const root = resolve(import.meta.dir, '../..');
const fixtures = [[32, 2], [99, 0], [145, 0]].map(([id, index]) => {
  const dir = join(root, 'docs/evalplus-20261012/humaneval/binary-v1/full/calls', 'HumanEval-' + id, 'sample-' + index, 'attempt-0');
  return { receipt: JSON.parse(readFileSync(join(dir, 'receipt.json'), 'utf8')), response: JSON.parse(readFileSync(join(dir, 'response.json'), 'utf8')) };
});
test('all three actual archived length responses are failed samples and preserve receipts', () => {
  for (const x of fixtures) {
    const before = JSON.stringify(x); const r = recoverEmptyLengthCompletion(x.receipt, x.response)!;
    expect(r.answer).toBe(''); expect(r.finishReason).toBe('length'); expect(r.countsAsGeneratedSample).toBe(true);
    expect(JSON.stringify(x)).toBe(before);
  }
});
test('provider errors, wrong routing, unexplained empty responses and actual code are not normalized', () => {
  for (const mutate of [
    (x: any) => { x.receipt.httpStatus = 502; },
    (x: any) => { x.response.error = { message: 'error' }; },
    (x: any) => { x.response.provider = 'Fireworks'; },
    (x: any) => { x.response.choices[0].finish_reason = 'stop'; },
    (x: any) => { x.response.usage.completion_tokens = 2; },
    (x: any) => { x.response.choices[0].message.content = 'def f(): pass'; }
  ]) { const x = structuredClone(fixtures[0]); mutate(x); expect(recoverEmptyLengthCompletion(x.receipt, x.response)).toBeUndefined(); }
});
test('a truncated empty answer consumes one check and continues with only failed feedback', async () => {
  const r = await runBinaryTask({ prompt: 'P', prior: [], persist() {},
    generate: async (index, messages) => {
      if (!index) return recoverEmptyLengthCompletion(fixtures[0].receipt, fixtures[0].response);
      expect(messages).toEqual([{ role: 'user', content: 'P' }, { role: 'assistant', content: '' }, { role: 'user', content: 'failed' }]);
      return { answer: 'correct code' };
    }, gradeBase: async answer => ({ valid: true, passed: !!answer }), gradeFinal: async () => ({ valid: true, passed: true }) });
  expect(r.samples.length).toBe(2); expect(r.samples[0].baseGrade.passed).toBe(false); expect(r.answer).toBe('correct code');
});
