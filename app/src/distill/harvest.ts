/**
 * 收割 —— 从一跑的库里把「判决教了什么」原样取出来，不调模型。
 *
 * 一道题在 F 臂里留下的东西：每个 node 上 verify 过哪些原文、判了什么（pass/why/note）、
 * 最后交的是哪一份、模型在这些调用旁边说了什么。再配上同一道题在 U 臂的成绩
 * （`unaided.csv`），就能划出「没反馈做不对、有反馈做对了」的那一批 —— 沉淀只看它们。
 *
 * 这里**只读 trace 表**，跟 `docs/loop.md` 里「分数从 trace 表算出来、从不存」是同一条。
 * 答案（y*）不在库里，所以这一步拿不到答案；拿得到的是判卷台判过的**候选原文**，
 * 那正是后面指纹闸要拦的东西。
 */

import { Database } from "bun:sqlite";
import { readFileSync } from "node:fs";

export interface Verdict {
  node: number;
  unit: number;
  /** 判的是哪一段原文（`graded`）。交卷复用那次没有原文，从上一次补。 */
  graded: string;
  pass: number;
  why: string;
  note: string;
  /** 谁问的：模型自己调 verify，还是交卷那一刻系统判的。 */
  by: "agent" | "submit";
}

export interface Attempt {
  node: number;
  verdicts: Verdict[];
  /** 模型在这个 node 里调工具时说的话（`call.text`），按序。 */
  said: string[];
}

export interface HarvestTask {
  id: string;
  domain: string;
  /** 题面：`description` 去掉发布口拼上去的 `## Acceptance criteria` 那一段。 */
  statement: string;
  fPass: number;
  /** U 臂有没有做对；没有 U 臂数据就是 null。 */
  uPass: number | null;
  attempts: Attempt[];
  /** 被判 1 的原文（去重）。 */
  accepted: string[];
  /** 被判 0 的原文（去重）。 */
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

/** `unaided.csv`：`task,submitted,parsed,equiv,seconds,units` —— `equiv` 那一栏就是 U 臂过没过。 */
function readUnaided(path: string): Map<string, number> {
  const out = new Map<string, number>();
  const lines = readFileSync(path, "utf8").split(/\r?\n/).filter(Boolean);
  const head = lines[0].split(",");
  const iTask = head.indexOf("task");
  // 各榜的判卷台叫法不同：CMT 是 `equiv`，ChemBench 是 `correct`，别的叫 `pass`
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
    // 这道题走过的每一站：哪个 node、哪个智能体实例
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

/** 沉淀默认只看这一批：**没反馈做不对、有反馈做对了**。没有 U 臂数据时退到「F 臂做对了」。 */
export function taught(h: Harvest): HarvestTask[] {
  const hasU = h.tasks.some((t) => t.uPass !== null);
  return h.tasks.filter((t) => t.fPass === 1 && (!hasU || t.uPass === 0));
}
