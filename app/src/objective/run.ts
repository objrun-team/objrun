/**
 * 求 G 的值。
 *
 * 按拓扑序跑：每个节点调它那个句柄，拿到的东西按值域封口，接线把输出送到下一个
 * 节点。根节点的 bool 就是 G 的判决。
 *
 * ## 全函数，默认 0
 *
 * **任何一处出岔子都归 0，不引入第三个值**：句柄没注册、脚本抛了、返回的东西
 * 不落值域、根没算出来 —— 全是 0。加一个「未知」档的话，上面每一处都要处理
 * 三态，而三态会一路渗到根，最后没人说得清 G 到底判了什么。
 *
 * 归 0 的时候**把原因带出来**。判决本身只有 0/1，但我们这边要能查为什么。
 */

import type { Registry } from "../engine/registry.ts";
import { checkValue, domainText, type Node, type Objective } from "./spec.ts";

export interface Verdict {
  /** 判决。**只有 0 和 1。** */
  pass: 0 | 1;
  /**
   * 归 0 的原因（判 1 时为空）。
   *
   * **这一栏给智能体**（`deliverVerdict` 和 `verify` 都带上它）—— 只给 0/1 的话
   * 它只知道错了不知道错在哪，下一条分支多半原样再来一遍。要藏的是 GT，不是判决。
   */
  why: string;
  /** 每个节点算出了什么。**这一栏只给我们排障看**，不出这一层。 */
  trace: { node: string; value: unknown; error?: string }[];
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
    try {
      got = await reg.get(n.handle).call({ node: n.name, moment: n.moment, domain: domainText(n.domain), feed, input });
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
    trace.push({ node: n.name, value: got, ...(error ? { error } : {}) });
  }

  const out = value.get(root);
  const pass = out === true ? 1 : 0;
  const broke = trace.filter((t) => t.error);
  return {
    pass,
    why: pass === 1 ? "" : broke.length ? broke.map((t) => `${t.node}: ${t.error}`).join("; ") : `${root} evaluated to false`,
    trace,
  };
}
