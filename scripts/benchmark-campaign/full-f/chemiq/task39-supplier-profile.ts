import {supplierProfile} from '../shared/chembench-supplier-profiles.ts';
export const SUPPLIER=process.argv[2]??process.env.CHEMIQ_TASK39_SUPPLIER??'relace';
if(!['relace','dekallm','wafer'].includes(SUPPLIER))throw Error('Only explicitly approved ChemIQ task39 supplier');
export const BENCHMARK_PROVIDER=supplierProfile(SUPPLIER);
