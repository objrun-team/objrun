# AIME 2024–2025 的 G

slug `aime`。四场（2024 I/II、2025 I/II）共 60 题，每题答案是 0–999 的整数。
判卷 = 从答卷里读出一个整数，跟官方答案相等。

| 字段 | 内容 |
| --- | --- |
| **来源** | 赛题：MAA 的 AIME（无论文）。题面与答案取自 HF 三个公开集，全钉 commit：<br>· 2024：`AI-MO/aimo-validation-aime` @ `13f9e12f`，Apache-2.0，parquet，90 道（22–24）里取 url 含 `2024_AIME` 的 30 道。题面自 AoPS wiki，答案带官方三位写法（`"025"`）<br>· 2025：`math-ai/aime25` @ `563bb840`，Apache-2.0，jsonl 30 道，`answer` 是干净 int<br>· 对账：`opencompass/AIME2025` @ `a6ad95f6`，MIT，I/II 各 15 道；30 个答案去掉非数字后必须与 math-ai 逐题一致（setup.sh 里 assert）<br>都不 gated，都能 `curl`。判据：`math-verify==0.9.0`（PyPI，Apache-2.0，HF 官方仓 `huggingface/Math-Verify`）|
| **cand** | 一段文字，末尾 `\boxed{N}`。台子只看最后 20000 字符，认最后一个 `\boxed{}`（math_verify 默认，`boxed_match_priority=0`），没有 boxed 时退到 latex 环境 / 裸算式 |
| **structure** | `parsed ──→ correct`，sink = `correct`。<br>`parsed`：`math_verify.parse(said)`（`src/math_verify/parser.py`）吐出的 sympy 对象里有一个整数，且 0 ≤ N ≤ 999<br>`correct`：`math_verify.verify(gold, got)`（`src/math_verify/grader.py`）说相等；上游判 0 直接 0<br>两格是官方规则自己的两段（答题卡只认三位整数 → 相等），跟 cmt/deepswe 一样最小 |
| **h_r** | 官方规则：整数相等（MAA 无判卷代码）。工程上「官方判据」= Math-Verify 的 `parse` + `verify`，OpenCompass `MATHVerifyEvaluator`、lighteval、Open-R1 判 AIME 用的都是它。**全确定性，无 LLM 判卷，60 题一道不舍**。替代：MathArena（eth-sri/matharena，MIT，`src/matharena/parser.py` 的 `extract_boxed_answer`/`parse_answer`/`check_answers`）——它是 AIME 最接近「官方榜」的判据，但不是 pip 包、要 clone 钉 commit；本例选能 pin 版本的 math-verify。两者对整数答案结论应一致 |
| **boundary** | `aime.jsonl` 带 `answer`，只在 `~/.cache/tgengin-aime/`，只有 stand.py 进程读；`/problems` 摘掉 `answer`。**不是隔离**（同 cmt）：solver 的 bash 与判卷台同机，一条 `cat` 就拿到；真堵死要把 solver 关进 `place` 沙箱。判卷不要容器、不要网、毫秒级 |
| **budget** | c=10，K=8，T=30 min/题（`solveSeconds=1800`）。判一次毫秒级，c 不是成本而是意义问题（见 m 一节）。T：人赛 3 小时 15 题 = 12 min/题，模型带工具 30 min 富余；cmt 60/deepswe 120 是研究级/工程级，AIME 没那么长 |
| **level** | 0 只回 bool；1 + 断在 `parse` 还是 `value` + 台子读出的整数；2 + 官方答案比你大/小（**泄露实验**，见下）；3 无——再多一个字（差多少、哪位对）就是交答案 |
| **m** | m = 1000。N = (K+1)(c+1)+1 = 100 < 1000，**名义枚举可达 0/60**。但答案分布不均匀：60 个官方答案里 <100 的 16 个（27%）、<300 的 39 个（65%）。按先验从小到大枚举 0..99，N=100 次能零推理命中 16/60。见下文 |
| **坑** | 数据污染（两年都在训练语料里）、答案先验偏小、`python_exec` 让计数题变成暴力枚举、opencompass II-5 答案写成 `336^\circ`、math-ai 的题面是转述不是原文、math_verify 超时只能在主线程用 |

---

## 一、来源为什么这么选

三个候选集都放了 2025，只有一个放 2024 且带 `answer` 列、许可清楚：

| 集 | 年 | 许可 | 格式 | `answer` | 结论 |
| --- | --- | --- | --- | --- | --- |
| `math-ai/aime24` | 2024 | Apache-2.0 | parquet | **没有**，藏在 `solution` 的 `\boxed{}` 里 | 不用：得自己解析答案 |
| `HuggingFaceH4/aime_2024` | 2024 | **无** | parquet | 有 | 不用：许可空白（它本身是 AI-MO 的子集）|
| `AI-MO/aimo-validation-aime` | 22–24 | Apache-2.0 | parquet | 有，官方三位写法 | **用**，取 2024 的 30 道 |
| `math-ai/aime25` | 2025 | Apache-2.0 | jsonl | 有，int | **用** |
| `opencompass/AIME2025` | 2025 | MIT | jsonl | 有，但 II-5 是 `"336^\circ"` | 对账用 |
| `MathArena/aime_2025` | 2025 | CC BY-NC-SA | parquet | 有，int | 不用：非商用条款 |

题号 `aime-<年>-<I|II>-<题号>`。2024 从 url 正则认（AI-MO 按 url 字串排序，`Problem_1, Problem_10, Problem_11…`，不能按行序）；2025 按 math-ai 行序（0–14 = I，15–29 = II）——setup 里跟 opencompass 的 I/II 两个文件逐题对账，顺序错了 assert 就炸。

## 二、h_r：为什么是 math-verify，不是自己写 `int(re.search(...))`

规则只有一句「整数相等」，难的全在读数：`\boxed{070}`、`\boxed{70.}`、`\boxed{70^\circ}`、`\boxed{\text{70}}`、`$70$`、"the answer is **70**"、`x = 35 \cdot 2 = 70`、以及模型在推理里写了七个 boxed 最后一个才是答案。每个边界自己定一次，就跟别人的表不可比一次。

`parse`（`parser.py`）：按优先级抓最后一个 `\boxed{}` → latex 环境 → 裸表达式，ANTLR 转 sympy。
`verify`（`grader.py`）：字符串 → 数值（精度内）→ 符号化简。对 Integer vs Integer 就是数值相等。

台子在两者中间只加一道**值域闸**：解析出的 sympy 对象里第一个整数（`is_Integer`，或 `is_Number` 且等于 `int`）落在 0–999。这是 AIME 规则，不是我们的判断。`verify` 的非对称性（gold 是数、答卷是等式链 `a+b=70` 也算对）对 AIME 无害——赛制只看最终数。

不能包的部分：**没有**。60 题全是整数答案，无 LLM 判卷。

## 三、m 与「有反馈的整数猜测」

### 名义上不可达

m = 1000，N = (8+1)(10+1)+1 = 100。均匀先验下，只回对错的判卷一次划掉一个数：N 次盲猜命中率 N/m = 10%。没有一道题「枚举可达」（m ≤ N）。

### 对错反馈能不能二分？不能

二分需要**序**反馈（大了/小了）。bool 判决只是「等/不等」——它不是一位序信息，是一次相等测试。信息量算一下：均匀先验下相等测试的回答熵是 H(1/1000) ≈ 0.011 bit，100 次合计约 1.1 bit；比较测试每次最多 1 bit，10 次就是 log2(1000) ≈ 10 bit，够定位任何一个数。所以：

| 反馈 | 每次最多划掉 | 定位 1000 个数要几次 | c=10 下盲猜命中 |
| --- | --- | --- | --- |
| 只回对错（本例 level 0/1）| 1 个 | ~1000 | 1.1% |
| 回大小（level 2）| 一半 | 10 | **100%** |

level 2 因此不是「多说一点」，是把 G 变成一个 10 次必中的 oracle，c=10 恰好够。它存在只为量这条差距，跑正式实验不用。

### 那反馈比纯枚举强在哪

强在**候选来自模型自己的后验**，不来自 0..999。一道 AIME 题模型常算出 2–3 个不同的数（漏了一种情形、mod 1000 前后、少算一半）。c 次检查把「pass@1」变成「在自己前 c+1 个候选里 pass@(c+1)」——AIME 上这个差距文献里通常是二三十个百分点量级（pass@1 与 pass@k / cons@64 之间），远大于 1.1% 的盲猜增益。`why` 那一栏另给一位信息：断在 `parse` 还是 `value`，只帮排版不帮解题。

### 先验不均匀：实际可达比例不是 0

60 个官方答案：

| 区间 | 2024 | 2025 | 合计 |
| --- | --- | --- | --- |
| 0–99 | 7 | 9 | **16 (27%)** |
| 100–299 | 11 | 12 | 23 |
| 300–999 | 12 | 9 | 21 |

一个不推理、只按「小数优先」枚举的求解器，把 N=100 次全花在 0..99 上，能命中 16/60。**这才是这套题真正的枚举可达比例：名义 0%，先验加权 27%。** 这是 AIME 出题习惯（小答案多）造成的，不是这个 G 的错，但 G 的作者得知道分数里可能有多少是它。

压这条的旋钮在预算，不在 G：

| c | K | N | 官方答案 < N 的题 | 先验加权可达 |
| --- | --- | --- | --- | --- |
| 10 | 8 | 100 | 16 | 27% |
| 10 | 2 | 34 | 5（16 19 23 25 33）| 8% |
| 3 | 4 | 21 | 2（16 19）| 3% |

**建议正式跑用 c=10、K=2**，或 K=8 / K=2 各跑一趟对照。也可以在成绩单里另列「同一题的判决序列单调递增」的题当作枚举嫌疑。

## 四、boundary

- 答案只在判卷台进程；`/problems` 不带 `answer`；引擎侧的 G 封在 sealed store。
- **同机不隔离**：solver 的 `bash` 一条 `cat ~/.cache/tgengin-aime/aime.jsonl` 就拿到。跟 cmt 一样是有意留着的一圈门槛；真堵死靠 `place` 沙箱。
- 判卷不需要容器、不需要网络；math_verify 纯本地，毫秒级；`expectMs` 给 5000 足够。
- 关 `web_search`：AoPS 有全部题解。`noSearch` 列 `"AIME 2025 I problem 3 solution"` 之类没用——直接关。
- `python_exec` 要定政策：留着的话计数题/数论题变成暴力枚举，分数跟 MathArena 那种无工具榜不可比；关掉的话才是「模型会不会做」。建议两种各跑一趟，成绩单分开标。

## 五、level

| 级 | `note` | 泄露 |
| --- | --- | --- |
| 0 | 空 | 无 |
| 1 | `{stage: parse\|value, read: N, detail}` | 无——`read` 是它自己写的数 |
| 2 | + `gold_is: higher\|lower` | 全泄：10 次二分必中 |
| 3 | 不做 | 差值 / 位数匹配 = 1–3 次拿到答案 |

## 六、budget

| 旋钮 | 值 | 理由 |
| --- | --- | --- |
| c | 10（`TGENGIN_AIME_CHECKS`） | 判卷毫秒级，成本无关；意义上够试 2–3 个候选、不够枚举 |
| K | 8（建议正式跑 2，见 m 一节）| 8 让 N 到 100，先验加权可达 27% |
| T | 30 min | 人赛 12 min/题；带工具 30 min 富余 |
| `maxBranches` | 4 | 同 deepswe |

## 七、已知坑

1. **数据污染**：2024 赛（2024-02）在所有近期模型的语料里；2025 赛（2025-02）对截止 2025 年中之后的模型也是。AoPS 有全解、GitHub 有几十份 jsonl。缓解：关 `web_search`；把 2024 vs 2025 的差距当污染信号看；要干净题去 MathArena 的 2026 赛（CC BY-NC-SA，本文未核对其 HF 地址）。这套题**测的是「引擎能不能把模型已会的东西做对」**，不是能力上限。
2. 答案先验偏小（上文）；不处理的话分数里混着枚举。
3. `math-ai/aime25` 的题面是转述（I-2 措辞与官方不同，opencompass 那份更接近原文）；数学等价，但不是逐字。要逐字就换 opencompass 当主来源并自己清洗 `^\circ`。
4. `opencompass` II-5 答案 `"336^\circ"`——直接 `int()` 会炸，这是不当主来源的原因。
5. math_verify 的 `parsing_timeout` / `timeout_seconds` 靠 `signal.alarm`，**线程里不能用**，台子传 `None`；用 `TAIL=20000` 截答卷兜底。极端输入可能让 ANTLR 慢。
6. 依赖：`math-verify[antlr4_13_2]==0.9.0`（拉 sympy、latex2sympy2_extended、antlr4 运行时）+ `pyarrow`（只为读一个 parquet）。Sherlock 上 `ml python/3.12.1`，venv 在 `$HOME/.cache`（~150 MB），pip 缓存指到 `$SCRATCH`。
7. 争议题：没查 AoPS 勘误；这 60 题里我不知道有作废题，但没核实。
8. `task.id` 必须包含 `aime-<年>-<I|II>-<题号>`；前缀跑名随意。

## 未验证

代码没在这台机器上跑过（登录节点禁 python）。逐行复读后，确定没验证的：

- `math-verify==0.9.0` 的 `parse/verify` 签名与我读的 **main 分支**源码一致（main 上 `utils.timeout` 对 `None` 明确不装 alarm，且报错文案自己建议线程里传 `parsing_timeout=None`；0.9.0 那个 tag 没单独读）。
- `math_verify.__version__` 是否存在（用 `getattr` 兜了）。
- `parse()` 对 `\boxed{070}` 回 `Integer(70)`、对 `\boxed{70.0}` 回 `Float` 且 `e == int(e)` 为真；对 `\boxed{1000}` 回 `Integer(1000)` 从而被值域闸挡住。
- `verify(gold, got)` 会不会在 `integer_of(got) != gold` 时仍回 True（`got` 列表里另一个元素撞上 gold）。自检只覆盖 gold / gold+1 / 无整数 / 越界四种。
- `ExprExtractionConfig()` 解析 `"70"`、`"25"` 这类纯数字 gold 的结果类型（预期 Integer）。
- Sherlock 计算节点上 `ml python/3.12.1` 在 `set -eu` 的非交互 bash 里能否生效（记忆里说有时不生效；不生效时 `python3` 是 3.6，脚本会在版本断言处停）。`pyarrow` 在 CentOS 7 glibc 2.17 + py3.12 是否有 manylinux2014 轮子。
- AI-MO parquet 里 2024 的 30 行、`answer` 为字符串——通过 datasets-server 看的是 main，与钉的 sha 同一提交，但没直接读 parquet。
- math-ai 行序 = I 1–15 / II 1–15——由 setup 里跟 opencompass I/II 文件逐题对账来保证，对账本身没跑。
- 引擎送来的 `input.result` 形状（`{body}` 或字符串）与 `feed[0].value` 的用法照抄 deepswe，没对着本次引擎版本核。
- `ThreadingHTTPServer` 下 math_verify 的 lru_cache（`parse_latex_cached`）线程安全性。
- `/problems` 按 (year, contest, number) 排序时 `contest` 字符串 "I" < "II" 成立，但 2024 的 `number` 是 int（从 url 取）——是。
