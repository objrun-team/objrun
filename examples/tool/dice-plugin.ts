/** 写法一：进程内插件。收 `{args}`，回一份 JSON。 */
export async function run(arg: unknown): Promise<unknown> {
  const { sides = 6 } = ((arg ?? {}) as { args?: { sides?: number } }).args ?? {};
  const value = 1 + Math.floor(Math.random() * sides);
  console.log(`[dice-plugin] sides=${sides} → ${value}`);
  return { sides, value, from: "fn" };
}
