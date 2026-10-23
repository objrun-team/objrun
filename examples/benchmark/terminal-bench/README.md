# Terminal-Bench 2.1

[Terminal-Bench 2.1](https://github.com/harbor-framework/terminal-bench-2-1)（arXiv 2601.11868）—— 89 道「把这个容器弄成某个样子」的终端任务，每道一个钉死的镜像、一份人写的参考解、一套 pytest 隐藏测试。判卷 = 在**干活的那个容器里**跑官方 `tests/test.sh`，看 `reward.txt` 是不是 1。

榜上（2.1，5 trials，`leaderboard/submissions/`）：Fable 5 xhigh + Claude Code **83.82**、GPT-5.5 xhigh + Codex 83.15、Fable 5 high + Terminus 2 80.45、Opus 4.8 high + Claude Code 78.88、Gemini 3 Pro + Terminus 2 73.93。

三条命令，同 deepswe：第一条在有 docker 的机器上（WSL），后两条在引擎这台。

```bash
ssh wsl "bash …/examples/benchmark/terminal-bench/setup.sh 10 0"
ssh wsl "cd …/examples/benchmark/terminal-bench && python3 stand.py --level 2"
cd app && bun run start
```

## 框图

```
  引擎（bun）                           台子 stand.py（有 docker 的机器）
  ┌────────────────────┐   POST /place   ┌───────────────────┐   docker exec -i   ┌──────────────────┐
  │ 求解器 bash/read/… ├────────────────►│ 转发 MCP          ├───────────────────►│ tb-<run>-<tid>   │
  │                    │                 │                   │                    │  /rt (运行时)    │
  │ G: ran → passed    │   POST /ran     │ docker cp tests/. │  → /tests          │  /app …          │
  │   (checks = 4)     ├────────────────►│ exec test.sh      ├───────────────────►│  test.sh 跑在这  │
  │                    │   POST /passed  │ cp /logs/verifier │  ← reward.txt      │  有网            │
  │                    ├────────────────►│ rm -rf /tests     │                    │                  │
  └────────────────────┘                 └─────────┬─────────┘                    └──────────────────┘
                                                   │ 读
                                     $HOME/.cache/tgengin-terminal-bench/
                                       terminal-bench-2-1/tasks/<tid>/{task.toml,instruction.md,tests/,solution/}
                                       logs/<tid>-<ms>/{reward.txt,ctrf.json,test-stdout.txt}
```

## 端点

| 端点 | 方法 | 干什么 |
| --- | --- | --- |
| `/health` | GET | 题数、级别、并发闸 |
| `/problems?n=&seed=` | GET | 题面（id、category、difficulty、instruction、官方时限、核/内存），**不带 solution** |
| `/place` | POST | `{place:"tb:<run>/<tid>", tool, args}` 转发进容器；`{op:"ping"}` 探活 |
| `/ran` | POST | G 第一格：test.sh 跑完、reward 读得出来 |
| `/passed` | POST | G 的根：reward == 1；读 `/ran` 刚判的那份 |

请求体是内核的 `{node, moment, domain, feed, input:{task:{id, place,…}, result}}`；回 `{"value": bool}` 或 `{"value": false, "note": …}`。

```bash
python3 stand.py [--port 7903] [--level 0..3] [--graders 4] [--selftest [TID…]] [--pull [TID…]]
```

## 与 deepswe 的三处不同

| | deepswe | terminal-bench |
| --- | --- | --- |
| 候选 | commit sha → 补丁 | **容器本身**；交的字符串只是名字 |
| 判在哪 | 另起干净容器，`--network none` | **干活的活容器里**（官方 shared 模式），有网 |
| 缓存 | 按补丁 sha256 | 不缓存；`ran` 判、`passed` 读那一份 |

分级、`(n, seed)` 点名、并发闸、位置转发全同 deepswe。详见 `G.md`。
