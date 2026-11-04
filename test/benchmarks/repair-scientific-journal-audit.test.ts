import { expect, test } from "bun:test";
import { randomUUID, createHash } from "node:crypto";
import { execFileSync } from "node:child_process";
import { mkdirSync, readFileSync, writeFileSync } from "node:fs";
import { join, resolve } from "node:path";
import { createCampaignJournal } from "../../scripts/benchmark-repair/campaign-journal.ts";

const root = resolve(import.meta.dir, "../.."), directory = join(root, ".scratch/scientific-journal-audit-" + randomUUID());
mkdirSync(directory, { recursive: true });
const sha = (value: string) => createHash("sha256").update(value).digest("hex");
const journal = createCampaignJournal({ directory, campaign: "repair-2026-10-08T00-00-00-000Z", capUsd: 1, priorCampaignCostUpperBoundUsd: .1 });
const admitted = journal.admit({ route: "small-fee", rawRequest: JSON.stringify({ model: "deepseek-flash", max_tokens: 8192, messages: [{ role: "user", content: "public fixture" }] }) });
if (!admitted.admitted) throw new Error("fixture admission failed");
journal.finish({ requestSeq: admitted.requestSeq, providerAttempted: true, httpStatus: 200, rawResponse: JSON.stringify({ id: "local-small-fee", model: "local-fixture", choices: [{ message: { role: "assistant", content: "public synthetic" } }], usage: { prompt_tokens: 10, completion_tokens: 2 } }) });
journal.close();
const original = readFileSync(join(directory, "api-events.jsonl"), "utf8");
function audit(path: string) {
  const code = `import importlib.util,json,pathlib,sys\nspec=importlib.util.spec_from_file_location('fixture_auditor',sys.argv[3]);m=importlib.util.module_from_spec(spec);spec.loader.exec_module(m)\nerrors=[]\ntry:\n offsets,prefix=m.journal_offsets(pathlib.Path(sys.argv[1]),pathlib.Path(sys.argv[2]).read_bytes(),lambda ok,name:errors.append(name) if not ok else None,[sys.argv[4],sys.argv[5]])\nexcept Exception as error:\n errors.append(type(error).__name__+':'+str(error));offsets={};prefix=None\nvalue=json.loads(pathlib.Path(sys.argv[1]).read_bytes().splitlines()[1])\nold=json.dumps(value,separators=(',',':'),ensure_ascii=False).encode()+b'\\n'==pathlib.Path(sys.argv[1]).read_bytes().splitlines(keepends=True)[1]\nprint(json.dumps({'errors':errors,'offsets':offsets,'prefix':prefix,'oldPythonCanonicalAccepted':old}))`;
  return JSON.parse(execFileSync(join(root, ".phase1-data/venv/Scripts/python.exe"), ["-B", "-X", "utf8", "-c", code, path, join(directory, "journal-config.json"), join(root, "scripts/benchmark-repair/audit-scientific-journal.py"), process.execPath, join(root, "scripts/benchmark-repair/audit-journal-canonical.ts")], { windowsHide: true }).toString());
}
test("real Bun small-fee JSON is rejected by Python float reserialization but accepted with exact JS bytes", () => {
  const result = audit(join(directory, "api-events.jsonl"));
  expect(original).toContain('"usdUpperBound":0.0000054');
  expect(result.oldPythonCanonicalAccepted).toBe(false);
  expect(result.errors).toEqual([]);
  expect(result.offsets[0].finishLineSha256).toBe(sha(original.split(/(?<=\n)/)[1]));
  writeFileSync(join(directory, "red-green.json"), JSON.stringify({ ...result, externalModelCalls: 0, source: "actual native Bun journal small usage fixture" }, null, 2));
});
test("duplicate keys, duplicate finish, noncanonical whitespace and truncation remain invalid", () => {
  const lines = original.trimEnd().split("\n"), last = JSON.parse(lines[1]);
  const duplicate = { ...last, eventSeq: 2, previousEventSha256: sha(lines[1] + "\n") };
  const cases = {
    "duplicate-key": original.replace('"eventSeq":0,', '"eventSeq":0,"eventSeq":0,'),
    "duplicate-finish": original + JSON.stringify(duplicate) + "\n",
    "whitespace": original.replace('"kind":"start"', '"kind": "start"'),
    "truncated": original.slice(0, -1),
  };
  const results: Record<string, unknown> = {};
  for (const [name, raw] of Object.entries(cases)) {
    const path = join(directory, name + ".jsonl"); writeFileSync(path, raw);
    const result = audit(path); results[name] = result; expect(result.errors.length).toBeGreaterThan(0);
  }
  writeFileSync(join(directory, "negative-controls.json"), JSON.stringify({ results, externalModelCalls: 0 }, null, 2));
});
