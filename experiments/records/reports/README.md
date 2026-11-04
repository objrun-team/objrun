# 当前覆盖与核验报告

本目录保留当前覆盖、来源范围、原始缺损、不可读来源及关键核验报告。报告中的实验事实与计数保持原值；2026-11-04 的搬迁没有重跑实验。

- `current-bench-coverage.json`、`bench-coverage.csv`、`current-source-scope.json`：当前选择集范围。
- `original-source-gaps.json`、`unreadable-sources.json`：原始缺失、损坏和未读取来源。
- `remaining-integrity-verification.json`、`remaining-sample-verification.json`：此前完整性核验及真实样例恢复证明。
- `terminal-conversion-verification.json`、`verification-redactions.json`：转换及脱敏核验。

历史报告和逐项审计正文保存在外置完整记录目录的 `reports/`，见 [记录说明](../README.md)。旧报告中的 Git 内存放位置和体积只描述当时状态，不能作为当前仓库布局或占用量。样例恢复成功不代表全部历史实验完整。
