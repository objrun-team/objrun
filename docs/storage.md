# 数据与归档

代码仓库保留程序、论文源码、正式图表和绘图数据、可复现实验源码、必要测试输入，以及实验记录索引、摘要和哈希。完整运行正文的位置与下载方法见 [记录说明](../experiments/records/README.md)；远端地址及 revision 以 [存储索引](../experiments/records/external-storage.json) 为准。

## 实验记录

`experiments/records/` 中的 catalog、运行索引、覆盖报告及哈希是记录入口。完整正文和详细映射由外置目录提供，使用 `records.py --root PATH` 或 `OBJRUN_RECORDS_ROOT` 指定。公开的图表数据仍在 `paper/current/data/`，论文编译不要求恢复原始运行目录。

## 测试样本与历史输入

[test/fixtures](../test/fixtures/README.md) 只保留少量人工构造的测试样本。历史自检报告、接口原始响应、余额快照、故障记录、恢复审核、旧实验导出和编译包均存放在仓库外，原始内容与哈希不变。

确需检查原始记录的脚本，通过 `.local-evidence/repository/<原仓库相对路径>` 读取。`.local-evidence` 是被 Git 忽略的本地目录链接，指向外部归档，不随克隆分发。旧 docs 路径到外部输入的映射见 [directory-map.json](../scripts/directory-map.json) 的 `external_inputs`。没有归档时，这些历史检查会缺少输入；核心测试和人工构造的定价、提供方测试不依赖它。

本机本轮归档在项目父目录的 `_objrun-cleanup-backup-20261104/followup-fixtures/archived/`，其中包含 `repository/`。在仓库根目录恢复链接：

```powershell
$archive = (Resolve-Path '../_objrun-cleanup-backup-20261104/followup-fixtures/archived').Path
New-Item -ItemType Junction -Path .local-evidence -Target $archive
```

其他机器应先取回原始归档，再把链接指向包含 `repository/` 的目录；Linux/macOS 可使用 `ln -s /absolute/archive/path .local-evidence`。历史材料的后续上传位置以实验存储索引为准，不将本地备份路径当作已发布的下载地址。

新自检报告写入 `.scratch/phase1/`，软件环境报告写入 `.scratch/software-preflight/`，代码基准 smoke 报告写入 `.scratch/code-benchmarks/`。不要把新输出写入历史归档或测试样本目录。编译包可用保留的构建脚本重新生成；指定输出路径时使用 `.scratch/` 等工作目录。

## 历史材料

旧交接、阶段计划、审计过程、论文修改记录与已废弃的目录说明保存在项目父目录的 `_objrun-cleanup-backup-20261104/`。本轮补充归档位于其 `followup-docs-examples/repository-before/`，按原仓库相对路径定位；文件哈希、移动清单、新旧提交对应表和验证结果位于该补充归档的 audit 目录。

原有 `_objrun-archive/` 继续保存早期原档，未改动其内容。原始 Git 备份用于恢复历史文件，不应推回清理后的远端。目录链接仅登记并移走链接入口，未递归修改外部归档。

当前可执行位置见 [脚本入口](../scripts/README.md) 和 [示例入口](../examples/README.md)。历史证据中的旧绝对路径、源文件 SHA-256 和运行编号保留原值；需要重放历史执行时，应恢复对应的原始源码和环境，而不是把当前改过路径的脚本冒充原执行版本。
