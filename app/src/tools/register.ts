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
  if (!w) throw new Error(`no row in workplace for ${place}`);
  if (!Number(w.forward)) return "local";

  let list: Policy[];
  try {
    list = JSON.parse(w.tools) as Policy[];
  } catch {
    throw new Error(`workplace ${place} has tools that is not a readable list`);
  }
  const hit = list.find((x) => x.tool === tool);
  if (!hit) return "local";
  if (hit.policy === "always") return place;
  if (hit.policy === "agent") return agentWants === false ? "local" : place;
  throw new Error(`unknown policy for ${tool} on workplace ${place}: ${hit.policy}`);
}

/** 改文件之前得先读过它 —— 这几个是「改」。 */
const MUTATES = new Set(["edit", "write"]);

/**
 * 这个单元读过这个文件没有。
 *
 * 判据是**库**：这个执行单元的消息里有没有一条 read 的返回，落在这个路径上。
 * 不是问工具、不是问内存 —— 工具跑在别的位置上，内存崩了就没了，只有库两边都算数。
 */
/**
 * 它**读到过这个文件的内容**没有。
 *
 * 两处以前是错的，合起来让这道闸按构造永远满足不了：
 *
 * - 找的是 `v.tool`，可结果行写进去的形状是 `{id, name, value}`（`tools/unit.ts`）——
 *   永远对不上，于是任何 `write` / `edit` 都被无限交回「先去读」。
 * - 范围只看当前这一站。可这道闸交回去的是一个**操作单元**，那个 read 落在
 *   **下一站**上 —— 本站里当然找不到。范围得是整个实例。
 */
function hasRead(db: Conn, agent: string, instance: string, path: string): boolean {
  const t = `agent_${agent.replace(/[^A-Za-z0-9_]/g, "_")}_msg`;
  const rows = all(db, `select body from "${t}" where instance = ? and kind = 'tool'`, [
    instance,
  ]) as { body: string }[];
  return rows.some((r) => {
    try {
      const v = JSON.parse(r.body) as { name?: string; value?: { path?: string } };
      return v.name === "read" && v.value?.path === path;
    } catch {
      return false;
    }
  });
}

/**
 * 那个位置上有没有这个文件。**得问那个位置** —— 文件未必在引擎这台机器上，
 * 在引擎这边 `stat` 一下的话，转发出去的场景会答错。
 *
 * 读不出来的错不止「没有这个文件」一种（没权限、那是个目录……）。只有 ENOENT
 * 才算「不存在」—— 别的错一律当成存在，否则一个读不动的文件就把整道闸绕过去了。
 */
async function existsAt(p: Place, path: string): Promise<boolean> {
  try {
    await p.call("read", { file_path: path, limit: 1 });
    return true;
  } catch (e) {
    return !/ENOENT|no such file/i.test(e instanceof Error ? e.message : String(e));
  }
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

      const where = placeFor(db, t.name, a.place ?? "local", a.forward);
      const p = await places.get(where);

      // 改之前没读过 → **不拒，回一个操作单元**：先去做这一步，再回来改。
      //
      // dsh 那边是策略层直接拒。我们不用拒 —— 手上有执行单元这个东西，
      // 把「下一步该干什么」交回去就行。拒只是告诉它「不行」，
      // 交回一个单元是告诉它「这么办」，后者模型接得住。
      //
      // **新建文件不过这道闸。** 闸挡的是「盖掉你没看过的内容」，而新建没有内容
      // 会被盖掉 —— 那儿本来就是空的。不这么分的话新建这条路根本走不通：
      // `write` 说「先去读」，`read` 说 ENOENT，两边各说各的，死循环。
      // 实测烧掉过一整道题（cmt-0：12 个单元全花在这上面，一个字答案都没写）。
      const path = typeof args.file_path === "string" ? args.file_path : "";
      if (MUTATES.has(t.name) && a.agent && a.instance && path && (await existsAt(p, path))) {
        if (!hasRead(db, a.agent, a.instance, path)) {
          return {
            unit: { tool: "read", args: { file_path: path } },
            why: `read ${path} first, then call ${t.name} again`,
          };
        }
      }

      return await p.call(t.name, args);
    });

    // **带条件的那几件退出「系统工具」那一档。** 系统工具是「谁都有、不看条件」，
    // 而条件正是要被看的 —— 两样同时成立的话，条件写了也没用，而且不报错。
    const conditional = (t.when ?? []).length > 0;
    run(
      db,
      `insert into tool (name, identity, does, params, output, prompt, concurrent, system, access, usable)
       values (?, ?, ?, ?, ?, ?, ?, ?, null, 1)
       on conflict(name) do update set
         identity = excluded.identity, does = excluded.does, params = excluded.params,
         output = excluded.output, prompt = excluded.prompt,
         concurrent = excluded.concurrent, system = excluded.system`,
      [
        t.name,
        identity,
        t.does,
        JSON.stringify(t.params),
        JSON.stringify(t.output),
        t.prompt,
        t.concurrent ? 1 : 0,
        conditional ? 0 : 1,
      ],
    );
    // 条件重写一遍：重装时旧的那几行不清掉的话，改了条件也不生效。
    run(db, `delete from trigger where owner_kind = 'tool' and owner = ?`, [t.name]);
    (t.when ?? []).forEach((group, i) => {
      for (const term of group) {
        run(
          db,
          `insert into trigger (owner_kind, owner, "group", dim, "key", op, value) values ('tool', ?, ?, ?, ?, ?, ?)`,
          [t.name, i, term.dim, term.key, term.op, term.value],
        );
      }
    });
    names.push(t.name);
  }
  return names;
}
