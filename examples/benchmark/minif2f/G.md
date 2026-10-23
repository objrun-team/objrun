# miniF2F（Lean 4）的 G

| 字段 | 内容 |
| --- | --- |
| **来源** | 论文 [arXiv:2109.00110](https://arxiv.org/abs/2109.00110)（Zheng, Han, Polu 2021，原版 MIT 许可）。Lean 4 版两处来源，都不 gated：**test 244** = HF [AI-MO/minif2f_test](https://huggingface.co/datasets/AI-MO/minif2f_test) @ `5def318348521dfc34875045a9ecddf729a2b49f`（Apache-2.0，Kimina 团队修正版，[Kimina-Prover Preview](https://github.com/MoonshotAI/Kimina-Prover-Preview) @ `7abd61a5`，[arXiv:2504.11354](https://arxiv.org/abs/2504.11354)）；**valid 244** = [DeepSeek-Prover-V1.5](https://github.com/deepseek-ai/DeepSeek-Prover-V1.5) @ `2c4ba911` 的 `datasets/minif2f.jsonl`（AI-MO 没发 valid；DeepSeek 版就是 AI-MO 修正的底本）。合计 488，名字全局唯一。Lean/Mathlib 钉死：`leanprover/lean4:v4.15.0`，Mathlib tag `v4.15.0` = `9837ca9d65d9de6fad1ef4381750ca688774e608`，REPL [leanprover-community/repl](https://github.com/leanprover-community/repl) tag `v4.15.0` = `21966799`。理由：Kimina 公开的 226 份证明的 `lean-toolchain` / `lake-manifest.json` 就是这一组，自检要靠它们 |
| **cand** | 一段完整的 Lean 4 文件文本：官方 header（`import Mathlib` … `open … Rat`，可省）+ 官方 `theorem <name> … := by` 逐字 + 缩进的 tactic 证明体。可裹在 ```lean 围栏里。台子只取 `:= by` 之后的部分送去编译 |
| **structure** | `stated → compiles → sound`，根 `sound`。`stated`：前缀（去注释、压空白）== 官方 header+声明，之后每个非空行都缩进（`stand.py:split_cand`，Lean 特有前置）。`compiles`：`not kimina_client.models.is_error(resp)`（REPL 消息里没有 `severity=error`）。`sound`：`not has_sorry(resp)` ∧ `#print axioms <name>` ⊆ {`propext`,`Classical.choice`,`Quot.sound`}（默认 + `Lean.ofReduceBool`）。没有第四格 `kernel_ok`：elaboration 无 error 即内核已过；绕内核只能靠公理（`sound` 现形）或顶格 `set_option debug.skipKernelTC`（`stated` 拦下） |
| **h_r** | Lean 4 编译器 + Mathlib，确定性。读结果的函数是官方的：`kimina-lean-server/client/kimina_client/models.py` 的 `is_error` / `has_sorry` / `is_valid`（"Valid means no error and no sorry"）；拼接协议是 DeepSeek-Prover-V1.5 `prover/lean/verifier.py:verify_lean4_file` 的 `header + formal_statement + 补全`（`complete = pass and not sorries`）。**没有任何 LLM 判卷**，488 道一道不舍弃。公理检查是我们比 Kimina 多加的一道（他们不查；`native_decide` 默认放行以对齐榜单） |
| **boundary** | 没有标准答案可藏 —— 证明即答案，判的是编译。Kimina 公开的 226 份证明装在台子侧 `golden/`，只自检用，`/problems` 不发。但它们**在 GitHub 上公开**（`minif2f_test_solved*.zip`），求解侧必须关 `web_search`，`noSearch` 写上 "Kimina-Prover-Preview minif2f_test_solved"。判卷不需要容器、不需要网（装好之后）；需要一台能跑 Lean 的机器（Sherlock 计算节点；每个 REPL ~3 GB 内存） |
| **budget** | **c=12, K=8, T=60 min**。一次判卷 = 一次编译（5–60 s，300 s 超时）；c 比 cmt 的 10 略高是因为 Lean 的自然工作方式就是「编译—看 goal—改」，12 够五六个来回，不够过一遍二三十条的 hammer 单子。K=8 同 cmt/deepswe。T=60 min：Kimina 是无反馈整证明采样，这里的对手是「带反馈的一个人」，一小时是 IMO 一题的量级 |
| **level** | 0：只 bit。1：哪一格断的 + 没闭合的 goal（`unsolved goals` 错误和 `sorries` 里的 `⊢` 行，≤8 条）+ 公理列表。2：+ 每条 error 的 `line/col`（相对 `theorem` 行）和第一行。3：+ Lean 报错原文（≤40 条 × 4000 字）。全部来自 REPL 的 JSON，台子不生成任何解释 |
| **m** | **∞**（证明文本）。N=(K+1)(c+1)+1=118，m ≤ N 的题：**0 / 488 = 0%**。但要说清「hammer 先验」：Kimina 公开的 197 份 test 证明里 **45 份（23%）是单行 tactic**，即至少 45/244 = 18% 的 test 题一条 `norm_num`/`nlinarith`/`omega`/`interval_cases … <;> omega` 就中——这些不是「答案空间小」，是「解空间里有个便宜点」，c=12 挡的是这个 |
| **已知坑** | 见下 |

## 结构说明

```
stated ──→ compiles ──→ sound          sink = sound；checks = 12
```

- 送去编译的永远是 **官方 header + 官方声明 + 候选证明体 + `#print axioms <name>`**（一条 REPL 命令，`env: 0` 是跑过 header 的环境）。声明被改**在构造上不可能**发生；`stated` 只是把「你交的前缀跟官方不一样」作为可读的 0 说出来，而不是默默编译另一道题。
- `compiles` 判 0 而 `sound` 不再判：内核按拓扑序跑，下游看 `feed[0].value !== true` 直接回 `{value:false}`（同 deepswe）。
- 一道题一份候选只编译一次（按 sha256 缓存），三格读同一次的结果。

## h_r 出处（逐条）

| 判断 | 官方代码 | 位置 |
| --- | --- | --- |
| 有 error 吗 | `is_error(response)`: `any(m["severity"] == "error" for m in messages)` | `client/kimina_client/models.py` |
| 有 sorry 吗 | `has_sorry(response)`: `len(sorries) > 0` | 同上 |
| 拼接协议 | `header + formal_statement + completion` → REPL `{"cmd": …}` | DeepSeek-Prover-V1.5 `prover/lean/verifier.py` |
| 公理 | Lean `#print axioms`（`src/Lean/Elab/Print.lean`: `'{name}' depends on axioms: […]`） | Lean 核心，我们只正则读那一行 |

台子里**自己写的**判断只有两处，都在 `stated`：注释/空白规范化后的字符串相等，和「`:= by` 之后每个非空行缩进」。前者是 DeepSeek 协议的显式化，后者是 Lean 4 语法（tactic 块只认缩进行）。

## 答案空间与枚举

| 项 | 值 |
| --- | --- |
| m | ∞ |
| N = (K+1)(c+1)+1 | 118 |
| m ≤ N 的题 | 0 / 488（0%） |
| 单行证明（Kimina 197 份公开证明） | 45（23%） |
| 用了 `native_decide` 的公开证明 | 11 / 197 |

## 已知坑

| 坑 | 说明 |
| --- | --- |
| **AI-MO 版 vs DeepSeek 版 test 声明不同** | 逐条 diff：**19 条**不一样（卡片列了 14 条修正 + 5 条未列：`mathd_algebra_158` 加 cast、`amc12a_2021_p18` `/.`→`/`、`algebra_ineq_nto1onlt2m1on` `<`→`≤`、两条 `∏` 加括号）。报分数时必须写明是 AI-MO 版；跟 DeepSeek-Prover 系列的 test 数字不严格可比 |
| **valid 没人修过** | 244 道照 DeepSeek 版，其中有多少不可证不知道（test 里被修了 19 条，valid 大概率也有个位数）。valid 分数只当开发集看 |
| **数据污染** | test 证明公开（Kimina zip、各家 HF 数据集 `*minif2f*sols*`）；valid 常被各家拿去 RL 训练。榜单只报 test；求解侧关网 |
| **`maxHeartbeats 0`** | header 关掉了 Lean 的心跳上限，一条 `nlinarith` 能跑到天荒地老。300 s 墙上超时 + `RLIMIT_AS` 8 GB 是唯一的闸；超时算 0，note 说 `timed out` |
| **`native_decide`** | 留下 `Lean.ofReduceBool`（信任编译器）。榜上都认，默认认；`TGENGIN_MF2F_STRICT_AXIOMS=1` 不认，那时 Kimina 11 份公开证明会判 0 |
| **golden 早于修订** | Kimina zip（2025-04/07）里 6 份的声明跟 2025-07 的 AI-MO 不同（`mathd_algebra_314`、`aime_1995_p7`、`amc12a_2019_p12`、`amc12a_2021_p22`、`amc12b_2002_p4` + 1），自检跳过 |
| **REPL v4.15.0 没有 `gc`** | 常驻 REPL 内存只涨不落；`MAX_USES=16` 换新。Kimina 官方 Docker 用的是 `FrederickPu/repl@lean415compat`（加了 `gc`），我们用官方 tag 保持可追溯 |
| **Kimina Lean Server 在 Sherlock 装不上** | 它 import `prisma`（需要 node + 新 glibc），CentOS 7 glibc 2.17 过不去；所以默认后端是台子自己起 REPL，只 vendored 它的 `models.py`（纯 Python：pydantic/pygments/colorama/tabulate） |
| **磁盘** | Mathlib .olean 5–6 GB + 工具链 1 GB，`$HOME` 15 GB 放不下；真身在 `$SCRATCH`，90 天不改就清，清了重跑 setup.sh |
| **依赖** | elan/Lean v4.15.0、Mathlib v4.15.0、REPL v4.15.0、jq、unzip、python ≥3.10（`str | None` 语法）+ 四个纯 Python 包。不需要 docker/sympy/rdkit |
| **许可证** | miniF2F MIT；AI-MO 数据 Apache-2.0；Kimina Lean Server MIT；REPL Apache-2.0；Mathlib Apache-2.0；DeepSeek-Prover-V1.5 仓库 MIT（数据文件同仓） |


## 定稿决定（2026-09-25）

| 决定 | 主跑 record | 对照臂（另一条 record，不混报） |
|---|---|---|
| 门数 | 三门 `stated → compiles → sound`，`why` 能区分「改了题」和「证不出」 | 无 |
| checks | 12（`TGENGIN_MF2F_CHECKS` 默认） | c=4：量 hammer 单子扫不完时曲线掉多少 |
| 公理 | 默认放行 `Lean.ofReduceBool`（与 Kimina / Seed 榜单口径一致） | `TGENGIN_MF2F_STRICT_AXIOMS=1`（与 AlphaProof 的最终检查一致） |
| 题集 | 先 test 244（AI-MO 修正版） | valid 244 待 test 通过后再跑 |
| 分层报告 | 单行 tactic 命中的题单独一层（Lean 上的 Prop enum 形态） | |

`objective.ts` 不改，以上全由环境变量和 record 记录。

## 未验证

代码在登录节点上一行没跑过。下面这些是复读时确定**没验证**的地方：

1. **Lean v4.15.0 的 Linux 二进制在 CentOS 7 / glibc 2.17 上能不能跑**。跑不了就得 apptainer（`ml system apptainer`）套 Kimina 的镜像，但那个镜像是 v4.26.0，Kimina 公开证明未必全过 —— 那时要重新钉版本、放弃一部分自检。
2. **`lake exe cache get` 对 v4.15.0 这个老 tag 还有没有缓存**。没有的话 `lake build` Mathlib 全量编译要几小时、几十 GB 内存。
3. **REPL v4.15.0 的输出框架**：假定「JSON + 空行」，照 Kimina `_read_response` 写的；`pretty` 输出里 JSON 字符串内不会出现裸空行（`\n` 是转义的）。
4. **`#print axioms` 在 REPL 里以 `severity: "info"` 的消息回来**，且格式为 `'<name>' depends on axioms: [a, b, c]`（v4.15.0 `Print.lean` 第 158/160 行确认了文本，消息通道未跑）。
5. **REPL 里 `env: 0`** 确实是 header 那条命令回的 env 号（README 说第一个环境标号从 0 起；Kimina 也写死 `env = 0`）。
6. **elaboration 出 error 后 `#print axioms <name>` 仍能找到该声明**（Lean 有错误恢复，一般会加进环境并带 `sorryAx`）；找不到时 `axioms=None` → `sound=0`，note 里 `axioms: null`，不会误判成 1。
7. **`split_cand` 对 golden 的 226 份全部通过**：在登录节点用 awk 做了等价的逐字比对（220 通过、6 不同），Python 版规范化未跑。
8. **Kimina 后端的行号平移**：`_apply_header_offset` 只按 import 行平移，我们再减整个 header 行数——正负号没跑过。
9. **datasets-server rows API 给的是最新 revision**，靠 `/api/datasets` 的 sha 断言钉版本；HF 改了 sha 脚本会停。
10. **`ml python/3.12.1` 建的 venv 里 pydantic 的 manylinux wheel 在 glibc 2.17 上可用**（pydantic-core 2.x 提供 manylinux2014 轮子，应当可以）。
11. **`RLIMIT_AS` 8 GB 够不够 `import Mathlib`**（Kimina 默认 8G，同一假设）。
12. `selftest` 默认取 `golden_ids()[:5]`，即按文件名排序的前 5 道；没看它们的编译时间，可能有慢的。

### 2026-09-25 实跑后的状态

- 1 Lean 二进制在 glibc 2.17 上**能跑**，但工具链 clang 不能 → REPL 链接失败；改在 apptainer（bookworm）里跑，通过。
- 2 `lake exe cache get` 对 v4.15.0 仍有缓存：通过（unpack 15 s）。
- 3/4/5 REPL 框架、`#print axioms` 的 info 消息、header 的 env=0：自检 5 道通过，形状如预期。
- 6 sorry 对照 5/5 判 `compiles=1, sound=0`。
- 7 全量 225 份 golden 自检：作业 `minif2f-selftest-all` 跑中。
- 10/12 venv 轮子、elan-init 参数：容器内通过。
- 11 RLIMIT_AS 8G：首题 import Mathlib 19.7 s 无 OOM。

### 2026-09-25 全量自检后的一处改动：`stated` 认辅助引理

225 份 golden 全量自检 211 过、14 挂。14 里 8 份是**先写 `lemma` 再证主定理**（Kimina 的输出格式，也是 Seed-Prover 的整个范式），
3 份是 AI-MO 后来修订过声明（amc12a_2019_p12 加了正性假设、amc12b_2002_p4 有理数写法、mathd_algebra_314 加了 `: ℝ`），
2 份只是 `open Real Set` 这样的 header 不同，1 份（amc12a_2002_p13）声明一致但 golden 本身编译不过（待查首条报错）。

原来的 `stated` 要求候选**只能是**官方声明 + 缩进证明体，把前两类都判 0，这会让 TgEngin 的分数与 Kimina / Seed 系统性不可比。
改成：候选按顶格命令切分，只认四种 —— `import Mathlib|Aesop`（丢弃）、`set_option maxHeartbeats N`（丢弃）、`open …`（保留）、
辅助 `lemma`/`theorem`（保留，不得与官方定理同名）；最后一条必须是官方声明逐字 + `:= by` + 缩进证明体。
其它顶格命令（`def`、`axiom`、其它 `set_option`、`namespace`、`macro`……）一律拒。
送去编译的是 官方 header + 候选的 open/引理 + 官方声明 + 证明体 + `#print axioms`。辅助引理里的 `sorry` / 公理逃不掉：
主定理用到就进 `#print axioms`，没用到也让 `sorries` 非空，`sound` 都判 0。

### 2026-09-25 收尾：225 份 golden 全量自检 = 220 过

| 未过 | 数 | 原因 | 处置 |
|---|---|---|---|
| amc12a_2019_p12、amc12b_2002_p4、mathd_algebra_314 | 3 | AI-MO 修订过声明，golden 用的是旧声明 | `stated` 判 0 是正确的；note 说「声明与官方不同」 |
| aime_1995_p7 | 1 | golden 自带 `open Real Set` 头；换成官方 header（多开了 `Nat` `Rat`）后 `sqrt` 三义，编译失败 | 保持 header 固定（DeepSeek-V1.5 / Goedel 协议）；这份 golden 在本协议下就是不合格。记为协议差异，不改台子 |
| amc12_2000_p1 | 1 | 第一轮 123 s 判 1，第二轮 REPL 进程死掉（`repl closed stdout`） | 台子偶发：judge 遇 `repl died` 换新进程重试一次；REPL 内存上限 8 → 12 GB |

所以在本协议下 golden 的真实通过率是 221/222（除去 3 份旧声明），唯一的 1 是 header 协议差异。
