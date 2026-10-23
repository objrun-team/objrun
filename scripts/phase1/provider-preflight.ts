import { mkdirSync, writeFileSync } from "node:fs";
import { dirname, resolve } from "node:path";

const key = process.env.DEEPSEEK_API_KEY;
const root = resolve(import.meta.dir, "../..");
const output = resolve(root, process.argv[2] ?? "docs/phase1/provider-preflight.json");
const report: Record<string, unknown> = { checkedAt: new Date().toISOString(), provider: "deepseek", keyPresent: Boolean(key?.trim()), userPilotBudgetUsd: 30, models: [], status: "unverified" };
if (!key?.trim()) report.status = "missing_credentials";
else {
  try {
    const response = await fetch("https://api.deepseek.com/models", { headers: { Authorization: `Bearer ${key}` }, signal: AbortSignal.timeout(15000) });
    report.httpStatus = response.status;
    if (response.ok) {
      const payload = await response.json() as { data?: { id?: string }[] };
      report.models = (payload.data ?? []).map(model => model.id).filter(Boolean);
      report.status = "authenticated";
    } else report.status = response.status === 401 || response.status === 403 ? "credentials_rejected" : "provider_unavailable";
  } catch {
    report.status = "network_unavailable";
  }
}
mkdirSync(dirname(output), { recursive: true });
writeFileSync(output, JSON.stringify(report, null, 2) + "\n");
console.log(JSON.stringify(report));
process.exitCode = report.status === "authenticated" ? 0 : 1;
