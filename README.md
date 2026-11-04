<p align="center">
  <img src="site/media/objrun-poster.png" alt="ObjRun" width="720">
</p>

<h1 align="center">ObjRun</h1>

<p align="center"><b>Objective Engineering for Agentic Science</b><br>你定义目标，AI 带着反馈去完成。</p>

<p align="center">
  <a href="https://objrun.imontlaji.workers.dev/">网站</a> ·
  <a href="site/paper.pdf">论文</a> ·
  <a href="https://objrun.imontlaji.workers.dev/runs">运行回放</a> ·
  <a href="https://objrun.imontlaji.workers.dev/blog/">案例博客</a> ·
  <a href="site/media/objrun-film-en-1080p60.mp4">介绍短片</a>
</p>

---

ObjRun 是一个目标运行时（objective runtime）。使用者只写“怎样算对”：把一个领域的检查器包装成评估器，封存起来，再规定一次尝试最多能问几次、一次拒绝能透露多少信息。模型、工具和搜索策略都以数据形式声明。智能体只能通过一个返回判决的端口接触标准，被拒后带着历史重启。每条判决都写进数据库，所有分数从记录中计数得出。

内核不包含任何学科、模型或工具的名字。论文中的 20 个评测接入时都没有改内核，每个评测只写了一份目标记录和一层官方评分器的包装。

## 工作原理

<p align="center">
  <img src="paper/current/figs/main-0-system.png" alt="ObjRun 系统总览（论文 Fig. 2）" width="760">
</p>

<p align="center"><sub><b>Fig. 2</b>　ObjRun 总览。a：作者定义任务 d、目标 G 和 harness 声明，校验后封存 G。b：求解器通过访问端口查询同一个封存的目标，每次尝试最多 c 次，按信息级别 L 得到反馈；提交被拒时，在 K 和 T 允许的范围内重启，保留历史并重置查询额度。c：调用、判决、历史和用量写入持久记录，结果从记录计算。</sub></p>

一道题的完整流程：

1. **发布**：写任务 d 和目标 G。内核检查 G 的图结构（边合法、无环、唯一出口且输出布尔值、每个端口都接线），任一条不满足就整批拒绝。通过后，G 的定义写入单独的封存库，主库的接口读不到它。
2. **尝试**：智能体在一次尝试里调用工具，并可向 G 查询最多 c 次，每次得到一条判决和事先声明的反馈。
3. **重启**：提交被拒后，带着历史重启，查询额度重置。
4. **结束**：提交通过、预算用完或时间耗尽时任务结束，最后一次提交重新评估，作为最终结果。

逐步说明见 [docs/loop.md](docs/loop.md)。

## 主要结果

以下结果均使用 DeepSeek V4.1 Flash。U 为同一模型的单次作答，F 为挂载目标后的运行。

<p align="center">
  <img src="paper/current/figs/fig1-vs-published.png" alt="20 个评测上的 U、已发表参考与 F（论文 Fig. 1）" width="820">
</p>

<p align="center"><sub><b>Fig. 1</b>　20 个评测上的单次作答（浅灰）、已发表参考结果（深灰）与 ObjRun（蓝）。</sub></p>



全部 20 项结果、预算和口径见论文附录。

### 科学案例

论文另选了四个近期论文中的科学问题，每个限时 5 小时，结果由宿主机上的检查器独立验证。四项的模型调用费用合计 5.62 美元。

| 问题 | 参考值 | 结果 | 验证方式 |
| --- | --- | --- | --- |
| DNA 编码（n = 10, d = 4, GC = 5） | 676 个词 | 1,688 个词 | 两套独立的整数实现 |
| 低存储 Runge–Kutta（5 级 3 阶，2N） | 误差范数 0.015632 | 0.013967，在固定可行集上最优 | 精确有理区间算术 |
| 球面设计（R⁶ 中 24 个单位向量） | 猜想 | 4 个非全局局部极小值 | 区间算术证书 |
| RNA 可设计性（Repetitious Sequences 8/10） | 上界 0.18740 | 上界 0.15770 | 全部赋值的包络枚举 |

<p align="center">
  <img src="paper/current/figs/discovery-runs.png" alt="四个科学案例的验证结果" width="820">
</p>

每个案例的过程见[案例博客](https://objrun.imontlaji.workers.dev/blog/)。

## 快速开始

### 环境要求

- [Bun](https://bun.sh)。运行时直接执行 `.ts`，没有编译步骤；SQLite 使用 Bun 自带的 `bun:sqlite`。
- 至少一个模型服务的 API key。

### 安装与启动

```bash
cp .env.example .env
```

在 `.env` 中填写 key。这个文件不进版本库：

```
DEEPSEEK_API_KEY=
DASHSCOPE_API_KEY=
```

```bash
cd app
bun install
bun start
```

服务默认监听 `127.0.0.1:7801`，接口在 `/api` 下，自带页面在 `/ui`。用到的 key 没有填写时，程序会报错并指出缺少哪一个。

检查服务状态：

```bash
curl -s http://127.0.0.1:7801/api/health
```

声明智能体、发送第一个任务，以及各评测的接入方式，见 [examples/](examples/README.md)。

### 配置

`config.yaml` 是程序唯一的配置文件，包括端口、日志级别、主库和封存库的位置等。文件中的路径都相对 `config.yaml` 所在目录解析，与启动时的工作目录无关，因此从仓库任何子目录启动，打开的都是同一个库。值里可以写 `${VAR}`，从环境变量读取。代码中的环境变量沿用旧名 `TGENGIN_*`。

### 打包

```bash
cd app && bun run build
```

产物在 `dist/`，每个平台一个独立的可执行文件（win-x64、mac-arm64、mac-x64），目标机器不需要安装运行时，把 `config.yaml` 放在可执行文件旁边即可。`bun run verify` 先做类型检查再打包。

项目没有 native 依赖，因此可以在 Windows 上一次交叉编译出 mac 版本。新增依赖同样不能是 native，也不能绑定特定运行时。

## 项目结构

```
config.yaml          唯一的配置文件
app/src/
  main.ts            入口：读配置，启动数据库和接口，注册句柄，处理停机
  H2H/               状态：数据库与对外接口
  engine/            读取、处理、写入的主循环
  objective/         目标 G；定义存放在封存库，主库读不到
  tree/              尝试树：派生、失败后开兄弟节点、回退
  llm/               模型接入：chat 与 duplex 两种模式
  tools/             read / write / edit / glob / grep / bash
  place/             执行位置：转发层与远端运行时
  ui/                引擎自带的页面，只通过 /api 访问
examples/            可运行的示例与各评测的接入
experiments/         Bench 来源与实验记录索引
paper/current/       论文源码、图表与绘图数据
scripts/             运行器、校验器与记录工具
site/                网站、运行回放与案例博客
docs/                架构、主循环、表结构与复现说明
test/                回归测试
```

## 网站

线上地址：https://objrun.imontlaji.workers.dev/