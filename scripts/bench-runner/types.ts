export type Bench = 'terminal-bench' | 'skillsbench';
export const STAGES = ['prepare','qualify','solve','grade','cleanup','reconcile','archive'] as const;
export type StageName = typeof STAGES[number];
export interface Pin { path: string; bytes: number; sha256: string }
export interface OriginalContract {
  cpu: number; memoryMb: number; solveSeconds: number; gradeSeconds: number;
  toolSeconds: number; providerSeconds: number;
  model: string; provider: string; reasoning: string;
  taskCapUsd: number; priorKnownUsd: number; priorUnknownUsd: number;
}
export interface StageSpec {
  kind: 'reuse' | 'command'; effect: 'read-only' | 'native' | 'model' | 'grade' | 'oracle';
  timeoutSeconds: number; command?: string[]; evidencePins: Pin[];
  successEvidence?: { path: string; equals: Record<string, unknown> };
  resourceMode?: 'driver-owned' | 'none';
  originalSuccessKey?: string; resumePolicy?: 'never' | 'after-closure' | 'original-result-first';
  bundledStages?: StageName[];
  outerTimeoutSeconds?: number;
}
export interface TaskManifest {
  schemaVersion: 1; taskId: string; bench: Bench; root: string; artifactRoot: string;
  original: OriginalContract;
  provenance: { sourcePins: Pin[]; contractPins: Pin[]; inventoryPin: Pin; authorizationPin?: Pin };
  history: { validResultPins: Pin[]; successfulStageProofs: Partial<Record<StageName, Pin[]>>;
    priorRunPins: Pin[]; stateKnown: boolean; originalResultRecoveryRequired: boolean };
  stages: Partial<Record<StageName, StageSpec>>;
  adapterConfig: Record<string, unknown>;
}
export type InventoryState = 'valid' | 'inflight' | 'recoverable' | 'never-started' | 'quarantined';
export interface InventoryTask {
  taskId: string; bench: Bench; state: InventoryState; reason: string;
  evidencePins: Pin[]; successfulStages: Partial<Record<StageName, Pin[]>>;
  priorKnownUsd?: number; priorUnknownUsd?: number; priorRunIds: string[];
  manifestPath?: string;
}
export interface AttemptContext {
  attemptId: string; taskId: string; bench: Bench; stage: StageName;
  runDir: string; manifestPath: string; manifestPin: Pin;
  admissionControlPath: string; inventoryTask: InventoryTask;
  bindings?: Record<string, string>;
  originalRecoveryProofPin?: Pin;
}
export interface StageResult {
  status: 'complete' | 'retryable' | 'invalid' | 'unknown' | 'valid';
  proofPins: Pin[]; nativeClosed: boolean; financialClosed: boolean;
  candidateOrSubmissionPresent: boolean; validResult?: { passed: boolean; outcome: string; proofPin: Pin };
  completedStages?: Partial<Record<StageName, { proofPins: Pin[] }>>;
  actualSolver?: { workerPid: number; enginePid: number; runId: string; mainTaskId: string;
    workerIncarnation: string; mainActive: boolean; dbHealthBound: boolean; liveLaneBound: boolean };
  reason?: string;
}
export interface BenchAdapter {
  bench: Bench;
  validate(manifest: TaskManifest): void;
  execute(manifest: TaskManifest, spec: StageSpec, context: AttemptContext): Promise<StageResult>;
  recover?(manifest: TaskManifest, context: AttemptContext): Promise<StageResult>;
}
