# AIME 2024–2026 — G design

Dataset: MathArena AIME 2024 I/II, 2025 I/II, and 2026 I/II: 90 tasks with integer answers from 0 to 999.
Criterion: exact integer match, following the official metric.

## Four fields (edit `G.json`)

| Field | Current value | Rationale | Possible change |
|---|---|---|---|
| Structure | Two nodes: `parsed → correct` | Distinguish malformed submissions from wrong answers; formatting is our responsibility | Merge into one node |
| Boundary | Answers remain in the grading process; `noSearch` blocks AIME/AoPS/MathArena solution pages | Solutions for all three years are online and easily searchable | Add phrases involving `"solution"` |
| Budget | `checks: 3` | Three attempts cannot enumerate 1000 integers, but AIME answers skew small, so guessing common answers carries some signal | 1 (strictest) / 5 |
| Feedback level | ℓ0: rejection identifies only the false node | Additional notes are not meaningful for integer answers | — |

## Null-model reminder

AIME answers range from 0 to 999. With checks=3, enumeration succeeds at approximately 0.3%, which is negligible. The eacndev record reports 27% for sequential enumeration in the old system, combining small-answer bias with repeated restarts. With K=8, examine the proportion of F-arm attempts that submit consecutive integers at the same node.

## Run

```
BENCH=aime ARM=U RUN=aime-u-0731 bash runs/bench-arm.sh
BENCH=aime ARM=F RUN=aime-f-0731 bash runs/bench-arm.sh
```
