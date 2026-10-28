# ObjRun

实验记录实体随普通 Git 保存，包含模型输入输出、对话、工具记录、日志、结果与评分依据。LabBench、Terminal-Bench、SkillsBench、ChemIQ 等来源已在原有 BIRD、ClassEval、OlympiadBench、SciBench、TheoPhysEval 记录基础上补入找到的可读证据。逐 Bench 的已覆盖范围、原始缺损及未读取来源见 [记录整理简报](docs/reproducibility/records-report.md)，不以文件数量或样例成功宣称全部历史实验完整。

ObjRun 学生协作仓库。项目是基于 Bun 和 TypeScript 的任务执行与评测引擎。

## 对外展示页

静态介绍页见 [site/](site/)（深色单页，无构建）。本地预览：

```bash
npx --yes serve site
```

或 `python -m http.server 5173 --directory site`，再打开提示地址。


## 本地整理后的入口

| 路径 | 内容 |
|---|---|
| [experiments/records/](experiments/records/README.md) | 普通 Git 内的实验记录实体、运行索引、摘要和独立压缩分片 |
| [experiments/](experiments/README.md) | Bench 来源、历史收集索引及论文来源 |
| [paper/current/](paper/README.md) | 当前 v6.25 论文；历史版本由索引定位 |
| [docs/provenance/](docs/provenance/README.md) | 审计、交接、写作来源和历史报告 |
| [docs/architecture/](docs/architecture/README.md) | 现有架构文档入口 |
| [scripts/](scripts/README.md) | 按 Bench 和用途命名的脚本入口及旧路径迁移表 |
| [artifacts/](artifacts/README.md) | 本地历史备份与大文件，Git 忽略 |

整理完成后，按 2026-10-24 的明确授权分组提交并发布到 Deref-IO/objrun。筛选后的真实 Bench 成功、失败、中断记录进入 `experiments/records/`，记录实体随普通 Git 文件保存。当前代码继续使用已有 `TGENGIN_*` 配置名。

查看轨迹、恢复日志与核验分片使用 [记录工具](experiments/records/README.md)，只需仓库内文件，不依赖 Restic 或 Release 附件。仓库外原档暂作筛选核对来源，不再是计划发布的资产。完整历史环境重放仍有不同于记录读取的依赖；当前源码、测试所需的小型输入和 v6.25 论文继续保留为普通文件。

运行依赖实体、未选入的资料和整理中间文件统一放在仓库外的 `_objrun-archive/review/`；旧路径保留本地兼容链接。移动与恢复规则见 [本地目录说明](docs/reproducibility/local-layout.md)。

后续提交分组和 GitHub 数据发布步骤见 [提交计划预览](docs/reproducibility/publication-plan.md)。

## 外面这三个是给人看的

| 文件 | 是什么 |
| --- | --- |
| `README.md` | 这份。 |
| `config.yaml` | **整个程序唯一一份配置**。路径一律相对这个文件所在的目录，不是相对 cwd —— 从仓库里任何一个子目录启动，开的都是同一个库。 |
| `.env` | 号和钥匙。**不进版本库**（见 `.gitignore`），只在这台机器上。 |

## 目录

```
config.yaml        唯一一份配置
app/               程序本体
  package.json     依赖也只有这一份
  src/
    main.ts        入口：读配置 → 起库和接口 → 装那些句柄 → 管停机
    H2H/           状态。库 + 对外接口
    engine/        读 → 处理 → 写 的循环。内核、句柄注册表、链路串、条件
    install/       装表。表是声明出来的（tables.json），不是写死的
    llm/           模型这一侧。chat 一条轨，duplex（实时会话）一条轨
    objective/     验证函数 G。定义存封存区，主库够不着
    tree/          树的控制流：派生 / 判死开兄弟 / 回退
    trigger/       防「静默不生效」：条件校验 + 活库检查
    msg/           往上下文里投消息。**只有这一处实现**
    tasks/         发任务、跑 bench
    tools/         基础工具 read / write / edit / glob / grep / bash
    place/         在哪儿干。转发层 + 送过去的那个运行时
    ui/            一张给人看的页，引擎自己 serve（/ui）。只是又一个客户端，只走 /api
docs/              给人看的
examples/          跑得起来的例子
data/              运行时产物，不进版本库
```

## 跑

```
cd app
bun install
bun start          # bun src/main.ts
```

**运行时是 Bun**，直接吃 `.ts`，没有编译步骤。sqlite 用它自带的 `bun:sqlite`。

## 打包

```
cd app && bun run build
```

出在 `dist/`，单文件，目标机器不用装任何运行时：win-x64 / mac-arm64 / mac-x64
一台机器上一次全出。把 `config.yaml` 放在可执行文件旁边就行。

`bun run verify` = 类型 + 三个包一起过。

**没有一个 native 依赖**，所以能从 Windows 一次交叉编译出 mac 的。新依赖进来先过两道闸：
不许是 native（一引进来交叉编译当场废），不许绑死运行时。

## `.env` 里要有什么

```
DEEPSEEK_API_KEY=
DASHSCOPE_API_KEY=
```

缺了应当当场炸，并且说得出缺的是哪个键 —— 悄悄跑下去的话，
错会在很远的地方才冒出来。
