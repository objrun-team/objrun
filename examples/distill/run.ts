/**
 * Command-line interface for distillation. Four steps, each reading and writing a file so intermediate results remain inspectable:
 *
 *   cd app   # Run all Bun scripts from app/ (.env encounters statx).
 *   bun ../examples/distill/run.ts harvest <F-arm h2h.sqlite> [U-arm unaided.csv] --out harvest.json
 *   bun ../examples/distill/run.ts extract harvest.json --out candidates.json [--only cmt-1,cmt-3] [--all]
 *   bun ../examples/distill/run.ts land candidates.json harvest.json --domain physics --out declare.json [--corpus cmt-0,cmt-2,…]
 *   bun ../examples/distill/run.ts probe declare.json harvest.json [--only <held-out-tasks>]
 *   bun ../examples/distill/run.ts pool candidates.json harvest.json --domain physics --out declare-pooled.json [--corpus ids] [--only ids] [--name topic] [--trigger "phrase|phrase"] (OR between phrases)
 *
 * `pool` is the second level: task-specific skills do not trigger on disjoint task sets (0/25 measured in CMT), so merge them into a domain-level skill triggered only by domain. Still apply the fingerprint gate to the original graded text for every task in the corpus.
 *
 * `extract` uses OpenRouter (`OPENROUTER_API_KEY`), defaulting to the same 0731 model and provider pinning as the six benchmarks.
 * `land --corpus` restricts the probe corpus: for held-out validation, provide only the training half, never any text from held-out tasks.
 */

import { readFileSync, writeFileSync } from "node:fs";
import { harvest, taught, type Harvest } from "../../app/src/distill/harvest.ts";
import { gate, type Candidate } from "../../app/src/distill/gate.ts";
import { extract, pool } from "../../app/src/distill/extract.ts";
import { declarationOf, probe, type Landed } from "../../app/src/distill/land.ts";
import { VENDORS } from "../../app/src/llm/index.ts";

const argv = process.argv.slice(2);
const cmd = argv[0];
const pos: string[] = [];
const opt: Record<string, string> = {};
for (let i = 1; i < argv.length; i++) {
  if (argv[i].startsWith("--")) {
    const k = argv[i].slice(2);
    if (i + 1 < argv.length && !argv[i + 1].startsWith("--")) opt[k] = argv[++i];
    else opt[k] = "1";
  } else pos.push(argv[i]);
}
const ids = (s?: string) => (s ?? "").split(",").map((x) => x.trim()).filter(Boolean);
const readJson = <T>(p: string) => JSON.parse(readFileSync(p, "utf8")) as T;
const writeJson = (p: string, v: unknown) => writeFileSync(p, JSON.stringify(v, null, 2) + "\n");

if (cmd === "harvest") {
  const [fDb, uCsv] = pos;
  if (!fDb || !opt.out) throw new Error("harvest <f.sqlite> [u.csv] --out harvest.json");
  const h = harvest(fDb, uCsv ?? null);
  writeJson(opt.out, h);
  const hasU = h.tasks.some((t) => t.uPass !== null);
  const learn = taught(h);
  console.log(`${h.run}: ${h.tasks.length} tasks, F passed ${h.tasks.filter((t) => t.fPass).length}` + (hasU ? `, U passed ${h.tasks.filter((t) => t.uPass).length}, taught by feedback ${learn.length}` : " (no U arm)"));
  console.log(`  taught: ${learn.map((t) => t.id).join(",")}`);
} else if (cmd === "extract") {
  const [hp] = pos;
  if (!hp || !opt.out) throw new Error("extract harvest.json --out candidates.json [--only ids] [--all] [--model m]");
  const h = readJson<Harvest>(hp);
  const only = new Set(ids(opt.only));
  let targets = opt.all ? h.tasks.filter((t) => t.fPass === 1) : taught(h);
  if (only.size) targets = targets.filter((t) => only.has(t.id));
  const vendor = VENDORS.openrouter;
  const apiKey = process.env[vendor.keyEnv];
  if (!apiKey) throw new Error(`${vendor.keyEnv} is not set (export it in the shell; bun cannot read .env on this node)`);
  const o = { model: opt.model ?? "deepseek/deepseek-v4-flash-0731", apiKey, baseURL: vendor.baseURL, extra: vendor.extra, reasoningEffort: opt.effort ?? "medium" };
  console.log(`extracting from ${targets.length} tasks with ${o.model}`);
  const out: (Candidate & { raw?: string; error?: string })[] = [];
  const at = Number(opt.parallel ?? 6);
  for (let i = 0; i < targets.length; i += at) {
    const batch = targets.slice(i, i + at);
    const got = await Promise.all(
      batch.map(async (t) => {
        try {
          const c = await extract(t, o);
          console.log(`  ${t.id}: ${c.label} | kw=${JSON.stringify(c.keywords)}`);
          return c;
        } catch (e) {
          console.log(`  ${t.id}: FAILED ${(e as Error).message.slice(0, 200)}`);
          return { task: t.id, identity: "", label: "", does: "", body: "", keywords: [], error: (e as Error).message } as Candidate & { error: string };
        }
      }),
    );
    out.push(...got);
  }
  writeJson(opt.out, out);
} else if (cmd === "land") {
  const [cp, hp] = pos;
  if (!cp || !hp || !opt.out || !opt.domain) throw new Error("land candidates.json harvest.json --domain d --out declare.json [--corpus ids] [--max-share 0.3] [--min-hits 2] [--min-match 2] [--mount-single]");
  const cands = readJson<(Candidate & { error?: string })[]>(cp).filter((c) => !c.error);
  const h = readJson<Harvest>(hp);
  const corpusIds = new Set(ids(opt.corpus));
  const corpus = h.tasks.filter((t) => !corpusIds.size || corpusIds.has(t.id)).map((t) => ({ id: t.id, statement: t.statement, accepted: t.accepted, rejected: t.rejected }));
  const landed: Landed[] = cands.map((c) => ({ ...c, report: gate(c, corpus, { maxShare: Number(opt["max-share"] ?? 0.3), minHits: Number(opt["min-hits"] ?? 2), minMatch: Number(opt["min-match"] ?? 2) }) }));
  const rows = landed.map((c) => `${c.task.padEnd(9)} ${c.report.status.padEnd(9)} hits=${String(c.report.hits.length).padStart(2)} kw=${JSON.stringify(c.report.keywords)}${c.report.problems.length ? "\n" + c.report.problems.map((p) => `           ! ${p}`).join("\n") : ""}`);
  console.log(rows.join("\n"));
  const n = (s: string) => landed.filter((c) => c.report.status === s).length;
  console.log(`landed ${n("landed")}, single ${n("single")}, rejected ${n("rejected")} (corpus ${corpus.length})`);
  writeJson(opt.out, declarationOf(landed, opt.domain, Boolean(opt["mount-single"])));
  writeJson(opt.out.replace(/\.json$/, "") + ".report.json", landed);
} else if (cmd === "probe") {
  const [dp, hp] = pos;
  if (!dp || !hp) throw new Error("probe declare.json harvest.json [--only ids]");
  const decl = readJson<Parameters<typeof probe>[0]>(dp);
  const h = readJson<Harvest>(hp);
  const only = new Set(ids(opt.only));
  const tasks = h.tasks.filter((t) => !only.size || only.has(t.id));
  const m = probe(decl, tasks);
  let fired = new Set<string>();
  for (const [id, hits] of m) {
    console.log(`${id}: ${hits.length ? hits.join(",") : "-"}`);
    hits.forEach((x) => fired.add(x));
  }
  console.log(`${decl.skills.length} skills; ${fired.size}/${tasks.length} tasks would get at least one`);
} else if (cmd === "pool") {
  const [cp, hp] = pos;
  if (!cp || !hp || !opt.out || !opt.domain) throw new Error("pool candidates.json harvest.json --domain d --out declare.json [--corpus ids]");
  // --only selects which tasks’ lessons to pool (for topic grouping); --trigger supplies phrases (`|`-separated, all AND). Without it, trigger only by domain.
  const onlyIds = new Set(ids(opt.only));
  const cands = readJson<(Candidate & { error?: string })[]>(cp).filter((c) => !c.error && c.body && (!onlyIds.size || onlyIds.has(c.task)));
  const h = readJson<Harvest>(hp);
  const corpusIds = new Set(ids(opt.corpus));
  const corpus = h.tasks.filter((t) => !corpusIds.size || corpusIds.has(t.id)).map((t) => ({ id: t.id, statement: t.statement, accepted: t.accepted, rejected: t.rejected }));
  const vendor = VENDORS.openrouter;
  const apiKey = process.env[vendor.keyEnv];
  if (!apiKey) throw new Error(`${vendor.keyEnv} is not set`);
  const o = { model: opt.model ?? "deepseek/deepseek-v4-flash-0731", apiKey, baseURL: vendor.baseURL, extra: vendor.extra, reasoningEffort: opt.effort ?? "medium" };
  const triggers = (opt.trigger ?? "").split("|").map((x) => x.trim()).filter(Boolean);
  const p = await pool(cands, o, opt.domain);
  if (opt.name) p.identity = `distill.${opt.domain}.pooled.${opt.name}`;
  // Still apply fingerprint and other-answer gates. Word and probe gates do not apply to domain triggers: use the first task as the source and minMatch 0 so the probe always matches.
  const src = corpus[0];
  const report = gate({ ...p, task: src.id, keywords: [] }, corpus, { minKeywords: 0, minMatch: 0, maxShare: 1, minHits: 1, maxBody: 4000 });
  console.log(`pooled from ${cands.length} lessons: ${p.body.length} chars; ${report.status}${report.problems.length ? "\n  ! " + report.problems.join("\n  ! ") : ""}`);
  console.log(p.body);
  const ok = report.problems.length === 0;
  writeJson(opt.out, {
    skills: ok
      ? [{ identity: p.identity, does: p.does, params: {}, role: "skill", usable: true, body: `Distilled from earlier solved problems of this kind. It is about the class of problem, not this one:\n\n${p.body}`,
          // Trigger phrases use OR (one phrase per group); without phrases, trigger only by domain.
          when: (triggers.length ? triggers : [""]).map((k) => [
            { dim: "task", key: "domain", op: "eq", value: opt.domain },
            { dim: "chain", key: "", op: "not_contains", value: ">" },
            ...(k ? [{ dim: "task", key: "description", op: "contains", value: k }] : []),
          ]) }]
      : [],
  });
  writeJson(opt.out.replace(/\.json$/, "") + ".report.json", { ...p, report });
} else {
  console.error("usage: run.ts harvest|extract|land|probe …  (see the header of this file)");
  process.exit(2);
}
