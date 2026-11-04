# 数据与归档

代码仓库保留程序、论文源码、正式图表和绘图数据、可复现实验源码、必要测试输入，以及实验记录索引、摘要和哈希。完整运行正文的位置与下载方法见 [记录说明](../experiments/records/README.md)；远端地址及 revision 以 [存储索引](../experiments/records/external-storage.json) 为准。

## 实验记录

`experiments/records/` 中的 catalog、运行索引、覆盖报告及哈希是记录入口。完整正文和详细映射由外置目录提供，使用 `records.py --root PATH` 或 `OBJRUN_RECORDS_ROOT` 指定。公开的图表数据仍在 `paper/current/data/`，论文编译不要求恢复原始运行目录。

## 测试固定输入

历史自检和协议测试使用的固定 JSON、HTML 位于 [test/fixtures](../test/fixtures/README.md)。这些文件按原字节保留；日期与运行标识属于证据身份，不是当前运行状态。原路径映射见 [directory-map.json](../scripts/directory-map.json) 的 fixed_test_inputs。新运行输出不应写入固定输入目录。

## 历史材料

旧交接、阶段计划、审计过程、论文修改记录与已废弃的目录说明保存在项目父目录的 `_objrun-cleanup-backup-20261104/`。本轮补充归档位于其 `followup-docs-examples/repository-before/`，按原仓库相对路径定位；文件哈希、移动清单、新旧提交对应表和验证结果位于该补充归档的 audit 目录。

原有 `_objrun-archive/` 继续保存早期原档，未改动其内容。原始 Git 备份用于恢复历史文件，不应推回清理后的远端。目录链接仅登记并移走链接入口，未递归修改外部归档。

当前可执行位置见 [脚本入口](../scripts/README.md) 和 [示例入口](../examples/README.md)。历史证据中的旧绝对路径、源文件 SHA-256 和运行编号保留原值；需要重放历史执行时，应恢复对应的原始源码和环境，而不是把当前改过路径的脚本冒充原执行版本。
