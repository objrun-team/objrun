# G for the nine-loop hexagon amplitude (planar N=4 SYM, six-gluon MHV)

Draft, 2026-09-27. **Neither run nor installed as a grading service**. Physics details were written from memory; arXiv identifiers and numbers marked "to verify" must be checked against the originals before publication.
This is one problem, not a question bank: express Anthropic's 2026-09-25 calculation as a TgEngin objective object and examine how it differs from miniF2F.

| Field | Content |
| --- | --- |
| **Source** | Problem: the second of Matt von Hippel's public challenges on 2026-08-07, "the six-particle (hexagon) amplitude in planar N=4 SYM at nine loops." Previous record, eight loops: Dixon & Liu 2023 (arXiv:2308.08199, to verify), obtained indirectly via antipodal self-duality. Six and seven loops: Caron-Huot, Dixon, Dulat, von Hippel, McLeod, Papathanasiou 2019 (arXiv:1903.10890, to verify). Result: Anthropic research page [yes-claude-can-do-nine-loops](https://www.anthropic.com/research/yes-claude-can-do-nine-loops), 2026-09-25; nine-loop symbol dataset by Song He, Jing, and Li on Zenodo, 2026-09-17. **Pin the input data**: one- through eight-loop amplitudes (Dixon–Liu public files), the Steinmann hexagon function space through weight 16, and the three-point form factor through eight loops (Dixon, McLeod, Wilhelm 2022; arXiv:2204.11901, to verify). These are part of the problem statement and may be read by the solver. |
| **cand** | A weight-18 hexagon function $\mathcal{E}^{(9)}(u,v,w)$ (BDS-like normalized MHV remainder), delivered as **coproduct coordinates**: one $\{17,1\}$ coproduct component for each of the nine letters $\{u,v,w,1{-}u,1{-}v,1{-}w,y_u,y_v,y_w\}$, each expressed as a rational coefficient vector in the weight-17 basis, plus MZV constant terms of weight ≤17. A pure symbol (sparse weight-18 tensor) is accepted as a reduced candidate, but can pass only the first two cells. |
| **structure** | `parsed → hexagon → physical → antipodal`, root `antipodal`. `parsed`: letters belong to the alphabet, weight = 18, coefficient domain = ℚ ⊕ ℚ·MZV with matching weights, and each coproduct component has the basis dimension. `hexagon`: integrability ($d^2=0$), first entries in {u,v,w}, Steinmann (letters in the same channel are not adjacent), and extended Steinmann: in other words, it is a hexagon function. `physical`: dihedral symmetry $S_3\times\mathbb{Z}_2$, final entries in the MHV allowed set, collinear normalization ($\mathcal{E}$ approaches a known value as $w\to0,\ u+v\to1$), vanishing in the Euclidean multi-Regge region, agreement of 2→4 MRK with all-loop BFKL predictions, and agreement of leading-order $T^1$ OPE (possibly also $T^2$) with flux-tube (BSV) predictions. `antipodal`: apply the antipodal map and known letter substitutions to the candidate symbol; the result must satisfy **three-point form-factor** constraints (six letters, first entries, Steinmann, form-factor final entries, leading-order form-factor OPE). All four cells use linear algebra and limit expansions, **without LLM grading**. |
| **h_r** | There is no official grader here. Constraint sources: integrability/first entries/Steinmann define hexagon functions (Dixon et al., 2011–2014 series); all-loop MRK predictions come from Del Duca et al.'s all-order MRK results (arXiv:1912.00188, to verify); OPE predictions come from the Basso–Sever–Vieira flux tube (arXiv:1306.2058, to verify), whose leading order is computable at arbitrary loop order; antipodal duality comes from Dixon, Gürdoğan, McLeod, Wilhelm 2021 (arXiv:2112.06243, to verify). The grading service must **implement these checks itself**, effectively rebuilding part of the Dixon group's `hexagon` codebase. Dixon's own verification took two weeks. |
| **boundary** | **No reference answer to hide, and no cheap verification**. miniF2F compilation takes 5–60 seconds; a full check here performs linear algebra on a 30-billion-term object, taking hours to days. Verification and solving have comparable costs: the fundamental difference from Lean. Contamination: Anthropic's coordinate files and Song He's group's Zenodo symbols are already public. Disable solver-side `web_search`; set `noSearch` to "nine-loop hexagon symbol Zenodo" and the Anthropic research page. One- through eight-loop data **may be read** as part of the statement. |
| **budget** | **c=3, K=4, T=7 days**. c=3 because one check takes at least hours and a candidate cannot be casually revised for another try; K=4 follows the same reasoning. T follows Anthropic's actual run, about one week on 96 cores. Account for costs per cell: `parsed` takes seconds, `hexagon` hours; OPE and MRK dominate `physical`; `antipodal` requires another full-symbol operation. Recommendation: check `hexagon` at symbol level before proceeding to function level. |
| **level** | 0: bit only. 1: failing cell and constraint (integrability / first entry / Steinmann / symmetry / final entry / collinear / MRK / OPE / antipodal). 2: adds the first violation's location (tensor position, limit-expansion order, mismatched coefficient). 3: adds full coefficient differences at violations (≤40). **Do not provide** the OPE/MRK prediction values: they are private grader data, and revealing them gives away the $T^1$ coefficients. |
| **m** | **∞** (functions). N=(K+1)(c+1)+1=21; enumeration is meaningless. There is a real prior, however: the Dixon group's experience is that the constraints reduce the solution space to one dimension, meaning **the answer space under the constraints is a single point**. The difficulty is calculating the constraints, not guessing. This is dual to miniF2F's "hammer prior": there, solving and checking are cheap; here both are expensive. |
| **Known pitfalls** | See below. |

## Structure

```
parsed ──→ hexagon ──→ physical ──→ antipodal      sink = antipodal; checks = 3
```

- `hexagon` is the **definition layer**. A candidate that fails is not a hexagon function; physical properties are not yet relevant.
- `physical` is the **theory layer**. Each constraint has an independent source (symmetry, BFKL, flux-tube integrability); a mismatch contradicts known physics.
- `antipodal` is an **independent route**. It uses constraints on a different object, the form factor, so a candidate cannot pass merely by fitting hexagon constraints. Anthropic ran two routes and required agreement; this cell incorporates the second route into grading.
- The root does not require term-by-term equality with Anthropic's or Song He's answer. Doing so would treat a public result as gold, even though it was itself bootstrapped and has no stronger standing than these four checks. Put such comparisons in the report as an additional control, outside G.

## Epistemic status of the constraints (must be explicit before publishing a paper)

| Constraint | Status | Consequence if wrong |
| --- | --- | --- |
| Integrability, first entries, Steinmann | Definition of hexagon functions | Cannot be wrong |
| Extended Steinmann | Empirically holds through seven/eight loops; **unproved** | May overconstrain the space and exclude the true answer |
| Dihedral symmetry, final entries | Theorem-level properties of MHV amplitudes | Cannot be wrong |
| Collinear, MRK vanishing | Theorem-level | Cannot be wrong |
| All-order MRK predictions | Depend on the all-order BFKL factorization assumption | The grader itself is wrong |
| Flux-tube OPE predictions | Depend on AdS/CFT integrability | The grader itself is wrong |
| Antipodal duality | Observed through eight loops; **unproved** | The root returns 0 for a correct candidate |
| Coaction / cosmic Galois principle | Empirical principle; **not used in this G** | — |

The root of this G rests on two unproved dualities/principles. This reflects the field's current state, rather than a defect: Dixon's 2023 eight-loop result itself used antipodal self-duality. However, this **must be recorded in the record**; passing cannot be equated with correctness as it is for the Lean kernel.

## Comparison with miniF2F

| | miniF2F | hexagon9 |
| --- | --- | --- |
| Verifier | Lean kernel; external, complete | Custom linear algebra; internal, depends on two conjectures |
| One grading call | 5–60 s | Hours to days |
| Verification cost / solving cost | ≪ 1 | ≈ 1 |
| Gold | None; the proof is the answer | None; the unique solution is the answer |
| Cheap solutions | One hammer solves 23% of questions | None; however, eight-loop input data already provides much of the answer's structure |
| Contamination | Public proofs | Public answers since 2026-09-17 |
| Number of problems | 488 | **1** |

With one problem, this is **one acceptance test**, not a benchmark. A leaderboard would require rerunning the pipeline at lower loop orders: supply loops 1 through L−1 and ask the engine for loop L, one problem each for L=4…8. Each grader can self-test against Dixon's published L-loop result. Only then are U/F arms and Δ meaningful to report.

## Known pitfalls

| Pitfall | Details |
| --- | --- |
| **The grading service does not exist** | The Dixon group's `hexagon` code is private, although some data files are public. Symbol algebra, coproducts, limit expansions, leading-order BSV, and the antipodal map must be implemented. This takes weeks, far beyond an engine patch. |
| **Memory** | Expanding the weight-18 symbol yields ~3×10¹⁰ terms. Work in coproduct coordinates instead; each $\{17,1\}$ component needs a rank computation in the weight-17 basis. Anthropic used 96 cores for a week; Sherlock would require the `bigmem` partition. |
| **3,821 uncertified coordinates** | Anthropic acknowledges that some coordinates were not certified against every constraint. Thus their run did not fully pass this G's `physical`; the root for the real candidate may be 0 or "undetermined". Records must distinguish violations from constraints that were insufficiently checked. |
| **References to verify** | All arXiv identifiers here were written from memory. The user will check references; verify each against the original before publication. |
| **Antipodal-map alphabet** | I have not checked the correspondence between nine hexagon letters and six form-factor letters against the paper. Read 2112.06243 before implementation. |
| **Sherlock environment** | Requires Python 3.12 + SymPy/FLINT or Mathematica (does Sherlock provide `ml math mathematica`? To check). Song He's group's Zenodo format can guide the `parsed` contract and supply self-test comparisons. |

## Not yet verified

Everything. Initial steps:

1. Fetch Song He's group's Zenodo dataset, inspect its format, and define the `parsed` contract as that format or a subset.
2. Self-test `hexagon` on public one- through seven-loop data. Integrability, first entries, and Steinmann should all pass at lower loops.
3. Self-test `physical` MRK and OPE checks on eight-loop data. These are the likeliest sources of grader bugs; do not proceed to higher loops until lower loops pass.
4. Self-test `antipodal` using the eight-loop form factor and eight-loop amplitude.
5. Only after those four steps pass, consider an L=4…8 ladder leaderboard.
