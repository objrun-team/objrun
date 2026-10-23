# OlympiadBench 接入

实现位于 `scripts/olympiadbench/`。`prepare.py` 从固定数据和已核验的 FrontierScience 引擎副本构建私有运行包；`ops.py deploy` 部署 novaeve 并执行零模型验收；验收通过后 `ops.py launch` 一次启动 8 题两组 canary，通过后自动继续其余题。canary 包含在 236 题内，不重复生成。

两组为 baseline 和 objrun，统一 DeepSeek 官方 deepseek-flash、thinking enabled/high/16384。运行包的 experiment.json、source-pins.json 和 dependencies.json 为实际配置与版本来源。使用本地动态端口桥接真实引擎，规则评分器在独立受限 Python 子进程执行，真实 Key 只由传输控制器持有。

`grade.py` 封装官方评分器；`runtime.py::Judge` 提供带身份哈希和并发去重的私有评分队列，`native.ts` 提供 G 的 present/correct HTTP 句柄。`report.py` 在停止写入后进行候选、评分、预算、请求和源码审计，产生 SUMMARY.json、AUDIT.json、FINAL_RESULTS.csv、REPORT.md。

`ops.py pull` 获取紧凑状态。完成后 `ops.py retrieve` 在 NAS 生成完整归档、回传并核对两端 SHA256；归档包含完整结果、原始响应、请求回执、费用、日志、SQLite、源码与私有依赖。

已有部署、launch、started 或 dispatch 记录时先检查状态，禁止盲目重复入口。有效输出不重新生成；异常与未知费用保留，有限重试最多三次。运行费用按官方 token 费率估算，逐请求实际账单另标不可得。
