/** GET-only SkillsBench resource snapshot. Never calls a model or takes a lock. */
import { randomBytes } from 'node:crypto';
import { closeSync, fsyncSync, mkdirSync, openSync, readFileSync, writeFileSync } from 'node:fs';
import { join, resolve } from 'node:path';
import { actualPin, demand, type Pin } from './paid-resource-proof-v2.ts';

const root = resolve(import.meta.dir, '../..');
const home = join(root, 'docs/repair-2026-10-08/skillsbench-ten-takeover-v1/resource-observations', randomBytes(12).toString('hex'));
mkdirSync(home, { recursive: true });
function save(name: string, value: string | object): Pin {
  const path = join(home, name), raw = Buffer.from(typeof value === 'string' ? value : JSON.stringify(value, null, 2) + '\n');
  const fd = openSync(path, 'wx', 0o600);
  try { writeFileSync(fd, raw); fsyncSync(fd); } finally { closeSync(fd); }
  demand(readFileSync(path).equals(raw), 'skb_readonly_resource_readback'); return actualPin(path);
}

const balance: any = { protocol: 'deepseek-resource-readonly-v1', provider: 'https://api.deepseek.com', endpoint: '/user/balance', method: 'GET',
  officialDocumentation: 'https://api-docs.deepseek.com/api/get-user-balance/', sourcePin: actualPin(import.meta.path),
  modelCalls: 0, credentialPrinted: false, scope: 'SkillsBench current balance; does not settle original four missing receipts' };
try {
  const key = process.env.DEEPSEEK_API_KEY;
  demand(typeof key === 'string' && key.length > 0, 'skb_project_credential_absent');
  const response = await fetch('https://api.deepseek.com/user/balance', { headers: { Authorization: 'Bearer ' + key }, signal: AbortSignal.timeout(20000) });
  balance.httpStatus = response.status;
  if (response.status === 200) {
    const body = await response.json();
    balance.rawResponsePin = save('balance-response.json', JSON.stringify(body) + '\n');
    balance.isAvailable = body.is_available;
    demand(Array.isArray(body.balance_infos), 'skb_balance_rows_absent');
    balance.balances = body.balance_infos.map((item: any) => {
      demand(['CNY', 'USD'].includes(item.currency), 'skb_balance_currency_unknown');
      const row: any = { currency: item.currency };
      for (const field of ['total_balance', 'granted_balance', 'topped_up_balance']) {
        demand(typeof item[field] === 'string' && /^\d+(?:\.\d+)?$/.test(item[field]) && Number.isFinite(Number(item[field])), 'skb_balance_field');
        row[field] = item[field];
      }
      return row;
    });
  } else balance.error = 'balance_endpoint_non_success';
} catch (error) { balance.error = error instanceof Error ? error.name : 'ResourceObservationError'; }
balance.observedAtUtc = new Date().toISOString();
const balancePin = save('balance.json', balance);

const url = 'https://api-docs.deepseek.com/zh-cn/quick_start/pricing/';
const price: any = { protocol: 'deepseek-cny-pricing-source-snapshot-v1', officialSource: url,
  sourcePin: actualPin(import.meta.path), model: 'deepseek-flash', advertisedModelVersion: 'DeepSeek-V4.1-Flash',
  currency: 'CNY', unit: 'per million tokens', peak: { uncachedInput: 2, cachedInput: .04, output: 8 },
  offPeak: { uncachedInput: 1, cachedInput: .02, output: 4 },
  officialTimeRule: 'Asia/Shanghai weekdays excluding Chinese statutory holidays:09:00-12:00,14:00-18:00 peak; other times off-peak',
  prospectiveConservativeTimeRule: 'Use weekday peak windows conservatively, including holidays; pending/unknown uses peak rates',
  retrieval: 'Actual GET of official pricing HTML; published table separately verified with web open',
  modelCalls: 0, invoiceRecovered: false, historicalUnknownUsageRecovered: false, historicalUsdPriceSnapshotModified: false };
try {
  const response = await fetch(url, { signal: AbortSignal.timeout(20000) });
  price.httpStatus = response.status;
  demand(response.status === 200, 'skb_price_http_status');
  const raw = await response.text(); demand(Buffer.byteLength(raw) <= 2*1024**2, 'skb_price_document_cap');
  price.rawHtmlPin = save('official-pricing.html', raw);
  const text = raw.replace(/<script\b[\s\S]*?<\/script>/gi, '').replace(/<style\b[\s\S]*?<\/style>/gi, '').replace(/<[^>]+>/g, ' ').replace(/\s+/g, ' ');
  demand(text.includes('deepseek-flash') && text.includes('DeepSeek-V4.1-Flash') && ['0.02', '0.04', '1元', '2元', '4元', '8元'].every(x => text.includes(x)), 'skb_price_document_changed_needs_review');
  price.documentIdentityCheckPassed = true;
} catch (error) { price.error = error instanceof Error ? error.name : 'PriceObservationError'; }
price.observedAtUtc = new Date().toISOString();
const pricePin = save('prices.json', price);
console.log(JSON.stringify({ balancePin, pricePin, balances: balance.balances, httpStatus: balance.httpStatus,
  balanceError: balance.error, priceHttpStatus: price.httpStatus, priceError: price.error,
  modelCalls: 0, credentialPrinted: false, paidLockAcquired: false }));
if (balance.httpStatus !== 200 || balance.isAvailable !== true || balance.error || price.error) process.exitCode = 1;
