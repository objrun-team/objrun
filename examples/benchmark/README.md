# Benchmark 示例与实验

现有 Bench 目录中的 README、G.md、stand.py 和 send.ts 介绍目标、官方判据和基本运行入口。

| 实验目录 | 内容 |
| --- | --- |
| `evalplus/` | HumanEval+、MBPP+ 执行、恢复与判分 |
| `climaqa/` | ClimaQA 数据准备与实验 |
| `code-benchmarks/` | BIRD、ClassEval 评测 |
| `frontierscience/` | FrontierScience 实验 |
| `gpqa/binary/` | GPQA 二值反馈实验 |
| `labbench/experiments/` | LAB-Bench 执行与核验 |
| `minif2f/formal/`、`minif2f/ablation/` | miniF2F 正式实验与消融 |
| `olympiadbench/experiments/` | OlympiadBench 实验 |
| `scibench/experiments/` | SciBench 实验 |
| `theophyseval/experiments/` | TheoPhysEval 实验 |

运行前阅读对应脚本的参数、输入和环境要求。源码保留历史实验的模型、预算与评分协议；原始运行、凭证和环境不随示例发布。读取历史结果使用 [记录工具](../../experiments/records/README.md)。通用运行器及多 Bench 共用实现仍在 `scripts/`。
