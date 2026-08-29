/**
 * `tab:deck` 这个地方的契约，写成一条规则。
 *
 * 挂在 `unit_start` 上，`when` 再加一条 `place = tab:deck` —— 只有落在这个地方的
 * 执行单元开工前才核。核两样：
 *
 * 1. **那个链接还开着** —— 地方就是这一页，页没了这个地方就不存在了
 * 2. **那几个期望的工具都在表里**
 *
 * ## 为什么这件事非得是规则
 *
 * 声明那一刻能核的只是第一遍：`/declare` 连不上 server 就整份拒了。但标签页是**活的
 * 东西** —— 人随手一关，库里那几行 `tool` 还好端端躺着，地方却已经空了。第二个执行
 * 单元照样把 `deck_next` 摆给模型，模型照样调，然后拿一条 isError 回来。
 *
 * 「登记」和「现在还在不在」是两回事，跟 `workplace.usable` 是登记不是探活一个道理。
 * 所以核这件事得挂在**每次开工那一刻**，而那正是时刻 + 规则。
 *
 * ## 它不拦
 *
 * 规则炸了只炸它自己，内核记一行日志，这一站照跑（见 `loop.ts` 的 `#atMoment`）。
 * 这是故意的：钩子挂在主路上，让它把整步带停的话，一条写坏的规则能让所有任务都不动。
 * 所以这儿的作用是**当场说清楚哪儿不对**，不是把闸拉了。
 */

const BASE = process.env.TGENGIN_BASE ?? "http://127.0.0.1:7801/api";
const CDP = process.env.TGENGIN_DECK_CDP ?? "http://127.0.0.1:9222";

/** 这个地方是哪一页、该有哪几个工具 —— 契约就是这两行。 */
const LINK = process.env.TGENGIN_DECK_URL ?? "file:///E:/sgu-bzhc/EACN_EX/TgEngin/examples/place/deck.html";
const WANT = ["deck_state", "deck_next", "deck_prev", "deck_goto"];

async function openTabs(): Promise<string[]> {
  const res = await fetch(`${CDP}/json/list`);
  const list = (await res.json()) as { type: string; url: string }[];
  return list.filter((t) => t.type === "page").map((t) => t.url);
}

async function registered(): Promise<string[]> {
  const res = await fetch(`${BASE}/query`, {
    method: "POST",
    headers: { "content-type": "application/json" },
    body: JSON.stringify({ sql: `select name from tool where identity like 'mcp:deck/%' order by name` }),
  });
  const got = (await res.json()) as { rows?: { name: string }[] };
  return (got.rows ?? []).map((r) => r.name);
}

export async function run(arg: unknown): Promise<unknown> {
  const at = (arg ?? {}) as { place?: string; task?: { id?: string }; unit?: number };
  const bad: string[] = [];

  let tabs: string[] = [];
  try {
    tabs = await openTabs();
  } catch {
    bad.push(`浏览器的调试口连不上（${CDP}）`);
  }
  if (tabs.length && !tabs.includes(LINK)) {
    bad.push(`那一页没开着：${LINK}（现在开着的是 ${tabs.join("、") || "空"}）`);
  }

  const have = await registered();
  const missing = WANT.filter((w) => !have.includes(w));
  if (missing.length) bad.push(`该有的工具少了：${missing.join("、")}（有的是 ${have.join("、") || "一个都没有"}）`);

  const where = `${String(at.task?.id)} 第 ${String(at.unit)} 站`;
  if (bad.length) {
    // 抛出去。内核记一行日志，这一站照跑 —— 它拦不住，也不该拦。
    throw new Error(`${at.place ?? "?"} 这个地方不对劲（${where}）：${bad.join("；")}`);
  }
  console.log(`[deck-contract] ${at.place} 齐了：${have.join("、")}｜${where}`);
  return { place: at.place, link: LINK, tools: have };
}
