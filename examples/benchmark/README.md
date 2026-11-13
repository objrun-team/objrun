# Benchmark examples and experiments

The README, G.md, stand.py, and send.ts files in the existing benchmark directories describe the objectives, official grading criteria, and basic execution entry points.

| Experiment directory | Contents |
| --- | --- |
| `evalplus/` | HumanEval+ and MBPP+ execution, recovery, and grading |
| `climaqa/` | ClimaQA data preparation and experiments |
| `code-benchmarks/` | BIRD and ClassEval evaluations |
| `frontierscience/` | FrontierScience experiments |
| `gpqa/binary/` | GPQA binary-feedback experiments |
| `labbench/experiments/` | LAB-Bench execution and verification |
| `minif2f/formal/`, `minif2f/ablation/` | miniF2F main and ablation experiments |
| `olympiadbench/experiments/` | OlympiadBench experiments |
| `scibench/experiments/` | SciBench experiments |
| `theophyseval/experiments/` | TheoPhysEval experiments |

Read each script's arguments, inputs, and environment requirements before running it. The source preserves historical models, budgets, and grading protocols; original runs, credentials, and environments are not distributed with the examples. Use the [record tools](../../experiments/records/README.md) to read historical results. Shared runners and implementations used by multiple benchmarks remain in `scripts/`.
