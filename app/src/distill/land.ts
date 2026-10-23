/**
 * 落位 —— 过了闸的候选拼成一份 `POST /declare` 能收的声明。**只拼，不写库。**
 *
 * 写库的口只有 `/declare`，一份不过整份不写（见 `declare/index.ts`）。这儿产出的是
 * 一个 JSON 文件，由跑臂的脚本在声明完机器之后再 POST 一次。默认不往任何活库里灌 ——
 * agentos 那边的纪律是「降解物进 live 之前先问用户」，我们这儿把「问」做成了
 * 「留出题上的 U 臂先涨了再说」。
 *
 * 触发条件：同 `domain`、只在**根站**（链路串里没有 `>`；分隔符是 ` > `，声明口不收带空格的值）、题面里至少共现 `minMatch` 个触发词
 * —— 拼成 OR 组，每组是 `minMatch` 个词的 AND（`when` 的语义：组间 or、组内 and）。
 * 只在根站投是因为 chat 每个单元都重发一遍 instructions，而 skill 那一行落在祖先链上
 * 之后每一站都还看得见 —— 每站都投等于每站都重复一遍。
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

/** 一份声明会在哪些题面上触发 —— 跟引擎 `contains` 同一个字面比较，不跑引擎。 */
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
