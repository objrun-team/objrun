/**
 * Turn accepted candidates into a declaration supported by `POST /declare`.
 * **Construct the declaration only; do not write the database.**
 *
 * `/declare` is the sole write path and rejects the entire declaration if any part is invalid
 * (see `declare/index.ts`). This module produces a JSON file for the arm runner to POST after
 * configuring the machine. It does not inject anything into a live database by default.
 * The agentos rule required user approval before generated skills entered a live system;
 * here, the prerequisite is an improvement in the U arm on held-out tasks.
 *
 * Trigger conditions require the same `domain`, a **root station** (no `>` in the chain string;
 * the separator is ` > `, and declaration values cannot contain spaces), and at least `minMatch`
 * literal trigger terms in the statement. Build OR groups, each an AND of `minMatch` terms,
 * consistent with `when`: OR between groups, AND within a group.
 * Inject only at the root because chat resends instructions for every execution unit, while
 * a skill row on the ancestor chain remains visible thereafter. Injecting at every station
 * would repeat the same content each time.
 */

import { combos, matches, type Candidate, type GateReport } from "./gate.ts";

export interface Landed extends Candidate {
  report: GateReport;
}

const HEADER = "Distilled from earlier solved problems of this kind. It is about the class of problem, not this one:";

export function declarationOf(cands: Landed[], domain: string, mountSingle = false): { skills: Record<string, unknown>[] } {
  const skills = cands
    .filter((c) => c.report.status === "landed" || (mountSingle && c.report.status === "single"))
    .map((c) => ({
      identity: c.identity,
      does: c.does,
      params: {},
      role: "skill",
      usable: true,
      body: `${HEADER}\n\n${c.body}`,
      when: combos(c.report.keywords, Math.min(c.report.minMatch, c.report.keywords.length)).map((group) => [
        { dim: "task", key: "domain", op: "eq", value: domain },
        { dim: "chain", key: "", op: "not_contains", value: ">" },
        ...group.map((k) => ({ dim: "task", key: "description", op: "contains", value: k })),
      ]),
    }));
  return { skills };
}

/** Which statements a declaration matches. Use the engine's literal `contains` semantics without running the engine. */
export function probe(decl: { skills: { identity: string; when: { dim: string; key: string; op: string; value: string }[][] }[] }, tasks: { id: string; statement: string }[]): Map<string, string[]> {
  const out = new Map<string, string[]>();
  for (const s of decl.skills) {
    const groups = s.when.map((g) => g.filter((t) => t.dim === "task" && t.key === "description" && t.op === "contains").map((t) => t.value));
    out.set(
      s.identity,
      tasks.filter((t) => groups.some((g) => matches(t.statement, g, g.length))).map((t) => t.id),
    );
  }
  return out;
}
