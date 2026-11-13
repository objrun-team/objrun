/** Approach 1: an in-process plugin. Accept `{args}` and return JSON. */
export async function run(arg: unknown): Promise<unknown> {
  const { sides = 6 } = ((arg ?? {}) as { args?: { sides?: number } }).args ?? {};
  const value = 1 + Math.floor(Math.random() * sides);
  console.log(`[dice-plugin] sides=${sides} → ${value}`);
  return { sides, value, from: "fn" };
}
