/** Original 16k budget and sampling settings; medium's DeepSeek alias is made explicit as high. */
import { BENCHMARK_PROVIDER, type BenchmarkProvider } from "./digitalocean-provider.ts";
export const BENCHMARK_INFERENCE = Object.freeze({
  maxTokens: 16384, reasoningEffort: "high", temperature: 0, seed: 42,
  retryTimes: 3, continueTimes: 3,
});
export type BenchmarkInference = Readonly<{
  maxTokens: number; reasoningEffort: string; temperature: number; seed: number;
  retryTimes: number; continueTimes: number;
}>;

/** OpenRouter keeps thinking on through submission; archived direct controls retain their wire contract. */
export function benchmarkProviderRequest(body: Record<string, any>, profile: BenchmarkInference = BENCHMARK_INFERENCE, provider?: BenchmarkProvider) {
  const choice = body.tool_choice;
  const forced = choice === "required" || choice?.type === "function" && typeof choice.function?.name === "string";
  const effort = provider ? profile.reasoningEffort : forced ? "none" : profile.reasoningEffort;
  const thinking = forced ? "disabled" : "enabled";
  const limits = [body.max_tokens, body.max_completion_tokens].filter(value => value !== undefined && value !== null);
  if (body.temperature !== profile.temperature || (body.seed !== profile.seed && !(provider && body.seed === undefined)) || body.reasoning_effort !== effort ||
      !limits.length || limits.some(value => value !== profile.maxTokens) ||
      body.thinking !== undefined && body.thinking?.type !== (provider ? "enabled" : thinking)) {
    throw new Error("Wire parameters differ from the benchmark inference profile");
  }
  const wire: Record<string, any> = { ...body, thinking: { type: thinking }, max_tokens: profile.maxTokens };
  delete wire.max_completion_tokens;
  if (provider) {
    if (body.model !== provider.model || profile.reasoningEffort !== "high") throw Error("OpenRouter V4.1 Flash high-thinking profile required");
    if (forced) {
      const name = choice?.function?.name;
      if (typeof name !== "string") throw Error("Constrained auto submission requires a named tool");
      wire.tools = (body.tools ?? []).filter((tool: any) => tool.type === "function" && tool.function?.name === name);
      if (wire.tools.length !== 1) throw Error("The required submit tool is absent or duplicated");
      wire.tool_choice = "auto";
    }
    wire.provider = { ...provider.routing };
    wire.reasoning = { enabled: true, effort: "high", exclude: false };
    delete wire.thinking;
    delete wire.reasoning_effort;
    // This endpoint does not advertise seed support; capture the true wire shape.
    delete wire.seed;
  }
  return wire;
}
