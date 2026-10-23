# 报告口径

当前状态以 final-verification.json、independent-verification.json、bench-coverage.csv 和 supplement-bench5-20261024.json 为准。bench-samples-bench5-20261024.json 登记新增五项的独立恢复样例；manifests/database-audit-bench5-20261024-* 包含外层与嵌套数据库的一致性记录。

selection.json、database-consistency.json、history-audit.json、publication-checks.json 保留首次选择集的历史验收范围，不代表补充后的总数；首次发布基线为 00ae1cc2fe209483b50ee255db7376c603168a51。其 main 历史扫描和 TypeScript 既存错误检查仍供参考。

deferred-original-collections.json 的 workspace-tmp 是部分完成；其中 source_files/source_logical_bytes 是整批原件规模，不是未处理余项规模。未读取的七个目录另列在 unreadable-sources.json。独立尝试数及所有原始来源的语义覆盖尚未审计，不能把文件数、运行范围数或状态字段计数当成真实实验次数。

补查旧选择集：3 批此前已发布来源的 342 个嵌套数据库成员引用仍标记为待导出（可能重复，不能据此认定缺失 342 份独有轨迹）。它们不属于本次新增五项，原档保留；逐项路径见 reports/legacy-nested-databases-pending.json。完整性核验针对已保存的片段和已导出的表，不代表这些旧成员已核验。
