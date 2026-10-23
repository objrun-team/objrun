# ChemBench 的 G

| 字段 | 内容 |
| --- | --- |
| 来源 | 论文 arXiv 2404.01475（Nature Chemistry 2025）。代码 https://github.com/lamalab-org/chembench 钉 `45f8bad062fe552810c52be3a328d5da8597ed30`（2025-09-11，v0.3.0）。数据 HF `jablonkagroup/ChemBench` 钉 `6e1d25748952393f44e35b8e85bbe567246a6430`（2026-04-22），**不 gated**，MIT。**2785 题**（论文写 2786；仓库 reports/ 里 2788 份）：选择题 2542（单选 2148、多选 394）+ 数值题 243。九个 topic：analytical 152、chemical_preference 1000、general 149、inorganic 92、materials 83、organic 429、physical 165、technical 40、toxicity_and_safety 675 |
| cand | **一段文本**，官方要求把最终答案写在 `[ANSWER]…[/ANSWER]` 里：选择题是逗号分隔的大写字母（`[ANSWER]A,C[/ANSWER]`），数值题是一个数（`[ANSWER]5.8e-3[/ANSWER]`，点作小数点，无单位）。台子对整段文本跑官方解析器，所以交上来的可以是整段推理 + 标签，也可以只有标签 |
| structure | `parsed ──→ correct`，sink = `correct`。`parsed`：官方解析器读出了一个答案（`prompter.prepare_mcq_answer` + `utils.run_regex(create_multiple_choice_regex)` / `prompter.prepare_general_answer`，`llm_extractor=None`）。`correct`：`prompter.BasePrompter._calculate_metrics` 算出的 `metrics["all_correct"] == 1`。就是官方 `_process_single_result` 的两段，拆开读，跟 cmt/deepswe 一样最小 |
| h_r | **选择题**：`metrics.classification_scores` 的 `hamming = (漏选+多选)/|正确集|`，`all_correct = hamming == 0`，即所选字母集合 **恰好等于** `target_scores` 里得分为 1 的集合（`prompter.py` `_calculate_metrics`）。**数值题**：`metrics.mae = |found − target|`，`all_correct = mae < tolerance`，`tolerance = task._relative_tolerance`，HF 数据集没有这一栏 → 永远走默认 `0.01 * float(target)`。名字叫 relative，实现是 **绝对误差 < 目标值的 1%（严格小于）**，照抄。两条都是确定性的。**官方有两处用了模型，不包**：① 正则读不出答案时调 LLM 兜底抽取（论文 A.8 / Table A7：守规矩的模型 0–2.4% 的回答走了这条路，GPT-4o ReAct 24%）—— 台子里 `llm_extractor=None`，读不出就是 0；**不是按题舍弃，舍弃的题数为 0**，舍弃的是这个宽容。② 关键词 + BERT 拒答检测（`refusal.py`，要 torch/transformers）—— 不包；拒答文本本来就解析不出答案，同样是 0，差别只在官方误报的那几条（回答里明明有标签却被当拒答，官方 0，这儿照判），偏向 solver，幅度 <1% |
| boundary | 答案在 `~/.cache/tgengin-chembench/chembench.jsonl`，**只有 stand.py 读它**；`/problems` 发官方模板拼好的题面（选择题必然带选项文字，那是题面）不带 `target`/`target_scores`。判卷不需要容器、不需要网络：纯 python（numpy / pint / fastcore / loguru / typing_extensions），毫秒级。跟 cmt 一样**不是隔离**：solver 的 bash 在同一台机器就能 cat 到题库 |
| budget | **c=1，K=2，T=10 min**。c=1：判一次是毫秒，成本无关；但 40% 的选择题只有两个选项，每问一次就是排除一个，多一次都是枚举。K=2：同理，判死重来也是枚举步。T=10 min：题都是单步知识 / 一次计算，官方跑法是一问一答；给智能体带工具（RDKit、PubChem）10 分钟够。对比 cmt c=10,K=8,T=60、deepswe c=6,K=8,T=120 —— 这套题的问题不是判得慢，是答案空间小 |
| level | 0：只有 bool。1：+ 断在 parse 还是 grade + 官方解析器从你的文本里读出了什么（回显自己的答案，不漏 GT）；parse 失败时把格式要求说给它。2：+ 选择题 `options_expected / options_given / wrong_count`；数值题 `direction`（偏大 / 偏小 → 可二分）。3：+ 选择题 `wrong_letters`；数值题 `relative_error`（**等于把答案给它**：一次就能反推 target）。级别只改 note 的详略，G 形状不变 |
| 答案空间 m | 单选 m = 选项数 n；多选 m = 2ⁿ − 1（题面只说 letter(s)，solver 不知道要选几个）；数值题 m = ∞（level ≥2 时 direction 让它可二分，level 3 直接给答案 —— 那时 m 名存实亡）。枚举可达比例见下表 |

## 答案空间与枚举可达

N = (K+1)(c+1)+1。选择题按 (选项数 n, 正确数 k) 的分布（2542 道）：

| n \ m | 单选 m=n | 多选 m=2ⁿ−1 |
| --- | --- | --- |
| 2 | 1013 | – |
| 3 | 69 | 13（m=7） |
| 4 | 898 | 123（m=15） |
| 5 | 89 | 18（m=31） |
| 6 | 3 | 5（m=63） |
| 7 | 1 | 5（m=127） |
| 9 | 74 | 229（m=511） |
| 10 / 16 | 1 | 1（m=65535） |

| 预算 | N | 枚举可达（m ≤ N）的选择题 | 占选择题 | 占全部 2785 |
| --- | --- | --- | --- | --- |
| c=1，K=1（最小） | 5 | 2069 | 81.4% | 74.3% |
| **c=1，K=2（建议）** | 7 | 2086 | 82.1% | 74.9% |
| c=10，K=8（cmt 的） | 100 | 2307 | 90.8% | 82.8% |

结论：**预算救不了 ChemBench 的选择题** —— 哪怕 c=1、K=1，八成题也在枚举范围内。真正挡枚举的只能是 note 不泄露（level 0/1）+ 树那边把重试压到最低；剩下 243 道数值题 + 235 道大空间多选题（9 选多、16 选 7）才是靠推理的部分。
chemical_preference 那 1000 道（36%）全是二选一，论文自己说各模型在这一块与随机无异 —— 建议发批时 `topics=` 把它排掉，另算一栏；但官方 overall 是含它的，比对论文那张表时要带上。

## 已知坑

- **12 道数值题判不出 1**：target ≤ 0（3 道 0、9 道负数），官方容差 `0.01 * target ≤ 0`，`mae < tolerance` 恒假。官方判据自己的性质，不改；台子 `SKIP` 掉、`/problems` 不发、报表按 0 计（0.43%）。
- **tolerance 随数据来源变**：早期版本从本地 JSON 读题时有 per-task `tolerance` 字段（文档 `contribute_questions.md` 里还写着 0.2 那种），HF 版把它丢了 → 全部 1%。钉 HF 版就是钉 1%，跟论文的跑法一致与否论文没写明。
- **多个 `[ANSWER]` 块会合并**：`prepare_mcq_answer` 取 `sorted(set(findall))`，CoT 里先写 `[ANSWER]B[/ANSWER]` 再改口 `[ANSWER]C[/ANSWER]` → 判成 {B, C}。只能写一对标签。
- **数值题取标签里第一个数**，带单位 → pint Quantity → `float()` 失败 → nan → 0。不写单位。
- **数字词兜底没有词边界**：`NUM_WORDS_REGEX` 会把 "second one" 里的 "one" 读成 1，裸文本可能被当成答了 1（自检的裸文本特意避开数字词）。
- **官方 `prepare_mcq_answer` 可能回 None**（无标签、无逗号、无空格、又不是单字母），官方接着 `re.findall(pattern, None)` 会 TypeError —— 官方跑时兜底 LLM 总在，走不到；台子把 None 当「没读出来」。这是唯一一处不照官方原样的地方。
- **一道题的 `target_scores` 有 0.5**（`GHS_pictograms`）：只有 1 算正确，0.5 的选了算多选，官方就这么判。
- **多选 394 道**题面只说 "letter(s)"，正确数不告诉；level 2 会把 `options_expected` 说出去，这是那一级的泄露。
- **数据污染**：题库 2024 起公开在 HF（带 canary GUID），题源含教材、ICHO 真题；论文自己承认。
- **依赖**：不要 rdkit（SMILES 只出现在题面文字里）、不要 torch。`chembench.types` 要 `typing_extensions`，`utils` 要 `pint` + `fastcore`。`pyarrow` 只在 setup 转 parquet 时用。
- **CentOS 7 / glibc 2.17**：numpy 2.x、pyarrow ≥15 的 manylinux2014 轮子理论上装得上；装不上就把 numpy 降到 1.26。

## 未验证

这台机器是登录节点，一行代码都没跑过。写完逐行复读了一遍，下面这些是确定没验证的：

1. `stand.py` 整个没跑：命名空间包绕过 `__init__.py` + 给五个重模块塞空壳后 `from chembench import prompter` 能不能 import（prompter 顶部只 import 那些类名，应该能）；`class Judge: is_mcq = BasePrompter.is_mcq` 这种借方法的写法。
2. `prepare_mcq_answer(..., example=ex, llm_extractor=None)` 的返回值形状（`"['A,C']"` 字符串）接 `run_regex(..., return_first=False)` 出 `['A','C']` —— 照官方 `tests/test_regex.py::test_mcq_label_parsing` 的用法写的，没跑。
3. 数值 golden：`[ANSWER]{target}[/ANSWER]` 里 target 原样是 HF 的字符串（如 `1.5e-05`），`NUM_REGEX` 应能吃；`wrong_of` 的 1.5 倍应落在 1% 外。
4. `setup.sh`：`git clone --no-checkout --filter=blob:none` + `sparse-checkout set src` + `checkout <sha>`（登录节点 git 2.45.1，支持；GitHub 支持 partial clone）；HF `resolve/<revision-sha>/<topic>/train-00000-of-00001.parquet` 路径（`main` 上 tree 查过是这个名字，按 sha 取没试）；pip 轮子在 glibc 2.17 上能不能装；`/share/software/user/open/python/3.12.1/bin/python3` + `LD_LIBRARY_PATH` 那条绕法（记忆里记的，登录节点上不设 LD_LIBRARY_PATH 时确实报 libpython 找不到）。
5. parquet → jsonl 的清洗照 `TaskRegistry.from_huggingface` 写的；每题恰好一个 example（jq 在 datasets-server 拉下来的 2785 行上验过是 0 道多 example）。
6. `feed` 的形状 `[{from,out,value}]` 抄 deepswe，没对着内核跑。
7. 论文 Table A3 的数字是从 PDF 抽的文本，行对齐没逐个核。
