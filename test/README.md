# Tests

Run commands from the repository root after installing the dependencies in `app/` with `bun install`.

| Location | Purpose |
| --- | --- |
| `unit/` | In-process engine, candidate selection, measurement and task-query regressions. |
| `integration/` | Engine lifecycle, local HTTP/WebSocket mocks, tool and workflow checks. |
| `benchmarks/` | Benchmark adapters, grading, journals, resource accounting and cache protocols. |
| `manual/` | Checks requiring Docker images, a benchmark corpus or a prepared scientific worker. |
| `fixtures/` | Read-only regression inputs. |
| `_lib.ts` | Shared temporary-engine helpers, also imported by examples and benchmark runners. |

## Core checks

```sh
bun test test/unit
bun test test/integration
```

Files ending in `.test.ts` use the Bun test runner. The other TypeScript files are standalone checks and must be run directly, for example:

```sh
bun test/integration/agent.ts
bun test/integration/answer-once.ts
bun test/integration/duplex-e2e.ts
```

These checks use temporary databases and local mock services. They do not need a paid model endpoint.

## Benchmark checks

Run individual suites according to the adapter or protocol being changed:

```sh
bun test test/benchmarks/benchmark-inference.test.ts test/benchmarks/repair-campaign-contract.test.ts
python -B test/benchmarks/gradelib_test.py
python -B test/benchmarks/container_isolation_test.py
```

The benchmark suites have different requirements. Some use Windows process/file-handle APIs, pinned native executables or separately archived campaign inputs. A blanket `bun test` or Python discovery run is therefore not a portable smoke test. A `v2` or `v3` filename identifies the protocol under test; both can remain relevant.

## Environment checks and generated files

Run `manual/` checks explicitly after preparing the environment described in each file. The Terminal-Bench probes need the matching cached images, corpus and verifier dependencies. The miniF2F unpack checks need Docker and the pinned public `leantar` archive. `scientific_codec_test.py` runs inside the scientific worker, where `/worker/codec.py`, NumPy and SymPy are installed.

Keep new temporary data in the system temporary directory or `.scratch/`. In particular, worker and miniF2F test reports must not overwrite `fixtures/`. Fixed-run acceptance audits and their generated reports are archived with the original experiment records outside this repository.
