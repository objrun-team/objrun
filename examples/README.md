# 快速启动

每个例子都假定这一步做过了。

```bash
cd app && bun start
BASE=http://127.0.0.1:7801/api
```

```bash
curl -s $BASE/health
```
```json
{"ok":true,"db":"…/h2h.sqlite","tables":12,"write":true,"query":true,"uptimeMs":31}
```

## 灌底子

一个干活的地方、一种最简单的机制、一个智能体。**只用灌一次**，后面所有例子共用。

```bash
curl -s -X POST $BASE/declare -H 'content-type: application/json' -d @- <<'JSON'
{
  "places": [{ "place": "local" }],
  "modes":  [{ "mode": "chat1", "cycles": [
              { "cycle":"ask", "apiMode":"chat", "from":[], "next":[], "infer":"fn:infer.dfs" }] }],
  "agents": [{ "name": "bot",
               "apis": [["DEEPSEEK_API_KEY", "deepseek-v4-flash"]],
               "unit": "fn:api.deepseek" }]
}
JSON
```
```json
{"places":["local"],"modes":["chat1"],"cycles":1,"agents":["bot"],
 "handles":[],"tools":[],"rules":[],"skills":[],
 "tables":["task_chat1","agent_bot_ctx","agent_bot_msg"],"entries":{"chat1":["ask"]}}
```

`tables` = 这一趟长出来的子表。灌完直接能发任务，不用重启。

## 发一个任务

```bash
curl -s -X POST $BASE/tasks -H 'content-type: application/json' -d @- <<'JSON'
{ "id":"t-1", "mode":"chat1", "agent":"bot", "place":"local",
  "source":"user", "description":"用一句话说说你是谁" }
JSON
```
```json
{"id":"t-1","mode":"chat1","cycle":"ask","instance":"t-1#1","objective":false}
```

```bash
curl -s $BASE/tasks/t-1
```
```json
{"id":"t-1","state":"done",
 "objective":{"has":false,"agentReadable":false,"verdict":null},
 "solve":{"limitSeconds":1800,"elapsedMs":4210,"leftMs":1795790,"overdue":false},
 "units":[{"cycle":"ask","unit":1,"phase":"done","handle":"fn:api.deepseek",
           "expectMs":900000,"deadlineInMs":null,"chain":"chat1/ask#1"}]}
```

| phase | |
| --- | --- |
| `pending` | 出站那一行还没落库 → 这一轮该动它 |
| `running` | 落了、返回还没落 |
| `done` | 两头都落了 |

```bash
curl -s $BASE/tasks/t-1/messages
```
```json
{"total":3,"rows":[
 {"unit":1,"seq":1,"role":"user","kind":"user","human":true,
  "body":"【人】用一句话说说你是谁","text":"用一句话说说你是谁"},
 {"unit":1,"seq":2,"role":"system","kind":"inject",
  "parsed":{"sent":true,"tools":["read","write","edit","glob","grep","bash"],"rules":[]}},
 {"unit":1,"seq":3,"role":"assistant","kind":"prompt","body":"我是…"}]}
```

任务不动的时候：

```bash
curl -s $BASE/tasks/t-1/why
```
```json
{"id":"t-1","state":"done","movable":true,"problems":[],"stuckAt":null}
```

## 接口清单

```bash
curl -s $BASE/help                # 全部 31 个口，终端里直接读
curl -s "$BASE/help?q=tasks"      # 只看相关的
curl -s "$BASE/help?format=json"  # 机器读的
```

## 例子

| | |
| --- | --- |
| [`tool/`](./tool/) | 工具：同一个，两种写法 |
| [`meet-join/`](./meet-join/) | 一个工具长出新句柄 |
| [`meet-book/`](./meet-book/) | 真的开一个谷歌会议 |
| [`benchmark/cmt/`](./benchmark/cmt/) | 跑一遍 CMT-Benchmark：`/bench` 整批发、G 判卷、判 0 换路重试。基线 **44 / 50** |
| [`benchmark/deepswe/`](./benchmark/deepswe/) | 跑一遍 DeepSWE：一道题一个容器，位置走自己那条句柄，官方判据判卷 |
| [`rule/`](./rule/) | 规则（挂在时刻上就是钩子） |
| [`skill/`](./skill/) | skill |
| [`mode/`](./mode/) | 任务机制 |
| [`agent/`](./agent/) | 智能体、挂哪几条轨 |
| [`objective/`](./objective/) | 验证函数 G |
| [`place/`](./place/) | 干活的地方 |

> 请求体都走 `-d @- <<'JSON'`。写成 `-d '{…}'` 也行，但在 Windows 的 Git Bash 里
> 带中文会撞上命令行转码，body 长度对不上。
