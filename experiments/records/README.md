# Git 内实验记录

本目录保存筛选后的真实记录实体。66 批已登记来源已筛选，当前范围以 [覆盖表](summaries/coverage.md)、[逐项报告](reports/current-bench-coverage.json) 和 [整理简报](../../docs/reproducibility/records-report.md) 为准。真实失败、中断、重试和成功证据都保留；原始缺损和七个不可读目录单独登记。不能据样例恢复成功宣称全部历史实验完整。

`runs/` 是运行范围索引，`summaries/` 是可读摘要，`packs/` 是去重的完整正文片段，`manifests/` 保存来源、哈希、有序重组与转换记录，`reports/` 保存覆盖和验收。每个 TAR/Zstandard 分片独立解压，不超过 25 MiB。读取不需要本地原档、LFS 或 Release。

需要 Python 3.12+ 和 `requirements-records.txt` 中的 zstandard。从仓库根目录执行：

```powershell
python scripts/storage/records.py runs --bench labbench --limit 20
python scripts/storage/records.py files --bench terminal-bench --limit 20
python scripts/storage/records.py --isolated read --collection COLLECTION --path '索引中的路径'
python scripts/storage/records.py extract --collection COLLECTION --path '索引中的路径' --output 'F:\selected-log.txt'
python scripts/storage/records.py verify
```

SQLite 表用 `--table TABLE_NAME`；压缩包成员用 `--member MEMBER_PATH`，可重复以读取多层嵌套。一个主库对应多个 WAL 状态时，以 `--member wal-WAL_SHA256 --table TABLE_NAME` 选择。read 输出完整保存内容，extract 拒绝覆盖已有文件。

`source_sha256` 描述原件，`content.sha256` 描述导出内容，`content.parts` 保存每次出现及其完整顺序。通过 `manifests/object-index.json` 中的哈希分片映射定位正文；读取工具兼容旧单文件索引。数据库转换、文本解码、资源剔除、凭证脱敏、原始截断分别登记，转换后不宣称原件字节一致。模型权重和数据集实体排除，随机数状态、调用参数、工具文本返回、事件顺序、评分与结果保留。

旧 342 个嵌套数据库引用已经按内容去重核查并补齐可用导出；旧 95 个输入已确认为合成夹具。历史选择和延期报告仅描述当时状态，当前判定见 reports/README.md。原档保留在仓库外供后续检查，不是发布资产。
