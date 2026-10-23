/**
 * 求 G 的值。
 *
 * 按拓扑序跑：每个节点调它那个句柄，拿到的东西按值域封口，接线把输出送到下一个
 * 节点。根节点的 bool 就是 G 的判决。
 *
 * ## 全函数，默认 0
 *
 * 句柄失败时仍按 false 封口，G 的值域保持 bool。执行是否成功另记在回执的
 * `valid` / `outcome`，故障不能作为候选答错、消耗有效检查额度或复用的依据。
 *
 * 归 0 的时候**把原因带出来**。判决本身只有 0/1，但我们这边要能查为什么。
 *
 * ## 判 0 的节点可以多说一份：`note`
 *
 * 返回值可以是光秃秃的 `true` / `false`（老形状，绝大多数节点该有的样子），
 * 也可以是 `{ value, note }` —— `note` 是自由格式（一段字或者一份 JSON），
 * 这一层解析完当字符串收进判决新加的那一栏。**默认空的**，不给的话行为一个字不变。
 *
 * `why` 那一栏没动：它说的还是「这一格根本没算出来」。两件事不该挤在一栏里 ——
 * 「算出来是假」和「算不出来」混在一起的话，判决为什么是 0 就说不清了。
 *
 * **说多少是节点自己的事**，这一层不解释也不裁剪。
 */

import type { Registry } from "../engine/registry.ts";
import { checkValue, domainText, type Node, type Objective } from "./spec.ts";

export interface Verdict {
  /** 判决。**只有 0 和 1。** */
  pass: 0 | 1;
  /** 所有节点成功执行并满足输出契约；false 时 pass=0 是关闭成功通路，不是答错。 */
  valid: boolean;
  outcome: "passed" | "rejected" | "grader_error";
  /**
   * 归 0 的原因（判 1 时为空）。
   *
   * **这一栏给智能体**（`deliverVerdict` 和 `verify` 都带上它）—— 只给 0/1 的话
   * 它只知道错了不知道错在哪，下一条分支多半原样再来一遍。要藏的是 GT，不是判决。
   */
  why: string;
  /**
   * 判 0 的节点自己**多说的那一份**（判 1 时为空）。**默认就是空的** ——
   * 节点回一个光秃秃的 `false`，这一栏什么都没有，跟以前一模一样。
   *
   * 内容是节点的自由格式（一段字或者一份 JSON），这一层不解释、不裁剪，
   * 解析完当字符串收着。详略要按跑来调的话，调的是那个节点，不是内核。
   */
  note: string;
  /** 每个节点算出了什么。**这一栏只给我们排障看**，不出这一层。 */
  trace: { node: string; value: unknown; error?: string; note?: string }[];
}

/**
 * 节点回来的东西拆成「值」和「它想说的话」。
 *
 * 光秃秃的 `true` / `false` / `[...]` 原样回去，一个字都不解释 —— 那是老形状，
 * 也是绝大多数节点该有的样子。带话的写成 `{ value, why }`。
 *
 * **数组要先挡掉**：`bool[n]` 的返回本身就是数组，不挡的话会被当成带话的那种形状。
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

/** 多说的那一份换成一行字。给的是 JSON 就原样序列化 —— 这一层不解释内容。 */
function say(note: unknown): string {
  if (note === undefined || note === null) return "";
  if (typeof note === "string") return note;
  try {
    return JSON.stringify(note);
  } catch {
    return String(note);
  }
}

/** 拓扑序。图已经过定义期检测，这儿不会遇到环。 */
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
 * 跑一遍 G。
 *
 * `input` 是给每个节点句柄的那份东西（任务、候选、工作区……）。这一层不解释它，
 * 原样递下去 —— **输入形式自由**，是节点自己的事。
 */
export async function evaluate(o: Objective, reg: Registry, input: unknown): Promise<Verdict> {
  const trace: Verdict["trace"] = [];
  const value = new Map<string, unknown>();
  const root = o.sink || o.nodes.find((n) => !o.edges.some((e) => e.src === n.name))?.name || "";

  for (const n of topo(o)) {
    // 上游送进来的：这个节点的每条入边，带着源节点那一路的第几个输出。
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
    // **判 `true` 的节点不收这一份。** 带话回来是为了说清「为什么不成」。
    if (got === true) note = "";
    trace.push({ node: n.name, value: got, ...(error ? { error } : {}), ...(note ? { note } : {}) });
  }

  const out = value.get(root);
  const broke = trace.filter((t) => t.error);
  const valid = broke.length === 0 && typeof out === "boolean";
  const pass = valid && out === true ? 1 : 0;
  // **新加的这一栏，默认空的。** 判 0 的节点自己带回来的那份东西，拼成一行。
  const note = pass === 1 ? "" : trace.filter((t) => t.note).map((t) => `${t.node}: ${t.note}`).join("; ");
  return {
    pass,
    valid,
    outcome: valid ? (pass === 1 ? "passed" : "rejected") : "grader_error",
    // 那一栏填了的话，这儿就写一句指过去 —— 内容归 `note`，这一栏不搬也不摘。
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
