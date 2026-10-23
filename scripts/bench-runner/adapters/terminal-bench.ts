import type { BenchAdapter } from '../types.ts';
import { validateFor, executeFor, recoverFor } from './index.ts';
export const terminalBenchAdapter: BenchAdapter = {
  bench:'terminal-bench', validate:m=>validateFor('terminal-bench',m),
  execute:(m,s,c)=>executeFor('terminal-bench',m,s,c), recover:(m,c)=>recoverFor('terminal-bench',m,c),
};
