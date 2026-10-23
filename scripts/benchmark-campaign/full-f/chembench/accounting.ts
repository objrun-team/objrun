import { readFileSync } from 'node:fs';
import { join } from 'node:path';
import { inspectCampaignJournal as inspectRelaceJournal } from '../../../benchmark-repair/campaign-journal.ts';
import { inspectCampaignJournal as inspectDigitalOceanJournal } from '../shared/digitalocean-journal.ts';
export { inspectFullFClosedCash as inspectAnyClosedCash } from '../shared/digitalocean-closed-run-cost.ts';
const json=(p:string)=>JSON.parse(readFileSync(p,'utf8'));
export function inspectAnyJournal(directory:string){return (json(join(directory,'journal-config.json')).providerSlug==='digitalocean'?inspectDigitalOceanJournal:inspectRelaceJournal)(directory);}