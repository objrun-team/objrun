<p align="center">
  <a href="README.md">English</a> | <strong>简体中文</strong>
</p>

<h1 align="center">ObjRun</h1>

<p align="center">面向智能体科研的目标工程</p>

<p align="center">
  <a href="https://objrun.imontlaji.workers.dev/zh/#video">
    <img src="site/media/objrun-poster.png" alt="观看 ObjRun 介绍视频" width="720">
  </a>
</p>

<p align="center">
  <a href="https://objrun.imontlaji.workers.dev/zh/">网站</a> ·
  <a href="https://objrun.imontlaji.workers.dev/paper.pdf">论文</a> ·
  <a href="https://objrun.imontlaji.workers.dev/zh/#video">视频</a> ·
  <a href="https://objrun.imontlaji.workers.dev/zh/runs">运行回放</a> ·
  <a href="https://objrun.imontlaji.workers.dev/zh/blog/">科学案例</a>
</p>

---

ObjRun 是让 AI 智能体围绕可验证目标工作的运行时。你提供检查器，设定反馈内容、查询次数、重试次数和时间限制；ObjRun 管理尝试过程，让智能体带着反馈重试，并记录每次判决。

模型、工具和搜索策略都以数据形式声明。论文中的 20 个评测均未修改内核，每项只需一份目标记录和一层官方评分器包装。

## 快速开始

需要 [Git](https://git-scm.com/)、[Bun](https://bun.sh)，以及所用模型服务的 API key。

```bash
git clone https://github.com/Deref-IO/objrun.git
cd objrun
cp .env.example .env
```

在 `.env` 中填写需要的 key，该文件已被版本控制忽略。基础示例使用 `DEEPSEEK_API_KEY`；使用 DashScope 的示例需要 `DASHSCOPE_API_KEY`。

```dotenv
DEEPSEEK_API_KEY=your-api-key
```

启动服务：

```bash
cd app
bun install
bun start
```

打开[内置界面](http://127.0.0.1:7801/ui)，API 地址为 `http://127.0.0.1:7801/api`。在另一个终端检查服务状态：

```bash
curl http://127.0.0.1:7801/api/health
```

接着按[示例](examples/README.md)声明智能体并发送第一个任务。用到的模型 key 缺失时，程序会明确报错。

## 工作原理

<p align="center">
  <img src="paper/current/figs/main-0-system.png" alt="ObjRun 系统总览（论文 Fig. 2）" width="760">
</p>

<p align="center"><sub>定义并封存目标 → 尝试、检查与重试 → 从判决记录计算结果。</sub></p>

1. **发布** — 定义任务和目标。内核校验目标图，再写入独立的封存库，主库接口无法读取。
2. **尝试** — 智能体调用工具，在额度内查询目标，每次获得判决及预先声明的反馈。
3. **重试** — 提交被拒后，若重试次数和时间仍有余量，则保留历史、重置查询额度，开始下一次尝试。
4. **结束** — 提交通过或预算耗尽时停止。判决、调用、历史和用量持久保存，分数从记录计算。

校验规则、提交处理与最终评估方式见[执行循环](docs/loop.md)。

## 主要结果

主实验使用 DeepSeek V4.1 Flash。**U** 为单次尝试基线，**F** 为挂载目标、允许在预算内检查与重试的运行。其中 17 项评测使用同一模型在本地运行 U/F；DeepSWE、Terminal-Bench 2.1 和 SkillsBench 1.1 使用外部单次尝试参考结果。

<p align="center">
  <img src="paper/current/figs/fig1-vs-published.png" alt="20 个评测上的 U、已发表参考与 F（论文 Fig. 1）" width="820">
</p>

<p align="center"><sub><b>Fig. 1</b>　20 个评测上的单次作答（浅灰）、已发表参考结果（深灰）与 ObjRun（蓝）。</sub></p>

这些结果并非等算力比较。全部 20 项结果、预算和评测口径见[论文附录](https://objrun.imontlaji.workers.dev/paper.pdf)。

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

每个案例的过程见[科学案例](https://objrun.imontlaji.workers.dev/zh/blog/)。

## 配置

[`config.yaml`](config.yaml) 管理服务、日志、模型默认值和数据库位置。路径相对此文件解析，切换启动目录不会换库。值中可使用 `${VAR}` 读取环境变量，现有 `TGENGIN_*` 名称继续保留。

Bun 直接执行 TypeScript 源码，并通过内置的 `bun:sqlite` 提供 SQLite。

## 打包

在 `app/` 目录执行：

```bash
bun run build
```

产物位于 `dist/`：Windows x64、macOS arm64/x64 的独立可执行文件、Linux x64 远端运行时，以及 `pyodide/` 资源。分发应用时，将 `config.yaml` 和 `pyodide/` 放在可执行文件旁；目标机器无需安装 Bun。

在 `app/` 执行 `bun run verify` 可完成类型检查和打包。测试套件见 [test/README.md](test/README.md)。

## 项目结构

```
app/src/             运行时、API、工具与内置界面
config.yaml          运行时配置
examples/            可运行的示例与各评测的接入
experiments/         评测来源与实验记录
paper/current/       论文源码、图表与绘图数据
scripts/             通用运行器与维护工具
site/                网站、运行回放与科学案例
docs/                架构、执行循环与数据库结构
test/                单元、集成和基准测试
```

## 文档

- [使用示例](examples/README.md)：智能体、任务、工具与目标。
- [架构与接口](docs/README.md)：执行循环、协议与数据表。
- [实验记录](experiments/README.md)：评测来源与运行记录。
- [论文源码](paper/README.md)：文稿、图表与构建方法。
