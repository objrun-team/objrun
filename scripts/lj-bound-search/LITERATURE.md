# Source audit, 2026-10-31, before first paid model request

Search scope: primary arXiv sources, publisher pages, author-hosted papers and
Optimization Online. Queries included exact title, minimum interparticle distance,
0.684, 0.767764, 2025/2026 bounds, and cited original proof authors. This is a
bounded literature check, not a guarantee that no unpublished/new paper exists.

1. Kiessling and Wales, arXiv:2511.15008 (HTML snapshot with SHA256 in sources.json),
   https://arxiv.org/html/2511.15008. Read introduction, Sections 2.3 and 2.5,
   and references 71,79,80. Abstract uses >1; body Eq12 uses >=1. Virial relation
   r_min^6=2R/A concerns stationary configurations. Arbitrary distance ratios do
   not establish realizability or global minimality. Numerical putative minima,
   contact count speculation and thermodynamic discussion are not assumptions
   in the frozen checker. The source was not blanket-endorsed.
2. Xue (1997), Minimum Inter-Particle Distance at Global Minimizers of Lennard-Jones
   Clusters, J Global Optimization 11,83-90, DOI 10.1023/A:1008284629099.
   Original publisher metadata/abstract traced. Full PDF attempt redirected to
   subscription preview; full proof could NOT be directly accessed. Do not claim
   otherwise. The bound .5 in equilibrium-length units, and disjoint-ball energy
   comparison lineage, are independently documented by Vinko and later papers.
   No purchase was made. This run relies on the fully read later proof instead.
3. Blanc (2004), Lower Bound for the Interatomic Distance in Lennard-Jones Clusters,
   Computational Optimization and Applications 29,5-12. Improvement .6108 in
   equilibrium-length units is documented in Vinko's comparison; not independently
   reproduced here. Full primary proof not retrieved in this run.
4. Vinko (2005), Minimal inter-particle distance in atom clusters. Author preprint
   https://www.inf.u-szeged.hu/~tvinko/mindist_vinko.pdf (cached). Journal metadata
   reports Acta Cybernetica 17(1),107-121, whereas the 2025 note cites105-119.
   Author preprint dated May9 2005; journal numbering is a bibliographic discrepancy,
   not a numerical discrepancy. Read Sections1-2, Lemmas1-3, comparison table.
   Bound .6187356774 (scaled units); pairwise ball packing plus relocation energy
   <=-1. Lemma1 strictly <-1 excludes N2; we use weak <=-1 for all N>=2.
5. Schachinger, Addis, Bomze, Schoen, New results for molecular formation under
   pairwise potential minimization, Optimization Online June2005 preprint;
   https://optimization-online.org/wp-content/uploads/2005/06/1151.pdf (cached).
   Text extraction font mapping corrupted; primary page images inspected for
   Theorem2.1/relocation proof, and searchable web extraction used for overview.
   Bound .67985 in 3D (not planar .7633). The relocation comparison uses an
   exterior point at nearest-neighbor distance1 and energy<=-1. This is prior art.
6. Yuhjtman, A sensible estimate for the stability constant of the Lennard-Jones
   potential, arXiv:1501.05248v2, submitted Jan21 2015/revised Oct13 2015.
   https://arxiv.org/pdf/1501.05248v2, J Stat Phys160,1684-1695 (2015).
   PDF internal typeset date says Nov5 2018; version identity follows arXiv v2
   and retained bytes, not the internal date. Read Sections2,3 and Cor3.3,
   visually checked Cor3.3. Potential Phi(s)=s^-12-2s^-6, pair minimum -1 at1.
   Cor3.3 states strictly >.684. Frozen reproduced nonstrict reference uses
   the stronger unrounded exact integral/root implication, not the printed bound.
7. Kuznetsov and Sahinidis (2025), New bounds and formulations for the deterministic
   global optimization of Lennard-Jones clusters, DOI10.1007/s10898-025-01476-7,
   https://link.springer.com/article/10.1007/s10898-025-01476-7 (cached HTML).
   Read abstract/introduction/Section2. New distance results concern diameter
   upper bounds and size-specific tightening, not a new uniform all-N separation
   constant. Its claims of finite-N certificates are not used to infer all-N.

## Exact reference and reproduction

The frequently quoted .767764 is (171/250)*2^(1/6)=.7677640410436111193...
in the requested units. Existing Yuhjtman proof actually gives c_ref at the root
in baseline/reference.json, ~.7684205255854960462. We count only candidates
strictly above its certified upper enclosure as improvements.

Lengths: r=2^(1/6)s; energies E_user=E_Phi/4. There is no extra factor of2 from
ordered pair sums: the requested E uses i<j, and single-particle comparison
cancels all unchanged pairs exactly. Standard Cambridge LJ values 4V share r
units but energies must be divided by4; none were imported for this experiment.

Reproduction: exact finite Bernstein cover of original cutoff .64 for .6<=a<=.7;
analytic integral to infinity; rational bootstrap .65 and .684 inequalities;
isolated positive root and exact N2,N3,N4 simplices. See PROOF_FAMILY.md and
baseline artifacts. Only this strongest used reference is re-proved fully;
earlier historical constants are a source-traced chronology, not new results.
