# Selection and novelty audit — 2026-10-30

The primary experiment is degree 7 on the triangular prism, uniform weight,
fully symmetric positive interior nodes. It is deliberately a modest reference
improvement experiment, followed by an attempt below the known 35-node count.

Diallo–Worku Table 5 gives prism counts for degrees 4–10 of 11,16,28,36,46,60,82;
their cited previous counts are 11,16,28,35,46,59,84. Table 6 gives pyramid counts
10,15,23,31,44,56,76. Prism degree 7 is the smallest known gap in the requested
domains. It has only 120 full moment conditions, small invariant systems and a
known feasible 35-node target. Degree 9 has the same one-node gap but 220 full
moments and 60 initial nodes. Pyramid 6–9 has no analogous known gap. This is
evidence for low cost, not a guarantee that a search will find a rule.

The author's current data repository includes both the 36-node paper rule and
the older 35-node rules. The 36-node BigFloat listing was loaded and independently
reexpanded from compact orbit parameters. Both full-moment validators pass.
The 35-node Jaśkowiec–Sukumar listing is on (u,v) in the unit triangle, z in (-1,1),
with total weight 1. Its documented map is x=2u-1,y=2v-1,w_new=4w_old. This is an
equivalent affine normalization, not a conflict requiring user selection.
The exact source commit is recorded in the preparation/run manifests.

Pinkse's September paper explicitly warns that its constraints differ from DW,
including less symmetry for some rules, and that some searches warm-start DW.
It covers standard Gaussian and uniform [0,1]^d measures, not prisms/pyramids.
Its repository's drivers, high-precision polishing, symmetry tests and provenance
banking were inspected. No counts from this different problem are substituted.

S3 refers to permutation of barycentric coordinates even though the displayed
reference triangle is right-isosceles. The author's calc_nodes(Prism) uses these
permutations. G checks that same full group together with z reflection.

No semantics-changing conflict was found. A 35-node success re-finds a known
quality level and improves only the specified 36-node construction. A <=34
result improves on the references checked here; further literature and rule-
equivalence searches are necessary before any record claim. No result of a
single run identifies the causal contribution of ObjRun without controls.

Primary sources:
- https://arxiv.org/html/2601.14488 (domain, Tables 1/5/6, numerical methodology)
- https://github.com/mdiallo-fula/SymmetricPositiveInteriorCubatures.jl
- https://arxiv.org/abs/2609.26840 and https://arxiv.org/pdf/2609.26840
- https://github.com/NittanyLion/PositiveWeightQuadratureSolvers.jl
- https://arxiv.org/abs/1409.1865 (Witherden–Vincent)

G's acceptance threshold is 1e-40 at 100/110 digits; it is numerical, weaker
than a theorem. Every monomial residual and symmetry/positivity margin is saved.
The independent verifier uses a different polynomial basis and arithmetic
library. No solver-reported residual is accepted without these host checks.
