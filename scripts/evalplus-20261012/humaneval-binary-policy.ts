export const MAX_BINARY_CHECKS = 5;
export function binaryFeedback(grade: any): 'passed' | 'failed' {
  if (grade?.valid !== true || typeof grade.passed !== 'boolean') throw Error('InvalidBinaryFeedbackGrade');
  return grade.passed ? 'passed' : 'failed';
}
export function binaryMessages(prompt: string, samples: any[]) {
  const messages: { role: string; content: string }[] = [{ role: 'user', content: prompt }];
  for (const sample of samples) {
    if (!sample.baseGrade?.valid) throw Error('UngradedHistory');
    messages.push({ role: 'assistant', content: sample.answer }, { role: 'user', content: binaryFeedback(sample.baseGrade) });
  }
  return messages;
}
// Persist the answer before asking the grader, so resumption never regenerates it.
export async function runBinaryTask(o: {
  prompt: string; prior: any[]; generate: (index: number, messages: any[]) => Promise<any>;
  gradeBase: (answer: string) => Promise<any>; gradeFinal: (answer: string) => Promise<any>;
  persist: (samples: any[]) => void; freeze?: (answer: string, stoppingReason: string) => void;
}) {
  const samples = o.prior.map(s => ({ ...s }));
  if (samples.length > MAX_BINARY_CHECKS) throw Error('BinaryCheckCeilingExceeded');
  for (let index = 0; index < MAX_BINARY_CHECKS; index++) {
    if (index >= samples.length) {
      const x = await o.generate(index, binaryMessages(o.prompt, samples));
      samples.push({ index, ...x }); o.persist(samples);
    }
    const s = samples[index];
    if (!s.baseGrade?.valid) { s.baseGrade = await o.gradeBase(s.answer); o.persist(samples); }
    s.feedback = binaryFeedback(s.baseGrade); o.persist(samples);
    if (s.baseGrade.passed || index === MAX_BINARY_CHECKS - 1) {
      if (samples.length !== index + 1) throw Error('SamplesAfterStoppingPoint');
      // The final candidate is frozen before enhanced tests. Enhanced outcomes never enter history.
      o.freeze?.(s.answer, s.baseGrade.passed ? 'base_passed' : 'check_ceiling');
      const grade = await o.gradeFinal(s.answer);
      return { samples, answer: s.answer, grade, stoppingReason: s.baseGrade.passed ? 'base_passed' : 'check_ceiling' };
    }
  }
  throw Error('UnreachableBinaryState');
}
