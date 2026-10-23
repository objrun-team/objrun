# 脚本目录

目录按 Bench 或职责命名，新增目录使用小写单词和连字符，不在目录名中加入运行日期。运行日期、任务标识和执行版本记录在实验索引与输出中；既有 Python 包名、协议标识和文件名保留其原有约定。

| 目录 | 用途 |
| --- | --- |
| `bench-runner/` | 通用运行器、执行与审计协议 |
| `benchmark-repair/` | 多 Bench 的诊断、修复、资源与评分核验 |
| `terminal-bench-repair/` | Terminal-Bench 的多任务修复、准备与恢复 |
| `benchmark-campaign/` | 多 Bench 的批次执行、共享适配器与恢复协调 |
| `code-benchmarks/` | BIRD、ClassEval 的代码和 SQL 评测 |
| `evalplus/` | HumanEval+、MBPP+ 的执行、判分与恢复 |
| `gpqa-binary/` | GPQA 的二值反馈运行 |
| `frontierscience/`、`labbench/`、`olympiadbench/`、`scibench/`、`theophyseval/` | 对应 Bench 的专用脚本 |
| `minif2f-formal/`、`minif2f-ablation/` | miniF2F 的正式实验与消融 |
| `phase1/` | 初始阶段的入口与自检 |
| `historical-root/` | 原仓库根目录迁入的历史脚本 |
| `storage/` | 实验记录导出、读取、归档与核验 |

本次目录迁移的精确旧路径与新路径见 [directory-map.json](directory-map.json)。主要对应关系如下：

| 原目录 | 当前目录 |
| --- | --- |
| `evalplus-20261012/` | `evalplus/` |
| `gpqa-binary-20261018/` | `gpqa-binary/` |
| `newbench-20261014/` | `code-benchmarks/` |
| `repair-2026-10-08/` | `benchmark-repair/` |
| `repair-2026-10-09/` | `terminal-bench-repair/` |
| `repair-2026-10-10/` | `benchmark-campaign/` |

`benchmark-campaign/full-f/` 及其 `skillsbench/next-segment/` 下的 `parallel-prep` 目录也已去掉日期；`pipeline-mailbox-root-transport-probe` 版本目录采用同样规则。

当前源码的导入、脚本调用和忽略规则使用新路径。实验日志、来源清单、已签名或按哈希锁定的发布回执，以及冻结快照中的原路径保留原值，可结合迁移表定位当前源码；历史源码的字节与哈希仍以对应归档或 Git 版本为准。`docs/` 下的历史输出目录不随脚本改名。
