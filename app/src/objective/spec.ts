/**
 * Verification function `G`: the criterion for whether a task has succeeded.
 *
 * **G is a directed acyclic graph**. Nodes evaluate Boolean values; edges connect outputs to
 * inputs. The complete graph returns `{0,1}`. Its shape and design rationale come from
 * `agents/tasks/objective/` in the old repository (DESIGN.md D19–D26).
 *
 * ## A closed set of value domains
 *
 * Only `bool` and `bool[n]` are permitted. Authors select a domain rather than defining one.
 * **This makes definition-time type checking fully decidable**. Arbitrary domains would require
 * matrices and validators to handle arbitrary values. Since `n` is fixed at definition time,
 * edge-index bounds can be **checked entirely statically**.
 *
 * ## Contract violations return 0, without a third value
 *
 * Outputs outside the declared domain violate the contract. Violations, unavailable results,
 * and execution failures **all map to 0**. An "unknown" state would require three-valued handling
 * everywhere and propagate through the graph to its root.
 *
 * ## One intentionally omitted check
 *
 * The old code declared but did not implement "lifecycle moments respect topological order."
 * Moments are not totally ordered: the same moment can occur repeatedly within a task, so
 * "A is no later than B" is ambiguous. **An ill-defined check would reject valid G definitions.**
 * It remains omitted here.
 */

/** A value domain. `width` is the number of output ports, known at definition time. */
export interface Domain {
  kind: "bool" | "bool[]";
  width: number;
}

export const BOOL: Domain = { kind: "bool", width: 1 };

export function domainText(d: Domain): string {
  return d.kind === "bool" ? "bool" : `bool[${d.width}]`;
}

/** Parse a domain. **Reject every other form** because the allowed domain set is closed. */
export function parseDomain(text: unknown): Domain {
  // Sealed storage contains **parsed** domains, which must be recognized when read back.
  // Otherwise seal → open would fail on reading, far from the original definition.
  if (text !== null && typeof text === "object") {
    const d = text as { kind?: unknown; width?: unknown };
    if (d.kind === "bool") return BOOL;
    if (d.kind === "bool[]" && Number.isInteger(d.width) && Number(d.width) >= 1) {
      return { kind: "bool[]", width: Number(d.width) };
    }
    throw new Error(`unrecognised domain: ${JSON.stringify(text)}`);
  }
  const s = String(text ?? "").trim();
  if (s === "bool") return BOOL;
  const m = /^bool\[(\d+)\]$/.exec(s);
  if (m) {
    const n = Number(m[1]);
    if (!Number.isInteger(n) || n < 1) throw new Error(`the n in bool[n] must be an integer >= 1, got ${m[1]}`);
    return { kind: "bool[]", width: n };
  }
  throw new Error(`domain must be 'bool' or 'bool[n]', got ${JSON.stringify(text)}. The domain set is closed; custom domains are not accepted`);
}

/** Validate at evaluation time: `null` means valid; otherwise return the **contract violation reason** so the caller maps it to 0. */
export function checkValue(d: Domain, v: unknown): string | null {
  if (d.kind === "bool") {
    return typeof v === "boolean" ? null : `domain ${domainText(d)} expects a bool, got ${typeof v}`;
  }
  if (!Array.isArray(v)) return `domain ${domainText(d)} expects a list of bools, got ${typeof v}`;
  if (v.length !== d.width) return `domain ${domainText(d)} expects length ${d.width}, got ${v.length}`;
  const bad = v.map((x, i) => (typeof x === "boolean" ? -1 : i)).filter((i) => i >= 0);
  if (bad.length) return `domain ${domainText(d)} expects every element to be a bool; indices ${bad.slice(0, 5).join(",")} are not`;
  return null;
}

/** A graph node. `handle` names the function evaluating it: store the script reference here, not its execution. */
export interface Node {
  name: string;
  /** The evaluation moment. This was a rule's `mode` in the old implementation; here it is a **nonempty** string. */
  moment: string;
  domain: Domain;
  handle: string;
}

/** An edge connects one output of a source node to a destination node. */
export interface Edge {
  src: string;
  out: number;
  dst: string;
}

/** A task's `G`: ordered nodes, edges, and an output node. */
export interface Objective {
  nodes: Node[];
  edges: Edge[];
  /** Output node: the node with out-degree 0. */
  sink: string;
  /**
   * **Maximum queries to this black box in one attempt.**
   *
   * This is a property of G, not of the task. It expresses how many queries the evaluator should
   * allow; the same G should retain the same limit across tasks or publishers.
   *
   * Without a limit, enumerating the answer space becomes the easiest strategy. One observed
   * multiple-choice task tried 77 combinations without any reasoning. The resulting score measures
   * answer-space size rather than problem-solving ability.
   *
   * A round is one attempt, or one tree node. Retrying after a dead node starts a new round with
   * a fresh allowance. **The final submission does not count** because the kernel requests that
   * check rather than the agent probing the evaluator.
   */
  checks: number;
  /** Only pure-text candidates independent of a mutable workspace may reuse verdicts. Regrade by default. */
  reuse?: "text" | "never";
}

/** Port ordering: expand each node by its domain width. */
export function ports(o: Objective): { src: string; out: number }[] {
  return o.nodes.flatMap((n) => Array.from({ length: n.domain.width }, (_, k) => ({ src: n.name, out: k })));
}

/** Node adjacency: `A[i][j] = 1` means an edge runs from i to j. */
function adjacency(o: Objective): number[][] {
  const idx = new Map(o.nodes.map((n, i) => [n.name, i]));
  const A = o.nodes.map(() => o.nodes.map(() => 0));
  for (const e of o.edges) {
    const i = idx.get(e.src);
    const j = idx.get(e.dst);
    if (i !== undefined && j !== undefined) A[i][j] = 1;
  }
  return A;
}

/**
 * Definition-time structural validation. **Inspect the definition without evaluating it.**
 *
 * Return all errors; an empty list means success. **Reject every nonempty list**; there is no
 * warning-only category. Do not publish a task whose G is structurally unable to produce a result.
 *
 * Semantic conflicts cannot be detected because scripts are black boxes. This is the limit
 * of "as much validation as possible."
 */
export function validate(o: Objective): string[] {
  const errs: string[] = [];
  const names = o.nodes.map((n) => n.name);
  const N = o.nodes.length;

  if (N === 0) return ["the grading function has no nodes"];

  const dup = [...new Set(names.filter((x, i) => names.indexOf(x) !== i))];
  if (dup.length) errs.push(`duplicate node names: ${dup.join(", ")}`);

  const idx = new Map(o.nodes.map((n, i) => [n.name, i]));
  for (const n of o.nodes) {
    if (!n.moment.trim()) errs.push(`node ${n.name}: missing moment`);
    if (!n.handle.trim()) errs.push(`node ${n.name}: missing handle`);
  }

  // Edges must reference existing nodes and valid port indices. **Widths are known at definition time, so do not defer bounds checks.**
  for (const e of o.edges) {
    if (!idx.has(e.src)) {
      errs.push(`an edge references a source node that does not exist: ${e.src}`);
      continue;
    }
    if (!idx.has(e.dst)) {
      errs.push(`an edge references a target node that does not exist: ${e.dst}`);
      continue;
    }
    const w = o.nodes[idx.get(e.src)!].domain.width;
    if (!(Number.isInteger(e.out) && e.out >= 0 && e.out < w)) {
      errs.push(`edge ${e.src}[${e.out}] -> ${e.dst} has an out-of-range output index: ${e.src} has width ${w}, valid indices are 0..${w - 1}`);
    }
  }
  if (errs.length) return errs; // Invalid edges prevent subsequent graph checks.

  const A = adjacency(o);
  const indeg = o.nodes.map((_, j) => A.reduce((s, row) => s + row[j], 0));
  const outdeg = A.map((row) => row.reduce((s, x) => s + x, 0));

  // Acyclicity: nodes left unprocessed by Kahn's algorithm indicate a cycle.
  const deg = [...indeg];
  const order: number[] = [];
  const stack = o.nodes.map((_, i) => i).filter((i) => deg[i] === 0);
  while (stack.length) {
    const i = stack.pop()!;
    order.push(i);
    for (let j = 0; j < N; j++) {
      if (!A[i][j]) continue;
      if (--deg[j] === 0) stack.push(j);
    }
  }
  if (order.length !== N) {
    const stuck = names.filter((_, i) => !order.includes(i)).sort();
    errs.push(`there is a cycle through nodes ${stuck.join(", ")} - evaluation would not terminate, so the grading function has no value`);
  }

  // Exactly one output node. Multiple zero-in-degree nodes are valid: they directly observe the world.
  const sinks = names.filter((_, i) => outdeg[i] === 0);
  if (sinks.length !== 1) {
    errs.push(`there must be exactly one output node; nodes with out-degree 0 are ${sinks.join(", ") || "(none)"}`);
  } else if (o.sink && o.sink !== sinks[0]) {
    errs.push(`the declared output node is ${o.sink}, but the node with out-degree 0 is ${sinks[0]}`);
  }

  const root = o.sink || (sinks.length === 1 ? sinks[0] : "");
  if (!root) return errs;

  // Full consumption: every output port except the root's must be used by an edge.
  for (const p of ports(o)) {
    if (p.src === root) continue;
    if (!o.edges.some((e) => e.src === p.src && e.out === p.out)) {
      errs.push(`output ${p.out} of node ${p.src} is not consumed by any edge`);
    }
  }

  const ri = idx.get(root);
  if (ri !== undefined) {
    // The root domain must be bool because G returns {0,1}.
    if (o.nodes[ri].domain.kind !== "bool") {
      errs.push(`the output node ${root} has domain ${domainText(o.nodes[ri].domain)}, but the grading function must output a bool`);
    }
    // Degeneracy: a root with no incoming edges is candidate-independent, making G constant and the objective invalid.
    if (indeg[ri] === 0) {
      errs.push(`the output node ${root} has no incoming edge - its value does not depend on the candidate, so the grading function is constant and the objective is void`);
    }
  }

  return errs;
}

/** Parse a G definition and fail immediately on invalid shape. This differs from structural validation, which checks the graph. */
export function parseObjective(raw: unknown): Objective {
  if (raw === null || typeof raw !== "object") throw new Error("the grading function must be an object");
  const o = raw as { nodes?: unknown; edges?: unknown; sink?: unknown; checks?: unknown; reuse?: unknown };
  if (!Array.isArray(o.nodes)) throw new Error("the grading function needs nodes, and it must be an array");
  if (!Array.isArray(o.edges)) throw new Error("the grading function needs edges, and it must be an array");
  const nodes: Node[] = o.nodes.map((n, i) => {
    if (n === null || typeof n !== "object") throw new Error(`node ${i} is not an object`);
    const x = n as Record<string, unknown>;
    if (typeof x.name !== "string" || !x.name.trim()) throw new Error(`node ${i} has no name`);
    return {
      name: x.name,
      moment: String(x.moment ?? ""),
      domain: parseDomain(x.domain),
      handle: String(x.handle ?? ""),
    };
  });
  const edges: Edge[] = o.edges.map((e, i) => {
    if (e === null || typeof e !== "object") throw new Error(`edge ${i} is not an object`);
    const x = e as Record<string, unknown>;
    return { src: String(x.src ?? ""), out: Number(x.out ?? 0), dst: String(x.dst ?? "") };
  });
  // Default to five checks when unspecified: enough for a few solve → verify → revise from why
  // → verify cycles, but not exhaustive enumeration. Treat zero and negative values as unspecified;
  // this field cannot express unlimited querying.
  const asked = Number((o as { checks?: unknown }).checks);
  if (o.reuse !== undefined && o.reuse !== "text" && o.reuse !== "never") throw new Error("objective.reuse must be 'text' or 'never'");
  return { nodes, edges, sink: String(o.sink ?? ""), checks: Number.isFinite(asked) && asked > 0 ? asked : 5, reuse: o.reuse === "text" ? "text" : "never" };
}
