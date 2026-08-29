/**
 * 接口的声明 —— **契约长在接口上，不在旁边的文档里。**
 *
 * ## 为什么不写文档
 *
 * 另写一份文档，它就会**悄悄漂**：文档说一套、代码做一套，而没有任何一刻会报错。
 * 客户端照着文档写，撞上去才发现对不上，那时候他只能去读我们的表 —— 一旦开始读表，
 * 两端就焊死了。
 *
 * 所以一个口的说明和它的实现**是同一份东西**：
 *
 * ```
 *              ┌── 生成 help（客户端 curl 一下就知道怎么用）
 * 一份声明 ────┼── 校验进来的请求（少了、多了、类型不对、取值不在范围内 → 400）
 *              └── 装路由（handler 挂在同一行上）
 * ```
 *
 * **它漂不了** —— 漂了的话请求会被错误地拒，当场就看得出来。这跟这个仓库别处
 * 一贯的做法是同一件事：表是声明出来的，工具是声明出来的，接口也是。
 *
 * ## 参数表就是操作范围
 *
 * 声明里有参数表和返回形状，这两样已经足够把客户端能做的事框死了：
 * **没声明的参数一律拒收**，不是忽略。忽略的话，客户端写错一个字段名
 * （`maxUnits` 打成 `max_units`）会被静静吞掉，然后拿到一个不是他要的结果，
 * 而两边都不报错 —— 这正是这台机器一路在防的那种失败。
 */

import type { FastifyInstance, FastifyReply, FastifyRequest } from "fastify";

/** 一个参数能是什么。**只这几种** —— 再多的形状交给 `shape` 那一层去说。 */
export type Kind = "string" | "int" | "number" | "boolean" | "object" | "array";

export interface Param {
  name: string;
  /** 在哪儿：路径段 / 查询串 / 请求体里的一个字段。 */
  in: "path" | "query" | "body";
  kind: Kind;
  /** 不给就得有 `def`，两样都没有 = 缺了就拒。 */
  required?: boolean;
  /** 没给时用什么。**写在这儿，不写在 handler 里** —— 不然 help 说不出真正的默认值。 */
  def?: unknown;
  /** 取值只能是这几个。写错一个字母当场拒，不是「那条永远不命中」。 */
  only?: readonly string[];
  /** 这是什么，以及**写错了会怎样**。后半句才是真正有用的那半句。 */
  note: string;
  /** 数组/对象里面长什么样，用一句话说清。 */
  of?: string;
}

export interface Errs {
  code: number;
  when: string;
}

export type Handler = (
  /** 已经校验、已经填好默认值的那一份。**handler 不再自己取参数。** */
  arg: Record<string, unknown>,
  req: FastifyRequest,
  reply: FastifyReply,
) => Promise<unknown>;

export interface Route {
  method: "GET" | "POST" | "PUT" | "DELETE";
  /** 不带前缀，如 `/tasks/:id/messages`。 */
  path: string;
  /** 归到哪一组，help 按它分节。 */
  group: string;
  /** 一句话：这个口干什么。 */
  does: string;
  /**
   * 为什么要有这个口 —— **客户端自己拼的话会怎样**。
   *
   * 不是客套话：一个口如果说不出这一句，多半说明它只是把库里的行原样倒出来，
   * 那客户端迟早会绕过它直接读表。
   */
  why?: string;
  params?: Param[];
  /** 回什么。一个**真实形状**的例子，不是类型名 —— 客户端照着它写解析。 */
  returns?: unknown;
  errs?: Errs[];
  handler: Handler;
}

class Bad extends Error {
  statusCode = 400;
  constructor(
    message: string,
    readonly at: string,
  ) {
    super(message);
  }
}

function coerce(p: Param, raw: unknown): unknown {
  // 路径段和查询串一律是字符串，得按声明的类型翻过来。请求体里本来就是 JSON。
  if (p.kind === "string") {
    if (typeof raw !== "string") throw new Bad(`${p.name} 得是个字符串`, p.name);
    return raw;
  }
  if (p.kind === "int" || p.kind === "number") {
    const n = typeof raw === "number" ? raw : Number(String(raw));
    if (!Number.isFinite(n)) throw new Bad(`${p.name} 得是个数，给的是 ${JSON.stringify(raw)}`, p.name);
    if (p.kind === "int" && !Number.isInteger(n)) throw new Bad(`${p.name} 得是个整数`, p.name);
    return n;
  }
  if (p.kind === "boolean") {
    if (typeof raw === "boolean") return raw;
    const s = String(raw).toLowerCase();
    if (s === "true" || s === "1") return true;
    if (s === "false" || s === "0") return false;
    throw new Bad(`${p.name} 得是 true 或 false`, p.name);
  }
  if (p.kind === "array") {
    if (!Array.isArray(raw)) throw new Bad(`${p.name} 得是个列表`, p.name);
    return raw;
  }
  if (raw === null || typeof raw !== "object" || Array.isArray(raw)) {
    throw new Bad(`${p.name} 得是个对象`, p.name);
  }
  return raw;
}

/**
 * 照着声明把一次请求校出来。
 *
 * **没声明的参数一律拒收**，不是忽略 —— 忽略的话，客户端把 `maxUnits` 打成
 * `max_units` 会被静静吞掉，然后拿到一个不是他要的结果，而两边都不报错。
 * 拒收的时候要**把认得的列出来**，不然他还得去猜正确的拼法是什么。
 */
export function take(r: Route, req: FastifyRequest): Record<string, unknown> {
  const params = r.params ?? [];
  const out: Record<string, unknown> = {};
  const path = (req.params ?? {}) as Record<string, unknown>;
  const query = (req.query ?? {}) as Record<string, unknown>;
  const body = req.body;

  const bodyParams = params.filter((p) => p.in === "body");
  if (bodyParams.length > 0 && body !== undefined && body !== null) {
    if (typeof body !== "object" || Array.isArray(body)) {
      throw new Bad("请求体得是一个 JSON 对象", "body");
    }
  }
  const bag = (body ?? {}) as Record<string, unknown>;

  // 多给的：查询串和请求体都查一遍。路径段不用 —— 那是路由自己切出来的。
  const known = new Set(params.map((p) => p.name));
  const qNames = params.filter((p) => p.in === "query").map((p) => p.name);
  for (const k of Object.keys(query)) {
    if (!known.has(k)) {
      throw new Bad(`不认得的查询参数 ${k}${qNames.length ? `（认得的是 ${qNames.join("、")}）` : "（这个口不收查询参数）"}`, k);
    }
  }
  const bNames = bodyParams.map((p) => p.name);
  for (const k of Object.keys(bag)) {
    if (!known.has(k)) {
      throw new Bad(`不认得的字段 ${k}${bNames.length ? `（认得的是 ${bNames.join("、")}）` : "（这个口不收请求体）"}`, k);
    }
  }

  for (const p of params) {
    const src = p.in === "path" ? path : p.in === "query" ? query : bag;
    const raw = src[p.name];
    if (raw === undefined || raw === null || raw === "") {
      if (p.required) throw new Bad(`少了 ${p.name}：${p.note}`, p.name);
      if (p.def !== undefined) out[p.name] = p.def;
      continue;
    }
    const v = coerce(p, p.in === "path" ? decodeURIComponent(String(raw)) : raw);
    if (p.only && !p.only.includes(String(v))) {
      throw new Bad(`${p.name} 只能是 ${p.only.join(" / ")}，给的是 ${JSON.stringify(v)}`, p.name);
    }
    out[p.name] = v;
  }
  return out;
}

// ── help：跟校验读的是同一份声明 ────────────────────────────────────────────

function pad(s: string, n: number): string {
  // 中日韩字符在终端里占两格。不算的话参数表会对不齐，而这张表全靠对齐才读得下去。
  let w = 0;
  for (const ch of s) w += /[⺀-꓏가-힣豈-﫿︰-﹏＀-｠【】、—]/.test(ch) ? 2 : 1;
  return s + " ".repeat(Math.max(n - w, 1));
}

function paramLine(p: Param): string[] {
  const must = p.required ? "必给" : p.def !== undefined ? `默认 ${JSON.stringify(p.def)}` : "可不给";
  // 取值只有那几个的时候，**列出来比写个类型名有用得多** —— 客户端照着填就行。
  const kind = p.only ? p.only.join("|") : p.kind;
  const out = [`      ${pad(p.name, 16)}${pad(p.in, 7)}${pad(kind, 20)}${pad(must, 12)}${p.note}`];
  // 里面长什么样单独一行。塞进类型那一列的话，一个长形状会把后面的列全顶飞，
  // 而这张表全靠对齐才读得下去。
  if (p.of) out.push(`      ${" ".repeat(16)}里面：${p.of}`);
  return out;
}

/** 一份能直接在终端里读的说明。**curl 一下就知道怎么用**，不用去翻别的地方。 */
export function asText(prefix: string, routes: Route[], q?: string): string {
  const hit = q
    ? routes.filter((r) => (r.path + r.does + r.group).toLowerCase().includes(q.toLowerCase()))
    : routes;
  const out: string[] = [];
  out.push(`TgEngin ${prefix} —— ${hit.length} 个口${q ? `（筛 "${q}"，共 ${routes.length} 个）` : ""}`);
  out.push(`加 ?format=json 拿机器读的那一份；加 ?q=tasks 只看相关的。`);

  const groups = [...new Set(hit.map((r) => r.group))];
  for (const g of groups) {
    out.push("", `【${g}】`);
    for (const r of hit.filter((x) => x.group === g)) {
      out.push("", `  ${pad(r.method, 7)}${pad(prefix + r.path, 34)}${r.does}`);
      if (r.why) out.push(`      为什么有这个口：${r.why}`);
      if (r.params?.length) {
        out.push(`      ${pad("参数", 16)}${pad("在哪", 7)}${pad("类型", 20)}${pad("给不给", 12)}说明`);
        for (const p of r.params) out.push(...paramLine(p));
      }
      if (r.returns !== undefined) {
        out.push(`      回：${JSON.stringify(r.returns, null, 2).split("\n").join("\n      ")}`);
      }
      for (const e of r.errs ?? []) out.push(`      ${e.code}：${e.when}`);
    }
  }
  return out.join("\n") + "\n";
}

/** 机器读的那一份。**跟上面那份是同一个来源**，不是另抄一遍。 */
export function asJson(prefix: string, routes: Route[]) {
  return {
    prefix,
    count: routes.length,
    routes: routes.map((r) => ({
      method: r.method,
      path: prefix + r.path,
      group: r.group,
      does: r.does,
      why: r.why,
      params: (r.params ?? []).map((p) => ({
        name: p.name,
        in: p.in,
        kind: p.kind,
        of: p.of,
        required: Boolean(p.required),
        def: p.def,
        only: p.only,
        note: p.note,
      })),
      returns: r.returns,
      errs: r.errs ?? [],
    })),
  };
}

/**
 * 照着声明把路由装上，顺带把 `help` 装出来。
 *
 * **handler 拿到的是已经校验、已经填好默认值的那一份** —— 它不再自己从
 * `req.query` 里取、不再自己写默认值。写在 handler 里的默认值 help 说不出来，
 * 于是客户端看到的和实际跑的就是两回事。
 */
export function mount(app: FastifyInstance, prefix: string, routes: Route[]): void {
  for (const r of routes) {
    const wrap = async (req: FastifyRequest, reply: FastifyReply) => {
      let arg: Record<string, unknown>;
      try {
        arg = take(r, req);
      } catch (e) {
        if (e instanceof Bad) {
          // 报错里带上这个口的用法 —— 客户端不用回头去查 help 就能改对。
          return reply.code(400).send({
            error: e.message,
            at: e.at,
            usage: `${r.method} ${prefix}${r.path}`,
            params: (r.params ?? []).map((p) => `${p.name}（${p.in}，${p.kind}${p.required ? "，必给" : ""}）`),
          });
        }
        throw e;
      }
      return await r.handler(arg, req, reply);
    };
    if (r.method === "GET") app.get(prefix + r.path, wrap);
    else if (r.method === "POST") app.post(prefix + r.path, wrap);
    else if (r.method === "PUT") app.put(prefix + r.path, wrap);
    else app.delete(prefix + r.path, wrap);
  }

}

/**
 * 把 `help` 装上。**全部口装完之后调一次** —— 路由是分几处装的（库那一层一处、
 * 内核那一层一处），help 却必须列全：漏掉一组的话，客户端就会以为那组不存在，
 * 然后去读表。
 */
export function mountHelp(app: FastifyInstance, prefix: string, all: Route[]): void {
  const list = [...all].sort((a, b) => a.group.localeCompare(b.group) || a.path.localeCompare(b.path));
  const help = async (req: FastifyRequest, reply: FastifyReply) => {
    const q = (req.query ?? {}) as { format?: string; q?: string };
    const hit = q.q ? list.filter((r) => (r.path + r.does + r.group).toLowerCase().includes(q.q!.toLowerCase())) : list;
    if (q.format === "json") return asJson(prefix, hit);
    return reply.type("text/plain; charset=utf-8").send(asText(prefix, list, q.q));
  };
  // 光打前缀也给说明 —— 拿到一个地址，第一件事就是往上打一下看看这是什么。
  app.get(prefix, help);
  app.get(`${prefix}/help`, help);
}
