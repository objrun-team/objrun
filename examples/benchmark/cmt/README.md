# cmtbench

[← 例子](../../) ｜ [tool](../../tool/) · [meet-join](../../meet-join/) · [meet-book](../../meet-book/) · [place](../../place/) · [rule](../../rule/) · [skill](../../skill/) · [mode](../../mode/) · **cmtbench**

[CMT-Benchmark](https://arxiv.org/abs/2510.05228)：50 道凝聚态理论的研究级题目，专家出的。
这个例子把它整批发进引擎，**判卷用官方那套**（LaTeX→Sympy），出一张成绩单。

用得上引擎的这几样：`/bench` 一整批发、**验证函数 G**、verifier-guided 的树
（判 0 就换条路重试）。

```
                         Windows                          WSL
   ┌──────────────────────────────────────┐   ┌────────────────────────┐
   │  引擎 tgengin-win-x64.exe            │   │  判卷台 grader.py      │
   │    place=local ← 智能体在这儿解题    │──▶│    官方 cmtbench 判据  │
   │    G 的两个节点 = 两条 http 句柄     │   │    题库 cmt_data.jsonl │
   └──────────────────────────────────────┘   └────────────────────────┘
```

**`place: local` 是引擎那台机器（Windows），不是 WSL。** 判卷台不是一个 place ——
它是一条 `http://` 句柄。两根轴不一样：`place` 说的是执行单元在哪儿干活，
句柄名前缀说的是那个句柄的实现在哪个进程。G 走的是句柄，不过位置转发那一层。

判卷台之所以在 WSL，只是因为官方评分代码要 Python ≥3.12，而这台机器 Windows 上
只有 Microsoft Store 那个空壳（`python --version` 一个字都不输出）。Windows 上有
真 Python 的话原地就能跑，引擎一个字不用改 —— 它只认那两个 URL。

---

## 一、备料

```bash
ssh wsl "bash /mnt/e/sgu-bzhc/EACN_EX/TgEngin/examples/benchmark/cmt/setup.sh"
```

（`ssh wsl` 不通就换 `wsl.exe -d Ubuntu-24.04 -- bash -lc "..."`，等价。这台机器上
WSL 重启之后 localhost 转发有时候回不来，sshd 明明听着 2222 也连不上。）

[`setup.sh`](./setup.sh) 干三件事，幂等。**三样全落在 `~/.cache/tgengin-cmt/`（WSL 家目录），
一样都不落仓库**：

| 落在哪儿 | 从哪儿来 |
| --- | --- |
| `~/.cache/tgengin-cmt/cmt_data.jsonl` | HuggingFace `JVRoggeveen/cmt_benchmark`，50 行 |
| `~/.cache/tgengin-cmt/vendor/cmt_benchmark_data/` | GitHub `JamesRoggeveen/cmt_benchmark_data`，官方评分代码 |
| `~/.cache/tgengin-cmt/venv` | sympy 1.13.3 / numpy 2.2.5 / regex 2024.11.6 |

```
── 1/3 题库 ──
下好了 50 行
── 2/3 官方评分代码 ──
克隆到 c114183
── 3/3 python 依赖 ──
装 uv（不用 root）
uv 0.12.7
sympy 1.13.3｜numpy 2.2.5｜regex 2.5.148

── 自检：官方判据能不能加载、判得对不对 ──
  √ cmt-0（HF）parsed=True equiv=True 
  √ cmt-1（HF）parsed=True equiv=True 
  √ cmt-2（HF）parsed=True equiv=True 
  √ cmt-3（HF）parsed=True equiv=True 
  √ cmt-4（HF）parsed=True equiv=True 
  拿 GT 当回答：5 道里 5 道判等价
```

自检是拿题库自己的 GT 当回答喂回去 —— 判据装对了就该 5/5。

### oracle 放哪儿：这是安全边界，不是整理癖

题库带 GT，是 oracle。solver 手上有 `read` / `glob` / `bash`，而它干活的地方
（`place: local`）**就是引擎那台机器** —— 题库放仓库里的话，它 glob 一下就找到。

**实测发生过**：模型先 `read grader.py` 搞清楚判据怎么比，接着 `read` 官方 parser
源码，然后 `glob` 到了 `cmt_data.jsonl`。那一跑它还没来得及读出 GT 就被判完了，
但路已经摸到门口。所以现在题库和判据都搬到 WSL 家目录 —— Windows 那侧的 solver
够不着那个路径。

发批的脚本也因此**读不到题库**，题得走 HTTP 取：

```bash
curl -s 'http://127.0.0.1:7901/problems?n=1'
```
```json
[{"index":0,"prompt":"Consider a spinful electron system…","parameters":"$U_0;U_1$",
  "functions":"","type":"HF"}]
```

**没有 `solution` 这一栏** —— 答案不出判卷台那个进程。

> **还漏着一条，说清楚**：判卷台在 `127.0.0.1:7901` 上，而 solver 的 `bash` 跟引擎在
> 同一台机器上。它要是猜到这个地址，`/equiv` 就成了一个免费的验证 oracle（提交候选、
> 回一个 bool，可以刷）。`readable: false` 只挡住「读 G 的定义」，挡不住「往那个端口打」。
> 真要堵死得把判卷台连题库一起塞进容器、只对引擎那个进程开口 —— 这台机器上暂时没有
> 容器 runtime，所以现在这条**是靠没写在任务描述里，不是靠够不着**。

### 三个坑

**版本要照抄官方 pin。** 自己搓一套 LaTeX 归一去比字符串的话，分数跟论文那张表就不可比，
那这一趟白跑。

**只装三个包。** 官方 `pyproject.toml` 还列着 openai / anthropic / google-genai /
datasets / matplotlib —— 那是它「拿模型跑一遍」和「画图」那半边要的，判卷用不上。

**绕开 `cmtbench/__init__.py`。** 它顶上 `from .query import ...`，而 `query.py` 要
openai 那一堆。[`grader.py`](./grader.py) 手工塞一个同名命名空间包，只加载
`evaluator` + `parser` + `parser_rules`，依赖因此收到三个。

## 二、判卷台

```bash
ssh wsl "cd /mnt/e/sgu-bzhc/EACN_EX/TgEngin/examples/benchmark/cmt \
         && ~/.cache/tgengin-cmt/venv/bin/python grader.py"
```
```
[cmt] 判卷台起来了：http://0.0.0.0:7901/{parsed,equiv}｜题库 50 道
```

[`grader.py`](./grader.py) **不实现任何判断**，只做三件事：接 HTTP、按官方
`scripts/evaluate.py` 那套分支挑该用哪个 evaluator、把结果缓存住。

```python
if parameters == "" and functions == "":
    if PARSER.parse_numeric_solution(solution).success:
        r = EV.evaluate_numeric_solution(response, solution_string=solution)
    else:
        r = EV.evaluate_solution(response, solution_string=solution, parameter_string=parameters)
elif parameters != "" and functions == "" and "NC" not in parameters:
    r = EV.evaluate_solution(response, solution_string=solution, parameter_string=parameters)
else:
    r = EV.evaluate_functional_solution(response, solution_string=solution,
                                        parameter_string=parameters, function_string=functions)
```

回的是官方那两栏：`success`（解析得出来吗）和 `is_equivalent`（跟 GT 等价吗）。

```bash
curl -s http://127.0.0.1:7901/health
```
```json
{"ok": true, "items": 50}
```

### 换成容器（题库和判据一起打包进去）

```bash
docker compose -f examples/benchmark/cmt/compose.yaml up -d --build
```

[`Dockerfile`](./Dockerfile) 把题库、官方判据（钉在 `c114183`）、三个 python 包和
`grader.py` 全封进镜像，构建时跑一遍 `--selftest`（拿 GT 当回答喂回去，该 5/5）
—— **装错了在 build 就炸，不会等到跑 bench 才发现**。

**引擎一个字不用改。** 它只认 `http://127.0.0.1:7901/{parsed,equiv}` 这两个名字，
后面是 WSL 里的一个 venv 还是一个容器，跟它无关 —— 这正是「句柄名就是地址」这条的用处。

`compose.yaml` 里 `127.0.0.1:7901:7901` 的 `127.0.0.1:` 别去掉：不写的话 Docker 会把
这个口发布到所有网卡，判卷台就从「本机一个进程」变成「局域网里谁都能打」。

验它，**从 Windows 那侧打**（引擎实际走的就是这条路）：

```bash
curl -s http://127.0.0.1:7901/health
curl -s -X POST http://127.0.0.1:7901/equiv -H 'content-type: application/json' \
  -d '{"input":{"task":{"id":"cmt-0","result":"So the answer is $\\boxed{\\frac{U_1}{2}}$"}}}'
```
```
{"ok": true, "items": 50}
                                     GT 是 U_1/2
  U_1/2  → parsed=true  equiv=true
  U_0/2  → parsed=true  equiv=false
```

**它解决的是可移植和可复现，不是那个洞。** 见下。

#### 在 WSL 里用 snap 的 docker，踩了三个坑

都不是这个例子特有的，但不写下来下次还得再撞一遍。

**一、snap 是严格 confinement，只读得到 `$HOME`。** 构建上下文在 `/mnt/e/...` 上，
`docker build` 直接就 permission denied —— 得先把 `Dockerfile` / `grader.py` 拷进
WSL 家目录再 build。（Docker Desktop 没这限制。）

**二、`dockerd` 拿不到你 shell 里的代理。** 代理 `export` 在 `~/.bashrc` 里，那是
**交互 shell** 才 source 的；`dockerd` 是个 systemd 服务，从来没经过任何 shell。
拉基础镜像是 **daemon 自己**发的请求，所以 `--build-arg http_proxy=…` 白给
（那个只管容器里的 `RUN`）。`snap set docker proxy.*` 也不接 —— 配了重启了，
`docker info` 里还是没有 proxy 栏。管用的是给 systemd 单元加 drop-in：

```bash
sudo mkdir -p /etc/systemd/system/snap.docker.dockerd.service.d
printf '[Service]\nEnvironment="HTTP_PROXY=http://%s:7890"\nEnvironment="HTTPS_PROXY=http://%s:7890"\nEnvironment="NO_PROXY=localhost,127.0.0.1,::1"\n' \
  "$(ip route show default | awk '{print $3}')" "$(ip route show default | awk '{print $3}')" \
  | sudo tee /etc/systemd/system/snap.docker.dockerd.service.d/proxy.conf
sudo systemctl daemon-reload && sudo snap restart docker
```

`docker info` 里出现 `HTTP Proxy:` 那行才算配上。地址是 **WSL 的默认网关**（不是
`localhost` —— NAT 模式转不过去），而且 `wsl --shutdown` 之后会变，变了要重写。

**三、`# syntax=` 那行会去 Docker Hub 拉 frontend 镜像。** 网络不稳的话它先炸在
`auth.docker.io`。现在的内置 frontend 自己就认 heredoc，所以那行删了 —— 少一次
网络往返，少一个失败点。

同理，Dockerfile 里**一个 apt 包都不装**：`git` / `curl` 只是为了拉两个文件，
python 自带的 `urllib` + `tarfile` 就够。`deb.debian.org` 走的是明文 HTTP，
在代理后面实测 502（`Failed to fetch … 502 Bad Gateway`）—— 而且这是个放着答案的
容器，能少一样是一样。建完的镜像里 `command -v git` / `curl` 都是空的，跑的是 uid 10001。

### 容器堵不住的那一条

上面说过 `/equiv` 能被 solver 当验证 oracle 刷。装进容器**不解决这个** ——
端口还是发布在同一台机器的 `127.0.0.1` 上，solver 的 `bash` 照样打得到。

往句柄名里塞个随机 token（`…/equiv?k=xxx`）也不行，我查过了：句柄是主库
`handle` 表里的一行，而 `/query` 是开放接口，solver 一条 SQL 就把 token 读出来了。
`readable: false` 封的是 **G 的定义**（在另一个库里），封不住句柄名。

真要堵死只有一条路：**让 solver 那个 place 够不着这个端口** —— 把执行单元也放进
一个网络受限的容器/沙箱里，只放行它该有的出口。那是 `place` 这一维的事，不是判卷台的事。

在那之前，这一条的实际状态是：**没把地址写进任务描述，仅此而已。** 记在这儿，
别让它被当成已经堵上了。

## 三、引擎

```bash
cp config.yaml dist/
dist/tgengin-win-x64.exe &
```
```
模型：deepseek-v4-flash｜出 16384 token（续写最多 3 次）｜思考 high
```

这三个旋钮在 `config.yaml` 的 `llm:` 底下，**这个例子对它们很敏感**：

| | |
| --- | --- |
| `maxTokens: 16384` | 开 `reasoning_effort: high` 之后思考本身就能吃掉整个额度。8192 那一跑 19 个执行单元里 12 个**一个字都没答出来** —— 不是不会做，是没写完就到顶了 |
| `continueTimes: 3` | `finishReason === "length"` 时把已出的这段当 assistant 前缀续写，最多三次 |
| `retryTimes: 3` | 一次调用炸了重打，第 n 次前多等 `5n` 秒。堵的是 SDK 的 `Failed to process successful response` ——「200 回来了但读不懂」，那一层的重试管不了，而内核按设计不重试，一次抖动就挂到 `expect_ms` 到点 |

## 四、跑一趟

```bash
bash examples/benchmark/cmt/run.sh 5 cmt-w
```

[`run.sh`](./run.sh) 把下面这几步串起来。

### 底子 + 判卷台那两条句柄

```bash
curl -s -X POST $BASE/declare -H 'content-type: application/json' -d @- <<'JSON'
{ "places":[{"place":"local"}],
  "modes":[{"mode":"solve","cycles":[
    {"cycle":"ask","apiMode":"chat","maxUnits":6,"from":[],      "next":["act"],"infer":"fn:infer.dfs"},
    {"cycle":"act",                 "maxUnits":6,"from":["ask"], "next":["ask"],"infer":"fn:infer.dfs"}]}],
  "agents":[{"name":"bot","apis":[["DEEPSEEK_API_KEY","deepseek-v4-flash"]],"unit":"fn:unit.tools"}],
  "handles":[
    {"name":"http://127.0.0.1:7901/parsed","expectMs":60000},
    {"name":"http://127.0.0.1:7901/equiv", "expectMs":60000}] }
JSON
```
```json
{"handles":["http://127.0.0.1:7901/parsed","http://127.0.0.1:7901/equiv"],
 "places":["local"],"modes":["solve"],"cycles":2,"agents":["bot"],
 "servers":{},"tools":[],"rules":[],"skills":[],
 "tables":["task_solve","agent_bot_ctx","agent_bot_msg"],"entries":{"solve":["ask"]}}
```

**句柄名就是地址**，没有别的注册动作。

`ask` / `act` 两站的机制：`ask` 让模型开口，`act` 走 `fn:unit.tools` 把它请求的工具
真跑掉。`infer` 是 `fn:infer.dfs` —— 这一条决定了这是**走树的机制**，判死会开兄弟，
而且树自省那两个工具会挂上来（见下）。

### 条件有没有毛病，发批之前先问

```bash
curl -s $BASE/check
```
```json
{"trigger":[],"data":[]}
```

空 = 全通。条件写错了**不报错**，只是那条永远不触发 —— 所以这一问得在发批之前，
不能等跑起来才发现。

（`run.sh` 在这两步之间还会挂一个从老仓库搬来的 skill，
见[最后那一节](#从老仓库搬过来的那一个-skill)。）

### 每道题的 G

```json
{
  "nodes": [
    { "name":"parsed", "moment":"task_done", "domain":"bool", "handle":"http://127.0.0.1:7901/parsed" },
    { "name":"equiv",  "moment":"task_done", "domain":"bool", "handle":"http://127.0.0.1:7901/equiv"  }],
  "edges": [{ "src":"parsed", "out":0, "dst":"equiv" }],
  "sink": "equiv"
}
```

两个节点正好是原基准自己报的那两栏。**根必须有入边** —— 一个节点的 G 发布这一关就被拒：

```
输出节点 graded 没有任何入边 —— 它的值与候选无关，G 恒定，是无效目标
```

### 发一批

[`send.ts`](./send.ts) **从判卷台 `/problems` 取题**（它自己读不到题库，见上），拼请求体。
**题面进 `description`，`solution` 不进** —— 智能体那一侧看不到答案。

```bash
bun examples/benchmark/cmt/send.ts 5 cmt-w
```
```
cmt-w：5 道
```

一道题的完整形状（`POST /bench` 的 `tasks[]` 里一项）：

```json
{ "id":"cmt-0", "mode":"solve", "agent":"bot", "place":"local", "source":"user",
  "domain":"physics",
  "solveSeconds": 900,
  "description":"Consider a spinful electron system in a two-dimensional triangular lattice…\n\n符号：$U_0;U_1$\n\n把最终答案放进 \\boxed{} 里。",
  "objective": { …上面那个… },
  "readable": false }
```

`domain: "physics"` 是**扩展分发用的** —— 下面那个 skill 就靠它。它跟 `mode` 是两回事：
`mode` 是推理机制（这儿是 ask/act 两站的树），`domain` 是这道题属于哪个领域。

`readable: false` —— 带 G 就必须显式给：这道题的智能体读不读得到 G 的定义。
`source` 只有 `user` 能带 G，智能体自己派生的任务不许带（那是自提权）。

**一道不过就整批不发。** 发一半的话成绩单的分母是错的，而且没人看得出来少了哪几道。

---

## 判卷台看到了什么

```
[cmt] cmt-0（HF）parsed=True  equiv=False ｜答尾 …So energy per site = U0/2.  $$\boxed{\frac{U_0}{2}}$$
[cmt] cmt-1（HF）parsed=True  equiv=False err=Number of expressions do not match: 4 vs 2
[cmt] cmt-4（HF）parsed=True  equiv=False ｜答尾 …exactly what breaks TR. Yes.  So the answer is (g).  $\boxed{g}$
[cmt] cmt-2（HF）parsed=False equiv=False err=Failed to parse model response: Unexpected error during pars…
[cmt] cmt-3（HF）parsed=False equiv=False err=Failed to parse model response: Unexpected error during eval…
```

**`parsed` 和 `equiv` 分开报是有用的**，两种失败要干的活完全不同：

| | |
| --- | --- |
| `parsed=True equiv=False` | **答错了**。`cmt-0` 答 `U_0/2`，GT 是 `U_1/2`；`cmt-1` 多给了两个自旋翻转项，4 个表达式对不上 2 个 |
| `parsed=False` | **格式没接住** —— 官方 parser 读不出来。可能物理上是对的，只是写法没合上口径 |

混成一个数的话，你分不清模型是不会做还是格式没对齐。论文里也是分开报的
（`parser_stats_summary` 和 `eval_stats_summary` 是两个文件）。

---

## 判 0 之后：判决进上下文，然后换条路

判 0 的题**不会收工**。`fn:infer.dfs` 拿到 G 的 0，做两件事：

**一、把判决投进上下文** —— 投成「一次带结果的工具调用」：

```bash
curl -s -X POST $BASE/query -H 'content-type: application/json' -d @- <<'JSON'
{ "sql": "select instance, unit, body from agent_bot_msg where kind='tool' and body like '%\"name\":\"verify\"%' limit 2" }
JSON
```
```json
{"instance":"cmt-0#1","unit":1,
 "body":"{\"id\":\"g-cmt-0#1-1-4\",\"name\":\"verify\",\"value\":{\"pass\":0,\"why\":\"equiv 判了 false\"}}"}
```

不当 `user`（模型会去接话辩解）、不当 `system`（instructions 每轮重发会糊在一起）、
不当 `assistant`（等于伪造它的轨迹）—— 它是**外部的、这一次的观测**，正好是 tool
结果的语义。`why` 一起给：只给 0/1 的话它只知道错了，不知道错在哪，下一条分支多半
原样再来一遍。

**二、把这一站盖上 `dead_failed`，在同一个父底下开一个兄弟换条路。**

```bash
curl -s -X POST $BASE/query -H 'content-type: application/json' -d @- <<'JSON'
{ "sql": "select task, count(*) as units, sum(case when status is not null then 1 else 0 end) as dead from task_solve group by task" }
JSON
```
```json
{"count":5,"rows":[
  {"task":"cmt-0","units":8, "dead":4},
  {"task":"cmt-1","units":9, "dead":4},
  {"task":"cmt-2","units":9, "dead":4},
  {"task":"cmt-3","units":10,"dead":3},
  {"task":"cmt-4","units":8, "dead":4}]}
```

**不许节点自己说了算，这就是 verifier-guided 的全部意思。** 模型说「我做完了」只是自评；
G 说 0，那就是「以为到了其实没到」。

## 兄弟看得见什么

新开的兄弟**默认只接单链**（直系祖先 root→父）。判死的那几条是别人的分支，
**默认不接入** —— 开兄弟正是为了换条路走，把另一条分支的话直接塞进来，两次尝试就
互相污染了。

但「不默认接入」不等于「看不见」。走树的机制会额外挂上两个工具（条件
`cycle.infer = fn:infer.dfs`，写在 `trigger` 里 —— 一条道走到黑的单链机制一个都拿不到）：

| | |
| --- | --- |
| `task_tree` | 看全树：试过哪几条、谁被判死了 |
| `node_load(unit)` | 读某一站说了什么，**连同它的判决** |

这一跑里模型**自己**用了 11 次：

```bash
curl -s -X POST $BASE/query -H 'content-type: application/json' -d @- <<'JSON'
{ "sql": "select count(*) as n from agent_bot_msg where kind='call' and (body like '%task_tree%' or body like '%node_load%')" }
JSON
```
```json
{"count":1,"rows":[{"n":11}]}
```

`cmt-0` 那条链看得最清楚 —— 被判死两次之后，它主动去读了前两条失败分支：

```
unit 1  答了 → G 判 0
unit 2  兄弟：答了 → G 判 0
unit 4  node_load(1)   ← 去读第 1 站说了什么
unit 6  node_load(2)   ← 再读第 2 站
unit 7  答了 → G 判 0
```

不是编排出来的：工具摆在那儿，它自己决定要看。

## 成绩单

```bash
curl -s $BASE/bench/cmt-w
```
```json
{"run":"cmt-w","total":5,"passed":0,"failed":5,"running":0,"open":0,
 "tasks":[
  {"id":"cmt-0","state":"failed","result":"{\"pass\":0,\"why\":\"equiv 判了 false\"}"},
  {"id":"cmt-1","state":"failed","result":"{\"pass\":0,\"why\":\"equiv 判了 false\"}"},
  {"id":"cmt-2","state":"failed","result":"{\"pass\":0,\"why\":\"equiv 判了 false\"}"},
  {"id":"cmt-3","state":"failed","result":"{\"pass\":0,\"why\":\"equiv 判了 false\"}"},
  {"id":"cmt-4","state":"failed","result":"{\"pass\":0,\"why\":\"equiv 判了 false\"}"}]}
```

**成绩是数出来的，不是存着的。** 存一份会跟真相漂，而且漂了不报错。

`failed` 得看 `why` 才知道是哪一种：

| `why` | |
| --- | --- |
| `equiv 判了 false` | **G 真判了 0** —— 树把该走的路走完了，是被判不成 |
| `超过 solve_seconds` | **耗光了** —— 一直没走到判决就没时间了 |

这一跑五道全是前者，一道超时都没有。

> 分数不是这个例子的重点。题是研究级的（论文里最好的 GPT-5 也只有 30%，
> DeepSeek v3 是 4%），这儿只跑了 50 道里的前 5 道、全是 HF 型。要跟论文那张表对齐，
> 得单轮问一次、跑满 50 道 —— 这儿是带工具的多轮 + 判 0 重试，本来就不是同一件事。

---

## 从老仓库搬过来的那一个 skill

老仓库（`OS_gui` 的 `mb/full`，`5128c075`）底下有 89 个 skill、74 个 tool、44 条 rule。
**这边只搬 cmt 用得上的那个**：`cmt-pre-symmetry-projection` —— 一段群投影的通用方法，
只投方法不投答案。

原样放在 [`parmeras/`](./parmeras/)，来源记在 [`parmeras/SOURCE.txt`](./parmeras/SOURCE.txt)。

### 怎么注册进去

```bash
bun examples/benchmark/cmt/parmeras/load.ts
```
```
cmt-pre-symmetry-projection：解题机制的提问站上，面对涉及对称性的物理题时投。关键词取自它自己的名字和正文标记

进去了：cmt-pre-symmetry-projection
```

一个 `.md` = frontmatter + 正文，这边一行 `skills[]` 要的正好是这三样：

| `.md` | → | `skills[]` |
| --- | --- | --- |
| `name` | | `identity` |
| `description` | | `does` |
| frontmatter 之后那一整段 | | `body` |

发出去的就是一条普通的 `/declare`，没有别的入口：

```json
{ "skills": [{
    "identity": "cmt-pre-symmetry-projection",
    "does": "边际处境标记——对称性投影（CMT）。注入通用群投影方法/定理：…只投方法不投答案。",
    "params": {}, "role": "user",
    "body": "=== 边际处境标记 + 通用方法(symmetry_projection)===\n…",
    "when": [[ …六条，见下… ]] }] }
```

塞进上下文之后**它的 role 是 `skill`，不是 `user`**：

```bash
curl -s -X POST $BASE/query -H 'content-type: application/json' -d @- <<'JSON'
{ "sql": "select role, kind, count(*) as n from agent_bot_msg group by role, kind order by n desc" }
JSON
```
```json
{"rows":[{"role":"system","kind":"inject","n":58},{"role":"tool","kind":"tool","n":41},
         {"role":"assistant","kind":"call","n":30},{"role":"assistant","kind":"prompt","n":19},
         {"role":"skill","kind":"skill","n":12},{"role":"user","kind":"user","n":5}]}
```

`role: user` 只剩真人发的那 5 条任务描述。**skill 有自己的身份**，走 `instructions`
不进消息流 —— 借 `user` 的话等于告诉模型「有人在跟你说这段话」，它会去接话：实测
过一版，模型回的是「请把本题的具体选项发出来，我会逐一代入该方法判断」，不再作答。

### `trigger` 是一张关键词匹配表

老系统的触发条件长这样：`constants: [[["coding"], ["fits","card"]]]` —— 三层：
组间 or、组内 and、项内 or。这边一比一装得下，**不用加维、不用加列**：

| 老的 | 这边 |
| --- | --- |
| 最外层（组间 or） | `trigger.group` |
| 中间层（组内 and） | 同组多行 |
| 最里层（同义词 or） | `op: "in"`，`value` 是一份 JSON 列表 |

一个 `value` 一个关键词 —— 带空格会被 `check` 拦下来（「拆成同一组的两条，别让系统猜」）。

### 一组条件就是一句话

「**哪个智能体、在什么时候、做什么事、面对什么问题，该拿到什么**」，这句话本身就是
一组条件。只写一两条等于没用这张表，所以这个 skill 的门写满了六条：

```ts
when: [[
  { dim: "task",  key: "domain",      op: "eq",       value: "physics" },          // 面对什么问题
  { dim: "task",  key: "description", op: "contains", value: "symmetry" },
  { dim: "task",  key: "mode",        op: "eq",       value: "solve" },            // 在做什么事
  { dim: "task",  key: "source",      op: "in",       value: '["user","eacn"]' },  // 谁发的
  { dim: "cycle", key: "cycle",       op: "eq",       value: "ask" },              // 什么时候
  { dim: "place", key: "",            op: "eq",       value: "local" },            // 在哪儿
]]
```

`cycle = ask` 那条要紧：这是**模型开口那一站**，不是跑工具那一站，塞晚了没用。

### 关键词从扩展自己身上来

同样是 `description contains "symmetry"`，**词是哪儿来的**决定它是正经匹配还是作弊：

| 词的来源 | |
| --- | --- |
| 扩展自己声明的 | ✔ 它在说「我是干这个的」，跟数据集里命中几道无关 |
| 翻了 50 道题挑出来的 | ✘ 拿样本挑样本，给一部分题开小灶，分数虚高还查不出来 |

这个 skill 自己声明得很清楚：名字 `cmt-pre-symmetry-projection`、描述「对称性投影（CMT）」、
正文头一行 `=== 边际处境标记 + 通用方法(symmetry_projection)===`。词取自这儿。

`domain` 是 `task` 上的一列（`physics` / `chem` / `coding`），发任务时给。它跟 `mode`
是两回事：**`mode` 是推理机制**（cot / tot / 树），**`domain` 是问题属于哪个领域**。

### 验这道门，不用发任务

```bash
for t in cmt-1 cmt-0 other-1; do
  curl -s -X POST $BASE/trigger/explain -H 'content-type: application/json' \
    -d "{\"kind\":\"skill\",\"owner\":\"cmt-pre-symmetry-projection\",
         \"task\":\"$t\",\"mode\":\"solve\",\"cycle\":\"ask\",\"place\":\"local\"}"
done
```
```
cmt-1    fired=true    六条全中
cmt-0    fired=false   symmetry 那条没中，其余五条中
other-1  fired=false   domain 和 symmetry 都没中（那是道 coding 题）
```

`explain` 会把**实际取到的值**一起摆出来 —— 没命中最常见的两个原因（词根本不在那段
文本里、维度上根本没那个属性）都得看着实际值才认得出来。

塞进去之后在上下文里是一行 `kind: "skill"`（`GET /tasks/cmt-1/messages?kind=skill`）
—— 跟人写的分得开。

### 两个坑

**skill 的条件不能写 `moment`。** skill 是在 `#advance` 里 fire 的，那份 facts 不带
moment（只有规则走的 `#atMoment` 才设）—— 写了就永远不中，而且不报错。

**词别贪多。** 一开始多写了一条 `description contains "wave"`（想着这方法是讲波函数的），
结果 cmt-1 题面里没这个词，整组被卡掉。同组是 and，多一条就多一道门。

### 剩下那些为什么没搬

| | 数量 | |
| --- | --- | --- |
| skills | 89 | 47 个是降级实验自动生成的；其余是 SWE-bench / ResearchCodeBench / 化学那几套的专用纪律，这边没搭那些 benchmark |
| tools | 74 | 能搬（`input_schema` 直接就是 `inputSchema`，`class.context` 正好对上 place 这一维），但要一个 Python MCP server 加载，而且化学那批依赖 rdkit |
| rules | 44 | 时刻对不上：`pre_task`(25) 大致对应 `unit_start`，但 `pre_tool`(3) / `post_tool`(5) / `on_node_claim`(3) / `on_task_retry`(2) / `on_phase_enter`(1) 这边没有；`judge`(5) 在这边根本不是 rule，是 **G** |

---

## 文件

| | |
| --- | --- |
| [`setup.sh`](./setup.sh) | 备料。题库 + 官方判据 + venv，幂等（不用容器那条路） |
| [`Dockerfile`](./Dockerfile) · [`compose.yaml`](./compose.yaml) | 判卷台连题库一起打包（用容器那条路，二选一） |
| [`grader.py`](./grader.py) | 判卷台。**判据是官方的，这个文件只接 HTTP**；另开一个 `/problems` 发题面 |
| [`send.ts`](./send.ts) | 从 `/problems` 取题，拼 `POST /bench` 的请求体 |
| [`run.sh`](./run.sh) | 声明 → 挂扩展 → 发批 → 等 → 成绩单 |
| [`parmeras/`](./parmeras/) | 从老仓库搬来的 skill + 注册脚本 |

题库和官方判据**不在这个目录里**，在 `~/.cache/tgengin-cmt/`（WSL 家目录）——
见[上面那一节](#oracle-放哪儿这是安全边界不是整理癖)。
