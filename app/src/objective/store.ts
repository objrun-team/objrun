/**
 * 封存区 —— G 的定义放在这儿。
 *
 * ## 为什么不放主库
 *
 * 红线只有两条：**不许直接读到 G 的定义**、**不许改它**。查询自由 —— 想调多少次
 * 都行，反推出这个黑盒的形状不是漏洞，那正是 test-time scaling 本体。
 *
 * 而强制方式**不是「规定不许」，是「够不着」**。我们的主库是全接口开放的：
 * 智能体一条 `/query` 就能读任意表。**G 要是存在主库里，那道墙根本不存在。**
 *
 * 所以 G 的定义落在一个**单独的库文件**里，H2H 不开它，接口够不着。
 * 主库上只留三样：`objective`（这个任务有没有 G，是哪一份）、`readable`（策略位）、
 * 还有判决落回来的 `result` / `state`。
 *
 * ## readable=true 的不用躲
 *
 * 运行态的真实任务里，验收标准本来就是需求的一部分，不给智能体看反而是错的。
 * 所以 `readable=true` 时**把 G 的定义并进任务描述** —— 它就是需求文本本身，
 * 连「读 G」这个动作都不存在。benchmark 样本才需要封。
 *
 * 墙只有一道，逻辑不分叉：**定义一律进封存区**；`readable` 只决定要不要**另外**
 * 把它抄一份进任务描述。
 */

import { mkdirSync } from "node:fs";
import { dirname } from "node:path";

import { Database } from "bun:sqlite";
import type { Objective } from "./spec.ts";
import { parseObjective, validate } from "./spec.ts";

/**
 * **一份候选长什么样** —— 也就是 G 收什么。
 *
 * 这份声明属于 G，不属于哪个工具：内核把 G 包装成 `verify`，交卷那一步问的又是
 * 同一个 G，两处要的东西当然一模一样。写在这儿，那两个工具都从这儿取；抄成两份
 * 字面量的话，哪天多一个字段就会只改到一边 —— 而那不报错，只表现为模型照着一边
 * 的说明填，另一边收到的少一样。
 */
export const CANDIDATE = {
  type: "object",
  properties: {
    answer: {
      type: "string",
      description:
        "The answer, verbatim (keep the \\boxed{} if the task asks for one). This exact text is what gets " +
        "graded, not your derivation.",
    },
  },
  required: ["answer"],
} as const;

export interface Sealed {
  /** 封存一份 G。**过不了定义期检测就拒**，一个字都不写。 */
  seal(task: string, g: Objective): void;
  /** 取一份 G。**只有内核这一侧调得到** —— 智能体那条路只能拿判决。 */
  open(task: string): Objective | null;
  /** 这道题的 G 收什么。没封过就回 `null`。 */
  paramsOf(task: string): Record<string, unknown> | null;
  /** 一轮里这个 G 最多被问几次。没封过就回 `null`。 */
  checksOf(task: string): number | null;
  has(task: string): boolean;
  forget(task: string): void;
  close(): void;
}

export function openSealed(file: string): Sealed {
  mkdirSync(dirname(file), { recursive: true });
  const db = new Database(file, { create: true });
  db.exec("pragma journal_mode = WAL");
  db.exec(`create table if not exists objective (
    task   text not null primary key,
    body   text not null,
    params text not null,
    checks integer not null,
    at     integer not null
  )`);

  return {
    seal(task, g) {
      const errs = validate(g);
      if (errs.length) {
        // **拒收整个任务**，不是「先存着回头再说」。存了一份算不出结果的 G，
        // 那道题会一直挂在系统里，判不出成败也没人知道为什么。
        throw new Error(`the grading function failed definition-time checks and was rejected:\n  - ${errs.join("\n  - ")}`);
      }
      // **一份候选长什么样，跟着 G 一起封。** 内核把 G 包装成 `verify`，交卷那一步
      // 问的又是同一个 G —— 两处要的东西都从这一列来，不各自抄一份字面量。
      db.prepare(
        `insert into objective (task, body, params, checks, at) values (?, ?, ?, ?, ?)
         on conflict(task) do update set body = excluded.body, params = excluded.params, checks = excluded.checks, at = excluded.at`,
      ).run(task, JSON.stringify(g), JSON.stringify(CANDIDATE), g.checks, Date.now());
    },
    open(task) {
      const row = db.prepare(`select body from objective where task = ?`).get(task) as { body: string } | null;
      return row ? parseObjective(JSON.parse(row.body)) : null;
    },
    checksOf(task) {
      const row = db.prepare(`select checks from objective where task = ?`).get(task) as
        | { checks?: number }
        | undefined;
      return row?.checks === undefined ? null : Number(row.checks);
    },
    paramsOf(task) {
      const row = db.prepare(`select params from objective where task = ?`).get(task) as
        | { params?: string }
        | undefined;
      if (!row?.params) return null;
      try {
        return JSON.parse(row.params) as Record<string, unknown>;
      } catch {
        return null;
      }
    },
    has(task) {
      return db.prepare(`select 1 from objective where task = ?`).get(task) !== null;
    },
    forget(task) {
      db.prepare(`delete from objective where task = ?`).run(task);
    },
    close() {
      db.close();
    },
  };
}
