/**
 * G for this benchmark. **Batch launch and resume share one definition.**
 *
 * Three nodes, whose handles are the service addresses:
 *
 * ```
 *   stated ──→ compiles ──→ sound      stated: theorem declaration unchanged (verbatim comparison with the original)
 *                                     compiles: Lean compilation has no errors
 *                                     sound: no sorry; axioms belong to the allowed set (root)
 * ```
 *
 * The root **must have an incoming edge**; otherwise its value is independent of the candidate, making G constant and the objective invalid. Publication rejects it (`objective/spec.ts`).
 *
 * These are the three existing stages of Lean grading, not a new criterion:
 *
 * - `stated` is a Lean-specific prerequisite: the declaration defines the problem, so changing it changes the problem. The service always compiles the official declaration + candidate proof body (DeepSeek-Prover-V1.5 protocol); this node only reports a mismatch between the submitted and official prefixes.
 * - `compiles` = negation of Kimina `is_error`: no REPL message has severity=error.
 * - `sound` = negation of Kimina `has_sorry` + `#print axioms` lists only Lean’s three core axioms (plus native_decide’s `Lean.ofReduceBool` by default, accepted by leaderboard participants).
 *
 * There is no separate `kernel_ok`: Lean checks each declaration when it is added, so error-free elaboration means it passed the kernel. There are only two ways around this: introducing axioms (exposed by `sound`) and `set_option debug.skipKernelTC` (a top-level command blocked by `stated`). A further node would detect nothing more, so it is folded into `sound`.
 *
 * **This definition lives in a separate file** because both batch launch and resume read it. Duplicating it risks silent divergence: changing one copy but not the other means the two runs solve different problems.
 */

/**
 * **How often the box may be queried in one round.**
 *
 * One grading call = one Lean compilation, measured at 5–60 seconds (`maxHeartbeats 0`, with a 300-second wall-time fallback). The answer space is proof text, m = ∞, so enumeration is impossible. This limit instead prevents trying a sequence of hammers: `norm_num` / `nlinarith` / `omega` / `simp` / `decide` / `aesop`… Of Kimina’s 197 public proofs, 45 are one-line tactics; that 18% of tasks can be solved by trial alone.
 *
 * Allow 12: enough for five or six cycles of writing a version → compiling → revising from open_goals → recompiling, but not enough to try a list of twenty or thirty hammers.
 */
export const CHECKS = Number(process.env.TGENGIN_MF2F_CHECKS ?? 12);

export interface Objective {
  nodes: { name: string; moment: string; domain: string; handle: string }[];
  edges: { src: string; out: number; dst: string }[];
  sink: string;
  checks: number;
}

export function objectiveOf(stand: string, checks = CHECKS): Objective {
  return {
    nodes: [
      { name: "stated", moment: "task_done", domain: "bool", handle: `${stand}/stated` },
      { name: "compiles", moment: "task_done", domain: "bool", handle: `${stand}/compiles` },
      { name: "sound", moment: "task_done", domain: "bool", handle: `${stand}/sound` },
    ],
    edges: [
      { src: "stated", out: 0, dst: "compiles" },
      { src: "compiles", out: 0, dst: "sound" },
    ],
    sink: "sound",
    checks,
  };
}
