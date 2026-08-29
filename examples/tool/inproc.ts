/**
 * 写法一：**把 `meet_join` 写成进程内的工具**。
 *
 * 这个文件不是拿来跑的，是拿来抄的 —— 把它抄进 `app/src/main.ts`（或者 `tools/`
 * 底下一个自己的文件里，再从 main 调一次），重新编译，这个工具就在了。
 *
 * ## 为什么进程内的必须写代码
 *
 * 库里存的永远只是**名字**。`fn:` 开头的句柄要换出一个真函数，而函数只有那个进程
 * 持有得住 —— 从外面往 `handle` 表写一行 `fn:tool.meet_join`，库里就有了一条谁都
 * 认领不了的句柄。所以注册一律走内核，而且外面**不许**注册 `fn:` 的名字。
 *
 * 跟写法二（`meetkit.ts`，进程外）比：
 *
 * - 进程内：同一个进程里直接调，没有一次 HTTP；但要改代码、要重新编译、
 *   要重启，而且只能跑在引擎那台机器上
 * - 进程外：注册一行就完事，不动内核、不重启、可以跑在别的机器上；
 *   代价是每次调用一次 HTTP
 */

import type { Conn } from "../../app/src/H2H/db.ts";
import { run } from "../../app/src/H2H/db.ts";
import type { Registry } from "../../app/src/engine/registry.ts";

/** 真的那套在这儿驱动 puppeteer；这里只把形状摆出来。 */
async function joinMeeting(meetUrl: string): Promise<{ ok: boolean; meetId?: string; why?: string }> {
  if (!/^https:\/\/meet\.google\.com\//.test(meetUrl)) return { ok: false, why: "这不是一个 Meet 地址" };
  return { ok: true, meetId: meetUrl.split("/").pop() };
}

/**
 * 抄进 `main.ts`：在 `registerTools(...)` 那几行旁边调一次。
 *
 * 注册一次落两处 —— `handle` 表一行（名字 + 多久算死），`tool` 表一行
 * （给模型看的那几样）。触发条件另外走 `trigger` 表，也就是 `/declare` 里的 `when`。
 */
export function registerMeetJoin(db: Conn, reg: Registry): void {
  const identity = "fn:tool.meet_join";

  // 只有内核持有得住这个函数。`expectMs` 是多久算死，内外一视同仁。
  reg.register(db, identity, 60_000, async (arg) => {
    const a = (arg ?? {}) as { args?: { meetUrl?: string } };
    return await joinMeeting(String(a.args?.meetUrl ?? ""));
  });

  // 给模型看的那一份。跟 `/declare` 里 tools 那一项是同一批字段。
  run(
    db,
    `insert into tool (name, identity, does, params, output, prompt, concurrent, system, access, usable)
     values (?, ?, ?, ?, ?, ?, 0, 0, null, 1)
     on conflict(name) do update set identity = excluded.identity, does = excluded.does,
       params = excluded.params, output = excluded.output, prompt = excluded.prompt`,
    [
      "meet_join",
      identity,
      "进一个已经预约好的会",
      JSON.stringify({
        type: "object",
        properties: { meetUrl: { type: "string" } },
        required: ["meetUrl"],
      }),
      JSON.stringify({
        type: "object",
        properties: { ok: { type: "boolean" }, meetId: { type: "string" } },
      }),
      "进会只调 meet_join，别自己拼地址。",
    ],
  );
}
