/** The provider used by new Bench runs. Historical direct-API receipts keep their own protocol. */
import { readFileSync, mkdirSync, writeFileSync } from "node:fs";
import { join, resolve } from "node:path";
import { createHash } from "node:crypto";

export const BENCHMARK_PROVIDER = Object.freeze({
  kind: "openrouter-deepseek" as const,
  model: "deepseek/deepseek-v4.1-flash",
  canonicalModel: "deepseek/deepseek-v4.1-flash-20260910",
  baseURL: "https://openrouter.ai/api/v1",
  endpoint: "https://openrouter.ai/api/v1/chat/completions",
  keyEnv: "OPENROUTER_API_KEY", currency: "USD" as const,
  providerName: "DigitalOcean", providerSlug: "digitalocean",
  peakRates: Object.freeze({ input: 0.3, cachedInput: 0.006, output: 1.2 }),
  routing: Object.freeze({ only: ["digitalocean"], allow_fallbacks: false, max_price: { prompt: 0.3, completion: 1.2 } }),
  forcedToolMode: "constrained-auto" as const,
});
export type BenchmarkProvider = typeof BENCHMARK_PROVIDER;

/** No credentials are copied to manifests, source snapshots, or child engines. */
export function benchmarkProviderKey(root: string): string {
  const supplied = process.env.OPENROUTER_API_KEY?.trim();
  if (supplied) return supplied;
  for (const path of [join(root, ".env")]) {
    let text: string;
    try { text = readFileSync(path, "utf8").replace(/^\uFEFF/, ""); } catch { continue; }
    for (const line of text.split(/\r?\n/)) {
      const match = line.match(/^\s*(?:export\s+)?OPENROUTER_API_KEY\s*=\s*(.*?)\s*$/);
      if (!match) continue;
      const value = match[1]!.replace(/^(['"])(.*)\1$/, "$2").trim();
      if (value) return value;
    }
  }
  throw new Error("OPENROUTER_API_KEY is missing in the process environment or the inner TgEngin/.env");
}

export function benchmarkFetch(raw: string, key: string): Promise<Response> {
  const body = JSON.parse(raw);
  if (body.model !== BENCHMARK_PROVIDER.model || JSON.stringify(body.provider?.only) !== JSON.stringify(BENCHMARK_PROVIDER.routing.only) || body.provider?.allow_fallbacks !== false)
    throw new Error("The pinned OpenRouter provider route is required before dispatch");
  return fetch(BENCHMARK_PROVIDER.endpoint, { method: "POST", headers: {
    "content-type": "application/json", authorization: "Bearer " + key,
    "X-OpenRouter-Title": "TgEngin Bench",
  }, body: raw, signal: AbortSignal.timeout(600000) });
}

export function officialOpenRouterFault(data: any, expectedProvider: string = BENCHMARK_PROVIDER.providerName): string | undefined {
  if (data?.provider !== expectedProvider) return "UnexpectedOpenRouterProvider";
  if (![BENCHMARK_PROVIDER.model, BENCHMARK_PROVIDER.canonicalModel].includes(data?.model)) return "UnexpectedOpenRouterModel";
  if (typeof data?.id !== "string" || !data.id) return "MissingOpenRouterGenerationId";
  const cost = data?.usage?.cost;
  if (typeof cost !== "number" || !Number.isFinite(cost) || cost < 0) return "MissingOrInvalidOpenRouterUsdCost";
}

/** An explicitly rejected shared-pool request has no generation or billable token usage. */
export function openRouterRateLimitRejection(data: any, status: number | undefined, providerName: string) {
  return status === 429 && data?.error?.code === 429 && data.error.metadata?.limit_source === 'upstream_provider_shared_pool'
    && data.error.metadata.provider_name === providerName && typeof data.error.metadata.raw === 'string'
    && data.error.metadata.raw.includes('temporarily rate-limited upstream') && !data.id && !data.usage && !data.choices;
}

export type ProviderPin = { path: string; bytes: number; sha256: string };
function pin(path: string): ProviderPin {
  const raw = readFileSync(path); return { path: resolve(path), bytes: raw.length, sha256: createHash("sha256").update(raw).digest("hex") };
}
function save(path: string, value: unknown) { writeFileSync(path, JSON.stringify(value, null, 2) + "\n", { flag: "wx" }); return pin(path); }
async function readOnlyFetch(url: string, headers?: Record<string, string>) {
  let failure: unknown;
  for (let attempt = 0; attempt < 3; attempt++) {
    try {
      const response = await fetch(url, { headers, signal: AbortSignal.timeout(30000) });
      if (response.status < 500 || attempt === 2) return response;
      await response.body?.cancel();
    } catch (error) { failure = error; if (attempt === 2) throw error; }
    await new Promise(resolve => setTimeout(resolve, 250 * (attempt + 1)));
  }
  throw failure;
}

/** A real public GET snapshot, not a price inferred from the old CNY account. */
export async function observeBenchmarkPrices(directory: string): Promise<ProviderPin> {
  mkdirSync(directory, { recursive: true });
  const url = `https://openrouter.ai/api/v1/models/${BENCHMARK_PROVIDER.model}/endpoints`;
  const response = await readOnlyFetch(url);
  const raw = Buffer.from(await response.arrayBuffer());
  if (!response.ok || raw.length > 4 * 1024 ** 2) throw new Error("OpenRouter endpoint tariff observation failed");
  const data = JSON.parse(raw.toString("utf8"));
  const endpoint = data.data?.endpoints?.find((row: any) => row.provider_name === BENCHMARK_PROVIDER.providerName && row.tag === BENCHMARK_PROVIDER.providerSlug);
  if (!endpoint) throw new Error("The model has no endpoint for the pinned provider");
  const prices = [endpoint.pricing, ...(endpoint.pricing?.overrides ?? [])];
  const peak = {
    input: Math.max(...prices.map((p: any) => Number(p.prompt ?? endpoint.pricing.prompt))) * 1e6,
    cachedInput: Math.max(...prices.map((p: any) => Number(p.input_cache_read ?? endpoint.pricing.input_cache_read))) * 1e6,
    output: Math.max(...prices.map((p: any) => Number(p.completion ?? endpoint.pricing.completion))) * 1e6,
  };
  for (const name of ["input", "cachedInput", "output"] as const)
    if (!Number.isFinite(peak[name]) || peak[name] < 0 || peak[name] > BENCHMARK_PROVIDER.peakRates[name] + 1e-12)
      throw new Error("Official OpenRouter tariff exceeds the configured reservation ceiling");
  const rawPath = join(directory, "openrouter-endpoints.json"); writeFileSync(rawPath, raw, { flag: "wx" });
  return save(join(directory, "openrouter-prices.json"), { protocol: "openrouter-usd-pricing-source-snapshot-v1",
    model: BENCHMARK_PROVIDER.model, canonicalModel: BENCHMARK_PROVIDER.canonicalModel, currency: "USD",
    providerName: BENCHMARK_PROVIDER.providerName, providerSlug: BENCHMARK_PROVIDER.providerSlug, quantization: endpoint.quantization,
    officialSource: url, originalResponsePin: pin(rawPath),
    observedAtUtc: new Date().toISOString(), peakRates: peak, reservationRates: BENCHMARK_PROVIDER.peakRates,
    modelCalls: 0, invoice: false, foreignExchangeConversion: false, actualOfficialGET: true,
    supportsToolChoice: endpoint.supports_tool_choice, supportedParameters: endpoint.supported_parameters });
}

export async function observeBenchmarkBalance(directory: string, key: string): Promise<ProviderPin> {
  mkdirSync(directory, { recursive: true });
  const response = await readOnlyFetch("https://openrouter.ai/api/v1/credits", { authorization: "Bearer " + key });
  const body = await response.json() as any;
  if (!response.ok || !Number.isFinite(body.data?.total_credits) || !Number.isFinite(body.data?.total_usage))
    throw new Error("OpenRouter USD credits observation failed");
  const remainingUsd = body.data.total_credits - body.data.total_usage;
  if (!Number.isFinite(remainingUsd) || remainingUsd < 0) throw new Error("Invalid OpenRouter credit balance");
  return save(join(directory, "openrouter-balance.json"), { protocol: "openrouter-usd-balance-readonly-v1",
    provider: "https://openrouter.ai", endpoint: "/api/v1/credits", method: "GET", httpStatus: response.status,
    observedAtUtc: new Date().toISOString(), currency: "USD", remainingUsd,
    modelCalls: 0, credentialPrinted: false, invoice: false, foreignExchangeConversion: false });
}
