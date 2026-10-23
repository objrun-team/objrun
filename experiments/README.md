# 实验登记与归档入口

实验记录实体位于 [records/](records/README.md)，按 2026-10-24 的明确授权随普通 Git 文件分组提交并推送。下列原有清单继续提供历史来源定位，不代表全部来源已经选入本轮交付。

| 文件 | 范围 |
|---|---|
| [benchmark-catalog.csv](benchmark-catalog.csv) | 论文中 20 项 Bench 的主要来源 |
| [collection-roots.csv](collection-roots.csv) | 133 个已发现收集根，不代表全部逐次尝试 |
| [catalog.csv](catalog.csv) | 旧 runs 下 60 个直属目录的基础登记；完整运行清单仍需扩展 |
| [paper-selection.csv](paper-selection.csv) | 当前 v6.25 的分母、协议及来源登记 |
| [provenance/local-path-map.json](provenance/local-path-map.json) | 本地迁移与旧路径兼容映射 |
| [archive-catalog.json](archive-catalog.json) | 已验证收集的快照、原路径、文件数、哈希清单和恢复状态 |
| [storage-policy.md](storage-policy.md) | 用户确认的保留、压缩与排除规则 |
| [provenance/unreadable-paths.json](provenance/unreadable-paths.json) | 7 个保留原位、未读取且未归档的目录 |
| [provenance/external-source-map.json](provenance/external-source-map.json) | 早期目录链接指向的盘外实际数据及只读收集对应关系 |

仓库外 `_objrun-archive/` 的 66 批原档是新记录筛选的核对来源。原档在新包验收前继续保留，本轮不删除，验收后仅登记待检查的可清理范围。它们不再作为发布资产。

日常列出运行、读取轨迹、恢复日志使用 [Git 内记录工具](records/README.md)，不依赖本地原档。CSV 中 `local_archive_ids` 仅保留原档核对来源；原有 `discovery_only`、分母和分数映射待审状态仍然有效，文件导出不能冒充逐次尝试语义全部审计。

此前使用 Release 附件存放日志的计划已取消。索引和摘要保持易读，压缩记录实体、哈希及重组映射一并进入普通 Git；完整覆盖与核验状态见 records/reports/。

SciCode 的独立输出目录采用只读归档，C 盘原件保留；具体状态见 `scicode-external` 收集。三项外部 U 参照不代表存在本地配对轨迹。

当前选择集已补入 OlympiadBench、SciBench、TheoPhysEval、ClassEval、BIRD 的模型输入输出、日志和结果记录，共 490,876 个文件记录。分 Bench 体积及范围见 [覆盖说明](records/summaries/coverage.md)。其余 15 批尚有延期材料，其中 workspace-tmp 已部分选取；不宣称全部原档已纳入 Git。
