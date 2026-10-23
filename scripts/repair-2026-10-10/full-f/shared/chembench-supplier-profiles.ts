/** Only the last unfinished ChemBench question may select one of these approved providers. */
import { BENCHMARK_PROVIDER as ORIGINAL } from './digitalocean-provider.ts';
const make=(providerSlug:string,providerName:string,cachedInput=.006)=>Object.freeze({...ORIGINAL,providerSlug,providerName,peakRates:Object.freeze({...ORIGINAL.peakRates,cachedInput}),routing:Object.freeze({...ORIGINAL.routing,only:[providerSlug]})});
export const CHEMBENCH_SUPPLIERS=Object.freeze({relace:make('relace','Relace'),dekallm:make('dekallm','DekaLLM'),wafer:make('wafer','Wafer',.049)});
export function supplierProfile(slug:string){if(slug==='digitalocean')return ORIGINAL;const p=(CHEMBENCH_SUPPLIERS as any)[slug];if(!p)throw Error('unapproved_chembench_supplier');return p;}
