/** Parse the actual public price document; a changed tariff or time rule stops this frozen campaign. */
export const CHEMIQ_OFFICIAL_PRICE_URL = 'https://api-docs.deepseek.com/zh-cn/quick_start/pricing/';
type Cell = { text: string; columns: number; rows: number };
function requirePrice(condition: unknown, reason: string): asserts condition {
  if (!condition) throw Error('chemiq_official_price_' + reason);
}
function text(html: string) {
  return html.replace(/<script\b[\s\S]*?<\/script>/gi, '').replace(/<style\b[\s\S]*?<\/style>/gi, '')
    .replace(/<[^>]*>/g, ' ').replace(/&#x([0-9a-f]+);/gi, (_, n) => String.fromCodePoint(parseInt(n, 16)))
    .replace(/&#([0-9]+);/g, (_, n) => String.fromCodePoint(Number(n)))
    .replace(/&nbsp;/g, ' ').replace(/&quot;/g, '"').replace(/&lt;/g, '<').replace(/&gt;/g, '>').replace(/&amp;/g, '&')
    .replace(/\s+/g, ' ').trim();
}
function span(attributes: string, kind: string) {
  const matches = [...attributes.matchAll(new RegExp('\\b' + kind + '\\s*=\\s*["\']?(\\d+)', 'gi'))];
  requirePrice(matches.length <= 1, 'duplicate_span');
  const size = matches.length ? Number(matches[0][1]) : 1;
  requirePrice(Number.isSafeInteger(size) && size >= 1 && size <= 30, 'invalid_span');
  return size;
}
function grid(table: string) {
  const rows = [...table.matchAll(/<tr\b[^>]*>([\s\S]*?)<\/tr>/gi)].map(row =>
    [...row[1].matchAll(/<(?:td|th)\b([^>]*)>([\s\S]*?)<\/(?:td|th)>/gi)].map(cell =>
      ({ text: text(cell[2]), columns: span(cell[1], 'colspan'), rows: span(cell[1], 'rowspan') } satisfies Cell)));
  const carried = new Map<number, { text: string; remaining: number }>();
  return rows.map(cells => {
    const result: string[] = [];
    for (const [column, cell] of carried) {
      result[column] = cell.text;
      if (--cell.remaining === 0) carried.delete(column);
    }
    let column = 0;
    for (const cell of cells) {
      while (result[column] !== undefined) column++;
      for (let offset = 0; offset < cell.columns; offset++) {
        requirePrice(result[column + offset] === undefined, 'overlapping_span');
        result[column + offset] = cell.text;
        if (cell.rows > 1) carried.set(column + offset, { text: cell.text, remaining: cell.rows - 1 });
      }
      column += cell.columns;
    }
    requirePrice(result.length === 5 && result.every(value => typeof value === 'string'), 'table_columns');
    return result;
  });
}
const compact = (value: string) => value.replace(/\s+/g, '').replaceAll('（', '(').replaceAll('）', ')');
export function parseChemiqOfficialFlashPricing(html: string) {
  const tables = [...html.matchAll(/<table\b[\s\S]*?<\/table>/gi)].map(match => match[0])
    .filter(table => table.includes('deepseek-flash') && table.includes('百万tokens'));
  requirePrice(tables.length === 1, 'unique_table');
  const rows = grid(tables[0]), heading = rows.filter(row => row[0] === '模型');
  requirePrice(heading.length === 1 && /^deepseek-flash(?:\s*\(\d+\))?$/.test(heading[0][3]) && heading[0][4] === 'deepseek-v4-pro', 'model_column');
  const versions = rows.filter(row => row[0] === '模型版本');
  requirePrice(versions.length === 1 && versions[0][3] === 'DeepSeek-V4.1-Flash', 'model_version');
  const labels = { uncachedInput: '百万tokens输入(缓存未命中)', cachedInput: '百万tokens输入(缓存命中)', output: '百万tokens输出' };
  const tariffs: { label: string; period: string; currencyText: string; value: number; modelColumn: number }[] = [];
  const periodRates = (period: string) => Object.fromEntries(Object.entries(labels).map(([key, label]) => {
    const matches = rows.filter(row => /^价格(?:\(\d+\))?$/.test(compact(row[0])) && compact(row[1]) === label && row[2] === period);
    requirePrice(matches.length === 1, 'unique_' + key + '_' + period);
    const rate = matches[0][3];
    requirePrice(/^(?:0|[1-9]\d*)(?:\.\d+)?元$/.test(rate), 'currency');
    const value = Number(rate.slice(0, -1));
    requirePrice(Number.isFinite(value) && value > 0, 'rate');
    tariffs.push({ label, period, currencyText: rate, value, modelColumn: 3 });
    return [key, value];
  })) as { uncachedInput: number; cachedInput: number; output: number };
  const peak = periodRates('高峰时段'), offPeak = periodRates('空闲时段');
  const exact = (rate: typeof peak, expected: typeof peak) => Object.keys(expected).every(key => rate[key as keyof typeof rate] === expected[key as keyof typeof expected]);
  requirePrice(exact(peak, { uncachedInput: 2, cachedInput: 0.04, output: 8 }) && exact(offPeak, { uncachedInput: 1, cachedInput: 0.02, output: 4 }), 'frozen_rates_changed');
  const rules = text(html).match(/北京时间周一至周五（不含中国法定节假日）9:00\s*-\s*12:00、14:00\s*-\s*18:00\s*为高峰时段；其余时段，包括周末及中国法定节假日全天均为空闲时段。/g);
  requirePrice(rules?.length === 1, 'time_rule');
  return { model: 'deepseek-flash', advertisedModelVersion: versions[0][3], currency: 'CNY', unit: 'per million tokens', peak, offPeak,
    officialTimeRule: 'Asia/Shanghai, Monday-Friday excluding statutory holidays: 09:00-12:00 and 14:00-18:00 peak; other times off-peak',
    observedTimeRuleText: rules[0], observedTariffs: tariffs, timeRuleVerified: true, tariffValuesParsedFromResponse: true };
}
