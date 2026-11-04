# Frozen Conway 99 objective

Construct an undirected simple SRG(99,14,1,2), OR provide a rigorous independently
checkable nonexistence proof covering every possible graph. This is the only main
objective. The adjacency matrix must be symmetric binary, have zero diagonal,
row sums 14, and satisfy A^2=12I-A+2J in exact integer arithmetic.
Approximate candidates, new lemmas and restricted UNSAT are partial results only.

Fixed paid experiment model: OpenRouter deepseek/deepseek-v4.1-flash. No fallback.
The ONLY campaign budget is five hours after the first paid dispatch, including
prechecks. /work/campaign-clock.json is authoritative; never reset or extend it.
No additional fee, token, candidate, or iteration limit. Use existing local CPU.
Stop new search immediately after verified main success or the absolute deadline.
Proof claims cannot trigger success without host review of encoding, proof replay,
coverage and symmetry completeness. CP-SAT INFEASIBLE alone is not a certificate.

The host supplies read-only independent integer checkers in /reference/checker/:
check_pairs.py enumerates common neighbours; check_matrix.py multiplies matrices.
Submit {"path":"candidate.json"} with file format {"matrix":[99 rows of 99 ints]}.
Keep complete candidates atomically (write a .tmp then rename). Save best and latest
under /work/candidates/ as *.json; the host audits files and exports edge lists.
Save methods, code versions, random seeds, raw solver output, proof files and
progress.json. Use no hidden success condition and do not alter the checker.
The host separately records host scaffolding and model-generated work.

Rooted reduction (encoding v1; all statements below apply to every target graph):
Choose any root r. Its 14 neighbours have induced degree lambda=1, hence form a
perfect matching. Relabel the root 0 and neighbours 1..14 with pairs (1,2), ...,
(13,14). This is only vertex relabelling, never an automorphism assumption.
Each of 84 nonneighbours of r has exactly two neighbours in N(r), by mu=2.
They cannot be a matched pair, whose sole common neighbour is already r. Every
unmatched pair has exactly one common neighbour besides r, so these 84 vertices
are in bijection with the 84 unmatched pairs. Relabel them by these pairs.
This fixes 189 edges; the sole unknown is a 12-regular graph B on 84 outer vertices.
With inner labels 0..13, mate(a)=a xor 1 and outer label P(u), the exact equations:
  sum_v B[u,v] = 12;
  sum_{v:a in P(v)} B[u,v] = (1 if a in P(u) else 2)-1[mate(a) in P(u)];
  sum_w B[u,w]B[w,v] + B[u,v] = 2 - |P(u) intersect P(v)|, u != v.
Together with binary symmetric B and zero diagonal these imply every SRG pair
condition (root pairs and inner pairs are already forced). Conversely every
target graph yields such B. The root selection and matching ordering lose no
isomorphism class. Do not silently impose any additional structure on B.

Read /reference/LITERATURE.md before designing searches. The October preprint v1
nonexistence claim was replaced in v2 (24 October) by a spanning-subgraph result.
Do not treat the obsolete abstract as a solution. Do not spend the campaign on
circulant/Cayley/vertex-transitive search or already excluded automorphism groups.
Any optional symmetry space must be explicitly labelled restricted; never assume
the graph has a nontrivial automorphism. The supplied rooted.py CP-SAT encoding
was recovered and checked on the rook SRG(9,4,1,2), at every possible root.

Work in /work, references in /reference (read only). Available: Python, numpy,
scipy, ortools CP-SAT, python-sat and g++. Choose mathematically useful local
structure, full-domain constraints, local repair and graph switches. Prefer
efficient incremental C++ search. A degree-preserving outer switch can explore
all simple 12-regular outer graphs; numerical loss zero must pass both checkers.
Document that heuristic failure is UNKNOWN. Keep CPU solver work productive while
using the model to diagnose, improve the encoding/search, or prove new constraints.
Use run_command background=true for long work, with a FOREGROUND shell command.
Do not launch nohup or shell '&' jobs: each command has a private PID namespace.
Do not spend many requests merely polling; do substantive work between polls.
The supervisor independently enforces the same absolute deadline for every job.
Do not publish, access credentials, install paid resources or touch other runs.
