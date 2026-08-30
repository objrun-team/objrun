# cmtbench

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

[`setup.sh`](./setup.sh) 干三件事，幂等：

| | 从哪儿来 |
| --- | --- |
| `cmt_data.jsonl` | HuggingFace `JVRoggeveen/cmt_benchmark`，50 行 |
| `vendor/cmt_benchmark_data/` | GitHub `JamesRoggeveen/cmt_benchmark_data`，官方评分代码 |
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

前两样都不进 git（`.gitignore`）：题库带 GT，是 oracle。

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

## 三、引擎

```bash
cp config.yaml dist/
dist/tgengin-win-x64.exe &
```

## 四、跑一趟

```bash
bash examples/benchmark/cmt/run.sh 5 cmt-demo
```

[`run.sh`](./run.sh) 把下面这几步串起来。

### 底子 + 判卷台那两条句柄

```bash
curl -s -X POST $BASE/declare -H 'content-type: application/json' -d @- <<'JSON'
{ "places":[{"place":"local"}],
  "modes":[{"mode":"solve","cycles":[
    {"cycle":"ask","apiMode":"chat","maxUnits":6,"from":[],      "next":["act"],"infer":"fn:infer.dfs"},
    {"cycle":"act",                 "maxUnits":6,"from":["ask"], "next":["ask"],"infer":"fn:infer.dfs"}]}],
  "agents":[{"name":"bot","apis":[["DEEPSEEK_API_KEY","deepseek-chat"]],"unit":"fn:unit.tools"}],
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

[`send.ts`](./send.ts) 读题库拼请求体。**题面进 `description`，`solution` 不进** ——
智能体那一侧看不到答案。

```bash
bun examples/benchmark/cmt/send.ts 5 cmt-demo
```
```
cmt-demo：5 道
```

一道题的完整形状（`POST /bench` 的 `tasks[]` 里一项）：

```json
{ "id":"cmt-0", "mode":"solve", "agent":"bot", "place":"local", "source":"user",
  "solveSeconds": 900,
  "description":"Consider a spinful electron system in a two-dimensional triangular lattice…\n\n符号：$U_0;U_1$\n\n把最终答案放进 \\boxed{} 里。",
  "objective": { …上面那个… },
  "readable": false }
```

`readable: false` —— 带 G 就必须显式给：这道题的智能体读不读得到 G 的定义。
`source` 只有 `user` 能带 G，智能体自己派生的任务不许带（那是自提权）。

**一道不过就整批不发。** 发一半的话成绩单的分母是错的，而且没人看得出来少了哪几道。

---

## 判卷台看到了什么

```
[cmt] cmt-0（HF）parsed=True  equiv=True  ｜答尾 …N = \frac{U_1}{2}$$  $$\boxed{\displaystyle \frac{U_1}{2}}$$
[cmt] cmt-4（HF）parsed=True  equiv=True  ｜答尾 …massive) layers, so the distinct masses present no obstacle.
[cmt] cmt-1（HF）parsed=True  equiv=False err=Number of expressions do not match: 4 vs 2
[cmt] cmt-2（HF）parsed=False equiv=False err=Failed to parse model response: Could not parse '\\ (2.09, 0…
[cmt] cmt-3（HF）parsed=False equiv=False err=Failed to parse model response: SymPy parsing error: invalid…
```

`parsed` 和 `equiv` 分开报是有用的：`cmt-1` 是**答错了**（解析出来了，4 个表达式对不上 2 个），
`cmt-2`/`cmt-3` 是**格式没接住**（官方 parser 读不出来）。这两种失败要分开看 ——
论文里也是分开报的。

## 判 0 之后：换条路再来

```
G 判了 cmt-0：1
G 判了 cmt-4：1
```

判 1 的收工。判 0 的那几道**没有停** —— `fn:infer.dfs` 拿到 G 的 0，把这一站盖上
`dead_failed`，在同一个父底下开一个兄弟换条路走：

```bash
curl -s $BASE/tasks/cmt-1/tree | grep -o '"chain":"[^"]*"\|"status":"[a-z_]*"'
```
```
"chain":"solve/ask#1"
"chain":"solve/ask#1 > solve/act#2"
"status":"dead_failed"
"chain":"solve/ask#1 > solve/act#2 > solve/ask#3"
```

**不许节点自己说了算，这就是 verifier-guided 的全部意思。** 模型说「我做完了」只是自评；
G 说 0，那就是「以为到了其实没到」。

## 成绩单

```bash
curl -s $BASE/bench/cmt-demo
```
```json
{"run":"cmt-demo","total":5,"passed":2,"failed":0,"running":3,"open":0,
 "tasks":[
  {"id":"cmt-0","state":"done",   "result":"{\"pass\":1,\"why\":\"\"}"},
  {"id":"cmt-1","state":"claimed","result":null},
  {"id":"cmt-2","state":"claimed","result":null},
  {"id":"cmt-3","state":"claimed","result":null},
  {"id":"cmt-4","state":"done",   "result":"{\"pass\":1,\"why\":\"\"}"}]}
```

**成绩是数出来的，不是存着的。** 存一份会跟真相漂，而且漂了不报错。

上面这张是跑到一半的快照：2 道判过，3 道还在换路重试，到 `solveSeconds` 才收。

> 这不是论文那张表上的数。论文是**单轮问一次**，这儿是带工具的多轮、判 0 还会重试，
> 而且只跑了 50 道里的前 5 道（全是 HF 型）。要跟论文对齐得单轮、跑满 50 道。

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
cmt-pre-symmetry-projection：只投方法（群投影），不投答案

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
    "when": [[{ "dim":"task","key":"run",        "op":"contains","value":"cmt" },
              { "dim":"task","key":"description","op":"contains","value":"symmetr" }]] }] }
```

### `when` 是这边定的，不是搬来的

老系统的触发维度叫 `constants`，这边是 `agent/task/cycle/chain/moment/place`，
**没有 constants 这一维**。所以门得重新写，而且写死在 [`load.ts`](./parmeras/load.ts)
的 `GATE` 里 —— 挑出来的东西就把门也说清楚，不靠名字前缀去猜。

两项在**同一组**所以是 and：`run` 里含 `cmt`，**并且**题面提到 `symmetr`。
只卡 `run` 的话 50 道全塞 —— 提示本身不含答案，但塞到无关的题上一样是噪声。
题面带 `symmetr` 的是 13 道。

不用发任务就能验这道门：

```bash
curl -s -X POST $BASE/trigger/explain -H 'content-type: application/json' \
  -d '{"kind":"skill","owner":"cmt-pre-symmetry-projection","task":"cmt-1"}'
```
```json
{"fired":true,"groups":[[
  {"dim":"task","key":"description","op":"contains","value":"symmetr","got":"…preserve translational symmetry…","hit":true},
  {"dim":"task","key":"run",        "op":"contains","value":"cmt",    "got":"cmt-demo","hit":true}]]}
```

```bash
curl -s -X POST $BASE/trigger/explain -H 'content-type: application/json' \
  -d '{"kind":"skill","owner":"cmt-pre-symmetry-projection","task":"cmt-0"}'
```
```json
{"fired":false,"groups":[[
  {"dim":"task","key":"description","op":"contains","value":"symmetr","got":"…ground state energy per site?…","hit":false},
  {"dim":"task","key":"run",        "op":"contains","value":"cmt",    "got":"cmt-demo","hit":true}]]}
```

`cmt-1` 塞，`cmt-0` 不塞。塞进去之后在上下文里是一行 `kind: "skill"`
（`GET /tasks/cmt-1/messages?kind=skill`）—— 跟人写的分得开。

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
| [`setup.sh`](./setup.sh) | 备料。题库 + 官方判据 + venv，幂等 |
| [`grader.py`](./grader.py) | 判卷台。**判据是官方的，这个文件只接 HTTP** |
| [`send.ts`](./send.ts) | 读题库拼 `POST /bench` 的请求体 |
| [`run.sh`](./run.sh) | 声明 → 发批 → 等 → 成绩单 |
| [`parmeras/`](./parmeras/) | 从老仓库搬来的 skill + 注册脚本 |
| `cmt_data.jsonl` | 题库（不进 git） |
| `vendor/` | 官方评分代码（不进 git） |
