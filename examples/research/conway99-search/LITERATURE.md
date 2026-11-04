# Literature audit — 2026-10-31 (host contribution)

- Cesarz & Woldar, *On the automorphism group of a putative Conway 99-graph*,
  Algebraic Combinatorics 8(2), 2025, DOI 10.5802/alco.418.
  https://alco.centre-mersenne.org/articles/10.5802/alco.418/
  This is an automorphism restriction result, not general nonexistence. In
  particular, even group order forces order dividing 6; divisibility by 7 forces
  the cyclic order-seven group. Do not assume nontrivial automorphisms.
- Keramatipour, *Approaching the Conway-99 problem using SAT solvers*,
  https://arxiv.org/abs/2604.23037 (v2, 2026-04-28).
  The tested SAT approaches did not resolve Conway-99. Timeouts are not UNSAT.
- Thakkar & Severini, *A Forced-Structure Reduction and Verifiable Bounds for Conway's
  99-Graph*, https://arxiv.org/abs/2608.11211 (v2, 2026-09-18). The forced root reduction and
  small rook-graph recovery are prior art. Circulant enumeration is already done;
  it is neither a promising unrestricted route nor a new result here. Reported
  approximate-score records are not solutions and metric differences matter.
  The latest paper reports 70.73% (3501/4950) via a four-vertex-switch tabu method;
  the earlier 69.43% record was not a universal bound. Avoid repeating that claim.
- Natal & Al-saadi, https://arxiv.org/abs/2610.16266 : the latest version is v2,
  2026-10-24, *A Spanning Subgraph of Conway's 99-graph*. It states a forced
  189-edge subgraph and spectrum (12^1,-4^30,3^40,-2^6,0^7) of the remaining
  84-vertex graph. The v1 title/abstract claimed nonexistence via SOS; that is
  superseded and must not be used as proof. Check latest source, not search snippet.
  https://arxiv.org/html/2610.16266v2
- Independent current searches also surfaced unreviewed automation repositories
  and restricted automorphism claims. They are leads, not verified premises.

Decision: no complete verified solution found in the inspected current sources.
Proceed without any extra automorphism assumption. Avoid known impossible
vertex-transitive/Cayley/circulant cases. Any new exclusions require precise scope
and independent proof replay; absence of a search hit is not a novelty certificate.
