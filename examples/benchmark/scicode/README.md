# SciCode 接入：原始版与Verified准备试跑

官方源码：https://github.com/scicode-bench/SciCode 。当前固定 commit：`e3158ea011d4235245a547460d3688d7ccbf9900`。

目标是接入原始 SciCode：按整题逐子步骤生成，继承本次模型生成的前序代码，同时报告子步骤和整题成绩。不能将首个子步骤冒充整题，也不能把参考解放进前序模型上下文。

原始数值目标`test_data.h5`由官方README的Google Drive文件夹提供，1,049,345,865字节。公开下载目前返回配额限制；原始版未试跑。已有Verified目标1,108,078,257字节，官方MD5已核对，来源与SHA256见运行manifest。

SciCode-Verified是独立修正版：https://github.com/flyingwagner/scicode-verified ，固定`ddab4a92f8d80a7113ab946628e994b52354d838`。本轮使用v2、with_background=true；预先选择问题5、8、9、11、12、14、15、16、17、18，逐步骤继承实际模型交付代码。10个完整问题、39个子步骤已完成，独立终判5/10通过、10/10有效；结果见docs/phase1/report.md。未将287个子步骤或两个版本各算一个bench。

## 环境

`Dockerfile` 固定 Python 和科学库版本。正式执行候选使用一次性评分容器，关闭网络，限制CPU/内存/进程，清理环境变量；仅挂载本次候选及评分端需要的数据。求解器不获得该容器、测试数据和评分端的访问权。

已有镜像的ID、额外依赖版本与文件摘要见docs/phase1/environment.json。已有本地缓存时，启动`stand.py --port 17921`后用`bun scripts/phase1/pilot-scicode.ts 10`试跑；每轮源代码快照在模型请求前保存。原始数据下载及镜像重建需先核空间。

当前只使用单一Python3.12/NumPy1.26.4/SciPy1.14.1准备环境，评分超时90秒；没有复现规范多环境OR与1800秒配置。每个子步骤单独使用300秒/c=2，不能称作整题只使用该预算。选中10个问题的39个子步骤均已通过按公开题面独立编写的正确实现控制；39个错误返回控制与10个语法异常控制也全部通过。隐藏目标、参考文件、无测试退出和科学对象传输另有控制。完整覆盖证据见scicode-expanded-controls.json、scicode-negative-controls.json与scicode-selfcheck.json；范围只包括这10个问题。因此本轮是明确标注的版本试跑，不宣称原始SciCode或完整规范接入验收完成。

## 控制与候选身份

控制脚本不生成模型答案、不下载数据：

```powershell
python scripts/phase1/scicode_expanded_controls.py
python scripts/phase1/scicode_expanded_controls.py --negative
python scripts/phase1/accept_scicode.py
```

布朗运动控制保持轨迹顺序与随机数状态，用有界批次展开线性递推；Numerov控制将相同带状递推交给已有BLAS执行。优化前90秒超时的实现与判决仍保留，分别有3项随机状态/结果等价检查及5项解析/递推检查。没有把这些独立正确控制混入既有模型的前序代码。

已交付模型候选的原验收保持在whole-problems.json；独立复评脚本另存whole-problems-reaccepted.json，保存每份原始交付答案、提取代码及整题累计代码的摘要。report.py要求完整控制通过、摘要与冻结候选一致、原判决未改变。后续pilot-scicode.ts在全部模型生成结束后才执行最终验收。

评分服务只缓存结构完整的有效布尔判决；评分故障、非法判决及异常返回HTTP503，不缓存，也不向求解器发送隐藏错误正文。真实HTTP回归只验证接口行为，不代替官方控制。
