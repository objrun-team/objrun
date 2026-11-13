/**
 * An inference function: **where to go after this execution unit finishes.**
 *
 * The kernel accepts only three answers:
 *
 * | Return | Meaning |
 * | --- | --- |
 * | `null` | Stop here |
 * | `"cycle-name"` | Enter that cycle, **continuing from the current row** |
 * | `{to, from_cycle, from_unit, status}` | Enter that cycle, **continuing from the specified row**, and assign a terminal status to the current row |
 *
 * Selecting anything outside the `next` candidates fails immediately; the kernel forbids arbitrary destinations.
 *
 * This example’s graph:
 *
 * ```
 *   plan ──→ work ──→ wrap
 *              ↑         │
 *              └─────────┘        work loops while unfinished, then proceeds to wrap
 * ```
 */

interface At {
  next?: string[];
  cycle?: { cycle?: string };
  task?: { id?: string };
  result?: { body?: unknown };
  unit?: number;
}

/** Whether the model’s message in this execution unit contains the word. */
function said(r: At["result"], word: string): boolean {
  return String((r ?? {}).body ?? "").includes(word);
}

export async function infer(arg: unknown): Promise<unknown> {
  const a = (arg ?? {}) as At;
  const here = a.cycle?.cycle;
  const next = a.next ?? [];

  // Only one path follows plan.
  if (here === "plan") return pick("work", a);

  if (here === "work") {
    // Proceed only when the model itself says the finish keyword; otherwise loop through work again.
    // `max_units` is the fallback: the kernel stops further cycles when exhausted, so no local counter is needed.
    return pick(said(a.result, "wrap up") ? "wrap" : "work", a);
  }

  // wrap is the endpoint.
  return pick(null, a);

  function pick(to: string | null, at: At): unknown {
    console.log(`[steps] ${at.task?.id} ${here}#${at.unit} -> ${to ?? "end of the line"} (candidates ${next.join(", ") || "none"})`);
    return to;
  }
}

/** Deliberately infer a cycle outside the candidate set to check whether the kernel blocks it. */
export async function wild(arg: unknown): Promise<unknown> {
  const a = (arg ?? {}) as At;
  console.log(`[steps] ${a.task?.id} ${a.cycle?.cycle}#${a.unit} -> something wild (candidates are ${(a.next ?? []).join(", ")})`);
  return "nowhere";
}
