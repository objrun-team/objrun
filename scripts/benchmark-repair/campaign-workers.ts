const MiB = 1024 * 1024;
export function requestedWorkers(value?: string): number {
  if (value === undefined) return 4;
  if (!/^[1-4]$/.test(value)) throw new Error("OBJRUN_REPAIR_WORKERS must be an explicit integer from 1 to 4");
  return Number(value);
}
export function workerPreflight(input: { requested: number; freeMemoryBytes: number; freeDiskBytes: number }) {
  if (!Number.isInteger(input.requested) || input.requested < 1 || input.requested > 4 || !Number.isFinite(input.freeMemoryBytes) || !Number.isFinite(input.freeDiskBytes) || input.freeMemoryBytes < 0 || input.freeDiskBytes < 0) throw new Error("Invalid worker resource evidence");
  const memoryHeadroom = 512 * MiB, memoryPerWorker = 256 * MiB, diskHeadroom = 512 * MiB, diskPerWorker = 128 * MiB;
  const memoryCapacity = Math.floor((input.freeMemoryBytes - memoryHeadroom) / memoryPerWorker), diskCapacity = Math.floor((input.freeDiskBytes - diskHeadroom) / diskPerWorker);
  const selected = Math.min(input.requested, memoryCapacity, diskCapacity);
  if (selected < 1) throw new Error("Insufficient memory or disk for even one worker; stop before generation");
  return { ...input, selected, observedAt: new Date().toISOString(), memoryHeadroomBytes: memoryHeadroom, memoryPerWorkerBytes: memoryPerWorker, diskHeadroomBytes: diskHeadroom, diskPerWorkerBytes: diskPerWorker, reason: selected === input.requested ? "requested_workers_available" : "reduced_before_generation_for_memory_or_disk", limits: "Host free-memory/disk admission estimate; not a guarantee against later resource changes. The per-call evidence disk guard remains active." };
}
/** Preserve each benchmark's fixed internal order while alternating ready benchmarks. */
export function roundRobinBenchmarks<T extends {benchmark:string}>(tasks: readonly T[], benchmarks: readonly string[]): T[] {
  if (new Set(benchmarks).size !== benchmarks.length) throw new Error("Repeated benchmark in schedule");
  const queues = new Map(benchmarks.map(name => [name, tasks.filter(task => task.benchmark === name)]));
  if (tasks.some(task => !queues.has(task.benchmark))) throw new Error("Task benchmark absent from schedule");
  const result: T[] = [], positions = new Map(benchmarks.map(name => [name, 0]));
  while (result.length < tasks.length) for (const name of benchmarks) {
    const queue = queues.get(name)!, position = positions.get(name)!;
    if (position < queue.length) { result.push(queue[position]!); positions.set(name, position + 1); }
  }
  return result;
}
