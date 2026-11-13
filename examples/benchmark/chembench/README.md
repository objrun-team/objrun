# ChemBench — G design

Dataset: HF `jablonkagroup/ChemBench`, 2785 tasks across 9 topics: 2542 choice questions (possibly multiple answers) + 243 numerical questions.
Criterion: official `all_correct` (choice: equal letter sets; numerical: error < 1% of the target value).

## Four fields

| Field | Current value | Rationale |
|---|---|---|
| Structure | `parsed → correct` | — |
| Boundary | `noSearch` blocks chembench/lamalab | The dataset is public |
| **Budget** | **`checks: 1`, `maxDeadSiblings: 1`** | Usually 4–6 options; multiple-answer space is 2^n−1. One attempt + one restart permits at most 2 candidates, still reaching approximately 50% for four-option single-answer questions. **ChemBench’s F arm is primarily a null-model control**. Numerical tasks (243) are unaffected and can be reported separately |
| Feedback level | ℓ0 | — |
| Time limit | 900 s | Short questions; 2785 tasks × 1 h is impractical |

## Topics

Include all 9 topics by default, matching eacndev’s 2785 tasks. `chemical_preference` (1000 tasks) asks for binary human preferences, not knowledge. To exclude it, change `TGENGIN_CHEMBENCH_TOPICS`.

## Recommendation

Report the U arm as the main result; the F arm is informative only on the numerical subset. Run a `HOW_MANY=20` smoke test before the full dataset.
