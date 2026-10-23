# Terminal-Bench 2.1 的 G

| 字段 | 内容 |
| --- | --- |
| **来源** | arXiv [2601.11868](https://arxiv.org/abs/2601.11868)（ICLR 2026）。题集仓库 `harbor-framework/terminal-bench-2-1`，钉 commit `7131e4375048a0e408a8fb404b5f499d726b695b`（2026-08-11），**89 道**，每道在 `tasks/dataset.toml` 里有 sha256 digest。旧仓库 `laude-institute/terminal-bench` 是 1.x 的 harness，2.x 起 harness 换成 `harbor-framework/harbor`（钉 `5b9adbe6…`）。HF 镜像 `harborframework/terminal-bench-2.0`：只读镜像、Apache-2.0、**不 gated**。**注意版本**：2.1 是 2.x 的最后一版；上游 2026-06 出 3.0（74 道）、2026-08-28 出 4.0（66 道，判卷容器分离，8 小时时限，3 道要 GPU），语义化版本，**分数与 2.x 不可比**。首页图上那个 2.1 就是这一份。 |
| **cand** | **判卷那一刻的容器本身**（文件 + 正在跑的进程）。没有 git、没有补丁。求解器交上来的字符串只是这一份候选的名字（把 `ran`/`passed` 两格对到同一次判卷），内容不参与判断，空的就叫 `done`。 |
| **structure** | `ran ──→ passed`，sink = `passed`。`ran`：官方 `tests/test.sh` 在它的容器里跑完、`/logs/verifier/reward.txt` 读得出一个有限的数（harbor `Verifier.verify` + `_parse_reward_text`）；`passed`：那个数 == 1（tbench 榜上 accuracy 就是 reward==1 的比例）。前置 + 官方判决，同 deepswe 的 applies → resolved。 |
| **h_r** | 每道题 `tasks/<id>/tests/test.sh` + `test_outputs.py`：装 uv 0.9.5，`uvx pytest==8.4.1 --ctrf /logs/verifier/ctrf.json /tests/test_outputs.py -rA`，退出码 0 → `echo 1 > reward.txt` 否则 0。**89/89 全是这个形状**（82 走 uvx，7 走 pip），89/89 写 `reward.txt`（无 `reward.json`、无部分分）。**确定性**：纯 pytest 断言，**没有任何 LLM 判卷**（harbor 有 rewardkit/LLM-judge 机制，但 2.1 一道没用）。→ 89 道全包，舍弃 0 道。 |
| **boundary** | 参考解 `solution/solve.sh` 装在台子机器 `$HOME/.cache/tgengin-terminal-bench/`，只在 `--selftest` 里碰；`/problems` 只发 instruction。判卷**需要容器 + 网络**：官方 89/89 `allow_internet = true`，而且 test.sh 自己 `curl astral.sh` / `apt-get` —— 容器不能 `--network none`。官方判卷模式是 `shared`：测试跑在求解器的活容器里 → 隐藏测试在判卷那几十秒里对求解器可见（台子判完立刻 `rm -rf /tests`，但窗口堵不死）。 |
| **budget** | **c = 4, K = 6, T = 官方 `agent.timeout_sec`**（900 s × 48 道、1200 × 5、1800 × 17、2400 × 2、3600 × 13、7200 × 1、12000 × 1；`--level` 不改 T）。c 比 deepswe 的 6 紧：每判一次 = 容器里跑一遍 test.sh（几十秒到几分钟，官方上限 900–12000 s），**容器会被 test.sh 改一次**（apt-get、装 uv），且每次都开一个 /tests 可见窗口。K = 6：判死重来不回档（同容器），多留几个兄弟意义不大。 |
| **level** | 0：只 0/1。1：`{stage, "k of n pass"}`（ctrf 计数）。2：+ 没过的测试名。3：+ ctrf `message`/`trace` 原文。89/89 都出 ctrf，所以 0–3 全可实现；但 **22 道只有 1 条测试**（级 1/2 等于级 0），**11 道断言里写着期望值字面量**（chess-best-move、crack-7z-hash、db-wal-recovery、gcode-to-text、git-leak-recovery、headless-terminal、multi-source-data-merger、hf-model-inference、pytorch-model-cli、compile-compcert、build-pov-ray）—— 级 3 对这些题等于念答案。 |
| **m** | **m = ∞**（容器状态）。N = (K+1)(c+1)+1 = 7×5+1 = **36**；枚举可达 **0/89**。但名义 ∞ 不等于实际大：chess-best-move 交的是两步棋、password-recovery / crack-7z-hash 交的是一串口令 —— 这些题的有效答案空间是「合法棋步的二元组」「字典」，靠 verify 循环猜不完 36 次，但级 3 一次就漏。 |

## 来源与版本

| | |
| --- | --- |
| 论文 | Merrill et al., *Terminal-Bench: Benchmarking Agents on Hard, Realistic Tasks in Command Line Interfaces*, arXiv 2601.11868 |
| 题集 | `harbor-framework/terminal-bench-2-1` @ `7131e437`，`tasks/` 下 89 个目录 + `dataset.toml`（digest） |
| 2.0 | `harbor-framework/terminal-bench-2`（= `laude-institute/terminal-bench-2`）@ `2fd12b88`，同 89 道；2.1 改了 28 道（9 道外部依赖漂了、8 道资源不够、其余题面和测试对不上；`train-fasttext` 的 test.sh 改成从源码编 fasttext，「verifier must be self-contained」） |
| harness | `harbor-framework/harbor` @ `5b9adbe6`，`src/harbor/verifier/verifier.py`、`agents/oracle.py`、`environments/docker/docker-compose-prebuilt.yaml` |
| 镜像 | 89 个 `alexgshaw/<题>:20251031`，Docker Hub 公开；**大小没量过** |
| 许可证 | Apache-2.0（题集、harbor 都是） |
| 题的分布 | 难度 easy 4 / medium 55 / hard 30；类别 software-engineering 26、system-administration 9、security 8、scientific-computing 8、data-science 8、file-operations 5、debugging 5、其余 20 |
| 资源 | cpus 1 × 83、2 × 3、4 × 3；memory 2048 × 68、4096 × 13、8192 × 8；gpus 0 × 89 |
| 榜（2.1，5 trials） | Fable 5 xhigh + Claude Code 83.82；GPT-5.5 xhigh + Codex 83.15；Fable 5 high + Terminus 2 80.45；Opus 4.8 high + Claude Code 78.88；Gemini 3 Pro high + Terminus 2 73.93；Opus 4.7 max + Claude Code 68.9 |

## cand：容器，不是文件

deepswe 有 git，交 sha 就把候选钉死了。这儿没有：题目是「让 nginx 记日志」「装上 Windows 3.11 并截屏 OCR 得对」「把 /app/move.txt 写对」，**候选就是容器**。两个后果：

1. **不做快照。** `docker commit` 存不下进程，而至少 14 道的测试查的是活着的服务或端口（nginx-request-logging、pypi-server、kv-store-grpc、qemu-alpine-ssh、qemu-startup、mailman、headless-terminal、configure-git-webserver……）。快照一律判 0，看着像题坏了。照官方：判在活容器里。
2. **不缓存。** 容器每一秒都可能变，没有东西可以当键。`ran` 判、把结果按 (容器, 交的名字) 存十分钟，`passed` 读一次就拿走。同一容器一次只判一份（锁）。

## structure：官方那把尺子拆成两段

```
harbor Verifier.verify():
    upload tests/ → /tests
    chmod +x /tests/test.sh
    exec "(/tests/test.sh) > /logs/verifier/test-stdout.txt 2>&1"
    download /logs/verifier
    reward = _parse_reward_text()      ← 空文件、非数、非有限 → 抛错，trial 记 error
tbench accuracy = mean(reward == 1)
```

`ran` = 读出了一个数，`passed` = 那个数是 1。判不出来的三种原因分开报（OOM 137 / 超时 / test.sh 退出但没写 reward），同 deepswe。

## h_r：89 道一个形状

```bash
curl -LsSf https://astral.sh/uv/0.9.5/install.sh | sh
uvx -p 3.13 -w pytest==8.4.1 -w pytest-json-ctrf==0.3.5 [-w 题目依赖…] \
    pytest --ctrf /logs/verifier/ctrf.json /tests/test_outputs.py -rA
[ $? -eq 0 ] && echo 1 > /logs/verifier/reward.txt || echo 0 > …
```

测试条数：1 条 × 22 道、2 × 13、3 × 20、4 × 9、5 × 6、6 × 10、7 × 4、8 × 1、9 × 3、11 × 1。**全部确定性**（文件内容、命令输出、端口、OCR 截图）；没有 LLM 判卷，没有网络判卷（除了 test.sh 自己装依赖）。**不舍弃任何题。**

「import 官方代码」在这儿的形式是**原样执行** `tests/test.sh`（它是脚本，不是库），reward 的读法照抄 harbor `_parse_reward_text`；台子不写任何断言。

## boundary

| 什么 | 在哪 | 怎么挡 |
| --- | --- | --- |
| 参考解 `solution/solve.sh` | 台子机器家目录 | 不进仓库、不进容器（自检除外，自检容器用完即删） |
| 隐藏测试 `tests/` | 同上 | 判卷时送进 `/tests`，**test.sh 一退出就删**；`/logs/verifier` 同 |
| 判卷进行中 | 求解器的容器里 | **堵不死**：shared 模式是官方设定，测试跑着的时候求解器同一个文件系统。引擎那边 verify 是同步的话，求解器的工具循环这时候不动，窗口只在理论上；有没有并发要看内核 |
| 网络 | 容器有网（官方） | **不挡**。参考解公开在 GitHub 上，`curl` 得到 —— 官方基准自己的洞（canary 字符串 + 荣誉制）。引擎侧关 `web_search`，`noSearch` 列上题名 |
| `/ran` `/passed` 可达 | 同 cmt | 不是洞，是判决；次数闸在 `checks` |

判卷**需要**：docker、容器有网（test.sh 装 uv / apt 包）、官方 verifier 时限（900–12000 s）。

## budget

| 旋钮 | 值 | 为什么 |
| --- | --- | --- |
| c（checks） | 4 | 判一次几十秒到几分钟，容器被改一次，/tests 露一次。够「做 → 验 → 改 → 验」两趟 |
| K（maxDeadSiblings） | 6 | 判死不回档，兄弟共用同一容器，多了只是在同一个坑里换姿势 |
| T | 官方 `agent.timeout_sec` | 900 s 占 48 道；换数字就不是同一个实验 |
| 判卷时限 | 官方 `verifier.timeout_sec` | 同上；build-pov-ray 12000 s |
| GRADERS | 4 | 台子机器扛得住多少，跟引擎并发无关 |

## level

| 级 | note | 备注 |
| --- | --- | --- |
| 0 | 空 | |
| 1 | `{stage:"tests", tests:"4 of 9 pass"}` 或 `{stage:"verifier", detail:"timed out at 900s"}` | 22 道只有 1 条测试，此级 = 级 0 |
| 2 | + `failing: [测试名]` | 测试名多半是描述性的（`test_move_correct`、`test_nginx_logs_requests`），本身就是提示 |
| 3 | + `failures: [{name, message, trace}]` | pytest 断言重写会把两边的值打出来：`assert ['a1a2'] == ['e2e4', 'g2g4']`。**上面列的 11 道等于漏答案** |

## m 与枚举可达

m = ∞。N = (K+1)(c+1)+1 = 36。可达 0/89。

## 已知坑

| | |
| --- | --- |
| **版本漂** | 上游已到 4.0，题集换了；这儿钉 2.1，报告里写清楚是 2.1 |
| **数据污染** | 题集、参考解、测试全部公开在 GitHub（2025-10 起），HF 有镜像；canary GUID `26b5c67b-…` 是唯一防线。4.0 就因「public solutions」删了题 |
| **容器要网** | 与 deepswe 相反；test.sh 装 uv 靠 astral.sh，`train-fasttext` 从 GitHub clone fastText 源码编 —— 外网一抖判卷就炸（2.1 修的 9 道就是这么坏的） |
| **判卷改容器** | test.sh `apt-get install curl`、装 uv 到 `~/.local`。多次 verify 后容器不是原样；官方一趟只判一次所以他们无所谓 |
| **超时杀不干净** | 客户端超时后 `pkill -f /tests/test.sh`，但 uvx 起的 pytest 子进程可能活着 |
| **重活的题** | install-windows-3.11（qemu + OCR，4 核 8 GB）、build-pov-ray（12000 s）、sam-cell-seg（7200 s）、compile-compcert；镜像大小没量，**盘要看着** |
| **Sherlock 没 docker** | 只有 `/bin/apptainer`。harbor 自带 singularity 后端（`--fakeroot --writable-tmpfs --containall --pid`，容器内起 FastAPI 收命令），说明 apptainer 上跑得通，但本台子按 docker 写；要在 sdev 上跑得换掉 `docker run/exec/cp` 那一层。test.sh 里 `apt-get` 在 fakeroot + writable-tmpfs 下 dpkg 有跨设备 rename 问题（harbor server.py 专门绕过） |
| **python** | stand.py 用 `tomllib`，需要 ≥ 3.11；Sherlock 登录节点是 3.6.8，用 `ml python/3.12.1` |
| **一道题一个容器** | `tb:<run>/<tid>`；judged 结果按容器名存，换跑名就是新容器 |
| **依赖** | docker、python ≥ 3.11、`dist/tgengin-runtime-linux-x64`；没有 sympy/rdkit/lean |

## 未验证

代码没在这台机器上跑过（登录节点禁跑、没 docker）。逐行复读后，确定没验证的：

1. `docker cp tests/. name:/tests` 会不会把文件属主弄成宿主 uid，导致 root 之外的用户读不了 —— 89 道镜像默认用户是不是 root 没查（harbor 的 `verifier.user` 默认 None = 容器默认用户）。
2. `docker exec name sh -c "(/tests/test.sh) > …"` 的工作目录是不是镜像的 `WORKDIR`（test.sh 检查 `$PWD != /`）；harbor 走 compose exec，同一机制，但没实测。
3. `pytest-json-ctrf 0.3.5` 输出里失败信息的字段名是 `message` 还是 `trace`，两者都取了；ctrf `results.tests[].status` 取值 `passed/failed/skipped` 按 CTRF 规范假设。
4. `RESULTS` 的键用「交的名字」：引擎在 `ran` 和 `passed` 两次 POST 里送的 `input.result` 是不是同一个字符串（deepswe 那边是同一个 sha，形状相同，未在这套上验）。
5. `feed[0].value` 是 `ran` 的输出这一假设（同 deepswe）。
6. 空容器判 0：有没有题在什么都不做时测试就过（自检会发现，但我没跑）。
7. 参考解是否 89/89 在本机过（官方说 2.1 「no task is unsolved」，指的是模型，不是本机 oracle）；`--selftest` 默认抽 4 道。
8. 镜像总大小、拉取时间；Docker Hub 匿名拉取限速。
9. `--memory` 单位写 `2048m`；`--cpus "1"` 传字符串；两处照 docker CLI 语法，没跑。
10. 超时后 `pkill -f /tests/test.sh` 能不能杀到 uvx 起的 pytest；杀不到的话下一次判卷前的 `rm -rf /logs/verifier/*` 会清掉它迟到的 reward，逻辑上安全，实际没试。
11. `setup.sh` 的 `pin()` 用 `git fetch --depth 1 origin <sha>`，需要服务端允许 `uploadpack.allowReachableSHA1InWant`（GitHub 允许）；未跑。
12. `harbor` 那份 clone 65 MB，只对照不 import —— 要是嫌大可以删掉那一步，不影响台子。
13. 级 3 「11 道漏答案」是 grep `assert .*== "` 数出 10 道加 chess-best-move（列表字面量）得来的，没逐道读；实际漏不漏还取决于 pytest 把多长的 diff 打进 ctrf。
