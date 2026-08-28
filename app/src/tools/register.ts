/**
 * 把基础工具注册进内核。
 *
 * **注册走内核**，因为只有它持有得住函数。注册一次落两处：
 *
 * - `handle` 表一行：名字 + 多久算死（谁引用这个句柄、超时怎么判，都看它）
 * - `tool` 表一行：给模型看的那几样（`does` / `params` / `output` / `prompt`）
 *
 * 注册进去的那个函数**本身不干活，它只负责转发**：按 `workplace` 决定这一次
 * 在哪儿跑，然后把调用发过去。真正干活的实现在 `./index.ts`，本机和运行时里
 * 装的是同一份。
 */

import type { Conn } from "../H2H/db.ts";
import { all, run } from "../H2H/db.ts";
import type { Registry } from "../engine/registry.ts";
import { openPlace, type Place } from "../place/index.ts";
import { TOOLS } from "./index.ts";

/** 开过的位置留着复用 —— 每次调用都重送一遍运行时的话，什么都别干了。 */
export class Places {
  #open = new Map<string, Promise<Place>>();
  #db: Conn;

  constructor(db: Conn) {
    this.#db = db;
  }

  /** 送什么过去，登记在 `workplace.runtime` 里 —— 不在代码里写死。 */
  #runtimeOf(place: string): string | undefined {
    const row = all(this.#db, `select runtime from workplace where place = ?`, [place])[0] as
      | { runtime: string | null }
      | undefined;
    return row?.runtime ?? undefined;
  }

  get(place: string): Promise<Place> {
    let p = this.#open.get(place);
    if (!p) {
      p = openPlace(place, this.#runtimeOf(place));
      this.#open.set(place, p);
      // 连不上就把这次的坑清掉，下次还能重试 —— 留着的话这个位置就永久废了
      p.catch(() => this.#open.delete(place));
    }
    return p;
  }

  closeAll(): void {
    for (const p of this.#open.values()) void p.then((x) => x.close()).catch(() => {});
    this.#open.clear();
  }
}

interface Policy {
  tool: string;
  policy: string;
}

/**
 * 这一次在哪儿跑。
 *
 * `workplace.forward` 是总闸；白名单 `tools` 里那一项的 `policy` 定细则：
 * `always` 一定转发，`agent` 由智能体那一次说了算，没列进白名单的不转发。
 *
 * 都不满足就在本机跑 —— **不是报错**。位置登记的是「可以转到哪儿」，
 * 不是「必须转过去」。
 */
export function placeFor(db: Conn, tool: string, place: string, agentWants: boolean | undefined): string {
  if (!place || place === "local") return "local";
  const w = all(db, `select forward, tools from workplace where place = ?`, [place])[0] as
    | { forward: number; tools: string }
    | undefined;
  if (!w) throw new Error(`workplace 表里没有 ${place}`);
  if (!Number(w.forward)) return "local";

  let list: Policy[];
  try {
    list = JSON.parse(w.tools) as Policy[];
  } catch {
    throw new Error(`workplace ${place} 的 tools 不是一份能读的列表`);
  }
  const hit = list.find((x) => x.tool === tool);
  if (!hit) return "local";
  if (hit.policy === "always") return place;
  if (hit.policy === "agent") return agentWants === false ? "local" : place;
  throw new Error(`workplace ${place} 上 ${tool} 的 policy 不认得：${hit.policy}`);
}

/** 改文件之前得先读过它 —— 这几个是「改」。 */
const MUTATES = new Set(["edit", "write"]);

/**
 * 这个单元读过这个文件没有。
 *
 * 判据是**库**：这个执行单元的消息里有没有一条 read 的返回，落在这个路径上。
 * 不是问工具、不是问内存 —— 工具跑在别的位置上，内存崩了就没了，只有库两边都算数。
 */
function hasRead(db: Conn, agent: string, instance: string, unit: number, path: string): boolean {
  const t = `agent_${agent.replace(/[^A-Za-z0-9_]/g, "_")}_msg`;
  const rows = all(db, `select body from "${t}" where instance = ? and unit = ? and kind = 'tool'`, [
    instance,
    unit,
  ]) as { body: string }[];
  return rows.some((r) => {
    try {
      const v = JSON.parse(r.body) as { tool?: string; value?: { path?: string } };
      return v.tool === "read" && v.value?.path === path;
    } catch {
      return false;
    }
  });
}

/**
 * 注册全部基础工具。行是 upsert 的 —— 重装一次不该多出一堆重复。
 *
 * **落进去的是 `system = 1`**：读写这一组谁一上来都有，不看 `trigger`。
 * 不标的话，按「一条条件都没有 = 从不触发」那条语义，它们谁也拿不到。
 */
export function registerTools(db: Conn, reg: Registry, places: Places): string[] {
  const names: string[] = [];
  for (const t of TOOLS) {
    const identity = `fn:tool.${t.name}`;

    reg.register(db, identity, t.expectMs, async (arg) => {
      const a = (arg ?? {}) as {
        place?: string;
        forward?: boolean;
        args?: Record<string, unknown>;
        agent?: string;
        instance?: string;
        unit?: number;
      };
      const args = a.args ?? {};

      // 改之前没读过 → **不拒，回一个操作单元**：先去做这一步，再回来改。
      //
      // dsh 那边是策略层直接拒。我们不用拒 —— 手上有执行单元这个东西，
      // 把「下一步该干什么」交回去就行。拒只是告诉它「不行」，
      // 交回一个单元是告诉它「这么办」，后者模型接得住。
      const path = typeof args.file_path === "string" ? args.file_path : "";
      if (MUTATES.has(t.name) && a.agent && a.instance && a.unit !== undefined && path) {
        if (!hasRead(db, a.agent, a.instance, a.unit, path)) {
          return {
            unit: { tool: "read", args: { file_path: path } },
            why: `改 ${path} 之前先读一遍它 —— 读完再来调 ${t.name}`,
          };
        }
      }

      const where = placeFor(db, t.name, a.place ?? "local", a.forward);
      const p = await places.get(where);
      return await p.call(t.name, args);
    });

    run(
      db,
      `insert into tool (name, identity, does, params, output, prompt, concurrent, system, access, usable)
       values (?, ?, ?, ?, ?, ?, ?, 1, null, 1)
       on conflict(name) do update set
         identity = excluded.identity, does = excluded.does, params = excluded.params,
         output = excluded.output, prompt = excluded.prompt,
         concurrent = excluded.concurrent, system = excluded.system`,
      [t.name, identity, t.does, JSON.stringify(t.params), JSON.stringify(t.output), t.prompt, t.concurrent ? 1 : 0],
    );
    names.push(t.name);
  }
  return names;
}
