# ChemBench —— G 设计表

题库：HF `jablonkagroup/ChemBench`，9 个主题 2785 题：2542 选择（可多选）+ 243 数值。
判据：官方 `all_correct`（选择 = 字母集合相等；数值 = 误差 < 1% 目标值）。

## 四个字段

| 字段 | 现在的值 | 理由 |
|---|---|---|
| 结构 | `parsed → correct` | — |
| 边界 | `noSearch` 挡 chembench/lamalab | 题库公开 |
| **预算** | **`checks: 1`，`maxDeadSiblings: 1`** | 选项通常 4–6 个，多选题空间 2^n−1；给 1 次 + 1 次重来 = 最多 2 个候选，枚举可达率对四选一 ≈ 50%，仍然高——**ChemBench 的 F 臂主要是零模型对照**；数值题（243）不受此限，可以单独报 |
| 信息级别 | ℓ0 | — |
| 时限 | 900 s | 题短；2785 题 × 1 h 跑不完 |

## 主题
默认 9 个主题全含（对齐 eacndev 的 2785）。`chemical_preference`（1000 题）是人类偏好二选一，不是知识题；要剔掉就改环境变量 `TGENGIN_CHEMBENCH_TOPICS`。

## 建议
主报 U 臂；F 臂只在数值题子集上有信息量。跑全量前先 `HOW_MANY=20` 冒烟。
