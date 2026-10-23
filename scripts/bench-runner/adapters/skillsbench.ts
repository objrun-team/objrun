import type { BenchAdapter } from '../types.ts';
import { validateFor, executeFor, recoverFor } from './index.ts';
export const skillsbenchAdapter: BenchAdapter = {
  bench:'skillsbench', validate:m=>validateFor('skillsbench',m),
  execute:(m,s,c)=>executeFor('skillsbench',m,s,c), recover:(m,c)=>recoverFor('skillsbench',m,c),
};
