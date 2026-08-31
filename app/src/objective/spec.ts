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
  // 封存区里存的是**解析过的**值域，读回来得认得它自己 —— 不认的话
  // seal → open 这一趟就断了，而断在读回来那一刻，离出错的地方很远。
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

/** 求值期封口：`null` = 合法，否则返回**违约原因**（调用方据此归 0）。 */
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
  /**
   * **一轮里这个黑盒最多被问几次。**
   *
   * 这是 G 自己的性质，不是任务的：能问几次，问的是这个盒子经得起被问几次 ——
   * 换一道题、换一个发布方，同一个 G 该是同一个数。
   *
   * 没有上限的话，最省事的策略是把答案空间枚举一遍。实测过：一道选项题被连着试了
   * 七十七个排列组合，一次推理都没有 —— 那样得来的分数量的是答案空间有多大，
   * 不是它会不会做。
   *
   * 一轮 = 一次尝试（树那套里就是一个节点）。判死之后重来是新的一轮，额度也是新的。
   * **交卷那一次不算** —— 那是内核替它问的，不是它自己去试。
   */
  checks: number;
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

  if (N === 0) return ["the grading function has no nodes"];

  const dup = [...new Set(names.filter((x, i) => names.indexOf(x) !== i))];
  if (dup.length) errs.push(`duplicate node names: ${dup.join(", ")}`);

  const idx = new Map(o.nodes.map((n, i) => [n.name, i]));
  for (const n of o.nodes) {
    if (!n.moment.trim()) errs.push(`node ${n.name}: missing moment`);
    if (!n.handle.trim()) errs.push(`node ${n.name}: missing handle`);
  }

  // 边：引用得存在，下标不许越界。**宽度定义期已知，没有理由留到求值期。**
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
    errs.push(`there is a cycle through nodes ${stuck.join(", ")} - evaluation would not terminate, so the grading function has no value`);
  }

  // 唯一输出节点。入度为 0 的有几个都正常 —— 那些是直接观测世界的。
  const sinks = names.filter((_, i) => outdeg[i] === 0);
  if (sinks.length !== 1) {
    errs.push(`there must be exactly one output node; nodes with out-degree 0 are ${sinks.join(", ") || "(none)"}`);
  } else if (o.sink && o.sink !== sinks[0]) {
    errs.push(`the declared output node is ${o.sink}, but the node with out-degree 0 is ${sinks[0]}`);
  }

  const root = o.sink || (sinks.length === 1 ? sinks[0] : "");
  if (!root) return errs;

  // 全消费：除根外，每个输出端口都得被某条边用上
  for (const p of ports(o)) {
    if (p.src === root) continue;
    if (!o.edges.some((e) => e.src === p.src && e.out === p.out)) {
      errs.push(`output ${p.out} of node ${p.src} is not consumed by any edge`);
    }
  }

  const ri = idx.get(root);
  if (ri !== undefined) {
    // 根的值域必须是 bool —— G 的输出是 {0,1}
    if (o.nodes[ri].domain.kind !== "bool") {
      errs.push(`the output node ${root} has domain ${domainText(o.nodes[ri].domain)}, but the grading function must output a bool`);
    }
    // 退化：根没有入边 ⇒ 它的值跟候选无关 ⇒ G 恒定 ⇒ 无效目标
    if (indeg[ri] === 0) {
      errs.push(`the output node ${root} has no incoming edge - its value does not depend on the candidate, so the grading function is constant and the objective is void`);
    }
  }

  return errs;
}

/** 解析一份 G。形状不对当场炸 —— 这跟结构校验是两回事，那个查的是图对不对。 */
export function parseObjective(raw: unknown): Objective {
  if (raw === null || typeof raw !== "object") throw new Error("the grading function must be an object");
  const o = raw as { nodes?: unknown; edges?: unknown; sink?: unknown; checks?: unknown };
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
  // 不给就用默认的五次：够「算出来 → 验一次 → 照着 why 改 → 再验」走上两三个来回，
  // 不够穷举。给 0 或者负数当成不给 —— 「随便问」不是这个字段能表达的意思。
  const asked = Number((o as { checks?: unknown }).checks);
  return { nodes, edges, sink: String(o.sink ?? ""), checks: Number.isFinite(asked) && asked > 0 ? asked : 5 };
}
