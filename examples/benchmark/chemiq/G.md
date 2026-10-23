# ChemIQ 的 G

| 字段 | 内容 |
| --- | --- |
| **来源** | 论文 [arXiv 2505.07735](https://arxiv.org/abs/2505.07735)（Runcie, Deane, Imrie, "Assessing the Chemical Intelligence of Large Language Models"，JCIM 2026, 66(1):216–227，DOI 10.1021/acs.jcim.5c02145）。仓库 [github.com/oxpig/ChemIQ](https://github.com/oxpig/ChemIQ)，BSD-3，钉 commit `63826f64990802e87f1b11b9192606a20838d522`（2026-03-26）。题库 `questions/chemiq.jsonl`，**816 题**，就在仓库里，不在 HF、不 gated。另一份 `additional_smiles_to_iupac.jsonl`（260 题）是论文做错误分析用的，不属于 816，不包。 |
| **cand** | 一行短答，按题 `answer_format`：整数（226）/ 浮点（20）/ 原子映射的元组列表 `[(0, 2), (1, 3), …]`（184）/ IUPAC 名（200）/ SMILES（186）。官方 parser 认 `\boxed{}`、`\text{}`、最后一行、最后一个数；SMILES 取最后一行最后一个词。**超过 200 字符或含换行的官方直接判错。** |
| **structure** | `parsed ──→ correct`，sink = `correct`。`parsed`：官方 `utils/parser.py::AnswerParser.parse(uuid, raw)` 回的不是 `False`；`correct`：官方 `utils/answer_verifier.py::AnswerVerifier.check_answer(uuid, parsed)["is_correct"]`。两格是官方 `analysis.ipynb` 里连着的两行，拆开读；上游 0 则根直接 0。 |
| **h_r** | `check_answer` 按每题 `verification_method` 分派五种，全确定性：`exact_match`（`str(a)==str(gt)`，226 题）、`range`（`low<=float(a)<=high`，带噪 SAR 20 题）、`list_of_tuples`（集合相等，184 题）、`canonical_smi_match`（RDKit `MolFromSmiles` → `RemoveStereochemistry` → 规范 SMILES 相等，186 题）、`opsin`（IUPAC 名发 OPSIN 网络服务转 SMILES，再走 RDKit 比较，200 题）。**没有 LLM 判卷，一题不舍。** 但 opsin 那 200 题依赖外部服务（EBI 托管的 OPSIN）——确定性的，但要网、有 2 秒超时。 |
| **boundary** | 答案在 `chemiq.jsonl` 每行的 `answer`（还有 `meta_data.*`、nmr 题顶层 `smiles`、sar 题的 `answer_range`/`system`）。只有 stand.py 读它；`/problems` 只放行 `uuid / question_category / sub_category / answer_format / prompt` 五栏。不需要容器；**判卷台需要出网**（OPSIN）。不是隔离：仓库公开，solver 能出网就能 clone 到答案（cmt 同款结论）。 |
| **budget** | c=3，K=8，T=15 min。理由见下。 |
| **level** | 0–3，见下。 |
| **m** | 按题型，见下表。N=(K+1)(c+1)+1=37 时枚举可达 226/816 = 27.7%。 |

## budget 为什么是 c=3, K=8, T=15min

- 题是单句短答，官方跑法一问一答无工具，o3-mini 一题几十秒到几分钟。T=15 min 已是官方设定的十倍以上；给 T 只是为了 NMR 解谱那种要反复搭结构的题。
- c 给 3 而不是 cmt 的 10：这套题有 226 道整数题答案空间在 6–25 之间，c=10 就是让它把 1–27 扫一遍。3 次够「答 → 验 → 照 note 改 → 再验」一个来回。
- K=8 照 cmt/deepswe。

## level：note 那一栏说多少

判 1 什么都不说。判 0 时按 `--level`：

| level | 说什么 | 来源 |
| --- | --- | --- |
| 0 | 只有 0/1 | — |
| 1 | 哪一格断的：`parse`（没抠出来 + 提醒格式）/ `verify` / `opsin`（服务超时）/ `task` / `collect` | 官方 parser 的返回值 |
| 2 | + 它交的东西本身站不站得住：IUPAC 名 OPSIN 认不认、SMILES RDKit 解不解、映射给了几对 | 候选侧，用官方 `_canonicalize_smiles` 只看候选 |
| 3 | + 抠出来的原文、名字被 OPSIN 翻成的 SMILES、候选 SMILES 的规范形 | 候选侧 |

任何级别都不出 GT，也不出「差多少」（整数题一说差多少就是二分查找）。

## 答案空间 m（按题型）

| 题型 | 题数 | 判法 | m | 依据 | N=37 可枚举 |
| --- | --- | --- | --- | --- | --- |
| counting_carbon | 50 | exact_match | 25 | 答案 3–27，每值 2 题，均匀 | 是 |
| counting_ring | 48 | exact_match | 6 | 答案 1–6，每值 8 题 | 是 |
| shortest_path | 108 | exact_match | 18 | 答案 3–20，每值 6 题 | 是 |
| sar/integer | 20 | exact_match | ≈260 | 答案 322–576，题面给的数据能算出来 | 否 |
| sar/noise | 20 | range | ≈20（有效） | 区间宽 13.6–27，分数跨度 ≈270，按步长扫约 20 次 | 是 |
| atom_mapping | 184 | list_of_tuples | ≥ 7! | n_atoms 7–25，排列 | 否 |
| smiles_to_iupac | 200 | opsin | ∞ | 开放字符串 | 否 |
| reaction | 90 | canonical_smi | ∞ | 开放 SMILES | 否 |
| nmr_elucidation | 96 | canonical_smi | ∞ | 开放 SMILES | 否 |

枚举可达：50+48+108+20 = **226 / 816 = 27.7%**。这四类无论 c 取多少（哪怕 c=1，N=19：数环、最短路仍可达）都在枚举范围内 —— 是题型本身的性质。建议成绩单按题型分列，把这 226 道单独标出来；论文里推理模型在数碳/数环上本来就接近满分，这一块区分度低。

## 已知坑

1. **疑似 30 道在官方判据下无解**（atom_mapping，n_atoms 23/24/25 各 10 题）。`check_answer` 先做 `len(str(model_answer)) > 200 → False`，而 parser 交过来的是 Python 列表，`str()` 出来带空格：n=25 的 GT 是 230 字符，n=23 是 210，n=22 正好 200（不超）。**算术推的，没跑过**；selftest 里加了一个探针专门验它。若坐实，这 30 道按 0 计并在成绩单里标出，跟论文（那张随 n_atoms 下降到 0 的曲线）一致。
2. **OPSIN 是外部服务**：`opsin.ch.cam.ac.uk` 现在 301 到 `www.ebi.ac.uk/opsin/ws/`，requests 会跟；从 Sherlock 登录节点一次往返约 1.0 s。官方 `@timeout(2)` 把网络算在内，超时在 `requests.get` 里响时被 `_get_opsin` 的 `except Exception` 接住、**把 False 写进缓存**，那个名字从此永远判错。stand.py 用「判前查缓存 + 计时 ≥1.9 s」识别这种情况，撤掉那条缓存重问（最多三次），不改判断本身。
3. `@timeout` 用 `signal.alarm`，只能在主线程 → 判卷台是**单线程 HTTPServer**，一次判一道。
4. 官方 verifier 用相对路径读写 `utils/opsin_cache.json` → stand.py 启动时 `chdir` 到 vendor 根；判卷会往 vendor 里写文件（git 会显示 dirty，无害）。
5. 官方 parser 抠出整数 0 时 `check_answer(uuid, 0)` 走 `if not model_answer` 直接判错。题库里没有答案为 0 的题，所以不影响。
6. **数据污染**：仓库 2025-05 起公开，含全部答案和六个模型的完整回答（`model_responses/`，1M 行）。题是从 ZINC 算法生成的，2D NMR 那 50 道 2025-07 才加入。
7. 判 `smiles_to_iupac` 时 IUPAC 名直接拼进 URL，不做编码（官方如此）；带 `#`、`%`、`/` 的名字会被截断或 404 → 判错。
8. 依赖：rdkit、numpy、requests。Sherlock glibc 2.17 装不上 PyPI 新版 rdkit wheel，用集群模块 `chemistry/py-rdkit/2024.3.2_py312`；官方 conda 环境未钉 rdkit 版本，规范化结果理论上可能随版本漂，这套题的分子都是简单药物样分子，风险低。
9. 题面 `prompt` 里的 SMILES 有一半是随机化的（`*_random` 子类），solver 自己有 RDKit 的话数碳/数环/最短路/原子映射/规范化全能用代码算 —— 这是「有没有工具」的实验变量，不是判卷的事。

## 未验证

代码没在这台机器上跑过（登录节点禁跑 python）。逐行复读后，以下几处确定没验证：

- `from utils.answer_verifier import AnswerVerifier`：`utils/` 没有 `__init__.py`，靠 namespace package；官方 notebook 从仓库根这么 import，应该行。
- `VERIFIER.question_dict` 的 key 全是 uuid（parser 那边多塞了 `"integer"` 等调试 key，verifier 没有）—— 读代码确认，未运行。
- selftest 里 `golden_of` 对 opsin 题扫 `_opsin_cache` 找一个名字映到 GT：缓存里 3900 多条是作者跑模型攒的，第一道 zinc_canonical / zinc_random 题未必有匹配 → 可能 `skip`。
- 坑 1 的 200 字符判断是算术推的，探针会给答案。
- 坑 2 的「计时 ≥1.9 s」阈值：`signal.alarm(2)` 精度是整秒，实际在 1.x–2.0 s 之间触发，1.9 可能偏高；若观测到重试从不触发就调到 1.5。
- OPSIN 从 **sdev 计算节点**能否出网只在登录节点试过（1.0 s）；setup.sh 第 3 步会再量一次。
- `ml math devel chemistry python/3.12.1 py-numpy/1.26.3_py312 py-rdkit/2024.3.2_py312` 这一行：rdkit 模块要 `chemistry` 前缀是 `ml spider` 说的；它和 numpy 1.26.3 是否二进制兼容没验。记忆里 py-numpy/1.26.3_py312 与 scipy/pandas 那组是好的。
- `python3 -m venv --system-site-packages` 在集群 python/3.12.1 上有没有 ensurepip 没验（cmt 那台 WSL 就没有，改用了 uv）。
- 内核送来的 `input.result` 形状按 cmt/deepswe 的写法（`result.body` 或裸值），没对着当前引擎版本核过。
- 端口 7903 与别的台子不冲突（cmt 7901、deepswe 7902）。
- setup.sh 里非交互 shell 拿 `ml`：`source $LMOD_PKG/init/bash`（登录节点上 `LMOD_PKG=/share/software/user/open/lmod/lmod`，目录存在）；`bash -n` 过了，没跑。
