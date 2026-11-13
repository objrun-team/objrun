/**
 * Tree control flow: **spawn children / mark dead and open a sibling / backtrack upward**.
 *
 * This is an **inference function** referenced by `cycle.infer`, not part of the kernel. The kernel recognizes return shapes, not the meaning of siblings or backtracking. Changing search strategy means replacing an `infer` handle without changing the kernel.
 *
 * ## Terminal node states are fixed when assigned and never revised
 *
 * | State | Meaning |
 * | --- | --- |
 * | `reached` | Reached the goal; this path succeeded |
 * | `dead_failed` | Marked dead: this step failed |
 * | `dead_below_bar` | Marked dead: below the required standard |
 * | Empty | Still running |
 *
 * **Death uses a mixed policy**: either `dead_failed` or `dead_below_bar` counts as dead and opens a sibling. Separate values preserve whether the attempt failed outright or was insufficient, but are equivalent for branching.
 *
 * ## What happens after marking a node dead?
 *
 * 1. Count dead siblings under the same parent.
 * 2. **Below the limit**: open a new sibling under that parent and try another direction.
 * 3. **At the limit**: backtrack **higher**, opening a branch under the grandparent because this level's directions are exhausted.
 * 4. **No path remains at the root**: stop.
 *
 * A separate concurrency gate prevents opening new rows when **unfinished** rows under one parent reach `max_branches`. This controls simultaneous branches, not the count of dead ones.
 *
 * ## Moves must stay within the candidates: data is authoritative
 *
 * The kernel permits only selections from `cycle.next`, rejecting anything outside it. Therefore:
 *
 * - To **open a sibling**, a cycle must **include itself** in `next`.
 * - To **backtrack**, `next` must include the cycle to return to.
 *
 * This expresses the problem's allowed transitions as data. If the cycle table does not allow siblings, the tree must not open them on the inference function's own authority.
 *
 * ## ĝ guides progress; G checks only a claimed arrival
 *
 * These criteria serve different purposes. Mixing them prevents the tree from reaching a second level:
 *
 * - **ĝ (self-assessment / heuristic)**: is this step finished? Continuing tool requests mean no; keep deriving children. As the old code explained, greenness, scores, and confidence levels are search heuristics internal to `F`: the model's **estimate** of progress, not part of the sample format.
 * - **G (verifier)**: returns only 0/1 and runs **when a node claims to have reached the goal**. A 1 confirms `reached`; a 0 means the claimed arrival was wrong, yielding `dead_failed` and a sibling trying another direction.
 *
 * That is verifier-guided search: not querying G at every step (which kills intermediate steps before the tree can grow), but **refusing to let the model's own claim be final**.
 */

import type { Conn } from "../H2H/db.ts";
import { all, run } from "../H2H/db.ts";
import type { Registry } from "../engine/registry.ts";
import { deliverVerdict } from "../msg/deliver.ts";
import { tableNameOf } from "../install/index.ts";
import { candidateInput, evaluate } from "../objective/run.ts";
import { CANDIDATE, type Sealed } from "../objective/store.ts";

type Row = Record<string, unknown>;

/** Input received by the inference function. */
interface Ask {
  task: Row;
  cycle: Row;
  agent: Row;
  chain: string;
  next: string[];
  result: unknown;
  /** Which subtable and row this is. */
  sub: string;
  unit: number;
}

/** The return shape expected by the kernel. */
interface Said {
  to: string | null;
  /** Parent of the new row. **`null` = attach at the root (no parent)**; omit the key to continue from the current row. */
  from_cycle?: string | null;
  from_unit?: number | null;
  status?: string;
}

interface Node {
  cycle: string;
  unit: number;
  /** The node this row belongs to. A node is one complete attempt with its own allowance. */
  node: number;
  from_cycle: string | null;
  from_unit: number | null;
  status: string | null;
  done: number;
}

const DEAD = new Set(["dead_failed", "dead_below_bar"]);

/** Inference function for the tree mechanism. Using this name in a cycle's `infer` selects this mechanism. */
export const TREE_INFER = "fn:infer.dfs";

/** The station supplied by this mechanism: **submission**. */
/** Verifier tool name. **One source of truth**, also used when recording the submission verdict. */
export const VERIFY = "verify";

export const SUBMIT = "submit";

/** Shape of a declared cycle (accepted by `declare/index.ts`). */
export interface DeclaredCycle {
  cycle: string;
  apiMode?: string;
  maxUnits?: number;
  from?: string[];
  next?: string[];
  infer: string;
  [k: string]: unknown;
}

/**
 * **Install the submission station with the mechanism; declarations need not define it.**
 *
 * Any mode with a cycle using the tree mechanism needs a submission station. This is a property of the mechanism, not of the problem: grade **the actual submission**, and give submission a designated station. Repeating its definition in every declaration risks an omission that reverts to the kernel guessing which message looks like an answer, and those guesses can be wrong.
 *
 * Also add it to working stations' `next`. The kernel only permits inference to select from `next`; without this, routing to submission would be rejected immediately.
 *
 * **Leave an explicitly declared `submit` unchanged.** Supply a default without taking control away.
 *
 * Do not introduce a separate allowance bottleneck: use the sum of working stations' limits for submission, so remaining work rounds, not remaining submissions, determine progress.
 */
export function withSubmit(cycles: DeclaredCycle[]): DeclaredCycle[] {
  const tree = cycles.filter((c) => c.infer === TREE_INFER);
  if (tree.length === 0) return cycles;
  if (cycles.some((c) => c.cycle === SUBMIT)) return cycles;

  // After submission, continue at the **entry station**, the mechanism's station with an empty `from`.
  //
  // A verdict of 0 only rejects this submission. What follows is **a fresh attempt**, starting with reasoning. Previously the successor was an action station, justified as completing the previous station's requested tools. That rationale fails after the node dies: running its tools has no purpose, and making a fresh node run tools it never requested wastes a slot.
  //
  // Observed sequence: `submit#8[dead_failed] → act#9 → submit#10`. The new node submitted again after two steps without reasoning once.
  const entry = tree.filter((c) => (c.from ?? []).length === 0);
  const after = entry.length > 0 ? entry : tree;
  const names = new Set(tree.map((c) => c.cycle));

  return [
    // **Every station can reach submission.** Submitting when the work allowance is exhausted is a node-level rule,
    // and it must be represented in the table. The kernel permits only edges the table describes
    // (the `loop.ts` allowlist: `if (!saidFrom && !next.includes(to))`).
    //
    // An inference function could bypass the allowlist by supplying a parent pointer, but that would hide the edge from the table. Divergence between declared and actual transitions is what would corrupt the model.
    ...cycles.map((c) => (names.has(c.cycle) ? { ...c, next: [...new Set([...(c.next ?? []), SUBMIT])] } : c)),
    // **This is the only submission row.** It fully declares its predecessors, successors, and judge.
    {
      cycle: SUBMIT,
      mustCall: SUBMIT_TOOL.name,
      // **This station can do only one thing, enforced in the request itself.**
      //
      // Only `submit` is offered (see the non-submission-station condition in `tools/index.ts`), but offering one tool does not prevent requests for unoffered ones. In practice the model requested `web_search` here, wasting a slot because nobody executed it; a "not executed" result was added later. Requiring this specific tool also prevents a long response with no submission.
      //
      // Previously this could not be the default because **it conflicts with reasoning**: models reject `tool_choice` with HTTP 400 while reasoning. The adapter now handles that constraint, disabling reasoning when a station requires a specific tool (see `llm/index.ts`). Submission needs no reasoning anyway; the answer was worked out earlier.
      // Use the same track type as the working stations. Hard-coding chat would strand a non-model mechanism (an external `agent.unit` handle) because its agent has no chat track.
      apiMode: tree.map((c) => (c.apiMode ?? "").trim()).find((x) => x !== "") ?? "",
      // **One submission per node.** Every submission station records a terminal state, successful or dead, ending the node;
      // a second submission within it is structurally impossible. Allowances are per node (see `full`), so 1 accurately describes this table. A large value such as the sum of working-station limits would falsely suggest multiple submissions per node.
      maxUnits: 1,
      from: tree.map((c) => c.cycle),
      // After submission, enter the next node's entry station. A 0 rejects this submission, not the entire problem.
      // The terminal-station version (`next: []`) could only backtrack, then immediately return to submission with the same answer.
      next: after.map((c) => c.cycle),
      infer: TREE_INFER,
    },
  ];
}

function nodesOf(db: Conn, sub: string, task: string): Node[] {
  return all(db, `select cycle, unit, node, from_cycle, from_unit, status, done from "${sub}" where task = ?`, [
    task,
  ]) as unknown as Node[];
}

/**
 * Answer submitted in this slot, or its predecessor within the same node. Return `null` if no submission exists.
 *
 * **The answer comes from call arguments, not parsed speech.** Parsing is a fallback guess: a model may produce three passages, each with a formula. Choosing the wrong one looks like a correct answer being graded 0, especially difficult to diagnose because the logs really do contain the correct answer.
 *
 * ## Why inspect the previous slot, and why restrict it to the same node?
 *
 * Submission from a working station is allowed. That call already submits the answer; control moves to the submission station without requiring it again. The submission station must therefore recognize the previous slot's call.
 *
 * **But the previous slot may belong to another node.** A fresh node's first station follows **the previous node's submission station**, which contains a `submit`. Without the node restriction, the new node is immediately classified as already submitted and redirected to submission. Its verification and previous-failure-inspection calls never run, and it blindly resubmits an unchanged answer.
 *
 * Observed example: cmt-3's node2 was consumed this way (`ask#5` requested four `verify` calls, none executed, and immediately moved to `submit#6` and died). Its node3 worked only because node2's submission station produced no submission: luck, not a reliable rule.
 */
/**
 * The instance's latest submitted answer. **The sole authority for what was submitted.**
 *
 * Submission means calling `submit` with the answer. Every consumer asks here. Independent readers could select two different answers: the submission station grades call arguments, while finalization grades incidental speech, and the latter becomes the reported score. Problems have been lost exactly this way.
 *
 * When `units` is supplied, inspect only those slots (the submission station uses it to restrict scope to one node); otherwise inspect the whole instance.
 */
export function handedIn(
  db: Conn,
  agent: string,
  instance: string,
  units?: number[],
): string | null {
  const t = tableNameOf("agent_{}_msg", agent);
  const where = units ? ` and unit in (${units.map(() => "?").join(", ")})` : "";
  const rows = all(db, `select body from "${t}" where instance = ?${where} and kind = 'call' order by unit, seq`, [
    instance,
    ...(units ?? []),
  ]) as { body: string }[];
  let found: string | null = null;
  for (const r of rows) {
    try {
      const v = JSON.parse(r.body) as { calls?: { name?: string; input?: { answer?: unknown } }[] };
      for (const c of v.calls ?? []) {
        if (c.name !== SUBMIT) continue;
        // An empty submission still counts: it is the submitted answer. Grading it 0 belongs to the grader, not this function.
        found = typeof c.input?.answer === "string" ? c.input.answer : "";
      }
    } catch {
      // An unreadable row counts as no submission.
    }
  }
  return found;
}
function submitted(
  db: Conn,
  inst: { agent: string; instance: string } | undefined,
  unit: number,
  sameNode: (u: number) => boolean,
): string | null {
  if (!inst) return null;
  const look = [unit, unit - 1].filter((u) => u > 0 && sameNode(u));
  if (look.length === 0) return null;
  return handedIn(db, inst.agent, inst.instance, look);
}

/**
 * Whether this exact candidate has already been checked by G through `verify`, and the resulting verdict.
 *
 * Compare the **original answer text** exactly. A one-character difference creates a different candidate to which the previous verdict does not apply.
 */
function verdictFor(
  db: Conn,
  inst: { agent: string; instance: string } | undefined,
  said: string,
): { pass: 0 | 1; why: string; note: string } | null {
  if (!inst || !said.trim()) return null;
  const t = tableNameOf("agent_{}_msg", inst.agent);
  const rows = all(db, `select unit, seq, kind, body from "${t}" where instance = ? order by unit, seq`, [
    inst.instance,
  ]) as { unit: number; seq: number; kind: string; body: string }[];
  const asked = new Map<string, string>(); // Call id → candidate checked.
  let hit: { pass: 0 | 1; why: string; note: string } | null = null;
  for (const r of rows) {
    let v: { calls?: { id?: string; name?: string; input?: { answer?: unknown } }[]; id?: string; name?: string; value?: { pass?: unknown; valid?: unknown; outcome?: unknown; why?: unknown; note?: unknown } };
    try {
      v = JSON.parse(r.body) as typeof v;
    } catch {
      continue;
    }
    if (r.kind === "call") {
      for (const c of v.calls ?? []) {
        if (c.name === "verify" && typeof c.input?.answer === "string" && c.id) asked.set(c.id, c.input.answer);
      }
    } else if (r.kind === "tool" && v.name === "verify" && v.id && asked.get(v.id) === said) {
      if (v.value?.valid === false || v.value?.outcome === "grader_error") continue;
      if (v.value?.pass !== 0 && v.value?.pass !== 1) continue;
      const pass = v.value.pass;
      hit = { pass, why: String(v.value?.why ?? ""), note: String(v.value?.note ?? "") };
    }
  }
  return hit;
}

/**
 * What this station **said aloud**.
 *
 * A `prompt` row's `body` is the text; a `call` row's `body` is `{text, calls}`, with speech in `text`. Passing the latter unchanged would supply a JSON object instead of the spoken answer.
 */
function spokenAt(result: unknown): string {
  const r = (result ?? {}) as { kind?: string; body?: unknown };
  if (r.kind === "prompt") return String(r.body ?? "");
  if (r.kind === "call") {
    try {
      return String((JSON.parse(String(r.body ?? "")) as { text?: unknown }).text ?? "");
    } catch {
      return "";
    }
  }
  return "";
}



/**
 * Whether this cycle's allowance **within this node** is exhausted.
 *
 * Counting across the whole problem would let the first node exhaust the budget, allowing only one submission and preventing retry after failure. Each node is one attempt with its own budget.
 */
function full(db: Conn, a: Ask, nodes: Node[], cycle: string, node: number): boolean {
  const cap = all(db, `select max_units from cycle where mode = ? and cycle = ?`, [
    String(a.task.mode),
    cycle,
  ])[0] as { max_units?: number } | undefined;
  if (!cap) return false;
  return nodes.filter((n) => n.cycle === cycle && Number(n.node) === node).length >= Number(cap.max_units);
}

/**
 * **The submission tool. The answer is in its arguments.**
 *
 * It does two things: submits an answer and declares completion, causing an early transition to the submission station.
 *
 * **Read the answer from arguments, not parsed speech.** The older version accepted no parameters and submitted speech from the submission station, with a fallback searching other calls' `answer` fields. Both paths guessed: a model may produce three passages with one formula each. Selecting the wrong one looks like a correct answer graded 0, especially hard to diagnose because the logs contain a correct answer.
 *
 * The parameter schema follows G (`objective.params`). The kernel wraps G as `verify`, and submission invokes that same G internally, so both naturally require identical inputs.
 *
 * Exhausting the working stations' allowances also reaches submission without calling this tool. Its purpose is **early** submission: after a 0, enough budget remains to open another node. All observed winning cases used that path.
 *
 * ## Division of responsibility with `verify`
 *
 * `verify` is **validation**: check a candidate during work, at any time and potentially repeatedly. `submit` is **submission**: work is complete; grade this answer. Two moments, two operations.
 *
 * Whether the problem has G does not change this tool's shape. It changes **whether the submission station performs an extra step**: grade once when G exists, otherwise finish directly.
 */
const SUBMIT_TOOL = {
  name: SUBMIT,
  does:
    "Hand the work in: the answer passed here is what gets graded, exactly as written. Text that is not " +
    "passed here is not read as an answer.",
  // **The parameter schema follows G** (`objective.params`). The kernel wraps G as `verify`, and submission invokes the same G,
  // so both require identical inputs. Duplicated literal schemas would drift when G gains a field: one would be updated while the other silently receives incomplete input from a model following the first description.
  params: CANDIDATE,
  output: { type: "object", properties: { handingIn: { type: "boolean" } } },
  prompt:
    "At the hand-in step no other tool is attached. The hand-in step is reached on its own once the working " +
    "budget runs out.",
  expectMs: 10_000,
};

/**
 * Register tree control flow.
 *
 * `sealed` supplies the criterion from G. Without it, only self-assessment remains, leaving the tree to search blindly.
 */
export function registerTree(db: Conn, reg: Registry, sealed: Sealed): string[] {
  reg.register(db, "fn:infer.dfs", 900_000, async (arg) => {
    const a = arg as unknown as Ask;
    const task = String(a.task.id);
    const here = String(a.cycle.cycle);
    const nodes = nodesOf(db, a.sub, task);
    const me = nodes.find((n) => n.cycle === here && n.unit === a.unit);
    if (!me) throw new Error(`cannot find ${here}#${a.unit} of ${task} in ${a.sub}`);

    const inst = all(db, `select agent, instance from "${a.sub}" where task = ? and cycle = ? and unit = ?`, [
      task,
      here,
      a.unit,
    ])[0] as { agent: string; instance: string } | undefined;

    // ── Working stations: **do not grade here** ────────────────────────────
    //
    // Verdicts are issued only at submission. Previously any `prompt` triggered G, meaning the kernel submitted something the agent never submitted. Empty prompts (a model call producing nothing) were also graded, wasting a G call and killing a branch. Two observed problems were lost this way.
    if (here !== SUBMIT) {
      const r = (a.result ?? {}) as { kind?: string; body?: unknown };

      // **Two routes to the submission station:**
      //
      // 1. It called `submit`: an actual submission, so route there early.
      // 2. It produced nonempty speech: a claim of completion, also routed there (reachable without a tool call).
      //
      // Empty output does not count. A `prompt` containing nothing is a failed generation, not a claim of completion. Advance normally so the next station can continue.
      // The `node` column determines which slots belong to this node.
      const here_node = Number(me.node);
      const sameNode = (u: number) => nodes.some((n) => Number(n.unit) === u && Number(n.node) === here_node);
      const handedIn = submitted(db, inst, a.unit, sameNode) !== null;
      const spoke = r.kind === "prompt" && spokenAt(a.result).trim() !== "";

      // **Routing to submission is a node-level rule represented in the table.** Every station's `next` includes submission
      // (added by `withSubmit`), so advance directly. The kernel permits only declared edges; bypassing the allowlist with a parent pointer would hide this edge from the table.
      const toSubmit = { to: SUBMIT } satisfies Said;

      // It finished speaking or invoked submission: route there early.
      if (handedIn || spoke) return toSubmit;

      // Working-station allowances are exhausted: time to submit. **This does not depend on whether it wants to submit.**
      const to = a.next.find((c) => c !== SUBMIT) ?? null;
      if (to === null || full(db, a, nodes, to, Number(me.node))) return toSubmit;

      // Allowance remains: advance one slot through the candidates, continuing from the current row.
      return { to } satisfies Said;
    }

    // ── Submission station ────────────────────────────────────────────────
    //
    // The station's speech is its submission. Problems without G finish here; those with G perform **one additional step**: grading. Prior verification does not change the shape of submission, only whether this step can succeed.
    let status = "reached";
    if (sealed.has(task)) {
      // **Submit the candidate in the call; do not parse the station's speech.**
      //
      // Previously submission used the station's speech with a fallback searching other tool calls for an `answer` field. Both guessed: a model could produce three passages, each with a formula. A wrong selection looks like a correct answer graded 0, hard to diagnose because the logs do contain the correct answer.
      //
      // There is now only one path: call `submit` with the answer. No call = no submission.
      // The `node` column determines which slots belong to this node.
      const here_node = Number(me.node);
      const sameNode = (u: number) => nodes.some((n) => Number(n.unit) === u && Number(n.node) === here_node);
      const said = submitted(db, inst, a.unit, sameNode);
      // **Nothing was submitted.** This station had one operation to perform and did not perform it. There is nothing to grade; the node ends here.
      //
      // An incorrect submission differs from no submission, so explain precisely. The former has a verdict with `why`, which the next node can inspect and address. The latter has only this message saying the required step was not performed.
      if (said === null) {
        if (inst) {
          deliverVerdict(db, {
            agent: inst.agent,
            instance: inst.instance,
            unit: a.unit,
            name: VERIFY,
            input: { task, at: `${here}#${a.unit}` },
            value: { pass: 0, why: "nothing was handed in - this step takes an answer and none was given" },
          });
        }
        status = "dead_failed";
      } else {
        const g = sealed.open(task)!;

      // **Do not grade an already verified candidate again.** `verify` validates during work; submission commits the candidate now.
      // These are different moments querying the same G. If the exact candidate was just checked, reuse that verdict. Another grader call only adds cost and another opportunity for variability.
      const had = g.reuse === "text" ? verdictFor(db, inst, said) : null;
      // **Pass the extracted candidate, not the raw result.** Passing it unchanged would give G the entire `{text, calls}` JSON object,
      // undoing the extraction above. Match finalization's shape (`main.ts`: `result: {body}`), so one G script works in both paths.
      const v = had ?? (await evaluate(g, reg, candidateInput(a.task, said, a.chain)));

      // **Put verdicts into context**, not only logs. Represent them as a tool call with a result: an external observation for this attempt, matching tool-result semantics.
      //
      // Attach them to **the submission station**. Siblings deliberately do not inherit them; they must use `node_load` to retrieve them. Shared progress means visibility, not direct inheritance.
      if (inst) {
        deliverVerdict(db, {
          agent: inst.agent,
          instance: inst.instance,
          unit: a.unit,
          name: VERIFY,
          input: { task, at: `${here}#${a.unit}` },
          // **Include `why`.** A bare 0/1 tells the model it failed without explaining why.
          // That is barely more useful than no verdict; the next branch will likely repeat the same path.
          value: { pass: v.pass, valid: "valid" in v ? v.valid : true, outcome: "outcome" in v ? v.outcome : (v.pass === 1 ? "passed" : "rejected"), why: v.why, note: v.note, ...(had ? { reused: true } : {}) },
        });
      }

        if (v.pass !== 1) status = "dead_failed";
      }
    }

    // A verdict of 1 means the problem is solved; stop the tree here.
    if (status === "reached") return { to: null, status } satisfies Said;

    // ── Verdict 0: try again in the next node ───────────────────────────────
    //
    // **Attach the new node under the closing row.** Node numbers grow as follows:
    //
    //   node(new row) = node(parent) + (parent.status nonempty ? 1 : 0)
    //
    // The closing row has a terminal state, so its child starts the next node with a fresh allowance. The backtracking path attaches under an ancestor **without** a terminal state, leaving node unchanged and budget unreset: "trying another path" would continue within the same node.
    //
    // The table chooses the destination (`submit.next` = action phase).
    //
    // `max_dead_siblings` controls how many nodes a problem may try. Count **dead nodes**, not rows: a node dies once, regardless of how many rows it contains.
    {
      const tried = new Set(
        nodes.filter((n) => n.status !== null && DEAD.has(n.status)).map((n) => Number(n.node)),
      ).size;
      if (tried >= Number(a.task.max_dead_siblings ?? 3)) return { to: null, status } satisfies Said;
      const on = a.next.find((c) => c !== SUBMIT) ?? null;
      if (on !== null) return { to: on, status } satisfies Said;
      return { to: null, status } satisfies Said;
    }

    // After a 0, use **the existing control flow**: submission does not open its own sibling (resubmitting the same candidate is pointless), so take the backtracking path. `to: parent.cycle` selects the action phase under the grandparent, a sibling of the dead action phase: the next node's action phase.
    //
    // I once added a direct forward step here, incorrectly: without `from_cycle`, the new row attaches under **the dead submission row**, making the tree deeper without any branching.
    //
    // ── A former sibling/backtracking block below was removed ──────────────
    //
    // It handled death at working stations: open a sibling under the same parent, then climb upward after enough attempts. But only submission issues verdicts; working stations never produce a status, so that block was unreachable.
    //
    // The node transition is already handled above: attaching under the closing row increments node and resets its allowance naturally. Keeping dead code would imply a second tree-growth mechanism that does not exist.
  });

  // **Install the submission tool with this mechanism.** It belongs to the mechanism, not a particular declaration.
  // Its condition checks whether this station uses the tree inference function, just like `task_tree` / `node_load`.
  reg.register(db, `fn:tool.${SUBMIT_TOOL.name}`, SUBMIT_TOOL.expectMs, async () => ({ handingIn: true }));
  run(
    db,
    `insert into tool (name, identity, does, params, output, prompt, concurrent, system, access, usable, gives)
     values (?, ?, ?, ?, ?, ?, 0, 0, null, 1, 'receipt')
     on conflict(name) do update set
       identity = excluded.identity, does = excluded.does, params = excluded.params,
       output = excluded.output, prompt = excluded.prompt, system = excluded.system`,
    [
      SUBMIT_TOOL.name,
      `fn:tool.${SUBMIT_TOOL.name}`,
      SUBMIT_TOOL.does,
      JSON.stringify(SUBMIT_TOOL.params),
      JSON.stringify(SUBMIT_TOOL.output),
      SUBMIT_TOOL.prompt,
    ],
  );
  run(db, `delete from trigger where owner_kind = 'tool' and owner = ?`, [SUBMIT_TOOL.name]);
  run(
    db,
    `insert into trigger (owner_kind, owner, "group", dim, "key", op, value)
     values ('tool', ?, 0, 'cycle', 'infer', 'eq', ?)`,
    [SUBMIT_TOOL.name, TREE_INFER],
  );

  return [TREE_INFER, SUBMIT_TOOL.name];
}
