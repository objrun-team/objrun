# GPQA Diamond — G design

Dataset: official `gpqa_diamond.csv`, 198 four-option questions (gated: accept the terms at https://huggingface.co/datasets/Idavidrein/gpqa and use a token to download it to `$TGENGIN_GPQA_DATA`).
Criterion: exact letter match. Shuffle options deterministically by question ID (seed 42), following official simple-evals.

## Four fields

| Field | Current value | Rationale |
|---|---|---|
| Structure | `parsed → correct` | Same as AIME |
| Boundary | `noSearch` blocks gpqa/idavidrein | The dataset is public on HF; a search reveals the answers |
| **Budget** | **`checks: 1`, `maxDeadSiblings: 2`** | **With four choices, checks ≥ 3 effectively gives away the answer** (null model: answer space 4 < allowance). checks=1 + at most 2 restarts permits 3 letters, still reaching 75% through enumeration. GPQA’s F arm is therefore essentially a null-model demonstration, which reports must disclose |
| Feedback level | ℓ0 | — |

## Null model

m = 4. Compare every F-arm result with expected random enumeration under the same budget: checks=1, K=2 → 3 opportunities → success probability 1 − (3/4)(2/3)(1/2) = 75%. **GPQA’s upper bound on Δ is determined by budget, not the model.** Report U-arm pass@1 as the main result and use F only as a null-model control.

## Run

```
BENCH=gpqa ARM=U RUN=gpqa-u-0731 bash runs/bench-arm.sh
```
