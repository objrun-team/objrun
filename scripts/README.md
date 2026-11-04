# 通用工具

| 目录 | 用途 |
| --- | --- |
| `bench-runner/` | 通用任务接入、执行状态、恢复与结果保留 |
| `benchmark-campaign/` | 多 Bench 共用的提供方、执行协调和冻结适配层 |
| `benchmark-repair/` | 共用协议、资源/评分核验及恢复实现；部分模块被测试和适配器直接引用 |
| `terminal-bench-repair/` | Terminal-Bench/SkillsBench 共用的隔离、工具网关及运行支持 |
| `phase1/` | 多 Bench 共用的数据准备与自检 |
| `storage/` | 实验记录读取、校验、导出和归档 |

独立 Bench 实验已放入 [examples/benchmark](../examples/benchmark/README.md)，科学问题实验放入 [examples/research](../examples/research/README.md)。这些目录提供具体实验入口；上表目录保留被多个入口使用的公共实现。

[directory-map.json](directory-map.json) 记录旧源码路径与当前路径，以及测试固定输入的位置。历史运行证据中的路径、哈希、截止时间和配置不做全局改写；复现原执行版本需要对应的外置原档。
