# SciBench criteria and feedback

| Field | Design |
|---|---|
| Candidate | The complete final submission text; the last boxed number is read using official postprocessing. |
| Structure | parsed → correct; root is correct. |
| parsed | Official extraction, scientific-notation handling, and float conversion yield a finite number. |
| correct | Official equiv: remove commas, try the complete string / first token, and compare with math.isclose using a symmetric 5% relative tolerance. |
| Feedback | parsed failures may explain the output format; correct returns only correctness, without error magnitude, direction, gold answer, or reference solution. |
| Budget | c5 counts attempts; 600 seconds / four branches / 12 units, plus a dollar-cost cap and whole-problem feedback counting. |
| Isolation | A private service holds answers and requires a token; the model tool allowlist provides no arbitrary file, network, or execution access. |
| Failures | Data/service exceptions are invalid grades; candidate format or numerical errors are valid rejections. Invalid grades are not cached. |

The original unit may contain the answer's 10^n scale. Statements use only the unit after official remove_not processing; the grader restores the full scale. Zero reference answers receive no additional absolute tolerance. Online grading and final judgment use the same numerical objective; independent final judgment must not be described as a new held-out objective.

Numerical correctness alone does not establish that a formula or derivation is correct; explanations of the repair mechanism require inspection of actual trajectories. Early stopping of independently sampled EX uses gold-based selection by the scheduler, so results must disclose the oracle-feedback condition.
