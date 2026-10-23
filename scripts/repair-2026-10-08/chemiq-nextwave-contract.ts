import { createHash } from "node:crypto";
import { mkdirSync, readFileSync, writeFileSync } from "node:fs";
import { join } from "node:path";
import { execFileSync } from "node:child_process";

const PROVENANCE_SHA = "ffda1b12d5d0190767a9564229362371277ffd01978ff936cc25efdbd762ca39";
const ARCHIVE_SHA = "7e1f476e9664a747436c17bb2e0506b2e1a3704128e4a07fa00152f30586d18b";
const digest = (path: string) => createHash("sha256").update(readFileSync(path)).digest("hex");
export function loadChemiqProvenance(root: string, store: string) {
  const path = join(root, "docs/repair-2026-10-08/chemiq-nextwave-grader-provenance.json");
  if (digest(path) !== PROVENANCE_SHA) throw new Error("ChemIQ provenance snapshot changed");
  const proof = JSON.parse(readFileSync(path, "utf8"));
  const validate = () => {
    if (digest(path) !== PROVENANCE_SHA || digest(proof.public_archive.path) !== ARCHIVE_SHA) throw new Error("ChemIQ public provenance/archive changed");
    for (const file of proof.public_source_files) if (digest(file.path) !== file.sha256) throw new Error("ChemIQ public grader source changed: " + file.relative_path);
    for (const file of [proof.host_bridge.script, proof.opsin_jar, proof.host_bridge.python_executable, proof.host_bridge.java_executable]) if (digest(file.path) !== file.sha256) throw new Error("ChemIQ actual bridge/runtime dependency changed");
  };
  validate();
  const directory = join(store, "grader-provenance/chemiq"); mkdirSync(directory, { recursive: true });
  const archiveCopy = join(directory, "public-grader-source.zip"), provenanceCopy = join(directory, "provenance.json");
  writeFileSync(archiveCopy, readFileSync(proof.public_archive.path)); writeFileSync(provenanceCopy, readFileSync(path));
  const audit = (stage: string) => {
    validate();
    const expected = proof.actual_grader_container;
    const current = JSON.parse(execFileSync("docker", ["inspect", expected.name], { encoding: "utf8", windowsHide: true, timeout: 30000, maxBuffer: 8 * 1024 * 1024 }))[0];
    if (!current.State.Running || current.Id !== expected.id || current.Image !== expected.image_id) throw new Error("ChemIQ actual container/image changed; declare a new freeze");
    const normalized = (path: string) => path.replaceAll("\\", "/").toLowerCase();
    for (const mount of expected.mounts) {
      const actual = current.Mounts.find((value: { Destination: string }) => value.Destination === mount.destination);
      if (!actual || normalized(actual.Source) !== normalized(mount.source) || actual.RW !== mount.read_write) throw new Error("ChemIQ declared readonly/queue mount changed");
    }
    const script = readFileSync(join(root, "scripts/repair-2026-10-08/chemiq-grader-provenance.py"), "utf8");
    const runtime = JSON.parse(execFileSync("docker", ["exec", "-i", expected.name, "python", "-", "--worker"], { input: script, encoding: "utf8", windowsHide: true, timeout: 120000, maxBuffer: 8 * 1024 * 1024 }));
    const observed = proof.runtime_observed_imports_and_dependencies;
    for (const [name, file] of Object.entries(observed.public_modules) as [string, {sha256:string}][]) if (runtime.public_modules[name]?.sha256 !== file.sha256) throw new Error("ChemIQ actual Python public module changed: " + name);
    for (const dist of observed.distributions) {
      const actual = runtime.distributions.find((value: {name:string}) => value.name === dist.name);
      if (!actual || actual.version !== dist.version || actual.file_manifest_sha256 !== dist.file_manifest_sha256 || actual.files.length !== dist.files.length) throw new Error("ChemIQ actual Python dependency digest changed: " + dist.name);
    }
    if (runtime.python_executable.sha256 !== observed.python_executable.sha256 || runtime.daemon_executable !== observed.daemon_executable) throw new Error("ChemIQ actual Python interpreter changed");
    const record = { stage, observedAt: runtime.observed_at_utc, valid: true, provenanceSha256: PROVENANCE_SHA, containerId: current.Id, imageId: current.Image,
      mounts: expected.mounts, pythonVersion: runtime.python_version, publicModules: Object.fromEntries(Object.entries(runtime.public_modules).map(([name, file]) => [name, (file as {sha256:string}).sha256])),
      dependencyDigests: runtime.distributions.map((dist: {name:string;version:string;file_manifest_sha256:string;files:unknown[]}) => ({name:dist.name,version:dist.version,sha256:dist.file_manifest_sha256,files:dist.files.length})), modelCalls: 0 };
    writeFileSync(join(directory, stage + "-runtime-audit.json"), JSON.stringify(record, null, 2) + "\n");
    return record;
  };
  return { validate, audit, metadata: { path, sha256: PROVENANCE_SHA, publicArchive: { path: proof.public_archive.path, sha256: ARCHIVE_SHA, runCopy: archiveCopy }, runProvenanceCopy: provenanceCopy,
    actualGraderContainer: { id: proof.actual_grader_container.id, imageId: proof.actual_grader_container.image_id },
    profile: proof.profile, completeGradingCodeScope: proof.complete_grading_code_scope, limits: proof.limits } };
}
