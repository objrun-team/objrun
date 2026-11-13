# SkillsBench 1.1

[SkillsBench](https://arxiv.org/abs/2602.12670) ([benchflow-ai/skillsbench](https://github.com/benchflow-ai/skillsbench), tag `v1.1`): 87 containerized tasks across 8 domains, each with Agent Skills, a pytest grader, and a human-written oracle. The paper compares the same model **with / without skills** (33.9% → 50.5% pass rate). All graders use deterministic pytest, without an LLM judge. See [G.md](./G.md) for grading details and issues.

```
Engine host                          Docker host (WSL)
┌────────────────────────────────┐   ┌──────────────────────────────────────────────────────┐
│ Engine                         │   │ Service stand.py :7903                               │
│ place=skb:<run>/<id>           │──▶│ /place → docker exec work-container /rt              │
│ G: verified → passed           │──▶│ /verified → docker commit snapshot                   │
│                                │   │ /passed → disposable container: official verifier/   │
│                                │   │ Dataset: ~/.cache/tgengin-skillsbench/               │
│                                │   │   tasks/<id>/{task.md,environment,                   │
│                                │   │               oracle/,verifier/}                     │
│                                │   │ oracle/ and verifier/ stay on this side              │
└────────────────────────────────┘   └──────────────────────────────────────────────────────┘
```

| Endpoint | Action |
| --- | --- |
| `GET /health` | Task count, level, skills mode, network mode |
| `GET /problems?n=&seed=` | Problem statement + workdir + official timeout + skill names/descriptions. **No oracle or verifier** |
| `POST /place` | Forward one tool call into the task container (address `skb:[<run>/]<task-id>`) |
| `POST /verified` | Official `verifier/test.sh` completed and wrote `reward.txt` |
| `POST /passed` | `reward == 1.0` (root) |

Three commands, the first two in WSL:

```bash
ssh wsl "bash /mnt/e/sgu-bzhc/EACN_EX/TgEngin/examples/benchmark/skillsbench/setup.sh 10 0"
ssh wsl "cd /mnt/e/sgu-bzhc/EACN_EX/TgEngin/examples/benchmark/skillsbench && ~/.cache/tgengin-skillsbench/venv/bin/python stand.py --level 2 --skills with"
cd app && bun run start
```

`setup.sh`: clone under `$HOME/.cache/tgengin-skillsbench/` (pin `b63b7b28`, stop on mismatch) → venv (PyYAML only) → check Docker → copy runtime → build selected images → self-test (empty container scores 0, official oracle scores 1). **On Sherlock, only cloning works**, because Docker is unavailable.

Settings: `--level 0..3` (note detail; 3 leaks ground truth), `--skills with|none` (the benchmark’s independent variable, requiring two experiments), `--network official|none` (86/87 official tasks use public networking; `none` changes the leaderboard experiment).

Batch scripts (`send.ts` / `run.sh`) have not yet been written: adapt the deepswe versions to port 7903, prefix `skb:`, and node names `verified`/`passed`, then append the `skills` returned by `/problems` to the problem statement.
