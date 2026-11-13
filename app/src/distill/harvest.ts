/**
 * Harvest the lessons recorded in a run's verdict history, without model calls.
 *
 * For each F-arm task, collect candidate text submitted to verify at each node, verdicts
 * (pass/why/note), the final submission, and model messages accompanying those calls.
 * Combine this with the same task's U-arm outcome (`unaided.csv`) to identify tasks that
 * failed without feedback but succeeded with it. Distillation considers only that group.
 *
 * **Read only trace tables**, following `docs/loop.md`: scores are computed from traces,
 * never stored. Reference answers (y*) are absent from the database and cannot be harvested.
 * What is available is **candidate text** evaluated by the grader, which the fingerprint gate
 * must prevent from entering a skill.
 */

import { Database } from "bun:sqlite";
import { readFileSync } from "node:fs";

export interface Verdict {
  node: number;
  unit: number;
  /** Candidate text evaluated (`graded`). A reused submission verdict has no text, so recover it from the previous check. */
  graded: string;
  pass: number;
  why: string;
  note: string;
  /** Who requested grading: the model calling verify, or the system at submission time. */
  by: "agent" | "submit";
}

export interface Attempt {
  node: number;
  verdicts: Verdict[];
  /** Model text accompanying tool calls in this node (`call.text`), in order. */
  said: string[];
}

export interface HarvestTask {
  id: string;
  domain: string;
  /** Problem statement: `description` without the `## Acceptance criteria` section appended during publication. */
  statement: string;
  fPass: number;
  /** Whether the U arm succeeded; null if no U-arm data is available. */
  uPass: number | null;
  attempts: Attempt[];
  /** Distinct candidate texts graded 1. */
  accepted: string[];
  /** Distinct candidate texts graded 0. */
  rejected: string[];
}

export interface Harvest {
  run: string;
  fDb: string;
  uCsv: string | null;
  tasks: HarvestTask[];
}

const CRITERIA = "\n\n## Acceptance criteria";

export function statementOf(description: string): string {
  const i = description.indexOf(CRITERIA);
  return i >= 0 ? description.slice(0, i) : description;
}

/** `unaided.csv`: `task,submitted,parsed,equiv,seconds,units`; `equiv` records U-arm success. */
function readUnaided(path: string): Map<string, number> {
  const out = new Map<string, number>();
  const lines = readFileSync(path, "utf8").split(/\r?\n/).filter(Boolean);
  const head = lines[0].split(",");
  const iTask = head.indexOf("task");
  // Graders name the outcome differently: CMT uses `equiv`, ChemBench uses `correct`, others use `pass`.
  const iPass = ["equiv", "correct", "pass"].map((k) => head.indexOf(k)).find((i) => i >= 0) ?? -1;
  if (iTask < 0 || iPass < 0) throw new Error(`${path}: no task/equiv columns in ${head.join(",")}`);
  for (const l of lines.slice(1)) {
    const c = l.split(",");
    out.set(c[iTask], Number(c[iPass]));
  }
  return out;
}

interface Row {
  unit: number;
  seq: number;
  kind: string;
  body: string;
}

export function harvest(fDb: string, uCsv?: string | null): Harvest {
  const db = new Database(fDb, { readonly: true });
  const u = uCsv ? readUnaided(uCsv) : null;
  const tasks = db.query(`select id, domain, description, run, result from task order by id`).all() as {
    id: string;
    domain: string;
    description: string;
    run: string;
    result: string | null;
  }[];
  const out: HarvestTask[] = [];
  let run = "";
  for (const t of tasks) {
    run ||= t.run;
    const fPass = t.result ? Number((JSON.parse(t.result) as { pass?: number }).pass ?? 0) : 0;
    // Every execution unit visited by this task: its node and agent instance.
    const units = db
      .query(`select node, unit, agent, instance from task_solve where task = ? order by unit`)
      .all(t.id) as { node: number; unit: number; agent: string; instance: string }[];
    const byNode = new Map<number, Attempt>();
    const accepted = new Set<string>();
    const rejected = new Set<string>();
    let lastGraded = "";
    for (const s of units) {
      const at = byNode.get(s.node) ?? { node: s.node, verdicts: [], said: [] };
      byNode.set(s.node, at);
      const rows = db
        .query(`select unit, seq, kind, body from "agent_${s.agent}_msg" where instance = ? and unit = ? order by seq`)
        .all(s.instance, s.unit) as Row[];
      let gradedCall = false;
      for (const r of rows) {
        let j: unknown;
        try {
          j = JSON.parse(r.body);
        } catch {
          continue;
        }
        if (r.kind === "call" || r.kind === "graded") {
          const c = j as { text?: string; calls?: { name: string; input?: { answer?: string } }[] };
          if (r.kind === "call" && c.text && c.text.trim()) at.said.push(c.text.trim());
          gradedCall = r.kind === "graded";
          for (const call of c.calls ?? []) {
            if ((call.name === "verify" || call.name === "submit") && call.input?.answer) lastGraded = call.input.answer;
          }
        } else if (r.kind === "tool") {
          const v = j as { name?: string; value?: { pass?: unknown; why?: string; note?: string; graded?: string; reused?: boolean } };
          if (v.name !== "verify" || typeof v.value?.pass !== "number") continue;
          const graded = v.value.graded ?? lastGraded;
          const verdict: Verdict = {
            node: s.node,
            unit: s.unit,
            graded,
            pass: v.value.pass,
            why: v.value.why ?? "",
            note: v.value.note ?? "",
            by: gradedCall ? "submit" : "agent",
          };
          at.verdicts.push(verdict);
          if (graded) (verdict.pass ? accepted : rejected).add(graded);
        }
      }
    }
    out.push({
      id: t.id,
      domain: t.domain,
      statement: statementOf(t.description),
      fPass,
      uPass: u ? (u.get(t.id) ?? null) : null,
      attempts: [...byNode.values()].sort((a, b) => a.node - b.node),
      accepted: [...accepted].filter((a) => !rejected.has(a)),
      rejected: [...rejected],
    });
  }
  db.close();
  return { run, fDb, uCsv: uCsv ?? null, tasks: out };
}

/** Distill by default only tasks that **failed without feedback and succeeded with it**. Without U-arm data, fall back to F-arm successes. */
export function taught(h: Harvest): HarvestTask[] {
  const hasU = h.tasks.some((t) => t.uPass !== null);
  return h.tasks.filter((t) => t.fPass === 1 && (!hasU || t.uPass === 0));
}
