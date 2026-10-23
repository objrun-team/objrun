# Git 内实验记录

按 2026-10-24 的用户确认，本轮交付已确认必要的选择集，其余材料先归档待查。补入 OlympiadBench、SciBench、TheoPhysEval、ClassEval、BIRD 后，本目录有 39 批来源的 490,876 个文件记录；不能据此宣称覆盖全部历史实验。完整范围、选择清单与验收结果见 [简报](../../docs/reproducibility/records-report.md)、catalog.json 和 reports/。

记录实体随普通 Git 保存，读取不需要本地原档、LFS 或 Release。

| 目录 | 内容 |
| --- | --- |
| runs/ | 按 Bench 的来源运行范围、显式标识和状态字段 |
| summaries/ | 可直接阅读的结果与覆盖统计 |
| packs/ | SHA-256 去重的完整记录片段；独立 TAR/Zstandard 分片，最多 25 MiB |
| manifests/ | 来源、原始/转换后哈希、片段顺序、分片映射和逐文件筛选决定 |
| reports/ | 选择与延期范围、体积、数据库一致性和隔离读取核验 |

需要 Python 3.12+ 及 requirements-records.txt 中的 zstandard。从仓库根目录执行：

```powershell
python scripts/storage/records.py runs --bench terminal-bench --limit 20
python scripts/storage/records.py files --bench chembench --limit 20
python scripts/storage/records.py verify
python scripts/storage/records.py read --collection COLLECTION --path '索引中的路径'
python scripts/storage/records.py extract --collection COLLECTION --path '索引中的路径' --output 'F:\selected-log.txt'
```

SQLite 表用 `--table TABLE_NAME`，压缩包成员用 `--member MEMBER_PATH`；嵌套压缩包可重复指定 `--member`，最后接 `--table` 读取其中的数据库表。read 输出完整内容，extract 拒绝覆盖已有文件。来源路径仍保留原来的 .gz 等后缀；format=text 时读取的是已解码文本，转换登记在 transformations 中。

source_sha256 是原件哈希，content.sha256 是导出内容哈希。content.parts 保存完整的有序片段引用，通过 manifests/objects.jsonl.gz 定位分片；重复片段可复用，重组时仍保留每次出现与顺序。没有以摘要替代已选真实轨迹或截断长输出。

数据库在主库配对 WAL 的一致性工作副本上导出，列定义、源行数、导出行数和行序均保留；导出表不是原数据库的字节副本。解码、脱敏、资源剔除分别登记。run_scope 表示可定位的来源目录，状态字段计数允许历史快照重复，不等同于已审计的独立实验次数。

剩余 15 批仍有未完成筛选的材料（14 批待筛选、workspace-tmp 部分已选）以及被移出的冻结副本、自测批量输出保留在仓库外归档。95 个未确认输入也已延期，不混入已验收选择集。7 个不可读目录原位保留；原档中仍有真实运行记录，本轮不删除。

五项补充新增 304,330 个文件记录、310 个压缩分片，共 304,476,343 字节；全目录现有 452 个压缩分片，共 506,874,549 字节。逐项覆盖、数据库核对和独立恢复样例见 reports/supplement-bench5-20261024.json、reports/bench-samples-bench5-20261024.json。全部统计是实际文件内容，不等同于网络推送流量。

补查旧选择集：3 批此前已发布来源的 342 个嵌套数据库成员引用仍标记为待导出（可能重复，不能据此认定缺失 342 份独有轨迹）。它们不属于本次新增五项，原档保留；逐项路径见 reports/legacy-nested-databases-pending.json。完整性核验针对已保存的片段和已导出的表，不代表这些旧成员已核验。
