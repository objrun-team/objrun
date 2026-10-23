# TgEngin 一道题的循环（对照 autoresearch 的 program.md）

从源码核出（b45758c + 未提交的 press.ts）：`objective/spec.ts` `objective/tool.ts` `tree/dfs.ts` `engine/loop.ts` `msg/press.ts`。
论文 §9 Methods 是它的形式化版本。

## 文件分工

| 文件/进程 | 内容 | 谁能改 |
|---|---|---|
| 判卷进程（`examples/benchmark/*/grader.py`，独立容器/端口） | 标准答案 y*、隐藏测试、评估器节点（CMT `parsed→equiv`；DeepSWE `applies→resolved`）、信息级别 `--level` | 人；solver 永远够不着 |
| 封存区（`objective/store.ts`） | G 的定义 (V, E, r, c)：节点、边、输出节点、每轮查询额度 | 发布时写一次，之后只读；主库全接口开放也翻不出来 |
| 任务描述 d | 题面（去掉参考解）+ 若标 readable 则附上 G 的定义（不含答案） | 发布方 |
| solver（`deepseek-v4-flash`, T=0, seed 42）+ 工具（bash/read/write/edit/glob/grep，或检索+Python） | 干活 | 每个 arm 一模一样，只有 `verify` 挂不挂不同 |
| trace 表（units / checks / tools） | 每一站、每次评估器调用、每次工具调用各一行 | 内核写；分数从这里算出来，从不存 |

## 发布（每道题一次）

```
0. 发布方写 d + G；内核检查 (W1)–(W6)：边合法、无环、唯一出口、出口是 bool、
   出口有入边、每个端口都接线。任一条不过 → 整批拒绝
1. G 封存；c（每轮查询额度）随 G 走，不随任务走
2. 写第一站（entry cycle）；墙钟 T 开始计时（CMT 3600 s，DeepSWE 7200 s）
```

## 一个 attempt（树里叫一个 node）

```
LOOP attempt a_j:
  1. ask   —— 模型看上下文（祖先链全部消息 + 结构化视图：题面 / 我在哪一站 / 剩余预算 / 试过几个 node 及死活）
  2. act   —— 跑它请求的工具（bash 等）；每个 cycle 最多 U 站（CMT 35，DeepSWE 70）
  3. 途中可调 verify(x)：
       - 本 attempt 已拿到判决的次数 < c（CMT 10，DeepSWE 6）→ 判卷进程跑整张 G，回
         {pass 0/1, why, note(按级别), graded=原文, left=剩余次数}；不回答案，不回 trace
       - 额度用完 → 拒绝，回一句提示；被拒的不计数
  4. 拐向交卷站，三种触发：调了 submit / 说出一段非空的话 / 工作预算 U 用完（不看意愿）
  5. 交卷（H1–H3）：
       H1 没调 submit → 判 0「nothing handed in」，不跑评估器
       H2 交的和本任务任何更早 verify 过的原文一字不差 → 复用那次判决，不跑评估器
       H3 否则跑一次 G
     判决以一次 verify 工具结果的形状投进上下文（含 why/note）
  6. 判 1 → reached，任务结束
     判 0 → dead
```

## 判死之后

```
  7. 已判死的 node 数 < K（8）且 t < T：
       在收口那一行底下开新 node —— 上下文里带着 a_1..a_j 的全部对话和判决，
       但查询额度 c 和工作预算 U 重置；产物不继承（答案重写；DeepSWE 里 commit 要重做）
     否则任务结束
  8. t = T 时任务还开着：关掉，把最后一份交过的候选再判一次，那个判决为最终
  9. 超过单站时限的 attempt 也算 dead，计入 K
```

## 上下文怎么拼

- 沿 `from_unit` 指针爬到根：看得见祖先，看不见兄弟（本机制下没有兄弟，新 node 挂在旧 node 收口行下面，所以等于全部历史）。
- 超过 `api.compress_at`（DeepSWE 900k）才压缩，只压已收口的 node，当前 node 永远原文；判决行一律保留（hand-in 记录是 verdict 部分 keep/keep/keep；verify 返回值是单行 JSON，tail/sample 不裁）。
- CMT 那一跑还没有压缩代码，全程原文。

## 不许做的事（和 autoresearch 的 prepare.py 只读对应）

| 规则 | 实现 |
|---|---|
| 只有人能绑 G；agent 派生的任务不能带 G | 发布路由 + 准入 |
| solver 读不到 y* | 判卷进程只暴露 ν(x)；DeepSWE 工作容器和判卷容器分离、无网络；CMT 是同机审计 |
| verify 只能问自己这道题 | `verify` 从库里查任务号，不收调用方传的 |
| 禁用的工具零调用 | 每个 run 审计 `tools.csv`（DeepSWE：web_search 0、python_exec 0） |
| 分数不存 | 从 trace 表按定义算 |

## 记什么（对应 results.tsv）

| 表 | 一行 = | 关键列 |
|---|---|---|
| units / stations | 一站 | node, cycle(ask/act/submit), status, 秒数, tokens |
| checks / verify | 一次评估器调用 | pass, why, note, graded, left, reused, asked_by(agent/submit) |
| tools | 每个工具的调用次数 | bash 16,782 … verify 642, submit 341 |
| tasks | 一道题 | state, pass, first_answer_pass, nodes, seconds |

分数 = tasks 里 pass=1 的份额；曲线 S(n) = 按 checks 里每题的评估器调用数累计。

## 和 autoresearch 逐条对

| | autoresearch | TgEngin |
|---|---|---|
| agent 改的东西 | train.py，commit 累积 | 一份答案 / 一个 commit，每个 attempt 重写 |
| 只读的东西 | prepare.py（评估函数） | 判卷进程 + 封存区（G 定义 + y*） |
| 评估一次 | 5 分钟训练，回一个实数 | 3–97 s 或跑整套测试，回 0/1 + why + note |
| 问几次 | 无限 | 每轮 c 次、最多 K 轮、墙钟 T |
| 保留/丢弃 | 指标降了留 commit，否则 git reset | 判 1 结束；判 0 开新 node，上下文继承、产物不继承 |
| 停止 | NEVER STOP | 第一次判 1，或 K/T 用尽 |
| 报什么 | 最终 val_bpb | 整条曲线 S(n) + 首候选 + 枚举脆弱标记 + 未跑的 pass@1 |
