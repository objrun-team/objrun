# GPQA Diamond —— G 设计表

题库：官方 `gpqa_diamond.csv`，198 题四选一（gated：去 https://huggingface.co/datasets/Idavidrein/gpqa 接受条款，拿 token 下载到 `$TGENGIN_GPQA_DATA`）。
判据：字母精确匹配。选项顺序按题号确定性洗牌（seed 42），和官方 simple-evals 的做法一致。

## 四个字段

| 字段 | 现在的值 | 理由 |
|---|---|---|
| 结构 | `parsed → correct` | 同 AIME |
| 边界 | `noSearch` 挡 gpqa/idavidrein | 题库公开在 HF，一搜就是答案 |
| **预算** | **`checks: 1`，`maxDeadSiblings: 2`** | **四选一：checks ≥ 3 等于把答案送给它**（零模型：答案空间 4 < 额度）。checks=1 + 最多 2 次重来 = 最多看 3 个字母，仍有 75% 枚举可达——所以 GPQA 的 F 臂本质上是「零模型的展示品」，报告里必须写明 |
| 信息级别 | ℓ0 | — |

## 零模型
m = 4。任何 F 臂结果都要和「随机枚举在同样预算下的期望」对比：checks=1、K=2 → 3 次机会 → 枚举成功率 1 − (3/4)(2/3)(1/2) = 75%。**GPQA 上 Δ 的上限被预算而不是模型决定。** 建议主报 U 臂 pass@1，F 臂只作零模型对照。

## 跑
```
BENCH=gpqa ARM=U RUN=gpqa-u-0731 bash runs/bench-arm.sh
```
