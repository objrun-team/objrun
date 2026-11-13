/**
 * Extract a skill **for other tasks** from one task's verdict history using a model.
 *
 * The model sees the problem statement, what was checked at each node, verdicts and grader
 * feedback, and the model's accompanying messages. It **cannot see** the reference answer,
 * which is absent from the database. It must produce a one-sentence `does`, a `body`, trigger
 * terms copied **verbatim** from the statement, and a category label.
 *
 * This step only generates the candidate. `gate.ts` decides whether it is valid or leaks answers.
 * Strict prompt instructions alone cannot enforce those constraints; the gate can.
 */

import type { HarvestTask } from "./harvest.ts";
import type { Candidate } from "./gate.ts";

export interface ExtractOptions {
  model: string;
  apiKey: string;
  baseURL: string;
  /** Extra request-body fields, such as OpenRouter provider pinning. */
  extra?: Record<string, unknown>;
  reasoningEffort?: string;
  /** Truncate the problem statement. */
  maxStatement?: number;
}

const SYSTEM = `You are distilling a reusable skill from the record of one solved problem.

The record shows a problem statement and the attempts a solver made: each candidate it had graded, whether the grader accepted it, and what the grader said. The solver eventually succeeded. Your job is to write down what a solver of a DIFFERENT problem of the same kind should know beforehand, so that it does not need the grader to learn it.

Return exactly one JSON object in a \`\`\`json fence with these fields:
- "label": a short class label for this kind of problem (3-8 words).
- "does": one sentence saying what the skill is for.
- "body": the skill text, at most 200 words. A method, a convention, a pitfall, a check to run. It must be useful on other problems of this class.
- "keywords": 2 to 5 short strings copied VERBATIM from the problem statement (exact substrings, same case and symbols) that identify the CLASS of problem, not this specific instance. Prefer terms of art and standard notation over numbers or names specific to this instance.

Hard rules:
- The body must NOT contain the accepted answer, any graded candidate, or any expression specific to this instance. Writing the answer down as "knowledge" is cheating and will be rejected by an automatic check.
- The body must not mention the problem id or say "this problem".
- Do not restate the problem. Do not pad.
- If the lesson is only about output format or notation the grader expects (for example how to list several results, what to leave out), say that plainly; that is a valid skill.`;

function clip(s: string, n: number): string {
  return s.length > n ? s.slice(0, n) + " …" : s;
}

export function materialOf(t: HarvestTask, maxStatement = 6000): string {
  const lines: string[] = [];
  lines.push("# Problem statement", "", clip(t.statement, maxStatement), "", "# Attempts");
  for (const a of t.attempts) {
    if (!a.verdicts.length && !a.said.length) continue;
    lines.push("", `## node ${a.node}`);
    for (const s of a.said.slice(0, 6)) lines.push(`- solver said: ${clip(s.replace(/\s+/g, " "), 400)}`);
    for (const v of a.verdicts) {
      const who = v.by === "submit" ? "hand-in" : "verify";
      const said = [v.why && `why: ${v.why}`, v.note && `note: ${clip(v.note, 600)}`].filter(Boolean).join("; ");
      lines.push(`- ${who}: ${clip(v.graded.replace(/\s+/g, " "), 300)} -> ${v.pass ? "ACCEPTED" : "rejected"}${said ? ` (${said})` : ""}`);
    }
  }
  return lines.join("\n");
}

function slug(s: string): string {
  return s
    .toLowerCase()
    .replace(/[^a-z0-9]+/g, "-")
    .replace(/^-+|-+$/g, "")
    .slice(0, 40);
}

async function chat(o: ExtractOptions, system: string, user: string): Promise<string> {
  const body: Record<string, unknown> = {
    model: o.model,
    temperature: 0,
    seed: 42,
    messages: [
      { role: "system", content: system },
      { role: "user", content: user },
    ],
    ...(o.reasoningEffort ? { reasoning: { effort: o.reasoningEffort } } : {}),
    ...(o.extra ?? {}),
  };
  const r = await fetch(`${o.baseURL}/chat/completions`, {
    method: "POST",
    headers: { "content-type": "application/json", authorization: `Bearer ${o.apiKey}` },
    body: JSON.stringify(body),
  });
  if (!r.ok) throw new Error(`${o.baseURL}: ${r.status} ${await r.text()}`);
  const j = (await r.json()) as { choices?: { message?: { content?: string } }[] };
  return j.choices?.[0]?.message?.content ?? "";
}

function parseJson(text: string): Record<string, unknown> {
  const m = text.match(/```json\s*([\s\S]*?)```/) ?? text.match(/(\{[\s\S]*\})/);
  if (!m) throw new Error(`no JSON in the reply: ${clip(text, 200)}`);
  return JSON.parse(m[1]) as Record<string, unknown>;
}

export async function extract(t: HarvestTask, o: ExtractOptions): Promise<Candidate & { raw: string }> {
  const raw = await chat(o, SYSTEM, materialOf(t, o.maxStatement));
  const j = parseJson(raw);
  const label = String(j.label ?? "").trim();
  const keywords = Array.isArray(j.keywords) ? j.keywords.map((k) => String(k)) : [];
  return {
    task: t.id,
    identity: `distill.${slug(t.domain)}.${slug(label) || slug(t.id)}.${slug(t.id)}`,
    label,
    does: String(j.does ?? "").trim(),
    body: String(j.body ?? "").trim(),
    keywords,
    raw,
  };
}

const POOL_SYSTEM = `You are merging several distilled lessons, each written from one solved problem, into ONE skill for a whole class of problems (research-level condensed-matter theory questions graded by an automatic symbolic checker).

Keep only what is general to the class: output conventions the grader expects, verification habits, and pitfalls that recur across the lessons. Drop anything that is about one specific problem: named models, specific results, which option is correct. If two lessons contradict, drop both.

Return exactly one JSON object in a \`\`\`json fence:
- "does": one sentence.
- "body": at most 350 words, as a compact checklist a solver reads before starting.

Hard rules: no answers, no problem-specific claims, no problem ids.`;

/** Second level: combine lessons from individual tasks into a **domain-level** skill. Trigger by domain, not keywords. */
export async function pool(cands: Candidate[], o: ExtractOptions, domain: string): Promise<Candidate & { raw: string }> {
  const user = cands.map((c, i) => `# Lesson ${i + 1}: ${c.label}\n${c.body}`).join("\n\n");
  const raw = await chat(o, POOL_SYSTEM, user);
  const j = parseJson(raw);
  return {
    task: cands.map((c) => c.task).join(","),
    identity: `distill.${slug(domain)}.pooled`,
    label: `pooled ${domain}`,
    does: String(j.does ?? "").trim(),
    body: String(j.body ?? "").trim(),
    keywords: [],
    raw,
  };
}
