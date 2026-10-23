/** Read-only reuse of the verified historical financial boundary and scanners. */
import { writeFileSync, mkdirSync } from "node:fs";
import { resolve, dirname, join } from "node:path";
import { prospectiveJpgFinancialPreflight } from "../../repair-2026-10-08/jpg-financial-abort-scanner-v1.ts";
import { ACTUAL_FINANCIAL_INTERRUPTED_BOUNDARY } from "../../repair-2026-10-08/financial-interruption-closure-v1.ts";
const root = resolve(import.meta.dir, "../../..");
const output = resolve(process.argv[2] ?? "");
const allowed = join(root, "docs/repair-2026-10-09/tb12-preparation-v1");
if (!output.startsWith(allowed + "\\")) throw new Error("TB preflight output scope");
const runId = "repair-" + new Date().toISOString().replace(/[:.]/g, "-");
mkdirSync(dirname(output), { recursive: true });
try {
  const result = await prospectiveJpgFinancialPreflight(root, runId, ACTUAL_FINANCIAL_INTERRUPTED_BOUNDARY);
  writeFileSync(output, JSON.stringify({
    protocol: "tb12-readonly-cross-family-preflight-v1", observedAtUtc: new Date().toISOString(),
    passed: true, underlyingReadOnlyResult: result, familyAdmissionAuthorized: false,
    canonicalWxRequired: true, ownTypedRegistryRequired: true, modelCalls: 0, lockMutations: 0,
  }, null, 2) + "\n");
  console.log(JSON.stringify({ output, passed: true, modelCalls: 0 }));
} catch (error) {
  writeFileSync(output, JSON.stringify({
    protocol: "tb12-readonly-cross-family-preflight-v1", observedAtUtc: new Date().toISOString(),
    passed: false, error: error instanceof Error ? {name:error.name,message:error.message,stack:error.stack}:String(error),
    familyAdmissionAuthorized: false, modelCalls: 0, lockMutations: 0,
  }, null, 2) + "\n");
  console.log(JSON.stringify({ output, passed: false, modelCalls: 0 }));
  process.exitCode = 2;
}
