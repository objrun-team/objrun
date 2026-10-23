# DeepSWE

[datacurve 的 DeepSWE](https://github.com/datacurve-ai/deep-swe) —— 113 道**原创**的长程工程任务,91 个仓库,五种语言(TypeScript 35 / Go 34 / Python 34 / JavaScript 5 / Rust 5)。每道题一个钉死的容器镜像、一套手写的行为验证器。参考解从零写,不抄任何 PR,也从不合进上游。

榜上(官方 `pier` + `mini-swe-agent`):GPT-5.6 Sol **72.70**、GPT-5.5 70%±3、GPT-5.4 56%±2、Claude Opus 4.7 54%±5、Claude Sonnet 4.6 32%±2。

三条命令。第一条在 WSL 里(docker 在那儿),后两条在引擎这台机器上。

```bash
ssh wsl "bash /mnt/e/sgu-bzhc/EACN_EX/TgEngin/examples/benchmark/deepswe/setup.sh 10 0"
ssh wsl "cd /mnt/e/sgu-bzhc/EACN_EX/TgEngin/examples/benchmark/deepswe && python3 stand.py --level 2"
cd app && bun run start
```

台子起着、引擎起着之后:

```bash
bash examples/benchmark/deepswe/run.sh 10 dsw-l2 0
```

---

## 一、备料

`setup.sh` 干五件事,幂等:

| | |
| --- | --- |
| 1 | clone 语料到 `$HOME/.cache/tgengin-deepswe/deep-swe`(**不进仓库** —— `tasks/<id>/solution/` 是参考解) |
| 2 | 把 `dist/tgengin-runtime-linux-x64` 拷进家目录(snap 装的 docker 够不着 `/mnt` 和 `/tmp`) |
| 3 | 按 `(n, seed)` 点名这一跑要哪几道 |
| 4 | 拉题目镜像、建判据镜像 |
| 5 | **自检**:每道题拿它自己的参考解喂回官方判据,该判 1;空补丁该判 0。`TGENGIN_DSW_SELFTEST=0` 跳过 |

```bash
ssh wsl "bash …/setup.sh [几道] [种子]"
ssh wsl "TGENGIN_DSW_SELFTEST=0 bash …/setup.sh 0 0"   # 全量 113 道，只备镜像不自检
```

`几道 = 0` 是全部。自检一道题要判两次卷，全量跑要几个钟头 —— 只想把镜像备齐就把它关掉。

代理:WSL 在 NAT 模式下够不着 Windows 那个 `127.0.0.1:7890`,脚本现算网关(`ip route`)。**网关每次重启会变**,所以不写死。

docker 守护进程那一侧另有一份代理配置:

```bash
systemctl show snap.docker.dockerd.service -p Environment
# Environment=HTTP_PROXY=http://172.20.48.1:7890 HTTPS_PROXY=… NO_PROXY=localhost,127.0.0.1,::1
```

### 空间预算

实测,全量拉完(113 道题目镜像 + 113 个判据镜像):

| | |
| --- | --- |
| 镜像(去重后) | **99.59 GB** |
| build cache | 25.04 GB,**可回收**(`docker builder prune`),建判据镜像留下的 |
| 干活容器的可写层 | 起步 60 MB / 个,随它改的东西涨 |
| 判卷日志 | `$HOME/.cache/tgengin-deepswe/logs/<task>-<patch16>/`,一次判卷几百 KB |
| 语料 | 30 MB |
| 拉完要多久 | 52 分钟(这台机器,走网关代理) |

单个镜像 3.7–11.1 GB,但 113 个**共用同一个 `swe-bench-202605` 底座**,去重后总共不到 100 GB —— 按单个尺寸乘 113 会高估一倍以上。十道的子集占 18.03 GB。

镜像落在 **`E:\wsl\Ubuntu\ext4.vhdx`**(WSL 的整块虚拟磁盘,稀疏增长):

```
/var/snap/docker/common/var-lib-docker   docker 自己说的根（snap 装的，overlayfs）
  └─ /dev/sdd                            1 TB，WSL 里的块设备
       └─ E:\wsl\Ubuntu\ext4.vhdx        真身
```

```bash
docker system df                       # 镜像 / 容器 / 构建缓存各占多少
df -h /                                # WSL 里还剩多少
docker builder prune -f                # 回收那 25 GB，不动已建好的镜像
```

**vhdx 只涨不缩** —— 在里面删了东西,E 盘不会自动还回来,要 `wsl --shutdown` 之后
`Optimize-VHD` 或者 `diskpart` 压缩。所以拉之前先看 E 盘,别拉到一半没地方。

## 二、台子

一个进程,跑在 WSL 里,手上有 docker。引擎那边它是**三条句柄**:

```
http://127.0.0.1:7902/place       在哪儿干:把工具调用转发进那道题的容器
http://127.0.0.1:7902/applies     G 的第一格:交出来的补丁打得上吗
http://127.0.0.1:7902/resolved    G 的根:官方判据说做成了吗
```

```bash
python3 stand.py [--port 7902] [--level 2] [--selftest [TASK_ID...]]
```

### 位置为什么在这儿

`workplace.identity` 指着的那条句柄负责**解析地址、转发调用**。内核自带的
`fn:place.hops` 读的是 `wsl` / `ssh` / `docker` 那套跳板串,在这台机器上三处过不去:

```
wsl.exe -- docker ps        docker: command not found（snap 装的，只在登录 shell 的 PATH 上）
ship() 只处理最外一跳        运行时 cp 进了 WSL 的 /tmp，不在容器里
docker cp /tmp/…            lstat: no such file（snap 够不着 /tmp）
```

所以这个例子自带一条:地址写法 `dsw:<task-id>` 是它自己的,容器怎么起、运行时怎么送,全在这个进程里。**内核一个字不用改。**

转发出去的工具**还是内核那一份实现** —— 送进容器的是 `dist/tgengin-runtime-linux-x64`(一个 MCP server,装的就是 `app/src/tools/` 那一批)。

### 容器

| | |
| --- | --- |
| 干活的 | `dsw-<task-id>`,那道题钉死的镜像,`--network none --cpus 2 --memory 8g`,`/app` 是仓库。**判死重来不回档** |
| 起容器时 | 送进运行时,并且把 git 调顺(`user.email` / `user.name` / `safe.directory`)—— 镜像里没有身份,第一次 `git commit` 会撞 `Please tell me who you are` |
| 判卷的 | 每次全新,`--rm`,镜像 = 同一个题目镜像 + 隐藏测试烤进 `/tests`,`--network none` |

两条限额照抄官方 `task.toml`(`cpus = 2`、`memory_mb = 8192`),判卷上限 1800 秒。

### 分级

`--level` 定 `note` 那一栏写多细。**每个级别是一次单独的实验**,引擎那边不知道有这回事,G 的形状不随级别变。

| 级 | `note` 里有什么 |
| --- | --- |
| 0 | (空) |
| 1 | 哪一段断的 + 计数 |
| 2 | + 是哪几条没过(测试名,最多 60 条) |
| 3 | + 失败信息原文(最多 40 条,每条 2000 字符) |

级别 2 判一份只做了一半的补丁,实际回的是:

```json
{ "stage": "tests",
  "new_behaviours": "15 of 20 pass",
  "existing_tests": "3 of 3 still pass",
  "failing": ["[f2p] …repl.TestChallengeBeginReplScriptModeWithModulePathFlag", "…"] }
```

## 三、引擎

`run.sh` 的第 2 步发一份声明。要紧的是位置那几行:

```json
{ "handles": [
    {"name": "http://127.0.0.1:7902/place",    "expectMs": 300000},
    {"name": "http://127.0.0.1:7902/applies",  "expectMs": 1800000},
    {"name": "http://127.0.0.1:7902/resolved", "expectMs": 1800000}],
  "places": [
    {"place": "local"},
    {"place": "dsw:abs-module-cache-flags",
     "identity": "http://127.0.0.1:7902/place",
     "forward": true,
     "tools": [{"tool":"bash","policy":"always"}, {"tool":"read","policy":"always"},
               {"tool":"write","policy":"always"},{"tool":"edit","policy":"always"},
               {"tool":"glob","policy":"always"}, {"tool":"grep","policy":"always"}]}],
  "modes": [{"mode": "solve", "cycles": [
    {"cycle":"ask","apiMode":"chat","maxUnits":70,"from":[],     "next":["act"],"infer":"fn:infer.dfs"},
    {"cycle":"act",                 "maxUnits":70,"from":["ask"],"next":["ask"],"infer":"fn:infer.dfs"}]}],
  "agents": [{"name":"bot","apis":[["DEEPSEEK_API_KEY","deepseek-v4-flash"]],"unit":"fn:unit.tools"}] }
```

**一道题一行位置** —— `task.place` 指的是 `workplace.place`,一道题一个容器。

关掉两件工具(第 3 步,改的是 `usable` 那一列,纯数据):

```sql
update tool set usable = 0 where name in ('web_search','python_exec')
```

`web_search` 关掉是因为官方两侧都是 `no-network`,而它不转发到 workplace —— 它是条真网络,而参考解就公开在 GitHub 上。`python_exec` 关掉是因为要跑什么都在容器里用 `bash` 跑,用容器自己那套工具链。

## 四、一道题长什么样

`send.ts` 拼的请求体:

```json
{ "id": "abs-module-cache-flags",
  "mode": "solve", "agent": "bot",
  "place": "dsw:abs-module-cache-flags",
  "source": "user", "domain": "software", "workdir": "/app",
  "solveSeconds": 10800,
  "maxBranches": 4, "maxDeadSiblings": 8,
  "noSearch": ["deepswe solution", "datacurve deep-swe", "abs-module-cache-flags solution"],
  "description": "<instruction.md>\n\nYou are working in a git repository at /app…",
  "readable": true,
  "objective": {
    "nodes": [
      {"name":"applies", "moment":"task_done","domain":"bool","handle":"http://127.0.0.1:7902/applies"},
      {"name":"resolved","moment":"task_done","domain":"bool","handle":"http://127.0.0.1:7902/resolved"}],
    "edges": [{"src":"applies","out":0,"dst":"resolved"}],
    "sink": "resolved",
    "checks": 6 } }
```

| 旋钮 | 值 | 从哪儿来 |
| --- | --- | --- |
| `solveSeconds` | 10800 | 官方 `task.toml` 的 `agent.timeout_sec` |
| `checks` | 6 | 判一次 3–97 秒,判卷上限 1800 秒 —— 不是成本问题 |
| `maxBranches` | 4 | 只留时间这一个闸 |
| `maxDeadSiblings` | 8 | 同上 |
| `readable` | true | 靶子该看得见 |
| 环境变量 | `TGENGIN_DSW_CHECKS` / `TGENGIN_DSW_SECONDS` / `TGENGIN_DSW_SEED` | 顶掉上面几个 |

### G 是官方那把尺子拆成两段

官方判据的公式:

```
reward = 1  ⟺  |f2p| > 0  ∧  每条 f2p 都过  ∧  没有一条 p2p 挂
```

补丁打不上就写 `apply_failed=1` 并且**不跑测试** —— 那是第零段。G 就照这个分:

```
applies ──→ resolved            根 = resolved
```

根**必须有入边**(`objective/spec.ts`:没有的话它的值跟候选无关,G 恒定,是无效目标)。一次判卷出一份 `reward.json` + 一份 `ctrf.json`,两格读同一份,按补丁的 sha256 认缓存。

### 交的是提交 sha

官方的收集钩子取的是 `git diff --binary <base> HEAD`,**带二进制 hunk** —— 让模型把它从工具调用里吐出来既贵又不可靠。所以交上来的是它自己那个提交的 sha,台子拿它去容器里跑同一条命令,只把 `HEAD` 换成那个 sha。

sha 不可变,而且只指一棵树 —— `verify` 回执里 `graded` 回显的就是它。

## 五、跑一趟

```bash
bash examples/benchmark/deepswe/run.sh [几道] [这一跑叫什么] [种子]
```

点名是确定的:同一个 `(n, seed)` 永远是同一批,复现靠这两个数。

```bash
curl -s "$STAND/problems?n=10&seed=0" | grep -o '"id":"[^"]*"'
```

成绩单:

```bash
curl -s http://127.0.0.1:7801/api/bench/dsw-l2
```

## 台子自检

判据装没装对,不靠读文档,靠跑:

```bash
python3 stand.py --selftest abs-module-cache-flags adaptix-name-mapping-aliases \
                            arktype-json-schema-refs-dependencies \
                            boa-hierarchical-evaluation-cancellation \
                            csstree-shorthand-expansion-compression
```

五种语言各一道,参考解喂回去全判 1,空补丁全判 0。顺带量到的墙上时间:

| 题 | 语言 | f2p / p2p | 镜像 | 空补丁 | 参考解 |
| --- | --- | --- | --- | --- | --- |
| abs-module-cache-flags | go | 20 / 3 | 3.90 GB | 14s | 14s |
| adaptix-name-mapping-aliases | python | 44 / 2738 | 3.71 GB | 19s | 29s |
| arktype-json-schema-refs-dependencies | typescript | 25 / 1679 | 5.24 GB | 75s | 76s |
| boa-hierarchical-evaluation-cancellation | rust | 17 / 7 | 9.92 GB | 12s | 97s |
| csstree-shorthand-expansion-compression | javascript | 79 / 16715 | 3.72 GB | 3s | 4s |

判一次的代价跟测试条数几乎无关(16715 条判完 4 秒,7 条判完 97 秒),贵的是**编译一棵被改过的树**。

容器冷启(起容器 + 送运行时 + MCP 握手)1.5 秒。

## 我们的基线

还没跑。这一节等第一趟出来再写:怎么跑的、分数、关键分解、数据在哪。

## 文件

```
setup.sh     备料：语料、运行时、镜像、自检。幂等
stand.py     台子：三条句柄（位置 + G 两格）。跑在 WSL 里，手上有 docker
send.ts      把题拼成一批带 G 的任务发出去
run.sh       跑一趟：声明 → 关工具 → 发批 → 等 → 成绩单
```

语料、参考解、镜像、判卷日志都在 `$HOME/.cache/tgengin-deepswe/`(WSL 家目录),不进仓库。
