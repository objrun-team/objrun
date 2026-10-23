# LLM-SRBench 独立 v2 续跑

人类用户已同意独立 v2，仅续跑原 v1 从未启动的483个单元。清单冻结于 `continuation-plan.json`：baseline120、objrun121、independent121、binary121；v1的475条已完成结果及2个中断单元不再调用模型。发布240题、模型、参数拟合器、候选/美元上限均不变。v1完整性失败永久保留，v2不覆盖v1目录。

远端 `/mnt/aliyunsb/pingxingwang/tgengin-bench/llm-srbench-20261019-v2`，本地结果 `F:/git/TgEngin-handoff-2026-10-07/TgEngin/runs/llm-srbench-release240-20261019-v2`。Python用 `D:/ProgramData/anaconda3/python.exe -X utf8`；操作入口为本目录 `local_ops.py`，动作 stage、controls、launch、pull、monitor。

controls须通过原18项完整控制、8项真实请求关闭回归、任务范围/反馈排空/审计回归，以及两组真实引擎-Gateway-真实拟合器的免费全链路。然后冻结源码，先运行独立10题×四组canary，40条计入483；技术审计通过才自动继续。canary在原剩余Synth四子集轮转选择，Transform已全部在v1启动；不增加、替换或重跑旧样本。

修复：关闭模型/反馈入口后等待所有已接受请求和拟合落盘，再冻结候选与费用；全局停止、截止时间在费用锁后重新核对；已知零派发取消留下零费用回执；HTTP200读超时归类未知费用，停止新派发；总额限制包括v1实际及4条未知预留。新包的引擎启动就绪等待从约10秒改为约60秒，仅影响新单元的设施等待，不增加600秒求解期限及重试次数。

最终先冻结v2全部483候选和费用，再在独立analysis副本冻结960个映射并批量评测ID/OOD：v1完成475、v2完成483、v1中断2。保留原始v1结果字节和原版失败审计；费用以完整journal统计并保留原行差异。报告按协议版本统计；不同版本覆盖不同题目队列，不能解释为纯v2的240题结果。数值指标不称SA。

监控每15分钟 pull 后 monitor，检查实际cmdline、冻结源码、allowlist、完成后派发及result/journal。运行中活跃任务未回执请求是预留；终止未知付费、费用/完整性/余额/权限故障须保存断点、停止新派发并通知。禁止恢复v1、重启已有native cell、重发未知请求、换key或增额。新故障先检查日志及真实PID，不自动重新采样。

归档包含v2完整证据、analysis副本、不可变v1原始归档、源码及manifest。仅在483条结束、SHA256与离线v2审计、960覆盖及分版本评测报告均核验后停用本聊天自动跟进。不能将两个中断单元称为已完成求解，也不能声称v1审计通过。
