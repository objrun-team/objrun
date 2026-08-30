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
import { HUMAN_KINDS, HUMAN_MARK, KINDS } from "../msg/deliver.ts";
import { MODES } from "../llm/index.ts";
import { SOURCES, STATES } from "../tasks/publish.ts";
import type { Route } from "./spec.ts";

/** 任务四态各是什么意思。**跟 `STATES` 同源** —— 那是值域，这是给人看的注解。 */
const STATE_NOTE: Record<string, string> = {
  open: "Waiting to be picked up: not a single execution unit has been opened",
  claimed: "Someone is working on it: there are unfinished execution units",
  done: "Everything finished. If it has a grading function, that function has the last word",
  failed: "Judged a failure - result says why",
};

const SOURCE_NOTE: Record<string, string> = {
  user: "Published by a person. Only this source may carry a grading function",
  agent: "Derived by the agent inside the tree. May not carry a grading function - that would be self-granted authority",
  world: "Triggered by the environment",
  eacn: "Published by the system above",
};

/** 执行单元的终止状态。**出生即定，不回改。** */
const UNIT_STATUS: [string, string][] = [
  ["reached", "Claims to have arrived"],
  ["dead_failed", "Ruled out: this step did not work"],
  ["dead_below_bar", "Ruled out: below the bar"],
];

export function aboutRoutes(prefix: string, store: Store, version: string, duplex: string[]): Route[] {
  return [
    {
      method: "GET",
      path: "/about",
      group: "This machine",
      does: "Which values this machine knows: states, sources, message kinds, api modes",
      why: "Do not hard-code these in a client. Add a message kind here, and a client switch without that branch renders the message as blank - no error, it is simply gone. Read this route as data, and a kind added here shows up there on its own.",
      returns: {
        version: "1.0.0",
        prefix: "/api",
        taskStates: [{ name: "open", note: "Waiting to be picked up: not a single execution unit has been opened" }],
        taskSources: [{ name: "user", note: "Published by a person. Only this source may carry a grading function" }],
        msgKinds: [{ name: "voice", note: "Spoken by a person (transcribed)", human: true }],
        apiModes: [{ name: "duplex", note: "Realtime, both directions. One execution unit = one turn in the session" }],
        unitStatuses: [{ name: "reached", note: "Claims to have arrived" }],
        humanMark: "[human] ",
        declared: { modes: ["dfs"], agents: ["solver"], places: ["local"], duplexHandles: [] },
      },
      handler: async () => {
        // `human` 这一位从投递那张推断表推出来，**这儿不另留一份名单** ——
        // 各留一份的话，加一种人类来源就会漏掉一处。
        return {
          version,
          prefix,
          taskStates: STATES.map((s) => ({ name: s, note: STATE_NOTE[s] ?? "" })),
          taskSources: SOURCES.map((s) => ({ name: s, note: SOURCE_NOTE[s] ?? "" })),
          msgKinds: KINDS.map(([name, note]) => ({ name, note, human: HUMAN_KINDS.has(name) })),
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
