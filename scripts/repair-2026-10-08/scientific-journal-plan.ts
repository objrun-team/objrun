import { createHash } from "node:crypto";
import { readFileSync } from "node:fs";
import { join } from "node:path";
import { roundRobinBenchmarks } from "./campaign-workers.ts";

export const digest = (data: string | Uint8Array) => createHash("sha256").update(data).digest("hex");
export const SCIENCE_PORTS: Record<string, number> = { chembench: 17906, aime: 17905, cmt: 17901, chemiq: 17918 };
export type PublicTask = { officialId: string; promptSha256: string; row: Record<string, unknown> };
export type PlannedTask = PublicTask & { index: number; benchmark: string; arm: "U" | "F"; replica: 0; prompt: string; seconds: number; route: string; taskId: string };
const catalogRun = "repair-2026-10-08T11-00-41-864Z";
const pins = {
  chembench: { count: 500, sha: "3136437ee5c146a12bb07da997880b3db88d0159a0d4fd6e00364ac7fa879142" },
  aime: { count: 60, sha: "7dc7352bbb12a107a4c8ab86945a953b78bdf1d4d50e1d5ef9f04cb2e4fcae7a" },
  cmt: { count: 50, sha: "9fcc304809a33a8a9deddfffdd6d8c5784c83527a9a8d037715cd733fe9b004d" },
};
const chemiqSha = "4b11ba7dbcef8f075941c2e5337d687fa94d28837fc93e87a4eed1673a99646f";
export function scientificPrompt(slug: string, row: Record<string, unknown>) {
  const text = String(row.prompt ?? row.problem ?? row.question ?? "") + (row.choices ? "\n\n" + Object.entries(row.choices as Record<string, string>).map(([k, v]) => `${k}. ${v}`).join("\n") : "") + (slug === "cmt" ? `\nParameters: ${row.parameters ?? ""}\nFunctions: ${row.functions ?? ""}` : "");
  const format = ["cmt", "aime"].includes(slug) ? "Put the final mathematical answer inside \\boxed{...}."
    : slug === "chemiq" ? `Use the requested ${row.answer_format ?? "short"} answer format. The final submitted answer must be a single line of at most 200 characters.` : "Preserve the required [ANSWER]...[/ANSWER] answer format.";
  return `${text}\n\n${format}\nSolve the task and submit your completed answer using submit. Search and filesystem tools are unavailable.`;
}
export function fixedScientificPlan(root: string, campaign: string, profile: string, selected: string[]) {
  if (!/^repair-[0-9TZ-]+$/.test(campaign) || !["full", "chemiq-calibration"].includes(profile) || !selected.length || new Set(selected).size !== selected.length || selected.some(s => !(s in SCIENCE_PORTS))) throw new Error("Invalid prospective scientific plan");
  if (profile === "chemiq-calibration" && selected.join(",") !== "chemiq") throw new Error("ChemIQ calibration has exactly one benchmark");
  const catalogs: Record<string, PublicTask[]> = {}, datasets: Record<string, unknown> = {};
  let calibration: Record<string, unknown> | undefined;
  for (const slug of selected) {
    let tasks: PublicTask[];
    if (slug !== "chemiq") {
      const pin = pins[slug as keyof typeof pins], path = join(root, "docs/repair-2026-10-08/campaigns", catalogRun, `${slug}-public-tasks.json`), raw = readFileSync(path);
      if (digest(raw) !== pin.sha) throw new Error(`Pinned public catalog changed: ${slug}`);
      tasks = JSON.parse(raw.toString("utf8"));
      if (tasks.length !== pin.count) throw new Error("Full denominator changed");
      datasets[slug] = { catalogPath: path, catalogSha256: pin.sha, origin: "Fixed public catalog frozen before the prior generation, reused in full without inspecting prior answers or outcomes" };
    } else {
      const path = join(root, ".phase1-data/chemiq/vendor/ChemIQ/questions/chemiq.jsonl"), raw = readFileSync(path);
      if (digest(raw) !== chemiqSha) throw new Error("Fixed ChemIQ book changed");
      // Project only published problem fields and category/method metadata; no answers/GT enter the plan.
      const rows = raw.toString("utf8").trim().split(/\r?\n/).map(line => {
        const input = JSON.parse(line);
        const row = Object.fromEntries(["uuid", "question_category", "sub_category", "answer_format", "prompt"].filter(k => k in input).map(k => [k, input[k]]));
        return { row: { ...row, id: `chemiq-${input.uuid}` }, method: String(input.verification_method) };
      });
      if (rows.length !== 816 || new Set(rows.map(r => r.row.id)).size !== 816) throw new Error("ChemIQ original denominator changed");
      const categories = [...new Set(rows.map(r => String(r.row.question_category)))].sort(), methods = [...new Set(rows.map(r => r.method))].sort();
      if (categories.length !== 8 || methods.length !== 5) throw new Error("ChemIQ class/method inventory changed");
      const subset = profile === "full" ? rows : categories.flatMap(category => {
        const group = rows.filter(r => r.row.question_category === category).sort((a, b) => String(a.row.id).localeCompare(String(b.row.id), "en"));
        const first = group[0], second = group.find(r => r.method !== first.method) ?? group.find(r => r.row.sub_category !== first.row.sub_category) ?? group[1];
        if (!second || second === first) throw new Error("Cannot fix two different calibration IDs per class");
        return [first, second];
      });
      if (profile === "chemiq-calibration" && (subset.length !== 16 || new Set(subset.map(r => r.method)).size !== 5)) throw new Error("Calibration method coverage incomplete");
      tasks = subset.map(({ row }) => ({ row, officialId: String(row.id), promptSha256: digest(scientificPrompt(slug, row)) }));
      calibration = { selectionRule: "Sort eight category names and UUIDs; choose first UUID, then first distinct method, otherwise distinct subcategory, otherwise second UUID. Only category/method/ID metadata; no answers, generations or positive-control outcomes.",
        originalQuestions: 816, prospectiveFullRuns: 1632, selected: subset.map(r => ({ id: r.row.id, category: r.row.question_category, method: r.method })),
        categories, methods, positiveReferenceControlsMissing: 34, referenceControlGapDoesNotRemoveDenominator: true,
        graderProfile: "Provisional revised localOPSIN2.8 + raw-input-length; old unknown REST equivalence is not certified" };
      datasets[slug] = { bookPath: path, bookSha256: chemiqSha, originalQuestions: 816, referenceAnswersArchived: false };
    }
    for (const task of tasks) if (!task.officialId || task.promptSha256 !== digest(scientificPrompt(slug, task.row))) throw new Error(`Public prompt digest mismatch: ${slug}`);
    if (new Set(tasks.map(t => t.officialId)).size !== tasks.length) throw new Error("Duplicate official task ID");
    catalogs[slug] = tasks;
    datasets[slug] = { ...(datasets[slug] as object), source: JSON.parse(readFileSync(join(root, `.phase1-data/${slug}/source.json`), "utf8")), selectedTaskIds: tasks.map(t => t.officialId), publicTaskDigest: digest(JSON.stringify(tasks)) };
  }
  const tasks = roundRobinBenchmarks(selected.flatMap(benchmark => catalogs[benchmark].flatMap(task => (["U", "F"] as const).map(arm => ({ ...task, benchmark, arm, replica: 0 as const, prompt: scientificPrompt(benchmark, task.row), seconds: benchmark === "cmt" ? 1800 : 600 })))), selected)
    .map((task, index) => ({ ...task, index, route: `${campaign}/${task.benchmark}/${task.arm}/0/${encodeURIComponent(task.officialId)}`, taskId: `${campaign}/${task.benchmark}/${task.arm}0/${task.officialId}` }));
  const taskSchedule = tasks.map(({ index, benchmark, arm, replica, officialId, promptSha256 }) => ({ index, benchmark, arm, replica, officialId, promptSha256 }));
  return { tasks, catalogs, datasets, calibration, taskSchedule, taskScheduleSha256: digest(JSON.stringify(taskSchedule)), fullScientificRuns: 1220 };
}
