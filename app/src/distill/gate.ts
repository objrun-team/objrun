/**
 * Gate candidate skills before installation. **All decisions are computed**, without consulting a model or person.
 *
 * These safeguards come from the agentos degradation pipeline (`agents/degrade/submit.py`)
 * and its usage examples; each addresses an observed failure:
 *
 * - **Fingerprints**: the body must not contain any candidate text graded on this task, whether
 *   accepted or rejected. Otherwise it repackages an answer as knowledge: another form of lookup.
 * - **Terms must occur in the statement**: trigger terms must be **literal substrings** of the
 *   problem statement. The engine's `contains` comparison is literal; inferred paraphrases
 *   never match and produce no error, a failure the old implementation called "silent ineffectiveness".
 * - **Positive and coverage probes**: the conjunction of trigger terms must match the source
 *   task and **at least one other task** in the corpus. A source-only match is task-specific
 *   and counts only as an observation. Coverage must also stay below a limit to avoid
 *   injecting irrelevant material into a broad set of unrelated tasks.
 * - **Other tasks' answers**: the body must not contain accepted candidate text from other
 *   corpus tasks. Leaking a neighboring task's answer is even subtler than leaking its own.
 *
 * Passing these gates establishes only that the skill is not an answer lookup, can trigger,
 * and is not excessively broad. **Usefulness is determined by the U arm on held-out tasks**,
 * which is the responsibility of `runs/cmt-distill-holdout.sh`, not this module.
 */

export interface Candidate {
  /** The task from which the skill was extracted. */
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
  /** Corpus tasks matched by the conjunction of trigger terms. */
  hits: string[];
  /** Trigger terms actually used: literal substrings of the statement. */
  keywords: string[];
  /** Minimum number of terms that must co-occur; installation builds OR groups from this threshold. */
  minMatch: number;
}

export interface GateOptions {
  /** Maximum fraction of the corpus that may match. */
  maxShare?: number;
  /** Minimum number of matching tasks, including the source, to avoid a task-specific skill. */
  minHits?: number;
  /** Minimum number of trigger terms. */
  minKeywords?: number;
  /** Maximum body length in characters. */
  maxBody?: number;
  /** Skip fingerprints shorter than this after normalization; comparing short forms such as `\boxed{a}` would create false positives. */
  minFingerprint?: number;
  /**
   * Minimum number of trigger terms that must co-occur in a statement. Requiring every term
   * matched only the source task in practice, because all 50 CMT statements differ. That creates
   * a task-specific skill. Installation uses this threshold to construct OR groups, each an AND
   * of `minMatch` terms, matching the decision made here.
   */
  minMatch?: number;
}

/** All combinations of `k` elements from `items`. */
export function combos<T>(items: T[], k: number): T[][] {
  if (k <= 0) return [[]];
  if (items.length < k) return [];
  const [h, ...rest] = items;
  return [...combos(rest, k - 1).map((c) => [h, ...c]), ...combos(rest, k)];
}

/** A statement matches if at least `minMatch` terms appear literally. */
export function matches(statement: string, keywords: string[], minMatch: number): boolean {
  const k = Math.min(minMatch, keywords.length);
  return keywords.filter((w) => statement.includes(w)).length >= k;
}

/** Normalize by removing `\boxed{}`, whitespace, backslashes, braces, and `$`, then lowercasing. Compare form, not bytes. */
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

  // Terms must appear verbatim in the statement.
  const kws = [...new Set(c.keywords.map((k) => k.trim()).filter(Boolean))];
  const present = kws.filter((k) => src.statement.includes(k));
  const missing = kws.filter((k) => !src.statement.includes(k));
  if (missing.length) problems.push(`keywords not found verbatim in the statement: ${missing.map((m) => JSON.stringify(m)).join(", ")}`);
  if (present.length < minKeywords) problems.push(`only ${present.length} usable keyword(s), need ${minKeywords}`);

  // Body.
  if (!c.body.trim()) problems.push("body is empty");
  if (c.body.length > maxBody) problems.push(`body is ${c.body.length} chars, cap is ${maxBody}`);
  if (c.body.includes(c.task)) problems.push("body names the task id");
  const nb = norm(c.body);

  // Fingerprints: every candidate text graded on the source task.
  for (const g of [...src.accepted, ...src.rejected]) {
    const ng = norm(g);
    if (ng.length >= minFp && nb.includes(ng)) {
      problems.push(`body contains a graded candidate of its own task: ${g.slice(0, 60)}`);
      break;
    }
  }
  // Answers from other tasks.
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

  // Positive and coverage probes.
  // No trigger terms, as with domain-based triggering, means the entire corpus matches.
  const hits = present.length || minMatch === 0 ? corpus.filter((x) => matches(x.statement, present, minMatch)).map((x) => x.id) : [];
  if (present.length && !hits.includes(c.task)) problems.push("keywords do not match the source task itself");
  const cap = Math.max(minHits, Math.ceil(maxShare * corpus.length));
  if (hits.length > cap) problems.push(`keywords match ${hits.length}/${corpus.length} tasks, cap is ${cap} (too wide)`);

  if (problems.length) return { status: "rejected", problems, hits, keywords: present, minMatch };
  if (hits.length < minHits) return { status: "single", problems: [`matches only its own task (${hits.length} hit); kept as an observation, not mounted`], hits, keywords: present, minMatch };
  return { status: "landed", problems: [], hits, keywords: present, minMatch };
}
