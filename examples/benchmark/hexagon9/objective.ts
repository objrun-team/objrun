/**
 * G for the nine-loop hexagon amplitude (planar N=4 SYM, six-gluon MHV). Draft, not run.
 *
 *   parsed ──→ hexagon ──→ physical ──→ antipodal
 *
 *   parsed: format — 9 letters, weight 18, correct coproduct-coordinate dimensions, coefficient field ℚ ⊕ ℚ·MZV
 *   hexagon: definition — integrability, first entry ∈ {u,v,w}, (extended) Steinmann; i.e. it is a hexagon function
 *   physical: theory — dihedral symmetry, final entry, collinear normalization, MRK vanishing + all-order BFKL, leading OPE = flux tube
 *   antipodal: independent route — satisfy the three-point form-factor constraints after the antipodal map (root)
 *
 * All four nodes use linear algebra and limit expansions, with no LLM grading and no gold answer: the unique solution is the answer.
 * The root relies on two unproven dualities/principles (antipodal duality and extended Steinmann); record must state this.
 * The fundamental difference from miniF2F: one grading run takes hours to days, so grading cost ≈ solving cost.
 */

/** Queries allowed per round. Grading takes at least hours, and candidates cannot be revised by simply trying something; allow 3. */
export const CHECKS = Number(process.env.TGENGIN_HEX9_CHECKS ?? 3);

export interface Objective {
  nodes: { name: string; moment: string; domain: string; handle: string }[];
  edges: { src: string; out: number; dst: string }[];
  sink: string;
  checks: number;
}

export function objectiveOf(stand: string, checks = CHECKS): Objective {
  return {
    nodes: [
      { name: "parsed", moment: "task_done", domain: "bool", handle: `${stand}/parsed` },
      { name: "hexagon", moment: "task_done", domain: "bool", handle: `${stand}/hexagon` },
      { name: "physical", moment: "task_done", domain: "bool", handle: `${stand}/physical` },
      { name: "antipodal", moment: "task_done", domain: "bool", handle: `${stand}/antipodal` },
    ],
    edges: [
      { src: "parsed", out: 0, dst: "hexagon" },
      { src: "hexagon", out: 0, dst: "physical" },
      { src: "physical", out: 0, dst: "antipodal" },
    ],
    sink: "antipodal",
    checks,
  };
}
