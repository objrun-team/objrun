/**
 * 这台机器认得什么。
 *
 * ## 为什么要有这个口
 *
 * **客户端不该把这些写死。** 写死的代价很具体：这边给消息类型加了一种 `voice`，
 * 客户端那边的 `switch` 没有这一支，于是现场说的话在界面上**显示成空白** ——
 * 不报错，就是没了。加一种状态、加一种调用形状，都是同一个下场。
 *
 * 所以客户端启动时拉一次这个口，把下面这些**当数据用**。这边加一种，那边自动就有。
 *
 * 「人给的标记」那一条尤其是：库里人写的消息带着它，客户端显示时要么剥掉、
 * 要么据它标个样式。硬编码 `"【人】"` 的话，这边一改那边就全乱。
 */

import { all, type Store } from "../H2H/db.ts";
import { HUMAN_MARK, KINDS } from "../msg/deliver.ts";
import { MODES } from "../llm/index.ts";
import { SOURCES, STATES } from "../tasks/publish.ts";
import type { Route } from "./spec.ts";

/** 任务四态各是什么意思。**跟 `STATES` 同源** —— 那是值域，这是给人看的注解。 */
const STATE_NOTE: Record<string, string> = {
  open: "待领取：一个执行单元都还没开",
  claimed: "有人在干：还有没干完的执行单元",
  done: "全干完了。有 G 的话还得 G 说了算",
  failed: "判失败了 —— result 里说为什么",
};

const SOURCE_NOTE: Record<string, string> = {
  user: "真人发的。**只有这一种能带 G**",
  agent: "智能体在树内派生的。不许带 G —— 那是自提权",
  world: "环境触发的",
  eacn: "上层系统发的",
};

/** 执行单元的终止状态。**出生即定，不回改。** */
const UNIT_STATUS: [string, string][] = [
  ["reached", "自称走到终点了"],
  ["dead_failed", "判死：这一步没成"],
  ["dead_below_bar", "判死：够不着及格线"],
];

export function aboutRoutes(prefix: string, store: Store, version: string, duplex: string[]): Route[] {
  return [
    {
      method: "GET",
      path: "/about",
      group: "这台机器",
      does: "这台机器认得哪些取值 —— 状态、来源、消息类型、调用形状",
      why: "**别把这些写死在客户端里。** 这边加一种消息类型，客户端的 switch 没有那一支，那条消息就在界面上显示成空白 —— 不报错，就是没了。拉这个口当数据用，这边加一种那边自动就有。",
      returns: {
        version: "1.0.0",
        prefix: "/api",
        taskStates: [{ name: "open", note: "待领取：一个执行单元都还没开" }],
        taskSources: [{ name: "user", note: "真人发的。**只有这一种能带 G**" }],
        msgKinds: [{ name: "voice", note: "真人说的（转写）", human: true }],
        apiModes: [{ name: "duplex", note: "实时双向。一个执行单元 = 会话里的一个来回" }],
        unitStatuses: [{ name: "reached", note: "自称走到终点了" }],
        humanMark: "【人】",
        declared: { modes: ["dfs"], agents: ["solver"], places: ["local"], duplexHandles: [] },
      },
      handler: async () => {
        // `human` 这一位是**算**出来的：库里那条消息压出去会不会缀标记。
        // 客户端拿它决定要不要剥前缀 —— 自己维护一张名单的话，加一种就漏一种。
        const human = new Set(["user", "voice"]);
        return {
          version,
          prefix,
          taskStates: STATES.map((s) => ({ name: s, note: STATE_NOTE[s] ?? "" })),
          taskSources: SOURCES.map((s) => ({ name: s, note: SOURCE_NOTE[s] ?? "" })),
          msgKinds: KINDS.map(([name, note]) => ({ name, note, human: human.has(name) })),
          apiModes: MODES.map(([name, note]) => ({ name, note })),
          unitStatuses: UNIT_STATUS.map(([name, note]) => ({ name, note })),
          humanMark: HUMAN_MARK,
          declared: {
            duplexHandles: duplex,
            modes: (all(store.ro, `select distinct mode from cycle order by mode`) as { mode: string }[]).map(
              (r) => r.mode,
            ),
            agents: (all(store.ro, `select name from agent order by name`) as { name: string }[]).map((r) => r.name),
            places: (all(store.ro, `select place from workplace order by place`) as { place: string }[]).map(
              (r) => r.place,
            ),
          },
        };
      },
    },
  ];
}
