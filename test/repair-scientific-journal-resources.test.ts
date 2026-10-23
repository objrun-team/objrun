import { expect, test } from "bun:test";
import { scientificWorkerResources } from "../scripts/repair-2026-10-08/scientific-journal-resources.ts";
const MiB = 1024 ** 2;
test("new entry chooses workers before generation with512MiB each and512MiB host headroom", () => {
  expect(scientificWorkerResources({ requested: 4, freeMemoryBytes: 2560 * MiB }).selected).toBe(4);
  const reduced = scientificWorkerResources({ requested: 4, freeMemoryBytes: 2048 * MiB });
  expect(reduced.selected).toBe(3);
  expect(reduced.memoryPerWorkerBytes).toBe(512 * MiB);
  expect(reduced.hostHeadroomBytes).toBe(512 * MiB);
  expect(scientificWorkerResources({ requested: 1, freeMemoryBytes: 1024 * MiB }).selected).toBe(1);
  expect(() => scientificWorkerResources({ requested: 4, freeMemoryBytes: 1024 * MiB - 1 })).toThrow();
  expect(() => scientificWorkerResources({ requested: 5, freeMemoryBytes: 2560 * MiB })).toThrow();
});
