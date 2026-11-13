/**
 * A dynamic skill: the kind with an empty `body`. The kernel calls it when triggered, and it constructs text on demand.
 *
 * It receives this round’s **facts**, the same ones used by trigger conditions, so it can respond to this task and execution unit’s specific circumstances, unlike a static skill.
 */

export async function run(arg: unknown): Promise<unknown> {
  const { facts } = (arg ?? {}) as {
    facts?: {
      task?: { id?: string; description?: string; source?: string };
      cycle?: { cycle?: string };
      place?: string;
    };
  };
  const t = facts?.task;
  const line = `[generated] this task is ${t?.id} (published by ${t?.source}, at ${facts?.place}): ${t?.description}`;
  console.log(`[recap] ${line}`);
  return line;
}
