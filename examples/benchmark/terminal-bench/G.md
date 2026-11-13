# G for Terminal-Bench 2.1

| Field | Content |
| --- | --- |
| **Source** | arXiv [2601.11868](https://arxiv.org/abs/2601.11868) (ICLR 2026). Dataset repository `harbor-framework/terminal-bench-2-1`, pinned to commit `7131e4375048a0e408a8fb404b5f499d726b695b` (2026-08-11): **89 tasks**, each with a sha256 digest in `tasks/dataset.toml`. The old `laude-institute/terminal-bench` repository is the 1.x harness; 2.x uses `harbor-framework/harbor` (pinned to `5b9adbe6…`). HF mirror `harborframework/terminal-bench-2.0` is read-only, Apache-2.0, and **ungated**. **Version matters**: 2.1 is the final 2.x release. Upstream released 3.0 in 2026-06 (74 tasks) and 4.0 on 2026-08-28 (66 tasks, separate grading containers, eight-hour limit, three GPU tasks). These use semantic versioning, and **scores are not comparable with 2.x**. The homepage figure's 2.1 refers to this dataset. |
| **cand** | **The live container at grading time**, including files and running processes. No git or patch. The submitted string only names this candidate, associating `ran` and `passed` with one grading run. Its contents are not judged; an empty string becomes `done`. |
| **structure** | `ran ──→ passed`, sink = `passed`. `ran`: official `tests/test.sh` finishes in the container, and `/logs/verifier/reward.txt` yields a finite number (harbor `Verifier.verify` + `_parse_reward_text`). `passed`: that number equals 1 (tbench leaderboard accuracy is the fraction with reward==1). A precondition followed by the official judgment, like deepswe's applies → resolved. |
| **h_r** | Each task's `tasks/<id>/tests/test.sh` + `test_outputs.py`: install uv 0.9.5, run `uvx pytest==8.4.1 --ctrf /logs/verifier/ctrf.json /tests/test_outputs.py -rA`, and write 1 to reward.txt for exit code 0, otherwise 0. **All 89/89 follow this pattern** (82 use uvx, seven pip); all write reward.txt, with no reward.json or partial credit. **Deterministic**: pure pytest assertions, **no LLM grading**. Harbor supports rewardkit/LLM judges, but no 2.1 task uses them. All 89 tasks are included; none are discarded. |
| **boundary** | Reference solutions `solution/solve.sh` reside under `$HOME/.cache/tgengin-terminal-bench/` on the grader machine and are accessed only by `--selftest`; `/problems` serves only instructions. Grading **requires containers + networking**: all 89 tasks officially set `allow_internet = true`, and test.sh itself uses `curl astral.sh` / `apt-get`, so `--network none` is unsuitable. Official grading mode is `shared`: tests run in the solver's live container, making hidden tests visible during those tens of seconds. The grader immediately removes `/tests` afterward, but cannot eliminate the exposure window. |
| **budget** | **c = 4, K = 6, T = official `agent.timeout_sec`** (900 s × 48 tasks, 1200 × 5, 1800 × 17, 2400 × 2, 3600 × 13, 7200 × 1, 12000 × 1; `--level` does not change T). c is tighter than deepswe's six: each call runs test.sh for tens of seconds to minutes, with official limits of 900–12000 s, **modifies the container** through apt-get/uv installation, and exposes `/tests`. K=6: marking a node dead and restarting does not roll back the shared container, so extra siblings have limited value. |
| **level** | 0: 0/1 only. 1: `{stage, "k of n pass"}` from ctrf counts. 2: adds failed test names. 3: adds raw ctrf `message`/`trace`. All 89 tasks emit ctrf, so levels 0–3 are feasible. However, **22 tasks have only one test**, making levels 1/2 equivalent to 0; **11 tasks embed expected values in assertions** (chess-best-move, crack-7z-hash, db-wal-recovery, gcode-to-text, git-leak-recovery, headless-terminal, multi-source-data-merger, hf-model-inference, pytorch-model-cli, compile-compcert, build-pov-ray). Level 3 effectively reads out their answers. |
| **m** | **m = ∞** (container state). N = (K+1)(c+1)+1 = 7×5+1 = **36**; enumeration reaches **0/89**. Nominal infinity does not imply a large effective space: chess-best-move submits two moves, while password-recovery / crack-7z-hash submit a password. Their effective spaces are legal move pairs or dictionaries. Thirty-six verify guesses cannot exhaust them, but level 3 leaks them in one call. |

## Sources and versions

| | |
| --- | --- |
| Paper | Merrill et al., *Terminal-Bench: Benchmarking Agents on Hard, Realistic Tasks in Command Line Interfaces*, arXiv 2601.11868 |
| Dataset | `harbor-framework/terminal-bench-2-1` @ `7131e437`: 89 directories under `tasks/` + `dataset.toml` digests |
| 2.0 | `harbor-framework/terminal-bench-2` (= `laude-institute/terminal-bench-2`) @ `2fd12b88`, the same 89 tasks. Version 2.1 changes 28: nine with drifting external dependencies, eight with insufficient resources, and the rest with statement/test mismatches. `train-fasttext` test.sh now builds fasttext from source because the verifier must be self-contained. |
| Harness | `harbor-framework/harbor` @ `5b9adbe6`: `src/harbor/verifier/verifier.py`, `agents/oracle.py`, `environments/docker/docker-compose-prebuilt.yaml` |
| Images | 89 public Docker Hub images, `alexgshaw/<task>:20251031`; **sizes unmeasured** |
| License | Apache-2.0 for both dataset and harbor |
| Task distribution | Difficulty: easy 4 / medium 55 / hard 30. Categories: software-engineering 26, system-administration 9, security 8, scientific-computing 8, data-science 8, file-operations 5, debugging 5, other 20. |
| Resources | cpus 1 × 83, 2 × 3, 4 × 3; memory 2048 × 68, 4096 × 13, 8192 × 8; gpus 0 × 89 |
| Leaderboard (2.1, five trials) | Fable 5 xhigh + Claude Code 83.82; GPT-5.5 xhigh + Codex 83.15; Fable 5 high + Terminus 2 80.45; Opus 4.8 high + Claude Code 78.88; Gemini 3 Pro high + Terminus 2 73.93; Opus 4.7 max + Claude Code 68.9 |

## cand: the container, not files

Deepswe uses git, so submitting a SHA fixes the candidate. Here, tasks include making nginx log requests, installing Windows 3.11 and passing screenshot OCR checks, or writing `/app/move.txt` correctly. **The container is the candidate.** Two consequences:

1. **No snapshots.** docker commit does not preserve processes, while at least 14 tasks test live services or ports (nginx-request-logging, pypi-server, kv-store-grpc, qemu-alpine-ssh, qemu-startup, mailman, headless-terminal, configure-git-webserver, etc.). Snapshots would score 0 and appear to indicate broken tasks. Follow the official procedure and grade the live container.
2. **No caching.** The container can change every second, leaving no stable key. `ran` grades and stores the result for ten minutes under (container, submitted name); `passed` consumes it once. A lock allows only one grading run per container at a time.

## structure: the official criterion in two stages

```
harbor Verifier.verify():
    upload tests/ → /tests
    chmod +x /tests/test.sh
    exec "(/tests/test.sh) > /logs/verifier/test-stdout.txt 2>&1"
    download /logs/verifier
    reward = _parse_reward_text()      ← empty, nonnumeric, or nonfinite: raise; record trial error
tbench accuracy = mean(reward == 1)
```

`ran` means a number was read; `passed` means it equals 1. Report three grading failures separately: OOM 137, timeout, and test.sh exiting without reward, as in deepswe.

## h_r: one pattern across 89 tasks

```bash
curl -LsSf https://astral.sh/uv/0.9.5/install.sh | sh
uvx -p 3.13 -w pytest==8.4.1 -w pytest-json-ctrf==0.3.5 [-w task-dependencies…] \
    pytest --ctrf /logs/verifier/ctrf.json /tests/test_outputs.py -rA
[ $? -eq 0 ] && echo 1 > /logs/verifier/reward.txt || echo 0 > …
```

Test-count distribution: one test × 22 tasks, 2 × 13, 3 × 20, 4 × 9, 5 × 6, 6 × 10, 7 × 4, 8 × 1, 9 × 3, 11 × 1. **All deterministic**: file contents, command output, ports, and screenshot OCR. No LLM grading or network grading, apart from dependency installation in test.sh. **No tasks are discarded.**

Here, importing official code means **executing `tests/test.sh` unchanged**, because it is a script rather than a library. Reward parsing follows harbor's `_parse_reward_text`; the grading service defines no assertions.

## boundary

| Item | Location | Protection |
| --- | --- | --- |
| Reference solution `solution/solve.sh` | Grader machine's home directory | Excluded from repository and containers except disposable self-test containers |
| Hidden `tests/` | Same location | Copied to `/tests` for grading, **removed immediately when test.sh exits**, along with `/logs/verifier` |
| Grading in progress | Solver's container | **Cannot fully isolate**: official shared mode uses the same filesystem during tests. If engine verify is synchronous, the solver's tool loop stops and the window is only theoretical; concurrency depends on the kernel. |
| Network | Container has official network access | **Unrestricted**. Public GitHub solutions are curl-accessible, an official benchmark weakness mitigated only by canaries and an honor system. Disable engine-side `web_search` and list task names in `noSearch`. |
| Reachable `/ran` `/passed` | As in cmt | These are judgments, not a vulnerability; `checks` gates their count. |

Grading **requires** docker, container networking for uv/apt installation, and the official verifier timeouts of 900–12000 s.

## budget

| Setting | Value | Rationale |
| --- | --- | --- |
| c (checks) | 4 | Each check takes tens of seconds to minutes, changes the container, and exposes `/tests`. Enough for two work → verify → revise → verify round trips. |
| K (maxDeadSiblings) | 6 | Marking a node dead does not roll back state; siblings share one container, so extra siblings merely try different approaches in the same state. |
| T | Official `agent.timeout_sec` | 48 tasks use 900 s; changing it changes the experiment. |
| Grading timeout | Official `verifier.timeout_sec` | Same rationale; build-pov-ray uses 12000 s. |
| GRADERS | 4 | Determined by grader-machine capacity, independent of engine concurrency. |

## level

| Level | note | Remarks |
| --- | --- | --- |
| 0 | Empty | |
| 1 | `{stage:"tests", tests:"4 of 9 pass"}` or `{stage:"verifier", detail:"timed out at 900s"}` | Equivalent to level 0 for the 22 single-test tasks. |
| 2 | Adds `failing: [test names]` | Names are often descriptive (`test_move_correct`, `test_nginx_logs_requests`) and are themselves hints. |
| 3 | Adds `failures: [{name, message, trace}]` | pytest assertion rewriting prints both values, e.g. `assert ['a1a2'] == ['e2e4', 'g2g4']`. **The 11 tasks above effectively leak their answers.** |

## m and enumeration coverage

m = ∞. N = (K+1)(c+1)+1 = 36. Reachable: 0/89.

## Known pitfalls

| | |
| --- | --- |
| **Version drift** | Upstream is at 4.0 with a different task set. This integration pins 2.1; state that explicitly in reports. |
| **Contamination** | Tasks, reference solutions, and tests have all been public on GitHub since 2025-10, with an HF mirror. Canary GUID `26b5c67b-…` is the only defense. Version 4.0 removed tasks because of public solutions. |
| **Containers need networking** | Unlike deepswe, test.sh installs uv from astral.sh and train-fasttext clones and builds fastText from GitHub. Network failures break grading; this caused the nine dependency failures fixed in 2.1. |
| **Grading changes the container** | test.sh runs `apt-get install curl` and installs uv under `~/.local`. After repeated verify calls, the container is no longer pristine. Official runs grade only once, so this does not concern them. |
| **Timeout cleanup is incomplete** | Client timeout triggers `pkill -f /tests/test.sh`, but pytest children launched by uvx may survive. |
| **Heavy tasks** | install-windows-3.11 (qemu + OCR, four cores / 8 GB), build-pov-ray (12000 s), sam-cell-seg (7200 s), compile-compcert. Image sizes are unmeasured; **monitor disk space**. |
| **Sherlock lacks docker** | Only `/bin/apptainer` is available. Harbor includes a singularity backend (`--fakeroot --writable-tmpfs --containall --pid`, with a FastAPI command server inside), demonstrating feasibility with apptainer. This grader is written for docker; running on sdev requires replacing the docker run/exec/cp layer. apt-get under fakeroot + writable-tmpfs encounters dpkg cross-device rename errors, which harbor server.py works around. |
| **Python** | stand.py uses tomllib and requires ≥3.11. Sherlock login nodes have 3.6.8; use `ml python/3.12.1`. |
| **One container per task** | `tb:<run>/<tid>`; judged results are keyed by container name. A new run name creates a new container. |
| **Dependencies** | docker, Python ≥3.11, `dist/tgengin-runtime-linux-x64`; no sympy/rdkit/lean. |

## Not yet verified

The code has not run on this machine: execution is prohibited on the login node, and docker is absent. Line-by-line review leaves these explicitly unverified points:

1. Whether `docker cp tests/. name:/tests` assigns host-UID ownership that prevents nonroot users from reading files. The default users of all 89 images have not been checked; harbor's `verifier.user` defaults to None, meaning the container default.
2. Whether `docker exec name sh -c "(/tests/test.sh) > …"` uses the image's WORKDIR. test.sh checks that `$PWD != /`. Harbor uses compose exec with the same mechanism, but this has not been tested.
3. Whether pytest-json-ctrf 0.3.5 uses `message` or `trace` for failures; both are read. The `passed/failed/skipped` values of `results.tests[].status` are assumed from the CTRF specification.
4. RESULTS is keyed by the submitted name: whether the engine sends the same input.result string in both ran and passed POSTs. Deepswe sends the same SHA with the same shape; this integration has not been checked.
5. The assumption that `feed[0].value` is ran's output, as in deepswe.
6. Whether an untouched container always scores 0; some tests might pass without work. Self-tests would reveal this, but have not run.
7. Whether all 89 reference solutions pass locally. The official 2.1 statement that no task is unsolved concerns models, not the local oracle. `--selftest` samples four by default.
8. Total image size, pull time, and Docker Hub anonymous pull rate limits.
9. `--memory` uses `2048m`, and `--cpus "1"` passes a string. Both follow docker CLI syntax but have not run.
10. Whether `pkill -f /tests/test.sh` after timeout kills pytest launched by uvx. If it does not, `rm -rf /logs/verifier/*` before the next grading run clears its late reward. Logically safe, but untested.
11. setup.sh's pin() uses `git fetch --depth 1 origin <sha>`, requiring server support for `uploadpack.allowReachableSHA1InWant`. GitHub permits it; this has not run.
12. The 65 MB harbor clone is only a reference, not imported. That step may be removed without affecting the grader if size is a concern.
13. The 11 answer-leaking level-3 tasks were counted by searching for `assert .*== "` (ten tasks), plus chess-best-move's list literal. They were not individually inspected; actual leakage also depends on how much pytest diff is written into ctrf.
