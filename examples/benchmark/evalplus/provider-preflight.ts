import {resolve,join} from 'node:path';
import {observeBenchmarkPrices,observeBenchmarkBalance,benchmarkProviderKey} from '../../../scripts/benchmark-campaign/full-f/shared/digitalocean-provider.ts';
const root=resolve(import.meta.dir,'../../..');
const out=join(root,'docs/evalplus-20261012/provider-'+Date.now());
const price=await observeBenchmarkPrices(out),balance=await observeBenchmarkBalance(out,benchmarkProviderKey(root));
console.log(JSON.stringify({price,balance,modelCalls:0}));
