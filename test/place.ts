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
 * **「怎么到那个位置」是一条句柄**（`workplace.identity`），跟工具、跟 G 的节点、
 * 跟推断函数一样。内置那条是 `fn:place.hops`（`wsl` / `ssh` / `docker` 那套
 * 命令前缀）；换成一条 `http://` 的，那台机器怎么进就由那个进程说了算 ——
 * 内核不用认得任何一种容器。
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
  "/unit": (u) => ({ role: "assistant", kind: "prompt", body: `I am working on ${u.place}` }),
  "/infer": () => null,
  // **一条自己写的转发器。** 它认得的地址写法内核一个字都不认识，命令怎么拼、
  // 送不送东西过去，全在这个进程里 —— 内核只知道一个名字。
  "/forwarder": (a) => (a.op === "ping" ? { alive: true } : { ran: a.tool, on: a.place }),
});

try {
  // ═══════════════ 第一部分：注册 ═══════════════
  part("Part one: registration");

  step("1. forwarding is on, but the place string uses a form nothing recognises");
  const unknownForm = await m.bad("POST", "/declare", {
    places: [{ place: "podman:box", identity: "fn:place.hops", forward: true, runtime: "/tmp/runtime", tools: [{ tool: "bash", policy: "always" }] }],
  });
  show("it answered:", unknownForm.problems);
  ok(
    "an unrecognised form fails immediately - guessing would connect somewhere else entirely",
    JSON.stringify(unknownForm.problems).includes("unrecognised segment in the place string"),
    unknownForm.problems,
  );

  step("1b. a place that does not forward can be named freely");
  const freeName = await m.api<{ places: string[] }>("POST", "/declare", { places: [{ place: "tab:deck" }] });
  show("accepted:", freeName.places);
  ok(
    "a place string has to be a chain of hops only when it forwards; otherwise the name simply says where this station is",
    freeName.places.includes("tab:deck"),
    freeName.places,
  );

  step("2. it says it forwards, but never says who carries the calls there");
  const noHandle = await m.bad("POST", "/declare", {
    places: [{ place: "wsl", forward: true, runtime: "/tmp/runtime", tools: [{ tool: "bash", policy: "always" }] }],
  });
  show("it answered:", noHandle.problems);
  ok(
    "forwarding without a handle is refused - how to reach a place is a handle's job, and a task would otherwise " +
      "walk all the way to the first forwarded tool call before finding out",
    JSON.stringify(noHandle.problems).includes("no handle was given"),
    noHandle.problems,
  );

  step("2b. it names a handle that nobody can claim");
  const ghost = await m.bad("POST", "/declare", {
    places: [
      { place: "wsl", identity: "fn:place.nowhere", forward: true, runtime: "/tmp/runtime", tools: [{ tool: "bash", policy: "always" }] },
    ],
  });
  show("it answered:", ghost.problems);
  ok("the same check every other handle reference gets", JSON.stringify(ghost.problems).includes("there is no handle named"), ghost.problems);

  step("2c. the built-in forwarder ships a runtime over, and none was given");
  const noRuntime = await m.bad("POST", "/declare", {
    places: [{ place: "wsl", identity: "fn:place.hops", forward: true, tools: [{ tool: "bash", policy: "always" }] }],
  });
  show("it answered:", noRuntime.problems);
  ok(
    "this one is asked of fn:place.hops only - what to ship over, or whether to ship anything at all, is that handle's own business",
    JSON.stringify(noRuntime.problems).includes("nothing to ship"),
    noRuntime.problems,
  );

  step("3. forwarding is on, but the allow-list is empty");
  const emptyList = await m.bad("POST", "/declare", {
    places: [{ place: "wsl", identity: "fn:place.hops", forward: true, runtime: "/tmp/runtime", tools: [] }],
  });
  show("it answered:", emptyList.problems);
  ok(
    "legal but certainly not what was meant, so it is said out loud",
    JSON.stringify(emptyList.problems).includes("not a single tool would be forwarded"),
    emptyList.problems,
  );

  step("4. an unrecognised policy in the allow-list");
  const badPolicy = await m.bad("POST", "/declare", {
    places: [{ place: "local", identity: "fn:place.hops", forward: true, tools: [{ tool: "bash", policy: "sometimes" }] }],
  });
  show("it answered:", badPolicy.problems);
  ok("it must be always or agent", JSON.stringify(badPolicy.problems).includes("unrecognised policy"), badPolicy.problems);

  step("4b. the same unrecognised address, carried by a handle of one's own");
  const mine = await m.api<{ places: string[] }>("POST", "/declare", {
    handles: [{ name: out.url("/forwarder"), expectMs: 20_000 }],
    places: [
      {
        place: "podman:box",
        identity: out.url("/forwarder"),
        forward: true,
        tools: [{ tool: "bash", policy: "always" }],
      },
    ],
  });
  show("accepted:", mine.places);
  ok(
    "step 1 refused this very string - not because the string is wrong, but because fn:place.hops cannot read it. " +
      "Reading the address is the handle's job, so a handle that can read it takes the same string",
    mine.places.includes("podman:box"),
    mine.places,
  );

  step("4c. probe it - the kernel asks that handle, and knows nothing about podman");
  const mineAlive = await m.api<Record<string, unknown>>("POST", `/places/${encodeURIComponent("podman:box")}/ping`);
  show("ping podman:box:", mineAlive);
  ok(
    "reachable, and the answer came from that process: it was asked op=ping, the two verbs of one handle",
    mineAlive.alive === true && out.calls["/forwarder"].some((c) => c.op === "ping" && c.place === "podman:box"),
    { mineAlive, asked: out.calls["/forwarder"] },
  );

  step("5. load two: this machine, and a registered but disabled remote");
  const loaded = await m.api<Record<string, unknown>>("POST", "/declare", {
    handles: [
      { name: out.url("/unit"), expectMs: 30_000 },
      { name: out.url("/infer"), expectMs: 10_000 },
    ],
    places: [
      { place: "local" },
      {
        place: "ssh://box-does-not-exist",
        identity: "fn:place.hops",
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
  ok("both went in", (loaded.places as string[]).length === 2, loaded.places);

  step("6. read back how they were registered");
  const { places } = await m.api<{ places: Record<string, unknown>[] }>("GET", "/places");
  show("the list:", places);
  const ssh = places.find((p) => String(p.place).startsWith("ssh://")) as { tools: unknown[]; identity: string };
  ok("the allow-list was kept, and so was the name of who carries the calls there", ssh.tools.length === 2 && ssh.identity === "fn:place.hops", places);

  // ═══════════════ 第二部分：使用层次的校验 ═══════════════
  part("Part two: checks at the level of use");
  console.log("  Registered is not the same as reachable. usable is a registration; reachability has to be probed on the spot.");

  step("7. probe this machine");
  const here = await m.api<Record<string, unknown>>("POST", "/places/local/ping");
  show("ping local:", here);
  ok("this machine is reachable", here.alive === true, here);

  step("8. probe the remote that does not exist");
  const remote = await m.api<Record<string, unknown>>("POST", `/places/${encodeURIComponent("ssh://box-does-not-exist")}/ping`);
  show("ping it:", remote);
  ok("unreachable is reported as unreachable, and it can say why", remote.alive === false, remote);

  step("9. after probing, that column in the database was NOT rewritten");
  const unchanged = (await m.api<{ places: Record<string, unknown>[] }>("GET", "/places")).places;
  show("usable in the list, read again:", unchanged.map((p) => ({ place: p.place, usable: p.usable })));
  ok(
    "a probe result is never written back - written back, it becomes a stale lie after any crash and restart",
    unchanged.find((p) => String(p.place).startsWith("ssh://"))?.usable === false &&
      unchanged.find((p) => p.place === "local")?.usable === true,
    unchanged,
  );

  step("10. really run a task on this machine");
  await m.api("POST", "/tasks", {
    id: "t-local", mode: "demo", agent: "bot", place: "local", source: "user", description: "do it right here",
  });
  await until("t-local to finish", async () => {
    const d = await m.api<{ state: string }>("GET", "/tasks/t-local");
    return d.state === "done" ? d : null;
  });
  const echoed = (await m.api<{ rows: Record<string, unknown>[] }>("GET", "/tasks/t-local/messages")).rows
    .filter((r) => r.kind === "prompt")
    .at(-1);
  show("it said:", echoed?.body);
  ok("where to work really reached the execution unit", String(echoed?.body).includes("local"), echoed?.body);

  step("11. publish a task to an unregistered place");
  const unregistered = await m.bad("POST", "/tasks", {
    id: "t-nowhere", mode: "demo", agent: "bot", place: "mars", source: "user", description: "do it on mars",
  });
  show("it answered:", unregistered.error);
  ok("rejected at publish time - it never sits in the database waiting to be noticed", String(unregistered.error).length > 0, unregistered);
} finally {
  out.stop();
  m.stop();
}

done();
