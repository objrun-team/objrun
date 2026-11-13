/**
 * Evaluate G.
 *
 * Execute nodes in topological order. Each invokes its handle, validates the returned value
 * against its domain, and passes outputs along edges. The root node's Boolean is G's verdict.
 *
 * ## A total function with default 0
 *
 * Handle failures still produce false so G's domain remains Boolean. Execution success is
 * recorded separately in receipt fields `valid` / `outcome`. Infrastructure failure must not
 * count as an incorrect candidate, consume a valid-check allowance, or justify verdict reuse.
 *
 * When returning 0, **include the reason**. The verdict is binary, but diagnostics must explain it.
 *
 * ## A false-valued node may also return `note`
 *
 * Nodes may return plain `true` / `false`, the original shape and the usual case, or `{ value, note }`.
 * `note` is free-form text or JSON, parsed and stored as a string in the added verdict field.
 * **It defaults to empty**, preserving existing behavior when omitted.
 *
 * `why` still describes a node that failed to evaluate. Keep it separate: combining "evaluated
 * to false" with "could not evaluate" would obscure why the final verdict is 0.
 *
 * **The node controls feedback detail**. This layer neither interprets nor truncates it.
 */

import type { Registry } from "../engine/registry.ts";
import { checkValue, domainText, type Node, type Objective } from "./spec.ts";

export interface Verdict {
  /** Verdict: **only 0 or 1**. */
  pass: 0 | 1;
  /** Whether every node executed successfully and satisfied its output contract. If false, pass=0 closes the success path; it does not mark the answer incorrect. */
  valid: boolean;
  outcome: "passed" | "rejected" | "grader_error";
  /**
   * Reason for a zero verdict, empty on success.
   *
   * **Expose this to the agent** through both `deliverVerdict` and `verify`. A bare 0/1 explains
   * neither the problem nor how to correct it, so the next branch may repeat the same failure.
   * Protect the ground truth, not the verdict.
   */
  why: string;
  /**
   * **Additional feedback supplied by false-valued nodes**, empty on success and **empty by default**.
   * A plain `false` therefore preserves the original behavior.
   *
   * Nodes may supply text or JSON. Store it as a string without interpretation or truncation.
   * Changing detail per run belongs in the node implementation, not the kernel.
   */
  note: string;
  /** Each node's output. **Internal diagnostics only**; it does not leave this layer. */
  trace: { node: string; value: unknown; error?: string; note?: string }[];
}

/**
 * Separate a node result into its value and accompanying feedback.
 *
 * Return plain `true` / `false` / `[...]` unchanged: these are the original forms and the usual
 * case. Feedback-bearing results use `{ value, why }`.
 *
 * **Exclude arrays first**: `bool[n]` itself returns an array, which must not be mistaken for
 * a feedback-bearing object.
 */
function unwrap(got: unknown): { value: unknown; note: string } {
  if (got !== null && typeof got === "object" && !Array.isArray(got)) {
    const status = got as { valid?: unknown; outcome?: unknown; error?: unknown };
    if (status.valid === false || status.outcome === "grader_error") throw new Error("grader returned an invalid decision");
  }
  if (got !== null && typeof got === "object" && !Array.isArray(got) && "value" in got) {
    const o = got as { value: unknown; note?: unknown };
    return { value: o.value, note: say(o.note) };
  }
  return { value: got, note: "" };
}

/** Online verification, hand-in, wrap-up and U grading must give G the same candidate shape. */
export function candidateInput(task: Record<string, unknown>, body: string, chain: unknown = []): unknown {
  return { task: { ...task, result: body }, chain, result: { kind: "prompt", body } };
}

/** Convert additional feedback to one string. Serialize JSON unchanged without interpreting it. */
function say(note: unknown): string {
  if (note === undefined || note === null) return "";
  if (typeof note === "string") return note;
  try {
    return JSON.stringify(note);
  } catch {
    return String(note);
  }
}

/** Topological order. Definition-time validation already excluded cycles. */
function topo(o: Objective): Node[] {
  const idx = new Map(o.nodes.map((n, i) => [n.name, i]));
  const deg = o.nodes.map(() => 0);
  for (const e of o.edges) deg[idx.get(e.dst)!]++;
  const out: Node[] = [];
  const stack = o.nodes.filter((_, i) => deg[i] === 0).map((n) => n.name);
  while (stack.length) {
    const name = stack.pop()!;
    out.push(o.nodes[idx.get(name)!]);
    for (const e of o.edges.filter((x) => x.src === name)) {
      if (--deg[idx.get(e.dst)!] === 0) stack.push(e.dst);
    }
  }
  return out;
}

/**
 * Evaluate G once.
 *
 * `input` is passed to each node handle: task, candidate, workspace, and so on. This layer
 * forwards it unchanged. **Input structure is unrestricted** and belongs to the node contract.
 */
export async function evaluate(o: Objective, reg: Registry, input: unknown): Promise<Verdict> {
  const trace: Verdict["trace"] = [];
  const value = new Map<string, unknown>();
  const root = o.sink || o.nodes.find((n) => !o.edges.some((e) => e.src === n.name))?.name || "";

  for (const n of topo(o)) {
    // Incoming edges identify the upstream node and the index of the output to consume.
    const feed = o.edges
      .filter((e) => e.dst === n.name)
      .map((e) => {
        const v = value.get(e.src);
        return { from: e.src, out: e.out, value: Array.isArray(v) ? v[e.out] : v };
      });

    let got: unknown;
    let error: string | undefined;
    let note = "";
    try {
      const said = unwrap(
        await reg.get(n.handle).call({ node: n.name, moment: n.moment, domain: domainText(n.domain), feed, input }),
      );
      got = said.value;
      note = said.note;
      const bad = checkValue(n.domain, got);
      if (bad) {
        error = `out of contract: ${bad}`;
        got = n.domain.kind === "bool" ? false : Array.from({ length: n.domain.width }, () => false);
      }
    } catch (e) {
      error = e instanceof Error ? e.message : String(e);
      got = n.domain.kind === "bool" ? false : Array.from({ length: n.domain.width }, () => false);
    }
    value.set(n.name, got);
    // **Ignore additional feedback from nodes returning `true`.** Its purpose is to explain failure.
    if (got === true) note = "";
    trace.push({ node: n.name, value: got, ...(error ? { error } : {}), ...(note ? { note } : {}) });
  }

  const out = value.get(root);
  const broke = trace.filter((t) => t.error);
  const valid = broke.length === 0 && typeof out === "boolean";
  const pass = valid && out === true ? 1 : 0;
  // **The added field defaults to empty.** Combine feedback supplied by false-valued nodes into one string.
  const note = pass === 1 ? "" : trace.filter((t) => t.note).map((t) => `${t.node}: ${t.note}`).join("; ");
  return {
    pass,
    valid,
    outcome: valid ? (pass === 1 ? "passed" : "rejected") : "grader_error",
    // When note is populated, point to it here. Its content belongs to `note`; do not duplicate or summarize it.
    why:
      pass === 1
        ? ""
        : note
          ? "see note"
          : broke.length
            ? broke.map((t) => `${t.node}: ${t.error}`).join("; ")
            : `${root} evaluated to false`,
    note,
    trace,
  };
}
