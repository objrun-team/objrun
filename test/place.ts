/**
 * 例子：**加一个干活的地方**。
 *
 * ```
 * bun examples/place.ts
 * ```
 *
 * 「在哪儿干」是一条**带层级的地址串**，一层套一层：
 *
 * ```
 *   local                        本机，同进程直接调
 *   wsl                          默认发行版
 *   wsl:Ubuntu-24.04             指定发行版
 *   ssh://box-7
 *   wsl/docker:build-01          WSL 里的容器
 *   ssh://box-7/docker:build-01
 * ```
 *
 * 调工具本质上是**转发给那个位置上的运行时**：建立连接的时候把运行时送过去、
 * 起起来，之后每次调用发一行 JSON 过去、收一行回来。
 *
 * ## 两条容易踩的
 *
 * 1. **`usable` 是登记，不是探活。** 远端断没断是活状态 —— 每次现探，不写回库。
 *    写回去的话，崩了重启读到的那一列就是过期的谎话
 * 2. **开了转发但白名单是空的** —— 合法，但一个工具都不会转过去。一定不是本意，
 *    所以在声明这一关就说出来
 */

import { done, machine, ok, outside, part, show, step, until } from "./_lib.ts";

const m = await machine();
const out = await outside({
  "/unit": (u) => ({ role: "assistant", kind: "prompt", body: `我在 ${u.place} 上干活` }),
  "/infer": () => null,
});

try {
  // ═══════════════ 第一部分：注册 ═══════════════
  part("第一部分：注册");

  step("① 要转发，位置串却写了个认不得的写法");
  const 认不得 = await m.bad("POST", "/declare", {
    places: [{ place: "podman:box", forward: true, runtime: "/tmp/runtime", tools: [{ tool: "bash", policy: "always" }] }],
  });
  show("回的是：", 认不得.problems);
  ok(
    "**认不得的写法当场炸** —— 猜的话会连到别的地方去",
    JSON.stringify(认不得.problems).includes("位置串不认得这一段"),
    认不得.problems,
  );

  step("①b 不转发的地方，名字随便起");
  const 随便起 = await m.api<{ places: string[] }>("POST", "/declare", { places: [{ place: "tab:deck" }] });
  show("收下了：", 随便起.places);
  ok(
    "**位置串只有要转发的时候才得是一串跳板** —— 不转发的地方，名字只是「这一站在哪儿」",
    随便起.places.includes("tab:deck"),
    随便起.places,
  );

  step("② 说要转发，却没说送什么运行时过去");
  const 没运行时 = await m.bad("POST", "/declare", {
    places: [{ place: "wsl", forward: true, tools: [{ tool: "bash", policy: "always" }] }],
  });
  show("回的是：", 没运行时.problems);
  ok("第一次调用才炸的事，提前到声明这一刻", JSON.stringify(没运行时.problems).includes("没东西可送过去"), 没运行时.problems);

  step("③ 开了转发，白名单却是空的");
  const 空名单 = await m.bad("POST", "/declare", {
    places: [{ place: "wsl", forward: true, runtime: "/tmp/runtime", tools: [] }],
  });
  show("回的是：", 空名单.problems);
  ok(
    "**合法但一定不是本意**，所以说出来",
    JSON.stringify(空名单.problems).includes("一个工具都不会转过去"),
    空名单.problems,
  );

  step("④ 白名单里的 policy 认不得");
  const 坏policy = await m.bad("POST", "/declare", {
    places: [{ place: "local", forward: true, tools: [{ tool: "bash", policy: "sometimes" }] }],
  });
  show("回的是：", 坏policy.problems);
  ok("只能是 always / agent", JSON.stringify(坏policy.problems).includes("policy 不认得"), 坏policy.problems);

  step("⑤ 灌两个：本机，和一个登记着但停用的远端");
  const 灌好 = await m.api<Record<string, unknown>>("POST", "/declare", {
    handles: [
      { name: out.url("/unit"), expectMs: 30_000 },
      { name: out.url("/infer"), expectMs: 10_000 },
    ],
    places: [
      { place: "local" },
      {
        place: "ssh://box-不存在",
        runtime: "/tmp/tgengin-runtime",
        forward: true,
        tools: [{ tool: "bash", policy: "always" }, { tool: "read", policy: "agent" }],
        // 登记着，但标成不可用 —— 这是**登记**，不是探活的结果
        usable: false,
      },
    ],
    modes: [{ mode: "demo", cycles: [{ cycle: "go", from: [], next: [], infer: out.url("/infer") }] }],
    agents: [{ name: "bot", apis: [], unit: out.url("/unit") }],
  });
  ok("两个都进去了", (灌好.places as string[]).length === 2, 灌好.places);

  step("⑥ 看一眼登记成什么样");
  const { places } = await m.api<{ places: Record<string, unknown>[] }>("GET", "/places");
  show("清单：", places);
  ok("转发那条的白名单留住了", (places.find((p) => p.forward) as { tools: unknown[] }).tools.length === 2, places);

  // ═══════════════ 第二部分：使用层次的校验 ═══════════════
  part("第二部分：使用层次的校验");
  console.log("  登记了 ≠ 连得上。usable 是登记，通不通得现探。");

  step("⑦ 现探本机");
  const 本机 = await m.api<Record<string, unknown>>("POST", "/places/local/ping");
  show("ping local：", 本机);
  ok("本机通", 本机.alive === true, 本机);

  step("⑧ 现探那个不存在的远端");
  const 远端 = await m.api<Record<string, unknown>>("POST", `/places/${encodeURIComponent("ssh://box-不存在")}/ping`);
  show("ping 它：", 远端);
  ok("**连不上就说连不上**，而且说得出为什么", 远端.alive === false, 远端);

  step("⑨ 探完之后，库里那一列**没被改写**");
  const 还是那样 = (await m.api<{ places: Record<string, unknown>[] }>("GET", "/places")).places;
  show("再看一遍清单里的 usable：", 还是那样.map((p) => ({ place: p.place, usable: p.usable })));
  ok(
    "**探活的结果不写回库** —— 写回去的话，崩了重启读到的就是过期的谎话",
    还是那样.find((p) => String(p.place).startsWith("ssh://"))?.usable === false &&
      还是那样.find((p) => p.place === "local")?.usable === true,
    还是那样,
  );

  step("⑩ 在本机上真跑一个任务");
  await m.api("POST", "/tasks", {
    id: "t-local", mode: "demo", agent: "bot", place: "local", source: "user", description: "就在本机干",
  });
  await until("t-local 跑完", async () => {
    const d = await m.api<{ state: string }>("GET", "/tasks/t-local");
    return d.state === "done" ? d : null;
  });
  const 回显 = (await m.api<{ rows: Record<string, unknown>[] }>("GET", "/tasks/t-local/messages")).rows
    .filter((r) => r.kind === "prompt")
    .at(-1);
  show("它说：", 回显?.body);
  ok("**「在哪儿干」真的传到了执行单元手里**", String(回显?.body).includes("local"), 回显?.body);

  step("⑪ 发一个任务到没登记的地方");
  const 没登记 = await m.bad("POST", "/tasks", {
    id: "t-nowhere", mode: "demo", agent: "bot", place: "火星", source: "user", description: "去火星干",
  });
  show("回的是：", 没登记.error);
  ok("发布那一刻就拒 —— 不会躺在库里等人发现", String(没登记.error).length > 0, 没登记);
} finally {
  out.stop();
  m.stop();
}

done();
