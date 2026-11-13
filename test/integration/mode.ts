/**
 * Example: **add a task mechanism externally**, at the same level as dfs.
 *
 * ```
 * bun test/integration/mode.ts
 * ```
 *
 * A mechanism consists of a graph of cycles linked by `from`/`next` and an
 * **inference function** (`infer`) deciding where to go after each station.
 *
 * Both the graph and inference function in this example live **outside the process**;
 * no kernel code is changed:
 *
 * ```
 *   plan --> work --> wrap
 *              ^         |
 *              +---------+   (work may loop to itself; wrap finalizes)
 * ```
 *
 * ## The kernel accepts only three response forms
 *
 * The inference function returns:
 *
 * - `null`: stop here.
 * - `"cycle-name"`: go to that cycle, **continuing from the current row**.
 * - `{to, from_cycle, from_unit, status}`: go to that cycle, **continuing from the
 *   specified row**, and mark the current row with a terminal status. Tree siblings
 *   and backtracking both use this form.
 *
 * **Selecting anything outside `next` fails immediately**. The second part tests this constraint.
 */

import { done, machine, ok, outside, part, show, step, until } from "../_lib.ts";

const m = await machine();

/** Every station calls this handle. Record the path for validation in the second part. */
const walked: string[] = [];

const out = await outside({
  "/unit": (u) => {
    walked.push(`${u.chain}`);
    return { role: "assistant", kind: "prompt", body: `${(u.cycle as { cycle?: string })?.cycle} finished` };
  },
  /**
   * Inference function. **The kernel provides candidates; this selects one of them.**
   *
   * The path is plan -> work -> work -> wrap -> stop. The second work deliberately
   * uses `{to, from_cycle, from_unit}` to test continuation from a specified row.
   */
  "/infer": (a) => {
    const cyc = (a.cycle as { cycle?: string })?.cycle;
    const next = (a.next ?? []) as string[];
    const unit = Number(a.unit);
    if (cyc === "plan") return "work";
    if (cyc === "work") {
      // The first work creates another work below itself; the second proceeds to finalization.
      const nth = walked.filter((c) => c.includes("/work#")).length;
      if (nth <= 1) return { to: "work", from_cycle: "work", from_unit: unit };
      return "wrap";
    }
    if (cyc === "wrap") return null; // Stop here.
    return next[0] ?? null;
  },
  /** Deliberately select a cycle outside the candidates to verify that the kernel rejects it. */
  "/infer-wild": () => "no-such-cycle-at-all",
});

try {
  // =============== Part 1: registration ===============
  part("Part one: registration");

  step("1. next points outside this mode");
  const strayed = await m.bad("POST", "/declare", {
    handles: [{ name: out.url("/infer"), expectMs: 10_000 }],
    modes: [
      {
        mode: "flow",
        cycles: [
          { cycle: "plan", from: [], next: ["work"], infer: out.url("/infer") },
          { cycle: "work", from: ["plan"], next: ["wrap-up"], infer: out.url("/infer") },
        ],
      },
    ],
  });
  show("it answered:", strayed.problems);
  ok("stopped - otherwise the flow would simply halt there, silently", JSON.stringify(strayed.problems).includes("not in this mode"), strayed.problems);

  step("2. a cycle nothing points at (dead code in a declaration)");
  const island = await m.bad("POST", "/declare", {
    handles: [{ name: out.url("/infer"), expectMs: 10_000 }],
    modes: [
      {
        mode: "flow",
        cycles: [
          { cycle: "plan", from: [], next: ["work"], infer: out.url("/infer") },
          { cycle: "work", from: ["plan"], next: [], infer: out.url("/infer") },
          { cycle: "island", from: ["plan"], next: [], infer: out.url("/infer") },
        ],
      },
    ],
  });
  show("it answered:", island.problems);
  ok("a cycle unreachable from any entry point is named", JSON.stringify(island.problems).includes("unreachable from any entry point"), island.problems);

  step("3. no entry point at all (every cycle has a non-empty from)");
  const noEntry = await m.bad("POST", "/declare", {
    handles: [{ name: out.url("/infer"), expectMs: 10_000 }],
    modes: [
      {
        mode: "flow",
        cycles: [
          { cycle: "a", from: ["b"], next: ["b"], infer: out.url("/infer") },
          { cycle: "b", from: ["a"], next: ["a"], infer: out.url("/infer") },
        ],
      },
    ],
  });
  show("it answered:", noEntry.problems);
  ok("the mode cannot be entered at all, and it says so at once", JSON.stringify(noEntry.problems).includes("cannot be entered"), noEntry.problems);

  step("4. load a correct graph");
  const loaded = await m.api<Record<string, unknown>>("POST", "/declare", {
    handles: [
      { name: out.url("/unit"), expectMs: 30_000 },
      { name: out.url("/infer"), expectMs: 10_000 },
      { name: out.url("/infer-wild"), expectMs: 10_000 },
    ],
    places: [{ place: "local" }],
    modes: [
      {
        mode: "flow",
        note: "think first, work a few rounds, then wrap up",
        cycles: [
          { cycle: "plan", from: [], next: ["work"], maxUnits: 1, infer: out.url("/infer") },
          { cycle: "work", from: ["plan", "work"], next: ["work", "wrap"], maxUnits: 5, infer: out.url("/infer") },
          { cycle: "wrap", from: ["work"], next: [], maxUnits: 1, infer: out.url("/infer") },
        ],
      },
      {
        mode: "wild",
        cycles: [
          { cycle: "one", from: [], next: ["two"], infer: out.url("/infer-wild") },
          { cycle: "two", from: ["one"], next: [], infer: out.url("/infer") },
        ],
      },
    ],
    agents: [{ name: "bot", apis: [], unit: out.url("/unit") }],
  });
  show("what went in:", { modes: loaded.modes, cycles: loaded.cycles, tables: loaded.tables, entries: loaded.entries });
  ok("both mechanisms went in", (loaded.modes as string[]).length === 2, loaded.modes);
  ok("the entry points come back too - with more than one, a task must name a cycle", JSON.stringify(loaded.entries).includes("plan"), loaded.entries);

  step("5. look at the graph");
  const g = await m.api<Record<string, unknown>>("GET", "/modes/flow");
  show("flow：", { entries: g.entries, walkable: g.walkable, agents: g.agents, cycles: (g.cycles as unknown[]).length });
  ok("it is walkable", g.walkable === true, g);
  ok("bot can serve it", (g.agents as string[]).includes("bot"), g.agents);

  // =============== Part 2: actual-use validation ===============
  part("Part two: checks at the level of use");
  console.log("  A correct graph is not the same as actually walking it. Publish a task and see which path it took.");

  step("6. publish a task and let it walk plan -> work -> work -> wrap");
  await m.api("POST", "/tasks", {
    id: "t-flow", mode: "flow", agent: "bot", place: "local", source: "user", description: "walk it once",
  });
  await until("t-flow to finish", async () => {
    const d = await m.api<{ state: string }>("GET", "/tasks/t-flow");
    return d.state === "done" ? d : null;
  });
  show("the chain string at each station:", walked);
  ok("it walked exactly the path in the declaration", walked.length === 4, walked);
  ok("the first station is plan", walked[0] === "flow/plan#1", walked[0]);
  ok(
    "the chain string runs from the head to here with no segment missing",
    walked.at(-1) === "flow/plan#1 > flow/work#2 > flow/work#3 > flow/wrap#4",
    walked.at(-1),
  );

  step("7. tree shape: a `{to, from_cycle, from_unit}` answer really hangs the node under the row it names");
  const tree = await m.api<{ roots: Record<string, unknown>[]; orphans: unknown[] }>("GET", "/tasks/t-flow/tree");
  const flatten = (n: Record<string, unknown>): string[] => [
    `${n.cycle}#${n.unit}`,
    ...((n.children ?? []) as Record<string, unknown>[]).flatMap(flatten),
  ];
  show("the tree:", tree.roots.map(flatten));
  ok("one tree, not four independent roots", tree.roots.length === 1, tree.roots.length);
  ok("no orphans (every parent row named is present)", tree.orphans.length === 0, tree.orphans);

  step("8. the inference function picks a cycle outside the candidates");
  await m.api("POST", "/tasks", {
    id: "t-wild", mode: "wild", agent: "bot", place: "local", source: "user", description: "see whether it dares pick freely",
  });
  const stuck = await until("the kernel to write the stuck reason into the database", async () => {
    const w = await m.api<{ problems: string[] }>("GET", "/tasks/t-wild/why");
    return w.problems.some((p) => p.includes("not among the candidates")) ? w : null;
  });
  show("why it is not moving:", stuck.problems);
  ok("the kernel does not let it improvise, and it names the candidates too", JSON.stringify(stuck.problems).includes("not among the candidates"), stuck.problems);
  ok(
    "this sentence came out of the API, with no need to dig through server logs",
    stuck.problems.some((p) => p.includes("the kernel threw while advancing it")),
    stuck.problems,
  );
} finally {
  out.stop();
  m.stop();
}

done();
