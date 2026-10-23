# AIME 2024–2026 —— G 设计表

题库：MathArena 的 AIME 2024 I/II、2025 I/II、2026 I/II，共 90 题，整数答案 0–999。
判据：整数精确匹配（官方口径）。

## 四个字段（改 `G.json`）

| 字段 | 现在的值 | 理由 | 可以怎么改 |
|---|---|---|---|
| 结构 | `parsed → correct` 两节点 | 分开「没按格式交」和「答错」，前者是我们的锅 | 合成一个节点 |
| 边界 | 答案只在判卷进程；`noSearch` 挡 AIME/AoPS/MathArena 题解页 | 三届题解全在网上，一搜就有 | 加 `"solution"` 相关词组 |
| 预算 | `checks: 3` | 整数答案空间 1000，3 次枚举不到；但 AIME 答案偏小、模型猜「常见答案」有一点信号 | 1（最严）/ 5 |
| 信息级别 | ℓ0：拒绝只说哪个节点 false | 整数题给 note 没意义 | — |

## 零模型提醒
AIME 答案 0–999，checks=3 时枚举率 ≈ 0.3%，可忽略。eacndev 记录：顺序枚举在旧系统上命中 27%——那是「答案偏小 + 多次重来」叠加的效果，K=8 时要看 F 臂里「同一节点连续递不同整数」的比例。

## 跑
```
BENCH=aime ARM=U RUN=aime-u-0731 bash runs/bench-arm.sh
BENCH=aime ARM=F RUN=aime-f-0731 bash runs/bench-arm.sh
```
