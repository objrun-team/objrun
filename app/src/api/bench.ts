/**
 * 跑分和诊断。
 *
 * 诊断那几个口是这台机器的**要害功能**，不是调试附赠品：条件写错了不会报错，
 * 那条规则只是永远不触发，而系统照常跑。老代码那边的原话是「写错的典型后果是
 * 静默不生效，跑一遍系统也看不出来」。
 */

import type { Store } from "../H2H/db.ts";
import { all } from "../H2H/db.ts";
import type { Registry } from "../engine/registry.ts";
import type { Sealed } from "../objective/store.ts";
import { runBench, runs, score, type Bench } from "../tasks/bench.ts";
import { check, explain } from "../trigger/check.ts";
import { checkData } from "../trigger/data.ts";
import type { Route } from "./spec.ts";

const BENCH = "跑分";
const DIAG = "诊断";

export function benchRoutes(store: Store, reg: Registry, sealed: Sealed, wake: () => void): Route[] {
  return [
    {
      method: "POST",
      path: "/bench",
      group: BENCH,
      does: "发一批带 G 的题",
      why: "**一道不过就整批不发。** 发一半的话成绩单的分母是错的，而且没人看得出来少了哪几道。",
      params: [
        { name: "run", in: "body", kind: "string", note: "这一跑叫什么。不给按时间生一个。**重名当场拒** —— 两次的成绩混在一起就说不清了" },
        { name: "tasks", in: "body", kind: "array", required: true, of: "跟 POST /tasks 收的一样，每道自带 objective", note: "这一批的题" },
      ],
      returns: { run: "2026-08-29T12-00-00", ids: ["b-1", "b-2"] },
      errs: [{ code: 400, when: "重名、一道题都没有、或者其中任一道过不了发布那道闸（整批都不发）" }],
      handler: async (a, _req, reply) => {
        const r = runBench(store.rw, a as unknown as Bench, sealed);
        wake();
        return reply.code(201).send(r);
      },
    },
    {
      method: "GET",
      path: "/bench",
      group: BENCH,
      does: "有哪几跑",
      returns: { runs: [{ run: "2026-08-29T12-00-00", n: 4 }] },
      handler: async () => ({ runs: runs(store.ro) }),
    },
    {
      method: "GET",
      path: "/bench/:run",
      group: BENCH,
      does: "一跑的成绩",
      why: "**数出来的，不是存着的。** 存一份会跟真相漂，而且漂了不报错。",
      params: [{ name: "run", in: "path", kind: "string", required: true, note: "这一跑的名字" }],
      returns: { run: "2026-08-29T12-00-00", total: 4, done: 2, failed: 1, running: 1, tasks: [] },
      handler: async (a) => score(store.ro, String(a.run)),
    },
    {
      method: "GET",
      path: "/check",
      group: DIAG,
      does: "整库过一遍：条件写得对不对 + 数据互相对不对得上",
      why: "**开机也自动跑一遍**，有问题打警告不拦启动。客户端该在「配置页」上直接显示它 —— 声明写错了不报错，只是那台机器什么都不干。",
      returns: {
        trigger: [{ owner_kind: "tool", owner: "read", group: 0, why: "比法 contain 不认得" }],
        data: [{ what: "task t-1", why: "走的模式 dfs 在任务周期表里没有 —— 这个任务谁都接不了，而且不会报错" }],
      },
      handler: async () => ({ trigger: check(store.ro), data: checkData(store.ro, reg) }),
    },
    {
      method: "GET",
      path: "/trigger/check",
      group: DIAG,
      does: "只把触发条件过一遍",
      why: "**不跑系统就能验。** 条件写错了的典型后果是静默不生效 —— 那条规则永远不触发而系统照常跑，所以这不是调试功能，是这张表能不能用的前提。",
      returns: { problems: [] },
      handler: async () => ({ problems: check(store.ro) }),
    },
    {
      method: "POST",
      path: "/trigger/explain",
      group: DIAG,
      does: "为什么这一条没命中 —— 逐组说清，**带上实际取到的值**",
      why: "只说「没匹配」的话，人得自己猜是词写错了、还是那段文本里根本没有。带上实际值就不用猜。",
      params: [
        { name: "kind", in: "body", kind: "string", required: true, only: ["rule", "skill", "tool"], note: "问哪一类的条件（`owner_kind`）" },
        { name: "owner", in: "body", kind: "string", required: true, note: "问哪一个（规则名 / skill / 工具名）" },
        { name: "agent", in: "body", kind: "string", note: "拿哪个智能体当事实。不给就当没有这一维" },
        { name: "task", in: "body", kind: "string", note: "拿哪个任务当事实" },
        { name: "mode", in: "body", kind: "string", note: "拿哪个模式的周期当事实，跟 `cycle` 一起给" },
        { name: "cycle", in: "body", kind: "string", note: "哪个周期" },
        { name: "chain", in: "body", kind: "string", note: "链路串，如 `dfs/open#1 > dfs/act#2`" },
      ],
      returns: {
        fired: false,
        groups: [{ group: 0, ok: false, items: [{ dim: "task", key: "source", op: "eq", value: "user", actual: "agent", ok: false }] }],
      },
      errs: [{ code: 400, when: "指名的 agent / task / cycle 在库里没有那一行" }],
      handler: async (a, _req, reply) => {
        try {
          const row = (what: string, sql: string, p: unknown[]) => {
            const r = all(store.ro, sql, p)[0];
            if (!r) throw new Error(`${what} 里没有这一行`);
            return r;
          };
          return explain(store.ro, String(a.kind), String(a.owner), {
            agent: a.agent ? row("agent", `select * from agent where name = ?`, [a.agent]) : {},
            task: a.task ? row("task", `select * from task where id = ?`, [a.task]) : {},
            cycle: a.mode ? row("cycle", `select * from cycle where mode = ? and cycle = ?`, [a.mode, a.cycle]) : {},
            chain: a.chain ? String(a.chain) : "",
          });
        } catch (e) {
          return reply.code(400).send({ error: e instanceof Error ? e.message : String(e) });
        }
      },
    },
  ];
}
