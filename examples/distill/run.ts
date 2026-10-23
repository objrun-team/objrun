/**
 * 沉淀（distill）的命令行。四步，每步一个文件进、一个文件出，中间都能看：
 *
 *   cd app   # bun 脚本一律从 app/ 起（.env 撞 statx）
 *   bun ../examples/distill/run.ts harvest <F 臂 h2h.sqlite> [U 臂 unaided.csv] --out harvest.json
 *   bun ../examples/distill/run.ts extract harvest.json --out candidates.json [--only cmt-1,cmt-3] [--all]
 *   bun ../examples/distill/run.ts land candidates.json harvest.json --domain physics --out declare.json [--corpus cmt-0,cmt-2,…]
 *   bun ../examples/distill/run.ts probe declare.json harvest.json [--only <留出题>]
 *   bun ../examples/distill/run.ts pool candidates.json harvest.json --domain physics --out declare-pooled.json [--corpus ids] [--only ids] [--name topic] [--trigger "短语|短语"]（短语间 OR）
 *
 * `pool` 是第二级：按题抽的 skill 在两两不同的题库上互不触发（CMT 实测 0/25），就把它们并成
 * 一份领域级的，只按 domain 触发；指纹闸照过（对语料里每道题被判过的原文）。
 *
 * `extract` 走 OpenRouter（`OPENROUTER_API_KEY`），模型默认跟六榜同一个 0731、同供应商钉法。
 * `land` 的 `--corpus` 限定探针语料 —— 做留出验证时只给训练那一半，留出题一个字都不许看。
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
  // --only 限定并哪几道题的教训（按 topic 分组时用）；--trigger 给触发短语（`|` 分隔，全部 AND），不给就只按 domain
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
  // 指纹和别人答案两道闸照过；词和探针不适用（按 domain 触发）—— 用第一道题当来源、minMatch 0 让探针恒命中
  const src = corpus[0];
  const report = gate({ ...p, task: src.id, keywords: [] }, corpus, { minKeywords: 0, minMatch: 0, maxShare: 1, minHits: 1, maxBody: 4000 });
  console.log(`pooled from ${cands.length} lessons: ${p.body.length} chars; ${report.status}${report.problems.length ? "\n  ! " + report.problems.join("\n  ! ") : ""}`);
  console.log(p.body);
  const ok = report.problems.length === 0;
  writeJson(opt.out, {
    skills: ok
      ? [{ identity: p.identity, does: p.does, params: {}, role: "skill", usable: true, body: `Distilled from earlier solved problems of this kind. It is about the class of problem, not this one:\n\n${p.body}`,
          // 触发短语之间是 OR（一组一个短语）；不给短语就只按 domain
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
