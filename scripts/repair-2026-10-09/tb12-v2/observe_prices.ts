/** Fresh public official tariff observation; no provider credential or model. */
import { mkdirSync, writeFileSync } from "node:fs";
import { dirname, resolve, join } from "node:path";
import { parseChemiqOfficialFlashPricing, CHEMIQ_OFFICIAL_PRICE_URL } from "../../repair-2026-10-08/chemiq-official-price-v2.ts";
import { actualPin, hash } from "../../repair-2026-10-08/paid-resource-proof-v2.ts";
const root = resolve(import.meta.dir, "../../..");
const output = resolve(process.argv[2]);
if (!output.startsWith(join(root,"docs/repair-2026-10-09/tb12-preparation-v1")+"\\")) throw Error("TB price output scope");
mkdirSync(output,{recursive:true});
const response = await fetch(CHEMIQ_OFFICIAL_PRICE_URL,{signal:AbortSignal.timeout(30000)});
const raw = Buffer.from(await response.arrayBuffer());
if (!response.ok || raw.length > 2*1024**2) throw Error("Actual official tariff GET failed");
const html = new TextDecoder("utf-8",{fatal:true}).decode(raw);
const parsed = parseChemiqOfficialFlashPricing(html);
writeFileSync(join(output,"official-price.html"),raw,{flag:"wx"});
const snapshot = {
  protocol:"deepseek-cny-pricing-source-snapshot-v1", model:parsed.model,currency:"CNY",
  officialSource:CHEMIQ_OFFICIAL_PRICE_URL,observedAtUtc:new Date().toISOString(),
  peak:parsed.peak,offPeak:parsed.offPeak,modelCalls:0,
  advertisedModelVersion:parsed.advertisedModelVersion,actualOfficialGET:true,
  originalHtml:actualPin(join(output,"official-price.html")),
  parserSource:actualPin(join(root,"scripts/repair-2026-10-08/chemiq-official-price-v2.ts")),
  source:actualPin(import.meta.path),timeRuleVerified:parsed.timeRuleVerified,
  officialTimeRule:parsed.officialTimeRule,tariffValuesParsedFromResponse:true,
  responseSha256:hash(raw),invoice:false,foreignExchangeConversion:false,
};
writeFileSync(join(output,"prices.json"),JSON.stringify(snapshot,null,2)+"\n",{flag:"wx"});
console.log(JSON.stringify({path:join(output,"prices.json"),actualOfficialGET:true,modelCalls:0}));
