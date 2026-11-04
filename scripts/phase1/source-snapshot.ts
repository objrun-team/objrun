import { createHash } from "node:crypto";
import { execFileSync } from "node:child_process";
import { mkdirSync, readdirSync, readFileSync, writeFileSync } from "node:fs";
import { dirname, join, relative, resolve } from "node:path";

const root = resolve(import.meta.dir, "../..");
const output = resolve(root, process.argv[2] ?? ".scratch/phase1/source-baseline.json");
const benchNames = ["_lib", "aime", "gpqa", "chembench", "chemiq", "cmt", "minif2f", "deepswe", "terminal-bench", "skillsbench", "scicode", "scibench", "scienceagentbench", "atomworld", "astrovisbench", "llm-srbench", "biocoder", "atmossci-bench", "lab-bench", "scienceworld", "putnambench", "humaneval-plus"];
const files: { path: string; sha256: string; bytes: number }[] = [];
function walk(dir: string) {
  let entries;
  try { entries = readdirSync(dir, { withFileTypes: true }); } catch { return; }
  for (const entry of entries) {
    if (["node_modules", "__pycache__", ".git", ".venv", "data", "outputs", "vendor"].includes(entry.name) || entry.name.includes("export")) continue;
    const path = join(dir, entry.name);
    if (entry.isDirectory()) walk(path);
    else if ((/\.(ts|py|json|yaml|toml|lock|md|sh|txt)$/.test(entry.name) || entry.name === "Dockerfile") && !entry.name.endsWith(".bak")) {
      const bytes = readFileSync(path);
      files.push({ path: relative(root, path).replaceAll("\\", "/"), sha256: createHash("sha256").update(bytes).digest("hex"), bytes: bytes.length });
    }
  }
}
for (const path of ["app/src", "app/scripts", "test", "scripts/phase1", "examples/benchmark/scibench/experiments", ...benchNames.map(name => `examples/benchmark/${name}`)]) walk(join(root, path));
for (const path of ["app/package.json", "app/bun.lock", "app/tsconfig.json", "config.yaml"]) {
  try { const bytes = readFileSync(join(root, path)); files.push({ path, sha256: createHash("sha256").update(bytes).digest("hex"), bytes: bytes.length }); } catch {}
}
files.sort((a, b) => a.path.localeCompare(b.path));
const git = (...args: string[]) => execFileSync("git", ["-c", `safe.directory=${root.replaceAll("\\", "/")}`, ...args], { cwd: root, encoding: "utf8" }).trim();
const snapshot = { schemaVersion: 1, createdAt: new Date().toISOString(), head: git("rev-parse", "HEAD"), provenance: "Current working-tree snapshot; this does not establish the source version used by historical runs.", sourceDigest: createHash("sha256").update(JSON.stringify(files)).digest("hex"), gitStatus: git("status", "--porcelain"), files };
mkdirSync(dirname(output), { recursive: true });
writeFileSync(output, JSON.stringify(snapshot, null, 2) + "\n");
console.log(JSON.stringify({ output, head: snapshot.head, files: files.length, sourceDigest: snapshot.sourceDigest }));
