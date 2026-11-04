import { expect, test } from 'bun:test';
import { readFileSync } from 'node:fs';
import { join } from 'node:path';
import { parseChemiqOfficialFlashPricing } from '../../scripts/benchmark-repair/chemiq-official-price-v2.ts';
const html=readFileSync(join(import.meta.dir,'../fixtures/pricing/flash-table.html'),'utf8');
test('the synthetic merged-cell table binds all six Flash prices and the actual Beijing time rule',()=>{
  const parsed=parseChemiqOfficialFlashPricing(html);
  expect(parsed.peak).toEqual({uncachedInput:2,cachedInput:0.04,output:8});
  expect(parsed.offPeak).toEqual({uncachedInput:1,cachedInput:0.02,output:4});
  expect(parsed.currency).toBe('CNY');expect(parsed.unit).toBe('per million tokens');
  expect(parsed.observedTariffs).toHaveLength(6);expect(parsed.observedTimeRuleText).toContain('9:00 - 12:00、14:00 - 18:00');
  expect(parsed.advertisedModelVersion).toBe('DeepSeek-V4.1-Flash');
});
test('changed prices, units, currency, model columns or official time rules cannot renew the frozen tariff',()=>{
  const mutations=[
    html.replace('>2元<','>3元<'),
    html.replace('>0.02元<','>0.03元<'),
    html.replace('>0.04元<','>0.04 USD<'),
    html.replaceAll('百万tokens','千tokens'),
    html.replace('deepseek-flash<sup>(1)</sup>','deepseek-v4-pro<sup>(1)</sup>'),
    html.replace('9:00 - 12:00','8:00 - 12:00'),
    html.replace('不含中国法定节假日','含中国法定节假日'),
    html.replace('DeepSeek-V4.1-Flash','DeepSeek-V5-Flash'),
  ];
  for(const changed of mutations){expect(changed!==html).toBe(true);expect(()=>parseChemiqOfficialFlashPricing(changed)).toThrow();}
});
