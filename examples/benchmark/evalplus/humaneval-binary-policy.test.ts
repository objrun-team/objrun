import { test, expect } from 'bun:test';
import { binaryFeedback, binaryMessages, runBinaryTask } from './humaneval-binary-policy.ts';
const g = (passed: boolean) => ({ valid: true, passed, feedback: 'PRIVATE', groups: { plus: 'SECRET' } });
test('only the binary verdict and own answers enter subsequent model requests', () => {
  expect(binaryMessages('PROMPT', [{ answer: 'CODE', baseGrade: g(false) }])).toEqual([
    { role: 'user', content: 'PROMPT' }, { role: 'assistant', content: 'CODE' }, { role: 'user', content: 'failed' }
  ]);
  expect(binaryFeedback(g(true))).toBe('passed');
  expect(() => binaryFeedback({ valid: false, passed: false })).toThrow();
});
test('five failed base checks select the fifth; final plus grading occurs once after generation', async () => {
  let generated = 0, finals = 0;
  const r = await runBinaryTask({ prompt: 'P', prior: [], persist() {},
    generate: async (i, messages) => { expect(messages.length).toBe(1 + 2 * i); generated++; return { answer: 'code' + i }; },
    gradeBase: async () => g(false), gradeFinal: async answer => { expect(generated).toBe(5); expect(answer).toBe('code4'); finals++; return g(false); }
  });
  expect(r.samples.length).toBe(5); expect(finals).toBe(1); expect(r.stoppingReason).toBe('check_ceiling');
});
test('base pass freezes the candidate before enhanced grading and stops even when enhanced tests fail', async () => {
  let generated = 0, frozen = false;
  const r = await runBinaryTask({ prompt: 'P', prior: [], persist() {}, generate: async () => ({ answer: String(++generated) }),
    freeze: () => { frozen = true; }, gradeBase: async () => g(true), gradeFinal: async () => { expect(frozen).toBe(true); return g(false); } });
  expect(generated).toBe(1); expect(r.grade.passed).toBe(false); expect(r.stoppingReason).toBe('base_passed');
});
test('resume regrades the saved ungraded answer without a new model call', async () => {
  let generations = 0;
  const r = await runBinaryTask({ prompt: 'P', prior: [{ index: 0, answer: 'saved' }], persist() {},
    generate: async () => { generations++; throw Error('must not generate'); }, gradeBase: async () => g(true), gradeFinal: async () => g(true) });
  expect(generations).toBe(0); expect(r.answer).toBe('saved');
});
test('grader environment failures cannot become failed feedback or consume another sample', async () => {
  let generations = 0; let saved: any[] = [];
  await expect(runBinaryTask({ prompt: 'P', prior: [], persist: s => { saved = structuredClone(s); },
    generate: async () => ({ answer: String(++generations) }), gradeBase: async () => ({ valid: false, passed: false }), gradeFinal: async () => g(true)
  })).rejects.toThrow('InvalidBinaryFeedbackGrade');
  expect(generations).toBe(1); expect(saved.length).toBe(1);
});
