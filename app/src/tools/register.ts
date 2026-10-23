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
import { openLocal } from "../place/index.ts";
import { TOOLS } from "./index.ts";

interface Policy {
  tool: string;
  policy: string;
}

/** 这一次在哪儿跑，以及**由谁把调用送过去**。 */
export interface Where {
  /** 位置串。`local` = 就在这个进程里跑。 */
  place: string;
  /** 转发它的那条句柄 → `workplace.identity`。本机跑的时候是空的。 */
  identity: string;
}

/**
 * 这一次在哪儿跑。
 *
 * `workplace.forward` 是总闸；白名单 `tools` 里那一项的 `policy` 定细则：
 * `always` 一定转发，`agent` 由智能体那一次说了算，没列进白名单的不转发。
 *
 * 都不满足就在本机跑 —— **不是报错**。位置登记的是「可以转到哪儿」，
 * 不是「必须转过去」。
 *
 * 判出要转发的时候，**得一并说清由谁转** —— 「怎么到那个位置」是那条句柄的事，
 * 不是这个文件的事。声明那一关保证了 `forward = 1` 的行必有 `identity`；
 * 真缺了在这儿炸，不往下走：往下走的话它会**悄悄退回本机跑**，而一件本该在
 * 容器里跑的 `bash` 落到宿主机上，是不报错的那种错。
 */
export function placeFor(db: Conn, tool: string, place: string, agentWants: boolean | undefined): Where {
  const HERE: Where = { place: "local", identity: "" };
  if (!place || place === "local") return HERE;
  const w = all(db, `select forward, tools, identity from workplace where place = ?`, [place])[0] as
    | { forward: number; tools: string; identity: string | null }
    | undefined;
  if (!w) throw new Error(`no row in workplace for ${place}`);
  if (!Number(w.forward)) return HERE;

  let list: Policy[];
  try {
    list = JSON.parse(w.tools) as Policy[];
  } catch {
    throw new Error(`workplace ${place} has tools that is not a readable list`);
  }
  const hit = list.find((x) => x.tool === tool);
  if (!hit) return HERE;

  const there = (): Where => {
    const identity = String(w.identity ?? "").trim();
    if (!identity) throw new Error(`workplace ${place} forwards, but no handle is registered to carry the call there`);
    return { place, identity };
  };
  if (hit.policy === "always") return there();
  if (hit.policy === "agent") return agentWants === false ? HERE : there();
  throw new Error(`unknown policy for ${tool} on workplace ${place}: ${hit.policy}`);
}

/** 不转发的时候工具就在这儿跑。**跟运行时里装的是同一份实现**，所以两边行为一样。 */
const here = openLocal();

/** 把一次工具调用发出去。转发的话经那条句柄，不转发的话就在这儿跑。 */
type Send = (tool: string, args: Record<string, unknown>) => Promise<unknown>;

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
async function existsAt(send: Send, path: string): Promise<boolean> {
  try {
    await send("read", { file_path: path, limit: 1 });
    return true;
  } catch (e) {
    return !/ENOENT|no such file/i.test(e instanceof Error ? e.message : String(e));
  }
}

/** 一件工具报给库的那几样。干活那个函数不在里头 —— 那是句柄的事，跟这张表无关。 */
export interface Declared {
  name: string;
  does: string;
  params: Record<string, unknown>;
  output: Record<string, unknown>;
  prompt: string;
  concurrent: boolean;
  /** 它的返回是哪一类东西 → `msg_part.name`。不填 = `event`。 */
  gives?: string;
  when?: { dim: string; key: string; op: string; value: string }[][];
}

/**
 * 把一件工具落进 `tool` 和 `trigger`。**只此一处。**
 *
 * 以前这段有两份：这个文件里一份（照 `when` 生成条件），`objective/tool.ts` 里
 * `verify` 又手写了两条 `insert into trigger`。同一件事两处各写各的，那两份就会漂，
 * 而且是**悄悄地漂**：一边改了 upsert 要更新哪几列、另一边没跟上，看着照常工作，
 * 只是有一列永远停在第一次写进去的值上。实际就已经差了一列（`concurrent`）。
 *
 * `when` 一并管两件事：条件写进 `trigger`，以及**这件算不算「系统工具」**。系统工具
 * 是「谁都有、不看条件」，所以带条件的必须退出那一档 —— 两样同时成立的话，条件写了
 * 不生效，而且不报错。
 *
 * 条件**先清后写**：重装时旧的那几行留着的话，改了条件也不生效。
 */
export function declareTool(db: Conn, t: Declared, identity = `fn:tool.${t.name}`): void {
  const conditional = (t.when ?? []).length > 0;
  run(
    db,
    `insert into tool (name, identity, does, params, output, prompt, concurrent, system, access, usable, gives)
     values (?, ?, ?, ?, ?, ?, ?, ?, null, 1, ?)
     on conflict(name) do update set
       identity = excluded.identity, does = excluded.does, params = excluded.params,
       output = excluded.output, prompt = excluded.prompt,
       concurrent = excluded.concurrent, system = excluded.system, gives = excluded.gives`,
    [
      t.name,
      identity,
      t.does,
      JSON.stringify(t.params),
      JSON.stringify(t.output),
      t.prompt,
      t.concurrent ? 1 : 0,
      conditional ? 0 : 1,
      t.gives ?? null,
    ],
  );
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
}

/**
 * 注册全部基础工具。行是 upsert 的 —— 重装一次不该多出一堆重复。
 *
 * **落进去的是 `system = 1`**：读写这一组谁一上来都有，不看 `trigger`。
 * 不标的话，按「一条条件都没有 = 从不触发」那条语义，它们谁也拿不到。
 */
export function registerTools(db: Conn, reg: Registry): string[] {
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

      // 在哪儿跑、由谁送过去。**送过去这件事经注册表**，跟调 G 的节点、调推断
      // 函数是同一条路 —— 这个文件不认得 wsl、ssh、docker 里的任何一个。
      const where = placeFor(db, t.name, a.place ?? "local", a.forward);
      const send: Send = where.identity
        ? (tool, args) => reg.get(where.identity).call({ place: where.place, op: "call", tool, args })
        : (tool, args) => here.call(tool, args);

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
      if (MUTATES.has(t.name) && a.agent && a.instance && path && (await existsAt(send, path))) {
        if (!hasRead(db, a.agent, a.instance, path)) {
          return {
            unit: { tool: "read", args: { file_path: path } },
            why: `read ${path} first, then call ${t.name} again`,
          };
        }
      }

      return await send(t.name, args);
    });

    declareTool(db, t, identity);
    names.push(t.name);
  }
  return names;
}
