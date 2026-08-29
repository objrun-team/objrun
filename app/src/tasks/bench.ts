/**
 * 跑一次 bench。
 *
 * 老代码那份协议就三步：
 *
 * 1. 给每个样本造一个 `G`
 * 2. 训练模式逐个求解 —— **第一个数：`G=1` 的道数**
 * 3. 降解，然后不带 `G` 重跑 —— **第二个数：resolved 的道数**
 *
 * 到我们这儿，一次 bench 就是**一批任务，每个自带一个 G**，靠 `task.run` 认。
 * 跑完数 `G=1` 的道数就是成绩 —— 不需要另一套统计，state 本来就是 G 判出来的。
 *
 * ## 要么全发，要么一个不发
 *
 * 一批里有一道的 G 写坏了，那**整批都别发**。发一半的话，成绩单上的分母是错的，
 * 而且没人看得出来少了哪几道 —— 这跟单个任务「拒收整个任务」是同一条理。
 *
 * ## 不另开一张 bench 表
 *
 * 一跑的成绩是**数出来的**，不是存着的：`task` 表按 `run` 一数就有。存一份的话
 * 它会跟真相漂，而且漂了不报错。
 */

import type { Conn } from "../H2H/db.ts";
import { all } from "../H2H/db.ts";
import type { Sealed } from "../objective/store.ts";
import { publish, type Publish } from "./publish.ts";

export interface Bench {
  /** 这一跑叫什么。不给就按时间生一个。 */
  run?: string;
  /** 这一批的每一道。`run` 由外层统一盖，各项不用写。 */
  tasks: Publish[];
}

export interface Score {
  run: string;
  total: number;
  /** `G=1` 的道数 —— **这就是第一个数**。 */
  passed: number;
  failed: number;
  running: number;
  /** 还没开跑的。 */
  open: number;
  tasks: { id: string; state: string; result: string | null }[];
}

/**
 * 发一批。**先把整批都验一遍，一道不过就整批不发。**
 *
 * 验的办法是先在一个事务里全发一遍，有一道抛就回滚 —— 每一道的检查（来源、G 的
 * 定义期检测、readable、模式/智能体/地方在不在）都在 `publish` 里，不在这儿抄一份。
 */
export function runBench(db: Conn, b: Bench, sealed: Sealed): { run: string; ids: string[] } {
  // 同 `publish`：先问「这是不是一份东西」。空请求打进来不该崩在字段上。
  if (b === null || typeof b !== "object") throw new Error("请求体得是一行 JSON 对象");
  if (!Array.isArray(b.tasks) || b.tasks.length === 0) throw new Error("这一批一道题都没有");
  const run = (b.run ?? "").trim() || new Date().toISOString().replace(/[:.]/g, "-");
  if (all(db, `select 1 from task where run = ? limit 1`, [run]).length > 0) {
    throw new Error(`已经有一跑叫 ${run} 了 —— 换个名字，别把两次的成绩混在一起`);
  }

  const ids: string[] = [];
  db.exec("begin");
  try {
    for (const t of b.tasks) {
      const r = publish(db, { ...t, run }, sealed);
      ids.push(r.id);
    }
    db.exec("commit");
  } catch (e) {
    db.exec("rollback");
    // G 是在 publish 里封存的，回滚不管它 —— 手动把这一批已经封进去的抹掉，
    // 否则下次同名重发会撞上一堆孤儿 G。
    for (const id of ids) sealed.forget(id);
    throw new Error(`这一批没发成（一道不过就整批不发）：${e instanceof Error ? e.message : String(e)}`);
  }
  return { run, ids };
}

/** 一跑的成绩。**数出来的，不是存着的。** */
export function score(db: Conn, run: string): Score {
  const rows = all(db, `select id, state, result from task where run = ? order by id`, [run]) as {
    id: string;
    state: string;
    result: string | null;
  }[];
  const by = (s: string) => rows.filter((r) => r.state === s).length;
  return {
    run,
    total: rows.length,
    passed: by("done"),
    failed: by("failed"),
    running: by("claimed"),
    open: by("open"),
    tasks: rows,
  };
}

/** 有哪几跑。 */
export function runs(db: Conn): { run: string; total: number; passed: number }[] {
  return all(
    db,
    `select run, count(*) as total, sum(case when state = 'done' then 1 else 0 end) as passed
       from task where run <> '' group by run order by run`,
  ) as { run: string; total: number; passed: number }[];
}
