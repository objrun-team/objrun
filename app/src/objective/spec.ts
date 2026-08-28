/**
 * 验证函数 `G` —— 一个任务「算不算做成了」的标准。
 *
 * **G 是一张有向无环图**：节点是一段能算出布尔的东西，边是接线。整张图算出
 * 一个 `{0,1}`。形状抄自老仓库 `agents/tasks/objective/`（DESIGN.md D19–D26），
 * 那边的决定和理由一条条带过来。
 *
 * ## 值域是封闭的
 *
 * 只有 `bool` 和 `bool[n]`，作者只能选、不能自定义。**封闭之后定义期的类型检查
 * 完全可判定** —— 值域要是能随便定义，矩阵和校验就得应付任意值域，那就查不动了。
 * `n` 在定义期写死，所以边的下标越界能**完全静态检出**。
 *
 * ## 违约一律归 0，不引入第三个值
 *
 * 脚本返回的东西不落值域 = 违约；违约、算不出来、跑挂了，**一律归 0**。
 * 加一个「未知」档的话，上面每一处都要处理三态，而三态会一路渗到根。
 *
 * ## 有一条检查故意没装
 *
 * 「时刻与拓扑序相容」—— 老代码留了接口没实装，理由是生命周期时刻不是全序
 * （同一个时刻一次任务里能发很多遍），「A 不晚于 B」在重复时刻上没有确切含义，
 * **写一个语义不明的检查反而会挡住合法的 G**。照样不装。
 */

/** 一个值域。`width` 是这个节点的输出端口数，定义期已知。 */
export interface Domain {
  kind: "bool" | "bool[]";
  width: number;
}

export const BOOL: Domain = { kind: "bool", width: 1 };

export function domainText(d: Domain): string {
  return d.kind === "bool" ? "bool" : `bool[${d.width}]`;
}

/** 解析值域。**写别的一律拒** —— 值域是封闭的。 */
export function parseDomain(text: unknown): Domain {
  const s = String(text ?? "").trim();
  if (s === "bool") return BOOL;
  const m = /^bool\[(\d+)\]$/.exec(s);
  if (m) {
    const n = Number(m[1]);
    if (!Number.isInteger(n) || n < 1) throw new Error(`bool[n] 的 n 要是 ≥1 的整数，实得 ${m[1]}`);
    return { kind: "bool[]", width: n };
  }
  throw new Error(`domain 只能是 'bool' 或 'bool[n]'，实得 ${JSON.stringify(text)}。值域是封闭的，不接受自定义`);
}

/** 求值期封口：`null` = 合法，否则返回**违约原因**（调用方据此归 0）。 */
export function checkValue(d: Domain, v: unknown): string | null {
  if (d.kind === "bool") {
    return typeof v === "boolean" ? null : `值域 ${domainText(d)} 要 bool，实得 ${typeof v}`;
  }
  if (!Array.isArray(v)) return `值域 ${domainText(d)} 要一串布尔，实得 ${typeof v}`;
  if (v.length !== d.width) return `值域 ${domainText(d)} 要长度 ${d.width}，实得 ${v.length}`;
  const bad = v.map((x, i) => (typeof x === "boolean" ? -1 : i)).filter((i) => i >= 0);
  if (bad.length) return `值域 ${domainText(d)} 要元素全是 bool，下标 ${bad.slice(0, 5).join(",")} 不是`;
  return null;
}

/** 图里的一个节点。`handle` 是算这一格的那个句柄名 —— 脚本引用在这儿，执行不在这儿。 */
export interface Node {
  name: string;
  /** 什么时刻算它。老代码那边是规则的 `mode`；这儿是个字符串，**不能是空的**。 */
  moment: string;
  domain: Domain;
  handle: string;
}

/** 一条边：源节点的第几个输出，接到哪个节点。 */
export interface Edge {
  src: string;
  out: number;
  dst: string;
}

/** 一个任务的 `G`：节点（有序）+ 边 + 输出节点。 */
export interface Objective {
  nodes: Node[];
  edges: Edge[];
  /** 输出节点。图上出度为 0 的那一个。 */
  sink: string;
}

/** 端口序：每个节点按值域宽度摊开。 */
export function ports(o: Objective): { src: string; out: number }[] {
  return o.nodes.flatMap((n) => Array.from({ length: n.domain.width }, (_, k) => ({ src: n.name, out: k })));
}

/** 节点级邻接：`A[i][j] = 1` 表示 i 有边到 j。 */
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
 * 定义期结构校验。**只看定义，不跑求值。**
 *
 * 返回错误列表；空 = 过。**非空即拒** —— 没有「警告」那一档：与其让一个必然
 * 算不出结果的 G 混进系统，不如这道题根本别发布。
 *
 * 做不了的一件事是语义冲突 —— 脚本是黑盒，这就是「尽可能」的全部含义。
 */
export function validate(o: Objective): string[] {
  const errs: string[] = [];
  const names = o.nodes.map((n) => n.name);
  const N = o.nodes.length;

  if (N === 0) return ["G 一个节点都没有"];

  const dup = [...new Set(names.filter((x, i) => names.indexOf(x) !== i))];
  if (dup.length) errs.push(`节点名重复：${dup.join("、")}`);

  const idx = new Map(o.nodes.map((n, i) => [n.name, i]));
  for (const n of o.nodes) {
    if (!n.moment.trim()) errs.push(`节点 ${n.name}：缺【时刻】`);
    if (!n.handle.trim()) errs.push(`节点 ${n.name}：缺【脚本】句柄`);
  }

  // 边：引用得存在，下标不许越界。**宽度定义期已知，没有理由留到求值期。**
  for (const e of o.edges) {
    if (!idx.has(e.src)) {
      errs.push(`边引用了不存在的源节点 ${e.src}`);
      continue;
    }
    if (!idx.has(e.dst)) {
      errs.push(`边引用了不存在的目标节点 ${e.dst}`);
      continue;
    }
    const w = o.nodes[idx.get(e.src)!].domain.width;
    if (!(Number.isInteger(e.out) && e.out >= 0 && e.out < w)) {
      errs.push(`边 ${e.src}[${e.out}] → ${e.dst} 输出下标越界：${e.src} 的宽度是 ${w}，合法下标 0..${w - 1}`);
    }
  }
  if (errs.length) return errs; // 边都对不上，后面无从查起

  const A = adjacency(o);
  const indeg = o.nodes.map((_, j) => A.reduce((s, row) => s + row[j], 0));
  const outdeg = A.map((row) => row.reduce((s, x) => s + x, 0));

  // 无环：Kahn 排不完的就是环
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
    errs.push(`存在**回环**，涉及节点 ${stuck.join("、")} —— 求值不终止，G 算不出来`);
  }

  // 唯一输出节点。入度为 0 的有几个都正常 —— 那些是直接观测世界的。
  const sinks = names.filter((_, i) => outdeg[i] === 0);
  if (sinks.length !== 1) {
    errs.push(`必须**唯一输出节点**；实际出度为 0 的是 ${sinks.join("、") || "（一个都没有）"}`);
  } else if (o.sink && o.sink !== sinks[0]) {
    errs.push(`声明的输出节点是 ${o.sink}，但图上出度为 0 的是 ${sinks[0]}`);
  }

  const root = o.sink || (sinks.length === 1 ? sinks[0] : "");
  if (!root) return errs;

  // 全消费：除根外，每个输出端口都得被某条边用上
  for (const p of ports(o)) {
    if (p.src === root) continue;
    if (!o.edges.some((e) => e.src === p.src && e.out === p.out)) {
      errs.push(`节点 ${p.src} 的第 ${p.out} 个输出**没被任何边消费**`);
    }
  }

  const ri = idx.get(root);
  if (ri !== undefined) {
    // 根的值域必须是 bool —— G 的输出是 {0,1}
    if (o.nodes[ri].domain.kind !== "bool") {
      errs.push(`输出节点 ${root} 的值域是 ${domainText(o.nodes[ri].domain)}，但 G 的输出必须是 bool`);
    }
    // 退化：根没有入边 ⇒ 它的值跟候选无关 ⇒ G 恒定 ⇒ 无效目标
    if (indeg[ri] === 0) {
      errs.push(`输出节点 ${root} 没有任何入边 —— 它的值与候选无关，G 恒定，是无效目标`);
    }
  }

  return errs;
}

/** 解析一份 G。形状不对当场炸 —— 这跟结构校验是两回事，那个查的是图对不对。 */
export function parseObjective(raw: unknown): Objective {
  if (raw === null || typeof raw !== "object") throw new Error("G 得是一个对象");
  const o = raw as { nodes?: unknown; edges?: unknown; sink?: unknown };
  if (!Array.isArray(o.nodes)) throw new Error("G 要有 nodes，而且是个数组");
  if (!Array.isArray(o.edges)) throw new Error("G 要有 edges，而且是个数组");
  const nodes: Node[] = o.nodes.map((n, i) => {
    if (n === null || typeof n !== "object") throw new Error(`第 ${i} 个节点不是对象`);
    const x = n as Record<string, unknown>;
    if (typeof x.name !== "string" || !x.name.trim()) throw new Error(`第 ${i} 个节点没有 name`);
    return {
      name: x.name,
      moment: String(x.moment ?? ""),
      domain: parseDomain(x.domain),
      handle: String(x.handle ?? ""),
    };
  });
  const edges: Edge[] = o.edges.map((e, i) => {
    if (e === null || typeof e !== "object") throw new Error(`第 ${i} 条边不是对象`);
    const x = e as Record<string, unknown>;
    return { src: String(x.src ?? ""), out: Number(x.out ?? 0), dst: String(x.dst ?? "") };
  });
  return { nodes, edges, sink: String(o.sink ?? "") };
}
