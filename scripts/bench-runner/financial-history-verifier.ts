/** Explicit child history verifier using the manifest's signed financial loader. */
import {readFileSync} from 'node:fs';
import {runFinancialEntry} from './financial-policy-loader.ts';
const args=process.argv.slice(2),m=JSON.parse(readFileSync(args[0],'utf8'));
await runFinancialEntry(m.adapterConfig.financialSourceConfigPin.path,import.meta.dir+'/verify-child-history-policy.ts',args);
