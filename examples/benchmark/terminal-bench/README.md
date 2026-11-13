# Terminal-Bench 2.1

[Terminal-Bench 2.1](https://github.com/harbor-framework/terminal-bench-2-1) (arXiv 2601.11868): 89 terminal tasks requiring a particular container state, each with a pinned image, a human-written reference solution, and hidden pytest tests. Grading runs official `tests/test.sh` **inside the work container** and checks whether `reward.txt` is 1.

Leaderboard (2.1, 5 trials, `leaderboard/submissions/`): Fable 5 xhigh + Claude Code **83.82**, GPT-5.5 xhigh + Codex 83.15, Fable 5 high + Terminus 2 80.45, Opus 4.8 high + Claude Code 78.88, Gemini 3 Pro + Terminus 2 73.93.

Three commands, as for deepswe: the first on the Docker host (WSL), the latter two on the engine host.

```bash
ssh wsl "bash …/examples/benchmark/terminal-bench/setup.sh 10 0"
ssh wsl "cd …/examples/benchmark/terminal-bench && python3 stand.py --level 2"
cd app && bun run start
```

## Architecture

```
Engine (Bun)                        stand.py service (Docker host)
  Solver bash/read/… ── POST /place ──▶ Forward MCP
                                         │ docker exec -i
                                         ▼
                                    tb-<run>-<tid>
                                      /rt (runtime), /app …
                                      Live container, network enabled
                                         ▲
  G: ran → passed (checks = 4)             │
    POST /ran ──────────────────────▶ docker cp tests/. → /tests
                                      exec test.sh in the live container
    POST /passed ───────────────────▶ cp /logs/verifier ← reward.txt
                                      rm -rf /tests
                                         │ Reads
                                         ▼
  $HOME/.cache/tgengin-terminal-bench/
    terminal-bench-2-1/tasks/<tid>/{task.toml,instruction.md,tests/,solution/}
    logs/<tid>-<ms>/{reward.txt,ctrf.json,test-stdout.txt}
```

## Endpoints

| Endpoint | Method | Action |
| --- | --- | --- |
| `/health` | GET | Task count, level, concurrency gate |
| `/problems?n=&seed=` | GET | Problem fields (id, category, difficulty, instruction, official timeout, CPUs/memory), **without solution** |
| `/place` | POST | Forward `{place:"tb:<run>/<tid>", tool, args}` into the container; `{op:"ping"}` probes liveness |
| `/ran` | POST | First G node: test.sh completed and reward is readable |
| `/passed` | POST | Root of G: reward == 1; read the result just produced by `/ran` |

Requests use the kernel’s `{node, moment, domain, feed, input:{task:{id, place,…}, result}}`; responses are `{"value": bool}` or `{"value": false, "note": …}`.

```bash
python3 stand.py [--port 7903] [--level 0..3] [--graders 4] [--selftest [TID…]] [--pull [TID…]]
```

## Three differences from deepswe

| | deepswe | terminal-bench |
| --- | --- | --- |
| Candidate | Commit SHA → patch | **The container itself**; the submitted string is only its name |
| Grading location | Fresh separate container, `--network none` | **Live work container**, official shared mode, with network access |
| Cache | Patch SHA256 | No cache; `ran` grades and `passed` reads that result |

Feedback levels, `(n, seed)` selection, concurrency gates, and place forwarding match deepswe. See `G.md`.
