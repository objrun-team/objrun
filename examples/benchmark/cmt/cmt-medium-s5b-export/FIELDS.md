# cmt-medium-s5b：四张表，字段是什么意思

一跑 = 50 道 CMT-Benchmark 题，每道一小时，思考强度 `medium`，不挂扩展，
检索每站 5 次，同时做 20 道。成绩 **44 / 50**。跑法和结论见 `RESULT.md`。

四张表是**四种粒度**，都能用 `task` 这一列接起来：

```
tasks.csv     一行一道题        50 行
stations.csv  一行一站          1,524 行
verify.csv    一行一次判卷      396 行
searches.csv  一行一次检索      171 行
```

几个词先说清楚，四张表里通用：

- **站（station / unit）** —— 一次「问模型」或者「跑工具」。一道题在一小时里
  走了几十站。`cycle = ask` 是问模型，`cycle = act` 是跑它要的工具。
- **节点（node）** —— 一次完整的尝试。判死了就开一个新节点从头再来，
  所以一道题可能有好几个节点，每个节点里有一串站。
- **判卷（verify）** —— 拿一个候选答案去问 G（官方判据）对不对，回一个是/否。
  一个节点里最多问 10 次。

---

## tasks.csv —— 一行一道题

| 字段 | 意思 |
| --- | --- |
| `task` | 题号，`cmt-0` … `cmt-49`，就是数据集里的下标 |
| `state` | `done` = 做对了；`failed` = 没做对 |
| `pass` | 1 / 0，跟 `state` 一回事，画图用这个方便 |
| `why` | 失败的原因原文。这一跑六道全是 `over solve_seconds=3600s; equiv evaluated to false`（时间到了、手上那份答案判错） |
| **`first_answer_pass`** | **第一个交给 G 的答案对不对**。1 / 0 |
| `verify_by_agent` | 它自己主动验了几次（交卷时那次不算） |
| `nodes` | 开过几个节点（几次从头再来） |
| `stations` | 一共走了几站 |
| `seconds` | 第一站到最后一站的墙上时间。上限 3600 |
| `searches` | 真检索回来几次 |
| `searches_refused` | 因为超了每站 5 次被回绝几次 |
| `calls` | 问了模型几次 |
| `tokens_in` / `tokens_cached` | 输入 token / 其中命中缓存的 |
| `tokens_out` / `tokens_reasoning` | 输出 token / 其中是思考的 |
| `max_searches` / `solve_seconds` | 这道题的配额，全跑一样：5 和 3600 |

**`pass` 和 `first_answer_pass` 差得很远，这是这份数据最要紧的一件事。**
44 道做对里，第一答就对的只有 19 道 —— 其余是验了不止一次才对的。
那里面两种混着：一种是「算错了、看到 false、回去改推导」，另一种是
「把选项一个一个报过去」（选择题的答案空间比一轮 10 次的额度还小）。
要分开的话去 `verify.csv` 看同一道题的 `answer` 列变化：改推导的答案在结构上变，
穷举的只是换个字母。

## stations.csv —— 一行一站

| 字段 | 意思 |
| --- | --- |
| `task` | 哪道题 |
| `node` | 第几次尝试 |
| `unit` | 第几站，在一道题里从 1 往上排，**就是时间序** |
| `cycle` | `ask` = 问模型，`act` = 跑工具 |
| `status` | 这个节点在这一站的结局：`reached` 走到了、`dead_*` 被判死。空 = 还没到头 |
| `started_at_ms` / `started_at_iso` | 这一站什么时候开的（毫秒 / ISO 8601） |
| `seconds` | 这一站花了多久 = 下一站开始 − 这一站开始。**最后一站是空的**（没有下一站） |
| `searched` | 这一站有没有真跑检索，1 / 0 |
| `tools` | 这一站跑了哪些工具，分号隔开 |
| `tokens_in` … `tokens_reasoning` | 这一站的 token 账。`act` 站不问模型，所以是 0 |
| `thought_chars` | 这一站的思维链有多少字 |

画「时间花在哪」用这张：按 `cycle` 和 `searched` 分组求 `seconds` 的和。
这一跑是 ask 65% / 带检索的 act 28% / 其余 act 6%。

## verify.csv —— 一行一次判卷

| 字段 | 意思 |
| --- | --- |
| `task` / `unit` | 哪道题、哪一站 |
| `order` | 这道题的第几次判卷，从 1 开始 |
| `asked_by` | `agent` = 它自己要验的；`submit` = 交卷时系统自动判的那次 |
| `pass` | G 的裁决，1 / 0 |
| `why` | 判错时的原因，例如 `equiv evaluated to false`、`parsed evaluated to false` |
| `checks_left` | 这一轮还剩几次额度（一轮 10 次）。`submit` 那行是空的 |
| `answer` | **它这次交上去的候选答案**（截到 300 字）。GT 不在这份数据里，任何一张表都没有 |

## searches.csv —— 一行一次检索

| 字段 | 意思 |
| --- | --- |
| `task` / `unit` | 哪道题、哪一站 |
| `order` | 这道题的第几次检索 |
| `status` | `answered` 查到了；`over_cap` 超了每站 5 次被回绝；`blocked` 撞上「不许搜这套题本身」被整份丢掉；`error` 搜了但什么也没说出来 |
| `queries` | 这次它跑了几条查询串 |
| `pages_opened` | 开了几个页面 |
| `moves` | 供应商那端一共走了几步 |
| `answer_chars` | 回来的答复有多长。`blocked` / `over_cap` 是 0 |
| `searcher_tokens_in` / `searcher_tokens_out` | 这次检索本身烧掉的 token |
| `error` | 出错时的原文（截断） |

`status` 不是 `answered` 的那些**不扣配额** —— 它们什么都没查到。

---

## 不在这份数据里的东西

- **标准答案（GT）**。它只在判卷台那一侧，引擎这边一个字都没有
- **题面**。要的话去 CMT-Benchmark 数据集，按 `task` 的下标取
- 模型说过的原话和完整思维链。它们在 `h2h.sqlite` 的 `agent_bot_msg` 表里，
  这四张表只带走了统计量
