# 报告口径

当前范围以 `current-bench-coverage.json`、`bench-coverage.csv`、`current-source-scope.json` 为准；`remaining-integrity-verification.json` 是最终增量完整性核验，`remaining-sample-verification.json` 是禁止原档访问的真实运行恢复证明，`publication-size.json` 是最终 Git 文件内容体积。`verification-reused-filtered6.json` 和此前五项样例证明仅在字节及映射一致时复用。

`legacy-member-state-audit.json` 说明旧 342 个引用、290 组主库/WAL 配对、285 个表内容状态及 47 个新增状态。`legacy-95-resolved.json` 说明旧 95 个引用的 11 类合成夹具。`terminal-conversion-verification.json` 验证资源剔除前后真实事件、非权重字段和 RNG 状态一致。

`original-source-gaps.json`、覆盖报告中的 issues 与 `unreadable-sources.json` 登记真实缺失、损坏或不可读来源。七个目录不改权限，文件数和体积未知。AstrovisBench 仅找到元数据；其详细轨迹恢复不适用，不能算成功样例。

`selection.json`、`deferred-original-collections.json`、`legacy-nested-databases-pending.json`、`final-verification.json`、`independent-verification.json`、`supplement-bench5-20261024.json` 等保留历史快照，不代表当前总数或仍待处理的来源。早期导出错误与 pending 列表保存在 `historical-export-findings.json`，后续恢复/排除/配对报告记录处理结果。不得把历史 pending 直接作为当前原始缺失结论。

正文大小、来源逻辑大小、分摊压缩大小、Git 文件内容和 `.git` 大小分别统计，不估算网络推送流量。来源运行范围、文件引用、消息行、数据库状态均不是独立实验或独有轨迹数量。真实样例恢复不代表全部运行完整；未重跑实验或判分器。
