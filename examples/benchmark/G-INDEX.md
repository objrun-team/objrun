# 九个 benchmark 的 G —— 一览（2026-09-25）

已跑：cmt、deepswe。新写（未在任何机器上跑过，每个目录 G.md 末尾有「未验证」清单）：其余七个。
每个目录：`G.md`（五字段记录）、`objective.ts`、`stand.py`（包官方判卷器，不重写判断）、`setup.sh`（幂等，要在 sdev 计算节点跑）、`README.md`。
官方源码浅克隆在 `/scratch/users/ehz0002/tmp/bench-src/`（skillsbench 1.1G、chembench 1.6G，看完可删）。

| slug | 题数 | cand | 节点（→ 根） | h_r 官方出处 | level | m | 建议 c/K/T | 枚举可达 | 判卷需要 |
|---|---|---|---|---|---|---|---|---|---|
| cmt（已跑） | 50 | \boxed 文本 | parsed → equiv | cmtbench LaTeX→SymPy | 0 | 选项/整数/∞ 混 | 10/8/60min | 15/50 = 30% | python |
| deepswe（已跑） | 112 | commit | applies → resolved | 官方隐藏测试 | 0–3 | ∞ | 6/8/120min | 0 | docker，断网 |
| gpqa | 198 | 字母 A–D | parsed → correct | idavidrein/gpqa run_baseline.py | 0–2 | 4 | **1/0**/15min | K≥1 即 100% | python |
| aime | 60 | \boxed 整数 | parsed → correct | math-verify 0.9.0 | 0–2（2=大小，10 次二分） | 1000 | 10/2/30min | 名义 0；答案偏小，0..99 顺序枚举命中 27% | python |
| chembench | 2785 | [ANSWER] 字母集/数 | parsed → correct | lamalab chembench prompter._calculate_metrics | 0–3 | 单选 n、多选 2^n−1、数值 ∞ | 1/2/10min | 选择题 82%，全集 75% | python |
| chemiq | 816 | 整数/SMILES/IUPAC/映射 | parsed → correct | oxpig/ChemIQ answer_verifier（RDKit+OPSIN） | 0–3 | 计数题 6–25，其余 ∞ | 3/8/15min | 226/816 = 28% | rdkit 模块 + 出网（OPSIN） |
| terminal-bench 2.1 | 89 | 活容器 | ran → passed | harbor tests/test.sh pytest | 0–3（3 漏答案 11 题） | ∞ | 4/6/官方 timeout | 0 | docker + 网；判卷在求解容器内（shared） |
| skillsbench 1.1 | 87 | 容器内文件 | verified → passed | verifier/test.sh pytest | 0–3（3 漏答案） | ∞ | 6/8/官方 timeout | 0 | docker + 网 |
| minif2f | 488 | Lean 证明体 | stated → compiles → sound | Lean 4.15 + Mathlib，REPL | 0–3 | ∞ | 12/8/60min | 0；23% 题一条 hammer 即中 | Lean（计算节点） |

## 读表的结论

1. **三类判卷器，三种边界强度**：纯函数（gpqa/aime/chembench/chemiq/cmt/minif2f，答案只在判卷进程）＞ 分离容器（deepswe）＞ 共享容器（terminal-bench、skillsbench，隐藏测试在判卷时对求解器可见，且容器有网、参考解在 GitHub 公开）。
2. **首页图上四个 benchmark 主要在测枚举**：gpqa 100%、chembench 75%、chemiq 28%、cmt 30%；aime 名义 0 但先验偏小。只有 deepswe、terminal-bench、skillsbench、minif2f 的分数不受 Prop enum 影响。
3. **level 3 在三处等于送答案**：terminal-bench 11 题、skillsbench 断言含期望值、chembench 数值题相对误差。这些只能当上界实验。
4. **无一处需要 LLM 判卷**（chembench 的 LLM 兜底解析设为关；关掉后正则读不出即 0，不舍题）。
5. **Sherlock 上能起判卷台的**：gpqa、aime、chembench、chemiq、minif2f（sdev 节点）。docker 三个只能在 WSL 那台。
6. 新发现的数据问题：chemiq 30 题疑似官方 200 字符门槛下无解；chembench 12 道数值题 target ≤ 0 恒判 0；minif2f Kimina 版对 DeepSeek 版实际改 19 条不是 8 条；terminal-bench 上游已到 4.0，2.1 分数不可比；skillsbench v1.1 tag 被重打过，三个 commit 号不一致。
