# 实验记录索引与外置正文

代码仓库保留运行索引、摘要、当前覆盖报告和 SHA-256 清单。完整正文分片、逐文件映射和历史整理报告已于 2026-11-04 移到仓库外，并从发布的 Git 历史中移除。Hugging Face 尚未上传；不能只克隆代码仓库就读取完整轨迹。

本机完整记录目录：

```text
F:\git\TgEngin-handoff-2026-10-07\_objrun-cleanup-backup-20261104\repository-before\experiments\records
```

这个目录包括原始 `catalog.json`、`packs/`、`manifests/`、`runs/`、`reports/` 和 `summaries/`，原有分片与重组映射保持原字节。以后上传 Hugging Face 时，应上传这整个记录目录，不能只上传 packs。先检查上传范围，再记录 dataset 地址和固定 revision；本次没有创建远端数据集。

只查看仓库内索引：

```powershell
python -B scripts/storage/records.py runs --bench labbench --limit 20
```

读取正文使用 Python 3.12+ 及 `requirements-records.txt` 中的 zstandard。明确指定备份目录，或以后下载的完整目录：

```powershell
$recordsRoot = 'F:\git\TgEngin-handoff-2026-10-07\_objrun-cleanup-backup-20261104\repository-before\experiments\records'
python -B scripts/storage/records.py --root $recordsRoot files --bench terminal-bench --limit 20
python -B scripts/storage/records.py --root $recordsRoot --isolated read --collection COLLECTION --path '索引中的路径'
python -B scripts/storage/records.py --root $recordsRoot extract --collection COLLECTION --path '索引中的路径' --output 'F:\selected-log.txt'
python -B scripts/storage/records.py --root $recordsRoot verify
```

也可以设置 `OBJRUN_RECORDS_ROOT`；命令行 `--root` 优先。未指定外置正文目录时，正文读取会给出明确提示，索引仍可查看。SQLite 表使用 `--table TABLE_NAME`，压缩包成员使用可重复的 `--member MEMBER_PATH`；提取拒绝覆盖已有输出。

`manifests/packs.json` 保存每个正文包的长度和 SHA-256，`manifests/object-index.json` 保存外置对象索引分片的 SHA-256。`catalog.json` 保留来源集合和详细清单位置。仓库中的这些相对路径以完整外置记录目录为根，不表示正文已存在于本仓库。

当前覆盖见 [覆盖表](summaries/coverage.md)、[当前报告](reports/current-bench-coverage.json) 和 [原始缺损](reports/original-source-gaps.json)。失败、中断、重试和成功证据都保存在外置目录；搬迁没有补造缺失记录，也没有重新执行实验或判分。`source_sha256` 描述原件，`content.sha256` 描述此前导出后的内容，两者不混同。
