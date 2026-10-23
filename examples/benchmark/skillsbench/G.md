# SkillsBench 1.1 的 G

| 字段 | 内容 |
| --- | --- |
| 来源 | 论文 [arXiv:2602.12670](https://arxiv.org/abs/2602.12670)（v1 2026-02，86 题/84 评；当前版 87 题）。官方仓库 [benchflow-ai/skillsbench](https://github.com/benchflow-ai/skillsbench)，Apache 2.0。**钉 tag `v1.1`**，tag 指向 commit `b63b7b2850226b6aa4fb5929a8c1ac7bc4d9a6af`（2026-06-16，tag 被「re-stamped」过：`registry.json` 说 87 道题的内容 digest 钉在 `55bfe693`，`docs/dataset-versioning.md` 又写 `27738384`；三个号不一致，我们钉 tag 解出来的那个 commit，题目内容按 registry 的 per-task digest 对）。HF 镜像 `benchflow/skillsbench`，只读、不 gated、和 GitHub 同内容。**87 道**默认题（`tasks/`），另 14 道 `tasks-extra/` 要凭据/GPU，官方不计分，我们也不发。 |
| cand | **容器状态**。求解器在那道题的容器里干活（工具调用经 `/place` 转发，和 deepswe 一样），要产出的是题面指定的绝对路径下的文件（50 题在 `/root/…`，13 题 `/app/…`，其余 `/data` `/home` `/workspace`）。交卷字符串本身**不看**（写什么都行）——判的是交卷那一刻容器里的文件。没有 patch、没有 commit。 |
| structure | 两个节点，官方判据拆成两段读：`verified`（官方 `verifier/test.sh` 跑完并写出了 `/logs/verifier/reward.txt`）→ `passed`（`reward == 1.0`，根）。边 `verified[0] → passed`。sink `passed`。`verified` 对应 BenchFlow harness「跑 test.sh、读 reward.txt」那一步；`passed` 对应论文 §3 的通过判据和 `experiments/scripts/run_benchflow_integration.py:549` 的 `reward == 1.0`。 |
| h_r | 每题 `tasks/<id>/verifier/test.sh`（87/87 `verifier.type: test-script`），几乎全是 `uvx pytest /verifier/test_outputs.py`，退出码 0 → `echo 1 > /logs/verifier/reward.txt`。论文原话：*A task passes iff all assertions in test_outputs.py succeed (reward = 1)*。**没有 LLM judge**：87 个 verifier 目录 grep `openai|anthropic|API_KEY|gpt-|claude` 只命中注释/数据字符串，`paratransit-routing/verifier/test.sh` 还主动 `unset` 所有 API key。所以**一道都不用舍弃**。确定性：pytest 断言，但 (a) 57 个 test.sh 判卷时 `apt-get`/`curl uv` 装依赖，版本钉死但要网；(b) **7 道写分数 reward**（`crystallographic-wyckoff-position-analysis` `debug-trl-grpo` `dialogue-parser` `drone-planning-control` `lab-unit-harmonization` `setup-fuzzing-py` `tictoc-unnecessary-abort-detection`，如 47/48=0.979），榜单是 `mean(reward)` 会给部分分，我们 G 是 bool 只认 1.0，这 7 道比榜单**严**；(c) `setup-fuzzing-py` 没有 `test_outputs.py`（`test_setup.py`+`test_lib.py`），无所谓，我们只跑 test.sh。 |
| boundary | 答案 = `verifier/`（含 `expected_output.json` `ground_truth.json` 等 18 种附件）+ `oracle/solve.sh`。两样只在判卷台那台机器的 `$HOME/.cache/tgengin-skillsbench/skillsbench/` 里；干活容器**从不**收到 `/verifier`——判卷时先 `docker commit` 干活容器成快照，再起一个**一次性**容器把 `verifier/` 拷进 `/verifier` 跑 `test.sh`（官方是 `verifier.service: main`、在同一容器里跑；我们改用快照是为了多次 verify 不把 apt/uv 装进干活容器，判据本身一字不改）。**但**：86/87 题官方 `environment.network_mode: public`，干活容器有网，而整个 benchmark（含 oracle）在 GitHub 公开——`git clone` 一下就是答案。这是官方设定，按官方跑；`--network none` 是本台子的旋钮，开了就不是榜单那个实验。判卷需要 docker + 网（57 个 test.sh 装依赖）。**Sherlock 没有 docker，台子只能在有 docker 的机器上跑（WSL 那台）。** |
| budget | c=6，K=8，T=官方 `agent.timeout_sec`（分布：600s×12、900s×21、1800s×27、3600s×12、7200s×3，中位 1800s=30min，上限 120min）。理由同 deepswe：也是「容器里干活 → verify → 照 note 改 → 再 verify」的回路，一次判卷是一趟 pytest（几十秒到几分钟，官方上限 `verifier.timeout_sec` 中位 1800s），c=6 够三趟来回；T 不另编，编了就和榜不可比。 |
| level | 0：只有 bool。1：`stage`（snapshot / verifier crashed / timed out / tests）+ `reward` 数值 + pytest 通过计数（81/87 个 test.sh 产出 `ctrf.json`，其余只有计数缺失）。2：+ 没过的测试名（ctrf `results.tests[].name`，≤60 条）。3：+ 断言原文（ctrf `message`，≤40 条×2000 字）。**注意 level 3 会漏 GT**：不少断言是 `assert got == 42, f"expected 42 got {got}"` 这种，原文里就是答案；level 3 只该当上界实验跑。 |
| m | **全部 87 道 m=∞**：产物是 docx/xlsx/pptx/代码/Lean 证明/CSV/JSON 等整个文件，不是选项或整数。N=(K+1)(c+1)+1=64，枚举可达 **0/87 = 0%**。个别题的一部分是小离散集（`tictoc` 交一组事务 id、`organize-messy-files` 分类到 5 个目录），但要交的是整个集合/整棵目录树，组合数远超 64。 |
| 已知坑 | ① tag 重打过（见来源），三个 commit 号；② 7 道分数 reward、13 个 test.sh 只在一个分支写 reward（崩了就没文件→`verified` 判 0，符合 harness 行为）；③ 87 个镜像要自己 build（ubuntu:24.04×53、python-slim×29、bugswarm×2、oss-fuzz、suricata），`build_timeout_sec` 最长 3600s，两道 bugswarm 题镜像很大；资源上限：`fix-druid-loophole-cve` 要 24 GB 内存，5 道要 8 核；④ `hardening.cleanup_conftests: true`（87/87）——官方 harness 判卷前删掉 agent 目录里的 `conftest.py` 防劫持 pytest，我们照做但 BenchFlow 的精确实现没看到（见未验证）；⑤ 数据污染：仓库公开半年、题面人写、答案在 oracle 里，模型可能背过；⑥ 「有 skills」条件：官方 harness（claude-code/codex/…）把 skill 名和描述注入 system prompt，我们的 solver 不是那些 harness，台子把 `environment/skills/` 拷到 `/root/skills` 和 `/root/.claude/skills`，`/problems` 附 skill 名+描述让 `send.ts` 拼进题面——这是**我们的**注入方式，和榜单上任一 harness 都不完全一样，`--skills none` 是 no-skill 对照；⑦ 依赖：台子只要 python3.11+、PyYAML、docker；判卷依赖在各题 test.sh 里自己装；⑧ `sec-financial-report/environment` 165 MB 数据在仓库里，clone 是 666 MB（超了 brief 的 100 MB，但它是仓库不是数据集，且已 `--depth 1`）。 |

## 说明

**为什么两个节点这么切。** 官方 harness 自己就是两段：跑 `test.sh`，然后读 `reward.txt`。`test.sh` 没跑出文件（崩、超时、OOM）和跑出 `0` 在榜上都是 0，但对求解器是两种信息——前者多半是环境问题不是答案问题。和 deepswe 的 `applies → resolved` 一样，没有另立尺子。

**cand 为什么是容器状态而不是文件清单。** 题面已经写死输出路径，verifier 直接 `open('/root/xxx')`。让求解器交「文件列表」再由台子拷出来，等于我们替官方判据决定看哪些文件——它要是还检查 `/root` 下不该有什么、或者 lean 项目要整个编译，就漏了。快照整个容器，官方判据看它想看的。

**分数 reward 怎么处理。** 论文的通过判据是二值的（reward=1）；leaderboard 的 `mean(reward)` 对那 7 道是部分分。我们的 G 值域是 bool，取 `reward == 1.0`。跟论文一致，跟榜单在这 7 道上差一点（我们更严）。`note` 里带 reward 数值，事后要算榜单口径能算。

**skills 是这个 benchmark 的自变量。** 论文比的是「同一模型有/无 skills」。台子 `--skills with|none` 是两趟实验，G 的形状不变。

## 未验证（代码没在这台机器上跑过）

1. `stand.py` 整份没跑过：Sherlock 上无 docker、且登录节点禁 python。
2. task.md 的 YAML frontmatter 用 PyYAML 解析——假设 `schema_version: '1.3'` 的 87 份都能 `yaml.safe_load`（只看了 3 份）。
3. `docker commit` 出来的快照能否直接 `docker create … bash /verifier/test.sh`：要求镜像里有 bash（53 道 ubuntu:24.04 有；29 道 `python:*-slim` 是 Debian 也有；suricata/oss-fuzz 未查）。
4. `cleanup_conftests` 的官方实现没看到（BenchFlow 是另一个仓库，没 clone）；我们做的是 `find / <workdir> /root -maxdepth 1 -name conftest.py -delete`（只删顶层，不动题目仓库自己的 conftest），范围可能和官方不同；agent 放在 cwd 的 `pytest.ini`/`pyproject.toml` 改 rootdir 这条路没堵。
5. verifier 容器的 `/logs` 用 bind mount，容器里以 root 写，宿主普通用户删不掉——照抄了 deepswe 的 `wipe()` 借容器删，没在这套镜像上试过。
6. Dockerfile 里 `WORKDIR` 用正则抓最后一条当 agent 的 cwd（66 道 `/root`、15 道 `/app`…），带变量的那一条（`WORKDIR ${WORKSPACE}`）会抓成字面量，那道题得手改。
7. `/place` 转发那套（`Runtime` 类、`/rt` 二进制）整段照抄 deepswe，假设 `dist/tgengin-runtime-linux-x64` 在这些镜像里能跑（glibc 版本：ubuntu:20.04 的两道 bugswarm 题存疑）。
8. 快照缓存键用 `docker diff` 的路径集合 + 90 s TTL，同一 hand-in 的两个节点共用一次判卷；改了文件内容但没改路径集合、且在 90 s 内再 verify 会读到旧判决——设计上接受，没实测。
9. 官方 oracle 是否假定「无 skills 注入」——`run_benchflow_integration.py:392` 里 oracle 模式不注入，自检照此。
10. 87 个镜像的总磁盘、build 总时长没量过。
