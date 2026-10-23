/** GET-only account/model observation. Never submits a completion or archives credentials. */
import { createHash } from 'node:crypto';
import { closeSync, fsyncSync, mkdirSync, openSync, readFileSync, writeFileSync } from 'node:fs';
import { join, resolve } from 'node:path';
import { CHEMIQ_OFFICIAL_PRICE_URL, parseChemiqOfficialFlashPricing } from './chemiq-official-price-v2.ts';
const root = resolve(import.meta.dir, '../..');
const sha = (raw: Uint8Array | string) => createHash('sha256').update(raw).digest('hex');
const key = process.env.DEEPSEEK_API_KEY;
if (!key || key.length < 16) throw Error('Configured DEEPSEEK_API_KEY unavailable');
const directory = join(root, 'docs/repair-2026-10-08/chemiq-f-journal-implementation-v2/observations');
mkdirSync(directory, { recursive: true });
const observation = 'provider-' + new Date().toISOString().replace(/[:.]/g, '-');
for (const endpoint of ['/user/balance', '/models']) {
  const startedAtUtc = new Date().toISOString();
  let record: any;
  try {
    const response = await fetch('https://api.deepseek.com' + endpoint, { method: 'GET', headers: { authorization: 'Bearer ' + key }, signal: AbortSignal.timeout(30000) });
    const raw = await response.text();
    if (raw.includes(key)) throw Error('Provider response contained credential; not archived');
    const payload = JSON.parse(raw);
    record = { protocol: endpoint === '/user/balance' ? 'deepseek-resource-readonly-v1' : 'chemiq-provider-models-readonly-v2',
      provider: 'https://api.deepseek.com', endpoint, method: 'GET', modelCalls: 0, credentialPrinted: false, headersArchived: false,
      sourceScriptSha256: sha(readFileSync(import.meta.path)), startedAtUtc, observedAtUtc: new Date().toISOString(), httpStatus: response.status,
      ...(endpoint === '/user/balance' ? { isAvailable: payload.is_available, balances: payload.balance_infos } : { data: payload.data }), responseRawSha256: sha(raw) };
  } catch (error) {
    record = { protocol: 'chemiq-provider-readonly-failure-v2', endpoint, method: 'GET', modelCalls: 0, credentialPrinted: false,
      startedAtUtc, observedAtUtc: new Date().toISOString(), error: error instanceof Error ? error.name + ':' + error.message.replaceAll(key, '[redacted]') : 'request_failure' };
  }
  const path = join(directory, observation + (endpoint === '/models' ? '-models.json' : '-balance.json'));
  const bytes = Buffer.from(JSON.stringify(record, null, 2) + '\n'), fd = openSync(path, 'wx', 0o600);
  try { writeFileSync(fd, bytes); fsyncSync(fd); } finally { closeSync(fd); }
  if (!readFileSync(path).equals(bytes)) throw Error('Read-only observation readback mismatch');
  console.log(JSON.stringify({ path, bytes: bytes.length, sha256: sha(bytes), endpoint, httpStatus: record.httpStatus ?? null,
    balances: record.balances, requestedModelListed: record.data?.some((r: any) => r.id === 'deepseek-flash'), error: record.error ?? null }));
}
const officialSource=CHEMIQ_OFFICIAL_PRICE_URL;
const response=await fetch(officialSource,{method:'GET',signal:AbortSignal.timeout(30000)});
if(!response.ok)throw Error('Official price GET failed:'+response.status);
const html=await response.text();
if(html.includes(key))throw Error('Official price response contained credential; not archived');
const parsed=parseChemiqOfficialFlashPricing(html);
const officialPath=join(directory,observation+'-official-pricing.html'),officialBytes=Buffer.from(html,'utf8'),officialFd=openSync(officialPath,'wx',0o600);
try{writeFileSync(officialFd,officialBytes);fsyncSync(officialFd);}finally{closeSync(officialFd);}
if(!readFileSync(officialPath).equals(officialBytes))throw Error('Official price readback mismatch');
const parserPath=join(import.meta.dir,'chemiq-official-price-v2.ts');
const prices={protocol:'deepseek-cny-pricing-source-snapshot-v1',...parsed,observedAtUtc:new Date().toISOString(),officialSource,method:'GET',
  retrieval:'Fresh unauthenticated official GET; six Flash tariffs, CNY, per-million-token units and exact official time rule parsed from the pinned response',
  sourceScriptSha256:sha(readFileSync(import.meta.path)),officialResponseSha256:sha(html),officialHttpStatus:response.status,
  officialResponsePin:{path:officialPath,bytes:officialBytes.length,sha256:sha(officialBytes)},priceParserSourcePin:{path:parserPath,bytes:readFileSync(parserPath).length,sha256:sha(readFileSync(parserPath))},
  prospectiveConservativeTimeRule:'Treat every weekday as potentially peak, including holidays; use the higher rate of all time windows crossed by a fully captured request. Pending/unknown transport uses peak reservation. Clock inconsistencies stop admission.',
  historicalUsdPriceSnapshotModified:false,invoiceRecovered:false,historicalUnknownUsageRecovered:false,credentialPrinted:false,modelCalls:0};
const pricePath=join(directory,observation+'-prices.json'),priceBytes=Buffer.from(JSON.stringify(prices,null,2)+'\n'),priceFd=openSync(pricePath,'wx',0o600);
try{writeFileSync(priceFd,priceBytes);fsyncSync(priceFd);}finally{closeSync(priceFd);}
console.log(JSON.stringify({path:pricePath,bytes:priceBytes.length,sha256:sha(priceBytes),endpoint:officialSource,httpStatus:response.status,modelCalls:0}));
