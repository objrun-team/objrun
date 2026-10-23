/**
 * 闸 —— 一份候选 skill 能不能落地，**全部是算出来的**，不问模型、不问人。
 *
 * 这几道闸是从 agentos 那边的降解管线（`agents/degrade/submit.py`）和它的用法案例册
 * 里抄来的教训，那边每一条都是踩出来的：
 *
 * - **指纹**：正文里不许出现这道题被判过的任何一段原文（对的、错的都不许）。
 *   出现了就是「把答案写成知识」—— 换个写法的打表。
 * - **词要在题面里**：触发词必须是题面里**原样**有的子串。引擎的 `contains` 是字面比较，
 *   模型「意会」出来的词永远不命中，而且零报错（老代码那边叫「静默不生效」）。
 * - **双边探针**：触发词的合取必须命中来源那道题（正例），**且**命中语料里至少另一道
 *   （不然是给一道题造的轮子，只算观测），**且**不许命中太大一片（地图炮：污染无关题）。
 * - **别人的答案**：正文里也不许出现语料里其它题被判对的原文 —— 一份 skill 顺手把
 *   隔壁题的答案带进上下文，比只泄自己那道更阴。
 *
 * 过了闸只说明「不是打表、能触发、不太宽」。**它有没有用，只有留出题上的 U 臂说了算**
 * —— 那是 `runs/cmt-distill-holdout.sh` 的事，不是这个文件的事。
 */

export interface Candidate {
  /** 从哪道题抽的。 */
  task: string;
  identity: string;
  label: string;
  does: string;
  body: string;
  keywords: string[];
}

export interface CorpusItem {
  id: string;
  statement: string;
  accepted: string[];
  rejected: string[];
}

export interface GateReport {
  status: "landed" | "single" | "rejected";
  problems: string[];
  /** 触发词合取命中了语料里哪几道。 */
  hits: string[];
  /** 真正用上的触发词（题面里原样有的那几个）。 */
  keywords: string[];
  /** 至少共现几个才命中；落位按它拼 OR 组。 */
  minMatch: number;
}

export interface GateOptions {
  /** 命中份额上限（占语料）。 */
  maxShare?: number;
  /** 至少命中几道（含来源）才算不是单题轮子。 */
  minHits?: number;
  /** 至少几个触发词。 */
  minKeywords?: number;
  /** 正文上限（字符）。 */
  maxBody?: number;
  /** 指纹比对时，原文归一化之后短于这个长度的不比（`\boxed{a}` 这种比了只会误伤）。 */
  minFingerprint?: number;
  /**
   * 题面里至少共现几个触发词才算命中。全 AND（= 词数）实测每份只命中来源那一道
   * （CMT 50 题两两不同），等于给一道题造轮子；落位时按这个数拼 OR 组（每组是
   * `minMatch` 个词的 AND），跟这里的判法一致。
   */
  minMatch?: number;
}

/** 从 `items` 里取 `k` 个的全部组合。 */
export function combos<T>(items: T[], k: number): T[][] {
  if (k <= 0) return [[]];
  if (items.length < k) return [];
  const [h, ...rest] = items;
  return [...combos(rest, k - 1).map((c) => [h, ...c]), ...combos(rest, k)];
}

/** 题面命中了吗：至少 `minMatch` 个词原样出现。 */
export function matches(statement: string, keywords: string[], minMatch: number): boolean {
  const k = Math.min(minMatch, keywords.length);
  return keywords.filter((w) => statement.includes(w)).length >= k;
}

/** 归一化：去 `\boxed{}`、空白、反斜杠、花括号、`$`，小写。比的是「形状」不是字节。 */
export function norm(s: string): string {
  return s
    .replace(/\\boxed\s*\{/g, "")
    .replace(/[\s\\{}$]/g, "")
    .toLowerCase();
}

export function gate(c: Candidate, corpus: CorpusItem[], o: GateOptions = {}): GateReport {
  const maxShare = o.maxShare ?? 0.3;
  const minHits = o.minHits ?? 2;
  const minKeywords = o.minKeywords ?? 2;
  const maxBody = o.maxBody ?? 2000;
  const minFp = o.minFingerprint ?? 6;
  const minMatch = o.minMatch ?? 2;
  const problems: string[] = [];
  const src = corpus.find((x) => x.id === c.task);
  if (!src) return { status: "rejected", problems: [`source task ${c.task} is not in the corpus`], hits: [], keywords: [], minMatch };

  // 词要在题面里，原样
  const kws = [...new Set(c.keywords.map((k) => k.trim()).filter(Boolean))];
  const present = kws.filter((k) => src.statement.includes(k));
  const missing = kws.filter((k) => !src.statement.includes(k));
  if (missing.length) problems.push(`keywords not found verbatim in the statement: ${missing.map((m) => JSON.stringify(m)).join(", ")}`);
  if (present.length < minKeywords) problems.push(`only ${present.length} usable keyword(s), need ${minKeywords}`);

  // 正文
  if (!c.body.trim()) problems.push("body is empty");
  if (c.body.length > maxBody) problems.push(`body is ${c.body.length} chars, cap is ${maxBody}`);
  if (c.body.includes(c.task)) problems.push("body names the task id");
  const nb = norm(c.body);

  // 指纹：自己这道题被判过的每一段原文
  for (const g of [...src.accepted, ...src.rejected]) {
    const ng = norm(g);
    if (ng.length >= minFp && nb.includes(ng)) {
      problems.push(`body contains a graded candidate of its own task: ${g.slice(0, 60)}`);
      break;
    }
  }
  // 别人的答案
  for (const other of corpus) {
    if (other.id === c.task) continue;
    for (const g of other.accepted) {
      const ng = norm(g);
      if (ng.length >= minFp && nb.includes(ng)) {
        problems.push(`body contains an accepted answer of another task (${other.id})`);
        break;
      }
    }
  }

  // 双边探针
  // 没有触发词（按 domain 触发的那种）= 命中全语料
  const hits = present.length || minMatch === 0 ? corpus.filter((x) => matches(x.statement, present, minMatch)).map((x) => x.id) : [];
  if (present.length && !hits.includes(c.task)) problems.push("keywords do not match the source task itself");
  const cap = Math.max(minHits, Math.ceil(maxShare * corpus.length));
  if (hits.length > cap) problems.push(`keywords match ${hits.length}/${corpus.length} tasks, cap is ${cap} (too wide)`);

  if (problems.length) return { status: "rejected", problems, hits, keywords: present, minMatch };
  if (hits.length < minHits) return { status: "single", problems: [`matches only its own task (${hits.length} hit); kept as an observation, not mounted`], hits, keywords: present, minMatch };
  return { status: "landed", problems: [], hits, keywords: present, minMatch };
}
