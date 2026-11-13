# Shared tools

| Directory | Purpose |
| --- | --- |
| `bench-runner/` | Shared task integration, execution state, recovery, and result retention |
| `benchmark-campaign/` | Providers, execution coordination, and frozen adapters shared across benchmarks |
| `benchmark-repair/` | Shared protocols, resource/grading verification, and recovery implementations; some modules are imported directly by tests and adapters |
| `terminal-bench-repair/` | Isolation, tool gateways, and runtime support shared by Terminal-Bench and SkillsBench |
| `phase1/` | Data preparation and self-checks shared across benchmarks |
| `storage/` | Reading, verifying, exporting, and archiving experiment records |

Individual benchmark experiments live in [examples/benchmark](../examples/benchmark/README.md), and scientific-problem experiments live in [examples/research](../examples/research/README.md). Those directories provide concrete experiment entry points; the directories above retain implementations shared by multiple entry points.

[directory-map.json](directory-map.json) records old and current source paths and fixed test-input locations. Paths, hashes, deadlines, and configurations in historical run evidence are not globally rewritten. Reproducing an original execution version requires the corresponding external originals.
