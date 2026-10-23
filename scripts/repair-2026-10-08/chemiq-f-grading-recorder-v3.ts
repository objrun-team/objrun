/** Host-only authenticated recording of the unchanged private parsed/correct HTTP handles. */
import { timingSafeEqual } from 'node:crypto';
import { closeSync, fsyncSync, mkdirSync, openSync, readFileSync, writeFileSync } from 'node:fs';
import { join } from 'node:path';
import { gzipSync } from 'node:zlib';
import { graderFetch } from '../../app/src/engine/registry.ts';
import { captureProviderResponse, CapturedTransportFailure } from './scientific-journal-proxy.ts';
import { actualPin, demand, hash, inside, type Pin } from './paid-resource-proof-v2.ts';
import { CHEMIQ_F_FAMILY, CHEMIQ_F_ROOT, type ChemiqFPlan } from './chemiq-f-journal-contract-v3.ts';
import { durableChemiqJson } from './chemiq-f-paid-admission-v3.ts';

type Reply = { httpStatus: number; rawResponse: string };
export function chemiqHeaderAuthorized(headers: Headers, token: string) {
  const got = Buffer.from(headers.get('X-ObjRun-Grader-Token') ?? ''), want = Buffer.from(token);
  return got.length === want.length && timingSafeEqual(got, want);
}
export class ChemiqGradingRecorder {
  private sequence = 0;
  private phase: 'generation' | 'independent-final' = 'generation';
  private flights = new Set<Promise<unknown>>();
  private receipts: Pin[] = [];
  constructor(readonly plan: ChemiqFPlan, readonly directory: string, readonly privateOrigin: string,
    readonly token: string, readonly fixture?: { transport: (node: string, raw: string) => Promise<Reply> }) {
    demand(token.length >= 16 && token.length <= 4096 && !/[\r\n\0]/.test(token), 'chemiq_private_grader_token');
    if (fixture) demand(inside(join(CHEMIQ_F_ROOT, '.scratch'), directory), 'chemiq_grader_mock_scope');
    mkdirSync(directory, { recursive: true });
  }
  finalPhase() { demand(this.flights.size === 0, 'chemiq_generation_grading_not_drained'); this.phase = 'independent-final'; }
  state() { return { activeHandlers: this.flights.size, receipts: this.receipts.length, phase: this.phase, fixtureOnly: !!this.fixture }; }
  async drain() { while (this.flights.size) await Promise.allSettled([...this.flights]); }
  handle(request: Request) {
    const job = this.perform(request); this.flights.add(job); void job.finally(() => this.flights.delete(job)).catch(() => {}); return job;
  }
  private bytes(name: string, raw: Uint8Array) {
    const path = join(this.directory, name), data = gzipSync(raw), fd = openSync(path, 'wx', 0o600);
    try { writeFileSync(fd, data); fsyncSync(fd); } finally { closeSync(fd); }
    demand(readFileSync(path).equals(data), 'chemiq_grade_gzip_readback'); return actualPin(path);
  }
  private async perform(request: Request) {
    if (!chemiqHeaderAuthorized(request.headers, this.token)) return Response.json({ error: 'Unauthorized private grading gateway' }, { status: 401 });
    const node = new URL(request.url).pathname.slice(1);
    if (request.method !== 'POST' || !['parsed', 'correct'].includes(node)) return Response.json({ error: 'Unsupported private grading node' }, { status: 404 });
    const raw = await request.text(); demand(Buffer.byteLength(raw) <= 4 * 1024 ** 2, 'chemiq_grade_request_bound');
    const body = JSON.parse(raw), taskId = body.input?.task?.id;
    const task = this.plan.tasks.find(task => task.taskId === taskId);
    if (!task || body.node !== node) return Response.json({ error: 'Unplanned private grading task' }, { status: 404 });
    const index = this.sequence++, phase = this.phase, startedAtUtc = new Date().toISOString();
    const requestPin = this.bytes(`grade-${index}-request.json.gz`, Buffer.from(raw));
    let reply: Reply | undefined, fault: string | undefined, bodyComplete = true, rawResponse: Uint8Array = Buffer.alloc(0);
    try {
      reply = this.fixture ? await this.fixture.transport(node, raw) : await captureProviderResponse(await graderFetch(this.privateOrigin + '/' + node,
        { method: 'POST', headers: { 'content-type': 'application/json' }, body: raw, signal: AbortSignal.timeout(120000) }), 4 * 1024 ** 2);
      rawResponse = Buffer.from(reply.rawResponse);
    } catch (error) {
      fault = error instanceof Error ? error.name : 'PrivateGraderTransportError'; bodyComplete = false;
      if (error instanceof CapturedTransportFailure) { rawResponse = error.capture.rawBytes; reply = { httpStatus: error.capture.httpStatus, rawResponse: '' }; }
    }
    const responsePin = this.bytes(`grade-${index}-response.json.gz`, rawResponse), finishedAtUtc = new Date().toISOString();
    let parsed: any;
    try { parsed = JSON.parse(new TextDecoder('utf-8', { fatal: true }).decode(rawResponse)); } catch { fault ??= 'PrivateGraderInvalidJson'; }
    const valid = !fault && bodyComplete && reply?.httpStatus === 200 && typeof parsed?.value === 'boolean';
    const receipt = durableChemiqJson(join(this.directory, `grade-${index}-receipt.json`), { protocol: 'chemiq-f-physical-grade-receipt-v3', family: CHEMIQ_F_FAMILY,
      runId: this.plan.runId, index, taskIndex: task.index, officialId: task.officialId, taskId, node, phase, startedAtUtc, finishedAtUtc,
      requestPin, requestRawSha256: hash(raw), responsePin, responseRawSha256: hash(rawResponse), httpStatus: reply?.httpStatus ?? null,
      bodyComplete, valid, value: valid ? parsed.value : null, fault: fault ?? null, fixtureOnly: !!this.fixture,
      privateOrigin: this.privateOrigin, modelCalls: 0, credentialHeadersArchived: false });
    this.receipts.push(receipt);
    return valid ? new Response(reply!.rawResponse, { status: 200, headers: { 'content-type': 'application/json' } })
      : Response.json({ valid: false, outcome: 'grader_error', error: fault ?? 'PrivateGraderUnavailable' }, { status: 503 });
  }
  closeArtifact(path: string) {
    demand(this.flights.size === 0, 'chemiq_grade_receipts_not_closed');
    return durableChemiqJson(path, { protocol: 'chemiq-f-grading-close-v3', family: CHEMIQ_F_FAMILY, runId: this.plan.runId,
      generationClosedBeforeAllFinalGrading: this.phase === 'independent-final', physicalGradeReceiptPins: this.receipts,
      physicalGCalls: this.receipts.length, explicitVerifyBudget: 5, budgetIsAllPhysicalGCalls: false, fixtureOnly: !!this.fixture, modelCalls: 0 });
  }
}
