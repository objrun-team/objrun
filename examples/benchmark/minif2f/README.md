# miniF2F (Lean 4)

Lean 4 [miniF2F](https://arxiv.org/abs/2109.00110): 488 olympiad-level formal statements (AMC / AIME / IMO / MATH). The 244 test tasks use [AI-MO/minif2f_test](https://huggingface.co/datasets/AI-MO/minif2f_test), Kimina’s corrected version with 19 declarations differing from DeepSeek’s. The 244 validation tasks use `datasets/minif2f.jsonl` from [DeepSeek-Prover-V1.5](https://github.com/deepseek-ai/DeepSeek-Prover-V1.5). Submit complete Lean 4 proofs; Lean compilation is the criterion.

Leaderboard (test, whole-proof pass@N sampling): Kimina-Prover-72B 92.2% @1024, DeepSeek-Prover-V2-671B 88.9% @8192, Kimina-Prover Preview 80.7% @8192 / 68.9% @32.

```
Engine (any host)                       Service (Lean host: Sherlock compute node)
┌───────────────────────────────────┐   ┌────────────────────────────────────────────────────┐
│ objective.ts:                     │   │ stand.py                                           │
│ stated → compiles → sound         │   │ split_cand: official header/declaration ↔ prefix   │
│ POST /stated                      │──▶│ LEAN.check → lake env repl (pool, env 0)           │
│ POST /compiles                    │──▶│           or Kimina Lean Server /verify            │
│ POST /sound                       │──▶│ is_error / has_sorry ← kimina_client               │
│ Response: {value, note}           │◀──│ Response to the engine                             │
│ GET /problems                     │◀──│ problems.jsonl; golden/ for self-tests only        │
│                                   │   │ #print axioms ⊆ {propext, choice, Quot…}           │
└───────────────────────────────────┘   └────────────────────────────────────────────────────┘
```

## Three commands

```bash
sdev -c 8 -m 32GB -t 02:00:00 && ml python/3.12.1
bash examples/benchmark/minif2f/setup.sh              # elan, REPL, Mathlib, dataset, golden, venv, self-test.
$TGENGIN_MF2F_HOME/venv/bin/python examples/benchmark/minif2f/stand.py --level 1
```

## Endpoints

| Endpoint | Action | Response |
| --- | --- | --- |
| `GET /health` | Task count, level, backend, allowed axioms | JSON |
| `GET /problems?split=test&n=10` | Problem fields: `id, name, split, informal, header, statement`. No answer is hidden here: the proof is the answer | List |
| `POST /stated` | Candidate prefix through `:= by` == official header + declaration (strip comments, collapse whitespace); all remaining lines are indented | `{value}` / `{value:false, note}` |
| `POST /compiles` | Send official declaration + candidate proof body to Lean; `not is_error` | Same as above |
| `POST /sound` | `not has_sorry` and `#print axioms` ⊆ allowed set (root) | Same as above |

Requests use the kernel’s `{node, moment, domain, feed, input:{task:{id}, result}}`. Take the final two segments of `task.id` (`test/<name>` / `valid/<name>`); if `result.body` has a ```lean fence, extract its contents. Each candidate for a task is compiled once, and all three nodes read that result.

## Settings

| Environment variable | Default | Description |
| --- | --- | --- |
| `TGENGIN_MF2F_HOME` | `~/.cache/tgengin-minif2f` | Installation path; on Sherlock, setup.sh stores the actual files under `$SCRATCH` |
| `TGENGIN_MF2F_LEVEL` / `--level` | 1 | Detail in note, 0–3 |
| `TGENGIN_MF2F_TIMEOUT` | 300 s | Wall-time limit per compilation; the only gate because the header sets `maxHeartbeats 0` |
| `TGENGIN_MF2F_REPLS` | 2 | Persistent REPL count (about 3 GB each; `RLIMIT_AS` 8 GB) |
| `TGENGIN_MF2F_MAX_USES` | 16 | Uses before replacing a REPL (v4.15.0 has no `gc`) |
| `TGENGIN_MF2F_BACKEND` / `--backend` | `repl` | `kimina` uses `/verify` at `TGENGIN_MF2F_KIMINA` (default `http://127.0.0.1:8000`) |
| `TGENGIN_MF2F_STRICT_AXIOMS` | 0 | 1 rejects `native_decide` (`Lean.ofReduceBool`) |
| `TGENGIN_MF2F_CHECKS` | 12 | G’s `checks` in objective.ts |

## Self-test

```bash
python stand.py --selftest                                   # First 5 tasks in golden.
python stand.py --selftest test/mathd_numbertheory_34 test/mathd_algebra_756
```

Grade each task twice: Kimina’s public proof should score 1 at all three nodes; the same declaration with `sorry` should give `compiles=1, sound=0`. Six golden declarations predate later AI-MO corrections (including `mathd_algebra_314`) and would fail `stated`; self-tests skip them automatically.

## Files

```
G.md          G specification: source, cand, structure, h_r, boundary, budget, level, m, issues, unverified items.
objective.ts  Three nodes: stated → compiles → sound, checks=12.
stand.py      Three handles + /problems + --selftest; imports grading functions from kimina_client.models.
setup.sh      Idempotent elan, REPL, Mathlib, official code, dataset, golden, and venv setup; run on a compute node.
```

## Sherlock (CentOS 7, glibc 2.17): run everything inside Apptainer

The bundled clang requires glibc ≥ 2.27, so the REPL cannot link on the host (`LEAN_CC=gcc` also fails; see setup.sh comments).
Use image `python:3.12-bookworm` (glibc 2.36), binding jq from the host. Installation root: `$SCRATCH/tgengin-minif2f-ctr`.

```bash
sbatch runs/minif2f-setup-apptainer.sbatch      # Setup + 5 self-tests, about 25 min; passed on 2026-09-25.
sbatch runs/minif2f-selftest-all.sbatch         # Self-test all 225 golden proofs.
```

Start the service inside the container too, since the REPL binary links to its libraries:

```bash
apptainer exec --cleanenv --bind /scratch/users/ehz0002,/home/users/ehz0002 \
  --env ELAN_HOME=$H/elan --env PATH=$H/elan/bin:/usr/local/bin:/usr/bin:/bin --env TGENGIN_MF2F_HOME=$H \
  /scratch/users/ehz0002/containers/py312-bookworm.sif $H/venv/bin/python examples/benchmark/minif2f/stand.py --level 1
```
Here `H=/scratch/users/ehz0002/tgengin-minif2f-ctr`. The Bun engine runs on the host and knows only `http://127.0.0.1:7903/{stated,compiles,sound}`.
