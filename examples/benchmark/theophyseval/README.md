# TheoPhysEval 自动题接入

固定官方 revision `6c6fe63a8c87f15e8fa05f3bcb549a3d44190b5d`，Realistic 条件。排除人工题 autonomous-de，保留 45 个单任务和一个四阶段任务，对应 49 个科学问题。四组为单次、真实 ObjRun、独立采样、二值反馈，费用不对齐，无单题美元上限。

运行实现位于 `scripts/theophyseval/`。本轮工作目录为工作区 `tmp/theophyseval-20261016-v3/`，控制器在宿主 Windows 运行，科学计算通过 Harbor 0.22.0 的 DockerEnvironment 在官方固定镜像中执行。Python 依赖单独安装在 `tmp/theophyseval-runtime/venv/`。评分使用官方 grader_runtime 的原函数，在可信宿主 Python 进程中执行；评分器不执行候选代码，也不向求解容器挂载 tests 或标准答案。

`prepare.py` 固定数据、隔离公开和私有材料，并复用已审计 SciCode 引擎快照。原生引擎每个求解单元 c5、600 秒、4 分支、12 units。其他三组每阶段使用最多 12 次工具求解模型调用、600 秒，一轮表示完整任务流程；独立和二值最多 5 轮，整题通过即停。独立每轮新容器与新上下文，二值保留本题上下文和环境，但外部正确性信息只返回整题 passed 或 failed。四阶段各组只继承本轮实际计算的 handoff，独立重试必须从第一阶段重来。

共同工具为 compute 和 snapshot。compute 仅在当前求解容器执行命令；snapshot 暂停该容器，冻结完整 /output 后生成包含文件哈希的不可变候选身份，再恢复容器。ObjRun 的 submit 和 verify 只接受该会话的候选；终判绑定真实 finalCandidate。格式失败可解释公共文件/语法约束，正确性回执不暴露数值误差、容差或标准答案。

评分自检覆盖 49 题的正例、非法答案、缺失答案、45 题的明显错误数值，以及容差边界、备选答案和共同比例归一化。容器控制覆盖容器内部超时及嵌套子进程终止、未授权请求拒绝、UID、测试/密钥隔离、候选冻结、独立环境重置、会话间候选拒绝和四阶段模板。引擎控制使用合成模型响应，真实执行 compute、snapshot、verify、submit，不调用付费模型。

试跑事先固定为 axion-dielectric-conversion、sllod-thermostat、dispersion-pi-series、all-electron-to-crystal，四组共 16 个任务流程、28 个科学问题终态。试跑是工程开发数据，正式汇总包含这些题时需要声明，并另报未用于开发的题。只有评分、容器、原生引擎控制和试跑逐项审计都通过，supervise.py 才写入 pilot-acceptance.json 并启动已授权的全量 46 任务、49 问题四组运行。科学问题答错不等于基础设施失败。

模型固定为 OpenRouter deepseek/deepseek-v4.1-flash / DigitalOcean / high / temperature=0 / 16384 tokens；实际 canonical model、回执、费用及未知费用全部保存。接口最多 3 次有限尝试，不自动扩大账户额度或换模型。已有 launch 记录不允许重复启动；未完成任务需要独立明确恢复，不能删除锁后重新生成。

输出包含每轮上下文、模型请求和原始响应、generation ID、费用回执、工具记录、候选 manifest、逐阶段评分、ObjRun SQLite/任务树、source pins 和审计报告。数据和引擎来源摘要在 data/source-pins.json、data/engine-origin.json。正式成绩分母固定 49，四阶段不得与父级聚合判据重复计数。

首个 v1 工程试跑发现 Docker 客户端超时后子进程仍可写输出，以及异常部分记录使状态汇总崩溃，已整体作废。修复后在 v2 新目录重新验收，不复用科学结果。原账单和失败证据保留在 v1/control/restart-record.json；正式汇总需另列开发费用。

v2 试跑在两个并发任务下一次推理发送前发生同时断连，整体停止且审计不通过。v3 为共用的账户只读查询增加最多 3 次有限重试和无敏感内容的逐次日志；鉴权失败不重试，耗尽后停止，不重复付费推理。故障注入覆盖 socket、503、非法 JSON、401 与耗尽路径。v2 已知费用 0.166497201 USD、1 笔未确定费用单独保留，没有遗留在途推理；不复用其科学结果。
