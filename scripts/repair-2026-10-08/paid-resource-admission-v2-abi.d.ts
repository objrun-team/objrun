/** Implemented ABI. This declaration does not acquire a lock or make API calls.
 * Factory/release are async (fresh native PID checks); cash hooks are synchronous
 * and return only after native fsync/readback. Import implementations directly.
 * The superseded plan declaration is retained in docs/.../controls as .snapshot.
 */
export {acquirePaidResourceAdmissionV2,acquirePaidResourceFixtureV2,RESOURCE_MODE,
 scanOtherPaidRuns,verifyPaidResourceCertification} from './paid-resource-admission-v2.ts';
export type {AdmissionInput,AdmissionLease,ReleaseInput,FixtureRuntime,Carry,
 PidObservation,AuditKind,AuditWrapper} from './paid-resource-admission-v2.ts';
export {createCnyCashShadow,verifyCashClosure} from './cny-cash-shadow-v2.ts';
export type {CashOptions,CashTicket,CashAdmission,JournalStart,FinishRef,CashFinish}
 from './cny-cash-shadow-v2.ts';
export type {Pin,Prefix,Clock} from './paid-resource-proof-v2.ts';
import type {createCnyCashShadow} from './cny-cash-shadow-v2.ts';
export type CnyCashShadow=ReturnType<typeof createCnyCashShadow>;
export type CashSnapshot=ReturnType<CnyCashShadow['snapshot']>;
export type BeforeForwardInput=Parameters<CnyCashShadow['beforeForward']>[0];
