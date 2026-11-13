/**
 * Express the contract for place `tab:deck` as a rule.
 *
 * Attach it to `unit_start`, with `when` requiring `place = tab:deck`, so it checks only execution units starting at this place:
 *
 * 1. **The URL is still open**: this page defines the place; if the page disappears, the place no longer exists.
 * 2. **All expected tools are registered**.
 *
 * ## Why this must be a rule
 *
 * Declaration can check only once: `/declare` rejects the whole declaration if the server cannot be reached. But a browser tab is **live state**: the user can close it while the tool rows remain in the database, leaving an empty place. The next execution unit still offers `deck_next`, the model calls it, and receives isError.
 *
 * Registration and current availability are different, just as `workplace.usable` is registration, not a liveness probe. Check **at every start**, which is precisely a moment + rule.
 *
 * ## It does not block execution
 *
 * A failed rule affects only itself: the kernel logs it and this execution unit continues (see `#atMoment` in `loop.ts`). This is deliberate. Hooks run on the main path; allowing one broken rule to stop the entire step could stall every task. This rule therefore **immediately explains what is wrong** rather than closing a gate.
 */

const BASE = process.env.TGENGIN_BASE ?? "http://127.0.0.1:7801/api";
const CDP = process.env.TGENGIN_DECK_CDP ?? "http://127.0.0.1:9222";

/** Which page defines the place and which tools it must provide: these two lines are the contract. */
const LINK = process.env.TGENGIN_DECK_URL ?? "file:///E:/sgu-bzhc/EACN_EX/TgEngin/examples/place/deck.html";
const WANT = ["deck_state", "deck_next", "deck_prev", "deck_goto"];

async function openTabs(): Promise<string[]> {
  const res = await fetch(`${CDP}/json/list`);
  const list = (await res.json()) as { type: string; url: string }[];
  return list.filter((t) => t.type === "page").map((t) => t.url);
}

async function registered(): Promise<string[]> {
  const res = await fetch(`${BASE}/query`, {
    method: "POST",
    headers: { "content-type": "application/json" },
    body: JSON.stringify({ sql: `select name from tool where identity like 'mcp:deck/%' order by name` }),
  });
  const got = (await res.json()) as { rows?: { name: string }[] };
  return (got.rows ?? []).map((r) => r.name);
}

export async function run(arg: unknown): Promise<unknown> {
  const at = (arg ?? {}) as { place?: string; task?: { id?: string }; unit?: number };
  const bad: string[] = [];

  let tabs: string[] = [];
  try {
    tabs = await openTabs();
  } catch {
    bad.push(`cannot reach the browser debugging port (${CDP})`);
  }
  if (tabs.length && !tabs.includes(LINK)) {
    bad.push(`that page is not open: ${LINK} (currently open: ${tabs.join(", ") || "nothing"})`);
  }

  const have = await registered();
  const missing = WANT.filter((w) => !have.includes(w));
  if (missing.length) bad.push(`expected tools are missing: ${missing.join(", ")} (present: ${have.join(", ") || "none"})`);

  const where = `${String(at.task?.id)} station ${String(at.unit)}`;
  if (bad.length) {
    // Throw the error. The kernel logs it and continues this execution unit; the rule cannot and should not block it.
    throw new Error(`something is wrong with the place ${at.place ?? "?"} (${where}): ${bad.join("; ")}`);
  }
  console.log(`[deck-contract] ${at.place} is complete: ${have.join(", ")} | ${where}`);
  return { place: at.place, link: LINK, tools: have };
}
