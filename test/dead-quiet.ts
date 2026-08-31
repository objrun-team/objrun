/**
 * 例子：**打完分的题，不许再花钱。**
 *
 * ```
 * bun test/dead-quiet.ts
 * ```
 *
 * 判死那一段的原话是「先落一个失败，让它别再被排上」。可挑活的那一句以前只问
 * 「这一行做完没有」（`where done = 0`），从不问「这道题还在不在」——
 *
 * 1. 任务超时，`#reap` 把 `state` 写成 `failed`，成绩当场定下
 * 2. 它底下那些没做完的行**还是 `done = 0`**
 * 3. 下一圈照样把它们扫出来、照样派给模型
 *
 * 实测一跑里 15 道死题在死后又开了 105 个执行单元，最狠的一道死后还跑了 33 分钟 ——
 * 每个单元都是一次真实的模型调用，而换回来的东西一分不进成绩单：分是判死那一刻
 * 定的。顺带还刷出一串报错，因为死掉那一刻在飞的调用回来之后会在上下文尾巴上留一条
 * 没人应答的工具调用，而收工时的补齐早就跑完了。
 *
 * 这个例子让一道题在做着的时候到点，然后盯着它**还敢不敢动**。
 */

import { done, machine, ok, outside, part, show, step, until } from "./_lib.ts";

const m = await machine();

/**
 * **一格比整道题的时限还慢。** 这一条是这个例子的全部关键：
 *
 * 到点那一刻，手上必须正有一个在飞的调用。它回来的时候任务已经打完分了，而它回来
 * 之后照样会推出下一格 —— **那下一格就是死后才被挑走的那一格**。慢不过时限的话，
 * 死亡那一刻手上一格待办都没有，也就没什么可派的，例子会毫无理由地绿着。
 */
let served = 0;
const out = await outside({
  "/step": async () => {
    served++;
    await Bun.sleep(4000);
    return { role: "assistant", kind: "prompt", body: `unit ${String(served)}` };
  },
  // 永远接着走 —— 这道题**自己不会停**，只能被时限停下。要拦的正是「停下之后
  // 还在动」，所以不能让它自己走到头。
  "/infer": () => "ask",
});

try {
  part("A task that has been scored does not spend any more");

  step("1. a station that loops, so it would keep going forever if nobody stopped it");
  await m.api("POST", "/declare", {
    places: [{ place: "local" }],
    handles: [
      { name: out.url("/step"), expectMs: 30_000 },
      { name: out.url("/infer"), expectMs: 10_000 },
    ],
    modes: [
      {
        mode: "loop",
        cycles: [{ cycle: "ask", maxUnits: 500, from: [], next: ["ask"], infer: out.url("/infer") }],
      },
    ],
    agents: [{ name: "bot", apis: [], unit: out.url("/step") }],
  });

  step("2. give it three seconds to live");
  await m.api("POST", "/tasks", {
    id: "t-dead-quiet",
    mode: "loop",
    agent: "bot",
    place: "local",
    source: "user",
    description: "keep going until the clock runs out",
    solveSeconds: 3,
  });

  const state = await until(
    "t-dead-quiet to be scored",
    async () => {
      const d = await m.api<{ state: string }>("GET", "/tasks/t-dead-quiet");
      return d.state === "failed" || d.state === "done" ? d : null;
    },
    30_000,
  );
  show("how it ended:", state);

  const atDeath = (
    await m.api<{ rows: { n: number }[] }>("POST", "/query", {
      sql: "select count(*) as n from task_loop where task = 't-dead-quiet'",
    })
  ).rows[0].n;
  show("units at the moment it was scored:", atDeath);

  step("3. keep waking the kernel for a while, then look again");
  // **每次写库都会把内核叫醒。** 这儿一直戳它 —— 挑活那一句要是还不看任务状态，
  // 这几秒足够它再派出去好几格。
  const until_ = Date.now() + 6000;
  while (Date.now() < until_) {
    await m.api("POST", "/exec", { sql: "update task set domain = domain where id = 't-dead-quiet'" });
    await Bun.sleep(250);
  }

  const after = (
    await m.api<{ rows: { n: number }[] }>("POST", "/query", {
      sql: "select count(*) as n from task_loop where task = 't-dead-quiet'",
    })
  ).rows[0].n;
  show("units six seconds later:", after);

  // 在飞的那一格回来之后还能推进**一格** —— 那一次调用是死之前就派出去的，
  // 它的结果该收下。要守的是「不再**新开**」，不是「当场断电」。
  ok("a scored task opens no new units", after <= atDeath + 1, { atDeath, after });

  step("4. and no call was made beyond the ones already out when the score was final");
  // 跟死亡那一刻的格数比，**不是跟「几秒前」比** —— 后者只说明「现在停了」，而洞
  // 早就在那几秒里花完了钱。这一条要守的是花销的总量。
  await Bun.sleep(2500);
  show("units at death vs calls served:", { atDeath, served });
  ok("the model was asked no more times than that", served <= atDeath, { atDeath, served });
} finally {
  out.stop();
  m.stop();
}

done();
