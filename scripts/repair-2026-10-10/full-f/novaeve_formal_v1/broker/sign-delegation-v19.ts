/** Explicit root-only signing command; never writes a queue inbox or starts anything. */
import {readFileSync,writeFileSync} from 'node:fs';
import {resolve,join} from 'node:path';
import {sign} from 'node:crypto';
import {actualPin,verifyPin} from '../../../../repair-2026-10-08/paid-resource-proof-v2.ts';
import {base} from '../coordinator/review-authority-v4.ts';
if(process.argv[2]!=='--sign')throw Error('root uses --sign unsignedPlanPath signedOutputPath');
const p=JSON.parse(readFileSync(resolve(process.argv[3]),'utf8'));if(p.protocol!=='novaeve-root-reviewed-parent-delegation-v19'||!p.coordinatorReviewed||p.newPort!==17895||!p.noNewFunding||!p.originalLockMustRemainUnchanged||!p.allResourcesUseOriginalPool)throw Error('root_review_concrete_delegation_required');
for(const pin of [...p.sourcePins,p.parentAdmissionPin,p.canonicalLockPin,p.accountHistoryPin,p.originalConnectionPin])verifyPin(pin);
const signature=sign(null,Buffer.from(JSON.stringify(p)),readFileSync(join(base,'review-authority.private.pem'),'utf8')).toString('base64'),out=resolve(process.argv[4]);
writeFileSync(out,JSON.stringify({protocol:'novaeve-root-signed-entry-v4',entry:p,signature},null,2)+'\n',{flag:'wx',mode:0o600});console.log(JSON.stringify({signedPlanPin:actualPin(out),queueEntriesWritten:0,serviceStarted:false,secretsPrinted:false}));
