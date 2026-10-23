# 实验记录与本地归档工具

当前发布方案使用普通 Git 中的 `experiments/records/`。`export_records.py` 从已验证原档流式筛选记录，`records.py` 只使用 Git 内文件列出运行、读取轨迹、恢复日志和核验分片。用法及格式见 [记录说明](../../experiments/records/README.md)。不通过 Release 提供日志，不需要原档才能读取已导出的记录。

`curate_records.py --root INPUT --output NEW_DIRECTORY --workspace WORKSPACE` 从已验证导出中生成本轮确认的选择集：保留真实记录，解码已确认的模型响应，归档冻结源码副本及合成批量夹具，保留自测摘要、生成器和独有诊断。输入只读，输出必须为新目录；逐文件决定写入 manifests/selection-decisions-*，不删除未选中的原件。该选择规则对应本轮人工确认范围，不应直接用于未知的新来源。

`export_records.py` 支持 `--work`、`--output`、`--only` 和 `--benches`，新导出使用独立工作目录；`--compression-level` 调节压缩级别。压缩包内的 SQLite 与 WAL 先按成员路径配对，再从一致性副本导出，WAL 在 TAR/ZIP 中出现的先后顺序不影响处理。未配对侧文件或无法核验的数据库必须登记，不能冒充完整记录。

`append_records.py --base EXISTING_RECORDS --supplement VERIFIED_EXPORT --output NEW_DIRECTORY --label UNIQUE_LABEL --partial workspace-tmp` 按哈希复用已有片段，原压缩分片保持不变，新增片段进入带标签的新分片。输出必须为新目录；新来源存在待核验条目时停止。`--partial` 标明仅选取了部分 Bench 的来源，不能视作整批完成。

`records.py read --collection COLLECTION --path outer.zip --member inner.tar.gz --member run.sqlite --table events` 可读取嵌套压缩包内的表。`verify` 同时核对这些嵌套数据库的行数。回归检查运行 `python -B scripts/storage/test_records_export.py`，使用临时合成小样本核验真实 WAL 依赖、嵌套读取、脱敏和增量去重，不访问原档或网络。

剩余来源的增量整理使用下列工具；每次输出均使用新目录，原档只读：

- `recover_tar_records.py` 恢复损坏 TAR 中实际可读的成员。截断正文保留可用字节和声明长度，不能把恢复部分内容说成完整原件。
- `repair_database_pairs.py` 根据已核对的原始封存清单配对改名后的 SQLite/WAL；先核对原始内容哈希，再导出一致性副本并登记配对依据。普通 `.sqlite-wal.snapshot` 命名由导出器直接识别。
- `curate_embedded_payloads.py` 识别 JSON 中 Base64 编码的资源本体，保留大小、哈希和路径；文本工具证据不截断，嵌入文本中的凭证同样脱敏。转换清单明确区分原件哈希与导出哈希。
- `redact_record_findings.py` 根据核验产生的对象哈希修正上传副本，报告不写匹配值；随后必须再次运行筛选打包与完整核验，确保旧分片中的未脱敏字节也不进入提交。
- `resume_export.py` 在清单写入失败后按原始内容哈希复用已导出记录，再顺序读取原档补齐缺项。缓存输出只是中间目录，可能包含未引用片段，必须经过增量合并与筛选后才能发布。
- `prepare_incremental.py` 比较来源路径和哈希，将新增及修复条目编入独立来源清单。`--resource-hashes` 接受经过内容核查的排除证据。此工具会登记未读条目，登记本身不代表已充分检索或恢复；应先完成内容检查。
- `append_records.py` 合并准备清单及其 `entry_overrides`。旧路径可通过 `records.py` 定位到已修复条目，旧分片仍保留。
- `finalize_incremental.py` 依据带证据的 JSON 路径规则排除资源，只重新打包尚未发布的片段；`--base` 指定的已发布分片字节不变。它会重建运行索引并登记排除项。
- `verify_incremental.py` 复用基线分片证明，对新分片完整解压、核验哈希及重组，检查数据库行数并扫描新增正文、跨片边界和解码后的元数据。读取范围限制在候选记录目录内。
- `verify_samples.py` 按选择清单恢复真实运行的数据库输入、输出、工具记录、状态以及独立请求/响应/结果；禁止读取记录目录以外的原档。样例成功只证明该样例，不证明所有运行完整。
- `coverage_records.py` 从当前有效索引生成逐 Bench 覆盖表，分别统计外层文件、嵌套记录引用、数据库状态和来源运行范围；这些数字不能作为独立实验次数。
- `shard_object_index.py --root RECORDS` 在最终验收前将对象索引拆成不超过 25 MiB 的独立 gzip 分片，逐片登记哈希并检查映射往返一致。`records.py` 同时兼容旧单文件索引和新 `manifests/object-index.json`；正文分片不变。
- `compact_record_reports.py --root RECORDS` 将较大的逐项资源排除清单转为带哈希的压缩分片，摘要仍可直接阅读，排除项不会因报告压缩而丢失。

`catalog.json` 的 `entry_overrides` 保存旧来源路径到修复条目的映射。`source_sha256` 始终描述原件，导出内容哈希描述转换后的记录。资源排除、凭证脱敏、归档展开、数据库导出和原始截断分别记录。

下面的 Restic 工具仅维护本地核对原件及历史完整环境恢复；本轮保留原档，不将其作为发布资产。

归档数据位于工作区根目录的 `_objrun-archive/`，不进入 Git。需 Python 3.12+ 和 Restic 0.19.1；本次 Windows 清理脚本使用 PowerShell 7。当前工具保留普通文件的完整字节、原路径与修改时间；不依赖 Windows ACL 来恢复实验记录。

一次收集的流程：

1. `archive_collection.py` 清点静止目录、以 TAR 流传入 Restic，写入逐文件 SHA-256 清单并检查快照结构。相同内容块跨收集去重，使用最高压缩等级。
2. `verify_collection.py` 完整读取归档内每个文件，核对 SHA-256、路径、长度与链接目标，并重新检查来源目录未变化。
3. `retire_collection.ps1` 默认只预览。显式 `-Apply` 才清理已验证的展开文件；逐路径核对，目录仅做非递归删除，出现新文件会停止。保留项目所需的小型输入文件，跳过已登记的不可读目录。

还原示例（PowerShell，变量应使用实际工作区与工具位置）：

```powershell
$workspace = 'F:\git\TgEngin-handoff-2026-10-07'
$restic = "$workspace\_publication-preview\2026-10-23\compact-execution\tools\restic-0.19.1\restic_0.19.1_windows_amd64.exe"
python "$workspace\objrun\scripts\storage\restore_collection.py" `
  --workspace $workspace --name legacy-runs --restic $restic `
  --destination 'F:\git\objrun-restored-runs'
```

`--destination` 默认必须为空。显式 `--merge-existing` 可恢复到保留了小型项目输入的旧目录，但已有文件必须与归档的 SHA-256 相同；不同内容不会被覆盖。恢复后逐文件重新核对 SHA-256。

只查看清单或提取单个日志，不必展开整个历史目录：

```powershell
python "$workspace\objrun\scripts\storage\inspect_collection.py" `
  --workspace $workspace --name legacy-runs list --limit 20
python "$workspace\objrun\scripts\storage\inspect_collection.py" `
  --workspace $workspace --name legacy-runs extract `
  --path '清单中的相对文件路径' --output 'F:\git\selected-log.txt' --restic $restic
```

单文件提取同样核对 SHA-256，拒绝覆盖已有输出。TAR 收集需要顺序读取到匹配内容，节省的是展开空间，不保证即时随机读取。

目录链接/符号链接的目标保存在来源清单及收集目录的 `last-restored-links.json`，TAR 恢复时不会自动建立这些链接。WSL 特殊符号链接还保留原始重解析数据。硬链接在收集内恢复。历史脚本中的绝对路径保持原文，重新运行时需结合路径迁移表处理；归档恢复不代表旧容器可以直接启动。

每个收集目录包括 `record.json`、压缩的路径清单、逐文件 SHA-256、完整性检查结果及清理日志。只有 `restore_verified: true` 的收集可以清理原展开文件。`excluded` 是未读取、未删除的范围；`kept_files` 是本批清理时保留的文件，后续批次可能再归档其中一部分。总索引中的 `expanded_kept_files` 表示当前仍在原路径的文件。

`--external-readonly` 用于工作区外已登记的实验输出；它只读取原件，清理工具明确拒绝删除这类来源。本次 SciCode 输出及早期运行目录链接的实际目标使用这一方式。链接与实际档案的对应关系见 `experiments/provenance/external-source-map.json`。

本地 Restic 仓库使用空密码；它与原始本地文件遵循相同的文件系统访问权限，不作为加密保密措施。原档保留本地核对，当前所有收集仍为 `uploaded: false`；新方案不上传这些原档。
