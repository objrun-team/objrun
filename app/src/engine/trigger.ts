/**
 * 什么时候轮到谁。
 *
 * 条件全在 `trigger` 表里，一行一个条件项：**同组之间 and，组和组之间 or**。
 * 这一层只会做比较，不认得任何一个具体的规则名、工具名、周期名。
 */

import type { Conn } from "../H2H/db.ts";
import { all } from "../H2H/db.ts";

/** 比的时候手上有这些东西。`chain` 是拼好的链路串。 */
export interface Facts {
  agent: Record<string, unknown>;
  task: Record<string, unknown>;
  cycle: Record<string, unknown>;
  chain: string;
}

interface Term {
  owner_kind: string;
  owner: string;
  group: number;
  dim: string;
  key: string;
  op: string;
  value: string;
}

/** 认得的比法。写错一个字母不该悄悄不匹配，所以不认得的当场炸。 */
function compare(op: string, got: string, want: string): boolean {
  switch (op) {
    case "eq":
      return got === want;
    case "ne":
      return got !== want;
    case "contains":
      return got.includes(want);
    case "prefix":
      return got.startsWith(want);
    case "suffix":
      return got.endsWith(want);
    case "in":
      return (JSON.parse(want) as unknown[]).map(String).includes(got);
    default:
      throw new Error(`不认得的比法：${op}`);
  }
}

function pick(f: Facts, dim: string, key: string): string {
  switch (dim) {
    case "chain":
      return f.chain;
    case "agent":
    case "task":
    case "cycle": {
      const row = f[dim];
      if (!(key in row)) throw new Error(`${dim} 上没有 ${key} 这一项`);
      return String(row[key] ?? "");
    }
    default:
      throw new Error(`不认得的维度：${dim}`);
  }
}

/**
 * 这一刻有哪些 owner 该触发。
 *
 * 一个 owner 只要**有一组**全中就算触发（组间 or）；一组里**每一条**都得中
 * （组内 and）。一个 owner 一条条件都没有 = 从不触发 —— 不是「总是触发」。
 * 反过来定的话，忘了写条件的东西会到处乱开。
 */
export function fire(db: Conn, kind: string, f: Facts): string[] {
  const terms = all(
    db,
    `select owner_kind, owner, "group", dim, "key", op, value from trigger where owner_kind = ?`,
    [kind],
  ) as unknown as Term[];

  const byOwnerGroup = new Map<string, Term[]>();
  for (const t of terms) {
    const k = `${t.owner}\u0000${t.group}`;
    const arr = byOwnerGroup.get(k);
    if (arr) arr.push(t);
    else byOwnerGroup.set(k, [t]);
  }

  const hit = new Set<string>();
  for (const [k, group] of byOwnerGroup) {
    const owner = k.slice(0, k.indexOf("\u0000"));
    if (hit.has(owner)) continue;
    if (group.every((t) => compare(t.op, pick(f, t.dim, t.key), t.value))) hit.add(owner);
  }
  return [...hit].sort();
}
