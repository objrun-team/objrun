# ChemIQ — G design

Dataset: oxpig/ChemIQ `questions/chemiq.jsonl`, 816 tasks in 8 categories (IUPAC naming 200, atom mapping 184, shortest path 108, NMR interpretation 96, reactions 90, carbon counting 50, ring counting 48, SAR 40).
Criterion: unchanged official `answer_verifier.py` (RDKit canonical SMILES; IUPAC names converted to SMILES through Cambridge’s OPSIN web service; exact counts; SAR intervals).

## Four fields

| Field | Current value | Rationale |
|---|---|---|
| Structure | `parsed → correct` | Official parser failures give parsed=0, matching the official zero score for invalid formatting |
| Boundary | `noSearch` blocks chemiq/oxpig | The dataset is on GitHub; SMILES alone does not reveal answers through search |
| **Budget** | `checks: 3`, `maxDeadSiblings: 4` | Carbon/ring counts have small answer spaces (6–25; eacndev estimates 28% enumeration reachability). **Report these two F-arm categories separately**. SMILES/IUPAC/mapping spaces are infinite, so 3 attempts are clean |
| Feedback level | ℓ0 | Optional ℓ1: distinguish RDKit parsing failure from nonequivalence on rejection, useful for NMR interpretation |

## Notes

- OPSIN requires network access (one request per IUPAC name, cached); the grading service needs outbound connectivity.
- The official grader immediately rejects responses containing a newline or exceeding 200 characters, so `suffix` requests only the answer inside boxed.
