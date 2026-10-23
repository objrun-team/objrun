const MiB = 1024 ** 2;
/** Independent new-entry memory gate. The old shared 256MiB estimate remains immutable. */
export function scientificWorkerResources(input: { requested: number; freeMemoryBytes: number; observedAt?: string }) {
  if (!Number.isInteger(input.requested) || input.requested < 1 || input.requested > 4 || !Number.isFinite(input.freeMemoryBytes) || input.freeMemoryBytes < 0) throw new Error("Invalid scientific worker resource evidence");
  const memoryPerWorkerBytes = 512 * MiB, hostHeadroomBytes = 512 * MiB;
  const capacity = Math.floor((input.freeMemoryBytes - hostHeadroomBytes) / memoryPerWorkerBytes);
  const selected = Math.min(input.requested, capacity);
  if (selected < 1) throw new Error("Insufficient memory for one 512MiB worker plus 512MiB host headroom; no generation permitted");
  return { ...input, selected, observedAt: input.observedAt ?? new Date().toISOString(), memoryPerWorkerBytes, hostHeadroomBytes,
    reason: selected === input.requested ? "requested_workers_available" : "reduced_before_generation_for_memory",
    basis: "Observed bounded status fixture used about410–414MB private memory;512MiB is a planning allowance, not a measured per-task or OS memory cap. This selection is fixed before generation." };
}
