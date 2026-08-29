# TgEngin

（这一行留给一句话说清楚这台机器是什么。）

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
