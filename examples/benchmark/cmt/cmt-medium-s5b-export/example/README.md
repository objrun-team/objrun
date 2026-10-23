# cmtbench

[← 例子](../../) ｜ [tool](../../tool/) · [meet-join](../../meet-join/) · [meet-book](../../meet-book/) · [place](../../place/) · [rule](../../rule/) · [skill](../../skill/) · [mode](../../mode/) · **cmtbench**

[CMT-Benchmark](https://arxiv.org/abs/2510.05228)：50 道凝聚态理论的研究级题目。
这个例子把它整批发进引擎，判卷用官方那套（LaTeX→Sympy），出一张成绩单。
最后一节是我们跑出来的基线。

```
                         Windows                          WSL
   ┌──────────────────────────────────────┐   ┌────────────────────────┐
   │  引擎 tgengin-win-x64.exe            │   │  判卷台 grader.py      │
   │    place=local ← 智能体在这儿解题    │──▶│    官方 cmtbench 判据  │
   │    G 的两个节点 = 两条 http 句柄     │   │    题库 cmt_data.jsonl │
   └──────────────────────────────────────┘   └────────────────────────┘
```

判卷台在 WSL，只是因为官方评分代码要 Python ≥3.12。Windows 上有真 Python 的话原地
就能跑，引擎一个字不用改 —— 它只认那两个 URL。

**题库带标准答案，所以它只在判卷台那一侧**（WSL 家目录或容器里），不在这个目录、
也不在仓库里。发题的脚本一样读不到，题走 HTTP 取。

---

## 一、备料

```bash
ssh wsl "bash /mnt/e/sgu-bzhc/EACN_EX/TgEngin/examples/benchmark/cmt/setup.sh"
```

`ssh wsl` 不通就换 `wsl.exe -d Ubuntu-24.04 -- bash -lc "..."`，等价。

[`setup.sh`](./setup.sh) 幂等，三样都落在 `~/.cache/tgengin-cmt/`：

| 落在哪儿 | 从哪儿来 |
| --- | --- |
| `cmt_data.jsonl` | HuggingFace `JVRoggeveen/cmt_benchmark`，50 行 |
| `vendor/cmt_benchmark_data/` | GitHub `JamesRoggeveen/cmt_benchmark_data`，钉在 `c114183` |
| `venv` | sympy 1.13.3 / numpy 2.2.5 / regex 2024.11.6 |

```
── 自检：官方判据能不能加载、判得对不对 ──
  √ cmt-0（HF）parsed=True equiv=True
  ...
  拿 GT 当回答：5 道里 5 道判等价
```

版本照抄官方 pin：自己搓一套 LaTeX 归一的话，分数跟论文那张表就不可比。只装那三个包
—— 官方 `pyproject.toml` 里的 openai / anthropic / google-genai / datasets / matplotlib
是它「拿模型跑一遍」和「画图」那半边要的，判卷用不上。

## 二、判卷台

```bash
ssh wsl "cd /mnt/e/sgu-bzhc/EACN_EX/TgEngin/examples/benchmark/cmt \
         && ~/.cache/tgengin-cmt/venv/bin/python grader.py"
```
```
[cmt] 判卷台起来了：http://0.0.0.0:7901/{parsed,equiv}｜题库 50 道
```

[`grader.py`](./grader.py) 不实现任何判断：接 HTTP、按官方 `scripts/evaluate.py` 那套
分支挑 evaluator、把结果缓存住。回的是官方那两栏 `success` / `is_equivalent`。

**从 Windows 那侧验**（引擎走的就是这条路）：

```bash
curl -s http://127.0.0.1:7901/health
curl -s -X POST http://127.0.0.1:7901/equiv -H 'content-type: application/json' \
  -d '{"input":{"task":{"id":"cmt-0","result":"So the answer is $\\boxed{\\frac{U_1}{2}}$"}}}'
curl -s 'http://127.0.0.1:7901/problems?n=1'
```
```
{"ok": true, "items": 50}
  U_1/2 → parsed=true equiv=true      （cmt-0 的 GT 就是 U_1/2）
[{"index":0,"prompt":"Consider a spinful electron system…","parameters":"$U_0;U_1$","functions":"","type":"HF"}]
```

`/problems` **没有 `solution` 这一栏** —— 答案不出这个进程。

### 换成容器（题库和判据一起打包进去）

```bash
docker compose -f examples/benchmark/cmt/compose.yaml up -d --build
```

[`Dockerfile`](./Dockerfile) 把题库、官方判据、三个 python 包和 `grader.py` 封进镜像，
构建时跑一遍 `--selftest`（该 5/5）。引擎一个字不用改，它只认那两个 URL。

`compose.yaml` 里 `127.0.0.1:7901:7901` 的 `127.0.0.1:` 别去掉 —— 不写的话这个口会
发布到所有网卡。

在 WSL 的 snap docker 上有三条要注意：

```bash
# 一、snap 是严格 confinement，只读得到 $HOME：构建上下文得先拷进家目录
mkdir -p ~/build && cp Dockerfile grader.py ~/build/ && cd ~/build && docker build .

# 二、dockerd 是 systemd 服务，拿不到 shell 里的代理（拉基础镜像是它自己发的请求）
sudo mkdir -p /etc/systemd/system/snap.docker.dockerd.service.d
printf '[Service]\nEnvironment="HTTP_PROXY=http://%s:7890"\nEnvironment="HTTPS_PROXY=http://%s:7890"\nEnvironment="NO_PROXY=localhost,127.0.0.1,::1"\n' \
  "$(ip route show default | awk '{print $3}')" "$(ip route show default | awk '{print $3}')" \
  | sudo tee /etc/systemd/system/snap.docker.dockerd.service.d/proxy.conf
sudo systemctl daemon-reload && sudo snap restart docker
docker info | grep -i proxy      # 出现 HTTP Proxy: 那行才算配上
```

地址要用 **WSL 的默认网关**，不是 `localhost`；`wsl --shutdown` 之后会变。

三、`# syntax=` 那行会去 Docker Hub 拉 frontend，网络不稳先炸在 `auth.docker.io` ——
不需要就别写。Dockerfile 里也一个 apt 包都不装（`deb.debian.org` 走明文 HTTP，
代理后面实测 502），拉两个文件用 python 自带的 `urllib` + `tarfile` 就够。

## 三、引擎

```bash
cp config.yaml dist/
dist/tgengin-win-x64.exe &
```
```
models: fn:api.deepseek, fn:api.dashscope | 16384 output tokens (up to 3 continuations) | reasoning medium
db …\data\h2h.sqlite | write on | token none
```

`config.yaml` 的 `llm:` 底下这几个旋钮，这个例子对它们敏感：

| | |
| --- | --- |
| `reasoningEffort` | 七档：`none` · `minimal` · `low` · `medium` · `high` · `xhigh` · `max`。**这一档得跟题目、模型、时限一样记进成绩单** —— 同一道题在不同档上耗时差着数量级。单个智能体可以用 `agent.knobs` 钉死自己那一档（`searcher` 钉的是 `none`） |
| `maxTokens: 16384` | 思考本身就能吃掉整个额度。8192 那一跑 19 个执行单元里 12 个一个字都没答出来 |
| `continueTimes: 3` | `finish_reason = length` 时把已经产出的（**包括思维链**）接回去续写，最多三次 |
| `retryTimes: 3` | 一次调用炸了重打，第 n 次前多等 `5n` 秒。哪些错该重打由 `api.retry_on` 那一列说了算 |

跑之前把 WSL 钉住 —— 判卷台在里面，而 WSL2 空闲时会回收整个虚拟机：

```bash
wsl.exe -d Ubuntu-24.04 -- sleep infinity &
```

## 四、跑一趟

```bash
TGENGIN_CMT_BARE=1 TGENGIN_CMT_AT_ONCE=20 bash examples/benchmark/cmt/run.sh 0 cmt-run
```

| 参数 | |
| --- | --- |
| 第一个位置参数 | 几道题。`0` = 判卷台有多少发多少 |
| 第二个位置参数 | 这一跑叫什么 |
| `TGENGIN_CMT_BARE=1` | 不挂领域扩展（无扩展基线） |
| `TGENGIN_CMT_AT_ONCE=20` | 同时做 20 道，做完一道补一道。留空 = 整批一次全发 |
| `TGENGIN_CMT_ONLY=3,5,8` | 只发点名的那几道（按题库下标）。空 = 不挑 |
| `TGENGIN_CMT_SECONDS=900` | 每道题多久。默认 3600 |

[`run.sh`](./run.sh) 把下面这几步串起来。

### 底子

```bash
curl -s -X POST $BASE/declare -H 'content-type: application/json' -d @- <<'JSON'
{ "places":[{"place":"local"}],
  "modes":[{"mode":"solve","cycles":[
    {"cycle":"ask","apiMode":"chat","maxUnits":35,"from":[],      "next":["act"],"infer":"fn:infer.dfs"},
    {"cycle":"act",                 "maxUnits":35,"from":["ask"], "next":["ask"],"infer":"fn:infer.dfs"}]}],
  "agents":[
    {"name":"bot","apis":[["DEEPSEEK_API_KEY","deepseek-v4-flash"]],"unit":"fn:unit.tools"},
    {"name":"searcher","apis":[["DEEPSEEK_API_KEY","deepseek-v4-flash"]],"unit":"fn:unit.tools",
     "knobs":{"reasoningEffort":"none"}}],
  "handles":[
    {"name":"http://127.0.0.1:7901/parsed","expectMs":60000},
    {"name":"http://127.0.0.1:7901/equiv", "expectMs":60000}] }
JSON
```

句柄名就是地址，没有别的注册动作。`ask` 让模型开口，`act` 把它请求的工具真跑掉；
`infer: fn:infer.dfs` 决定了这是走树的机制 —— 判 0 就在同一个父底下开兄弟换条路。

一道纯推导题用不上文件系统，那几个 system 工具关掉（改的是 `usable` 那一列，纯数据）：

```bash
curl -s -X POST $BASE/exec -H 'content-type: application/json' -d @- <<'JSON'
{ "sql": "update tool set usable = 0 where name in ('bash','read','write','edit','glob','grep')" }
JSON
```

条件写错了不报错，只是那条永远不触发，所以发批之前先问一次：

```bash
curl -s $BASE/check          # {"trigger":[],"data":[]} = 全通
```

### 每道题的 G

```json
{ "nodes": [
    { "name":"parsed", "moment":"task_done", "domain":"bool", "handle":"http://127.0.0.1:7901/parsed" },
    { "name":"equiv",  "moment":"task_done", "domain":"bool", "handle":"http://127.0.0.1:7901/equiv"  }],
  "edges": [{ "src":"parsed", "out":0, "dst":"equiv" }],
  "sink": "equiv",
  "checks": 10 }
```

两个节点正好是原基准自己报的那两栏。根必须有入边，否则发布这一关就拒：
`输出节点 … 没有任何入边 —— 它的值与候选无关，G 恒定，是无效目标`。

`checks` 是**一轮里能主动问几次 G**（`verify` 工具），判死重来是新的一轮。

### 一道题的形状

[`send.ts`](./send.ts) 从 `/problems` 取题，拼 `POST /bench` 的请求体：

```json
{ "id":"cmt-0", "mode":"solve", "agent":"bot", "place":"local", "source":"user",
  "domain":"physics",
  "solveSeconds": 3600,
  "maxBranches": 4,
  "maxDeadSiblings": 8,
  "maxSearches": 5,
  "noSearch": ["cmt benchmark", "cmt dataset", "cmt jsonl"],
  "description":"Consider a spinful electron system in a two-dimensional triangular lattice…\n\nSymbols: $U_0;U_1$\n\nPut the final answer inside \\boxed{}.",
  "objective": { "…上面那个…": null },
  "readable": true }
```

| | |
| --- | --- |
| `solveSeconds` | 每道题多久。要长过一次调用的死期（模型那条句柄 `expect_ms` 是 15 分钟），否则「一次调用卡住 → 判死这一站 → 换条路」永远走不到 |
| `maxSearches: 5` | 一站准搜五次。判死重来是新的额度，被拦下的和超额被拒的不扣数 |
| `noSearch` | 不许搜到这套题本身。一条项是**一组词**，全都出现才算命中；整份检索结果（答复、跑过的查询串、开过的页）只要命中就整份丢掉，模型拿到一句 `Forbidden access` |
| `readable: true` | 带 G 就必须显式给（没有默认值）。给 `true` 会把 G 的定义并进任务描述 —— 要藏的只有 GT，不是尺子 |
| `source: "user"` | 只有 `user` 能带 G，智能体自己派生的任务不许带 |
| `domain: "physics"` | 扩展按它分发，跟 `mode`（推理机制）是两回事 |

一道不过就整批不发 —— 发一半的话成绩单的分母是错的，而且没人看得出来少了哪几道。

### 成绩单

```bash
curl -s $BASE/bench/cmt-run
```
```json
{"run":"cmt-run","total":50,"passed":44,"failed":6,"running":0,"open":0,
 "tasks":[{"id":"cmt-0","state":"done","result":"{\"pass\":1,\"why\":\"\"}"}]}
```

成绩是数出来的，不是存着的。`failed` 得看 `why`：`equiv evaluated to false` 是 G 真判了 0，
`over solve_seconds=…` 是时间先没了。

---

## 我们的基线

`cmt-medium-s5b`，2026-09-01。**50 道全量、每道一小时、思考 `medium`、不挂扩展、
检索每站 5 次、同时做 20 道。**

```bash
TGENGIN_CMT_BARE=1 TGENGIN_CMT_AT_ONCE=20 bash examples/benchmark/cmt/run.sh 0 cmt-medium-s5b
```

### 44 / 50

失败的六道（`cmt-2` `cmt-11` `cmt-37` `cmt-44` `cmt-46` `cmt-49`）判词都一样：
`over solve_seconds=3600s; equiv evaluated to false` —— **走满一小时、手上有答案、
答案不对**，没有一道是交不出来的。

44 道做对里，第一个交给 G 的答案就对的是 **19 道**，其余 25 道验了不止一次才对。
后者两种混着：一种是「算错了、看到 false、回去改推导」，另一种是「把选项一个个报过去」
—— 选择题的答案空间比一轮 10 次的额度还小。**要一个更严的数就报第一答**，
库里每道题都记着。

### 一小时花在哪

| | |
| --- | --- |
| 问模型 | 762 次 × 62 秒 = **65%** |
| 等检索 | 153 次 × 133 秒 = **28%** |
| 跑别的工具 | 559 次 × 8 秒 = 6% |

一共走了 1,474 站。检索 102 次：34 道题用过，最多的一道 8 次，7 次撞到每站 5 次的上限。
每次调用输入 98,011 token（88% 命中缓存），输出 6,842，其中思考 6,398。

### 数据

`data/runs/cmt-medium-s5b/`（`data/` 不进仓库）：

| | |
| --- | --- |
| `h2h.sqlite` | 这一跑的整个库 |
| `engine.log` · `run.log` | 引擎日志、跑批日志 |
| `RESULT.md` | 这一跑的完整结论 |
| `export/csv/{tasks,stations,verify,searches}.csv` | 四种粒度的表 |
| `export/FIELDS.md` | 每一列是什么意思 |

---

## 文件

| | |
| --- | --- |
| [`setup.sh`](./setup.sh) | 备料。题库 + 官方判据 + venv，幂等（不用容器那条路） |
| [`Dockerfile`](./Dockerfile) · [`compose.yaml`](./compose.yaml) | 判卷台连题库一起打包（用容器那条路，二选一） |
| [`grader.py`](./grader.py) | 判卷台。判据是官方的，这个文件只接 HTTP；另开一个 `/problems` 发题面 |
| [`send.ts`](./send.ts) | 从 `/problems` 取题，拼 `POST /bench` 的请求体 |
| [`run.sh`](./run.sh) | 声明 → 关掉用不上的工具 → 挂扩展 → 发批 → 等 → 成绩单 |
| [`parmeras/`](./parmeras/) | 从老仓库搬来的 skill + 注册脚本（`TGENGIN_CMT_BARE` 就是不挂它） |

题库和官方判据不在这个目录里，在 `~/.cache/tgengin-cmt/`（WSL 家目录）或容器里。
