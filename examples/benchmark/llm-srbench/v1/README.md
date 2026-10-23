# LLM-SRBench 发布版四组运行器

固定数据：`pkuHaowei/llm-srbench@f4101e201952bb35cab8332b6dcf337b6df02aa8`，240 道方程；四组共 960 条记录。服务器目录为 `/mnt/aliyunsb/pingxingwang/tgengin-bench/llm-srbench-20261019-v1`。

四组为单次结构生成、真实 ObjRun、最多五次独立采样、同一 ObjRun 外壳下的二值反馈。共同拟合器使用 SciPy least_squares、三组固定初始化、每次至多1000次函数求值、最多2048个固定训练点；反馈用完整训练集。候选为表达式 JSON，参数按 p0、p1 顺序编号，最终参数冻结后评测。

模型为 OpenRouter `deepseek/deepseek-v4.1-flash`，只允许 DigitalOcean，high reasoning，temperature=0，max_tokens=16384，无供应商回退，无 seed。单次组每题 $0.025；其余每题 $0.10，正式求解最多 $78。所有调用与有限重试计费；未知请求保留上界，不自动再次生成。

先运行免费控制，再冻结源码与协议。canary 是每个子集按 ID 排序前两题，四组40条记录；按执行、费用、信息隔离和轨迹检查决定是否继续，其通过率不作为放行标准。试跑与正式使用同一冻结包，合格记录直接计入全量。

所有训练判决均来自训练数组。全量候选及三个费用截点冻结后才批量评测 ID/OOD；没有测试早停或测试挑选。输出 NMSE、Acc0.1、项目 NMSE≤0.01 成功率、配对区间、重复率、截断与异常、全部实际/未知费用。未运行 GPT-4o SA judge。

发布包的参考公式字符串需要状态函数展开与参数记号规范化，部分数值参考也不能直接复现数组；相关记录保存在 `outputs/controls/reference-metadata-audit.json`，不改变原始数组或240题范围。评分器不读取这些字符串。原始参考与规范化检查结果均保留。

本轮 engine 复制自当前项目工作树，保留逐文件哈希。只有复制件增加二值 verdict 投影和 stdout/stderr 持久化，原项目核心代码不变。Python 使用独立 runtime 入口引用此前冻结的科学依赖；Bun SDK 使用冻结依赖，版本及文件哈希随结果保存。候选为白名单表达式，执行子进程无网络、降至 UID65534、无API密钥，私有评分数据目录0700。

本地操作入口：`F:/git/TgEngin-handoff-2026-10-07/TgEngin/examples/benchmark/llm-srbench/v1/local_ops.py`，用 `D:/ProgramData/anaconda3/python.exe` 执行。

| 动作 | 用途 |
| --- | --- |
| `stage` | 仅在源码未冻结时准备独立包与发布数据 |
| `refresh` | 仅在付费运行前刷新源码 |
| `controls` | 不调用模型的协议、数值、隔离与真实引擎控制 |
| `launch` | 从现有项目.env读授权Key，经SSH stdin传入控制器进程，不写Key文件 |
| `pull` | 同步紧凑状态；终止后导出、下载、校验并解压完整归档，再离线审计 |

本地结果：`F:/git/TgEngin-handoff-2026-10-07/TgEngin/runs/llm-srbench-release240-20261019`。`retrieval.json` 同时记录服务器与本地 SHA256、实际任务数和离线审计结果。不能把归档下载成功当作全部实验成功。

恢复仅使用同一冻结入口，已有 result.json 不重跑，已有请求不扩大有限尝试链。中断的 native cell 不自动重新启动；未知付费派发保留，异常与模型答错分开。不能在正式运行中刷新 package 或依据 ID/OOD 修改协议。
