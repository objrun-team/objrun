# dsw-full

91 / 112 solved.

## csv/tasks.csv — 一道题一行

| 栏 | 是什么 |
| --- | --- |
| `task` | 题号（去掉跑名前缀） |
| `state` | `done` / `failed` / `claimed` |
| `pass` | 1 = 官方判据说做成了。**数出来的**，库里没有「分数」这一栏 |
| `place` | 它的容器（`dsw:<跑名>/<题号>`） |
| `solve_seconds` | 时限，取自官方 `task.toml` 的 `[agent] timeout_sec` |
| `stations` | 走了多少站（两个周期加起来） |
| `asks` | 其中多少站是问模型 —— 相当于模型轮次 |
| `dead_stations` | 判死了几站 |
| `attempts_died` | 判死了几次尝试（树上开了几次兄弟） |
| `checks` | 它自己问了几次 G |
| `result` | 收尾判决的原文 `{pass, why, note}` |

## csv/stations.csv — 一站一行

`status` 空 = 还在跑；`reached` = 走到了；`dead_*` = 被判死。
`at` 是这一站开始的毫秒时刻，配 `done` 能算出每一站花了多久。

## csv/checks.csv — 每次问 G 一行

| 栏 | 是什么 |
| --- | --- |
| `pass` | 这一次判 1 还是 0 |
| `graded` | 判的是哪个提交（sha）。**改一个字符就是另一份候选** |
| `left` | 这一轮还剩几次额度 |
| `reused` | 1 = 交卷那次没重判，用的是它自己验过的那次判决 |
| `why` | 判 0 的时候是 `see note` |
| `note` | **判卷台说的话**，详略由台子的 `--level` 定 |

判 0 的 414 次里，300 次带着 `note`。
**这个比例要是不到十成，这一趟的级别设了等于没设。**

## csv/tools.csv — 每道题每件工具跑了几次

`web_search` 和 `python_exec` 这一跑是关掉的，**这两列必须全是 0**。
不是 0 的话这一趟不作数：官方那套两侧都是 `no-network`。
