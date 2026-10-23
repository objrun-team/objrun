# miniF2F（Lean 4）

[miniF2F](https://arxiv.org/abs/2109.00110) 的 Lean 4 版：488 道奥数级形式化命题（AMC / AIME / IMO / MATH），test 244 用 [AI-MO/minif2f_test](https://huggingface.co/datasets/AI-MO/minif2f_test)（Kimina 修正版，19 条声明跟 DeepSeek 版不同），valid 244 用 [DeepSeek-Prover-V1.5](https://github.com/deepseek-ai/DeepSeek-Prover-V1.5) 的 `datasets/minif2f.jsonl`。交的是完整 Lean 4 证明，判的是 Lean 编译。

榜上（test，各家 pass@N 整证明采样）：Kimina-Prover-72B 92.2% @1024、DeepSeek-Prover-V2-671B 88.9% @8192、Kimina-Prover Preview 80.7% @8192 / 68.9% @32。

```
 引擎（任意机器）                          台子（有 Lean 的机器：Sherlock 计算节点）
 ┌──────────────┐  POST /stated    ┌──────────────────────────────────────────┐
 │ objective.ts │  POST /compiles  │ stand.py                                  │
 │ stated       │─────────────────▶│  split_cand   官方 header+声明 ⟷ 候选前缀   │
 │  └▶compiles  │  POST /sound     │  LEAN.check ─▶ lake env repl（池，env 0）  │
 │     └▶sound  │◀─────────────────│               或 Kimina Lean Server /verify│
 └──────────────┘  {value, note}   │  is_error / has_sorry  ← kimina_client     │
        ▲          GET /problems   │  #print axioms ⊆ {propext, choice, Quot…}  │
        └──────────────────────────│  problems.jsonl · golden/（只自检）         │
                                   └──────────────────────────────────────────┘
```

## 三条命令

```bash
sdev -c 8 -m 32GB -t 02:00:00 && ml python/3.12.1
bash examples/benchmark/minif2f/setup.sh              # elan、REPL、Mathlib、题库、golden、venv、自检
$TGENGIN_MF2F_HOME/venv/bin/python examples/benchmark/minif2f/stand.py --level 1
```

## 端点

| 端点 | 干什么 | 回什么 |
| --- | --- | --- |
| `GET /health` | 题数、级别、后端、允许的公理 | JSON |
| `GET /problems?split=test&n=10` | 发题：`id, name, split, informal, header, statement`。没有答案可藏——证明就是答案 | 列表 |
| `POST /stated` | 候选到 `:= by` 为止的前缀 == 官方 header + 声明（去注释、压空白）；之后全是缩进行 | `{value}` / `{value:false, note}` |
| `POST /compiles` | 官方声明 + 候选证明体送 Lean，`not is_error` | 同上 |
| `POST /sound` | `not has_sorry` 且 `#print axioms` ⊆ 允许集合（根） | 同上 |

请求体是内核的 `{node, moment, domain, feed, input:{task:{id}, result}}`；题号取 `task.id` 最后两段（`test/<name>` / `valid/<name>`）；`result.body` 里有 ```lean 围栏就取围栏内。一道题一份候选只编译一次，三格读同一次。

## 旋钮

| 环境变量 | 默认 | 说明 |
| --- | --- | --- |
| `TGENGIN_MF2F_HOME` | `~/.cache/tgengin-minif2f` | 装在哪（Sherlock 上 setup.sh 会把真身放 `$SCRATCH`） |
| `TGENGIN_MF2F_LEVEL` / `--level` | 1 | note 说多细，0–3 |
| `TGENGIN_MF2F_TIMEOUT` | 300 s | 一次编译的墙上上限（header `maxHeartbeats 0`，这是唯一的闸） |
| `TGENGIN_MF2F_REPLS` | 2 | 常驻 REPL 个数（每个 ~3 GB 内存，`RLIMIT_AS` 8 GB） |
| `TGENGIN_MF2F_MAX_USES` | 16 | 一个 REPL 用几次换新（v4.15.0 的 REPL 没有 `gc`） |
| `TGENGIN_MF2F_BACKEND` / `--backend` | `repl` | `kimina` 走 `TGENGIN_MF2F_KIMINA`（默认 `http://127.0.0.1:8000`）的 `/verify` |
| `TGENGIN_MF2F_STRICT_AXIOMS` | 0 | 1 = 不认 `native_decide`（`Lean.ofReduceBool`） |
| `TGENGIN_MF2F_CHECKS` | 12 | G 的 `checks`（objective.ts） |

## 自检

```bash
python stand.py --selftest                                   # golden 里前 5 道
python stand.py --selftest test/mathd_numbertheory_34 test/mathd_algebra_756
```

每道题两次判卷：Kimina 公开的证明该三格全 1；同一声明接 `sorry` 该 `compiles=1, sound=0`。golden 里有 6 份的声明早于 AI-MO 后来的修订（`mathd_algebra_314` 等），`stated` 会挂，自检自动跳过它们。

## 文件

```
G.md          这套题的 G：来源、cand、结构、h_r、边界、预算、level、m、坑、未验证
objective.ts  三格 stated → compiles → sound，checks=12
stand.py      台子：三条句柄 + /problems + --selftest；判据 import 自 kimina_client.models
setup.sh      备料：elan、REPL、Mathlib、官方代码、题库、golden、venv。幂等；在计算节点上跑
```

## Sherlock（CentOS 7，glibc 2.17）：整套在 apptainer 容器里跑

工具链自带的 clang 要 glibc ≥ 2.27，宿主机上 REPL 链接不出来（`LEAN_CC=gcc` 也不行，见 setup.sh 注释）。
镜像 `python:3.12-bookworm`（glibc 2.36），jq 从宿主机绑进去。安装根 `$SCRATCH/tgengin-minif2f-ctr`。

```bash
sbatch runs/minif2f-setup-apptainer.sbatch      # 备料 + 自检 5 道，约 25 min（2026-09-25 实测通过）
sbatch runs/minif2f-selftest-all.sbatch         # 225 份 golden 全量自检
```

台子也在容器里起（REPL 二进制链的是容器的库）：

```bash
apptainer exec --cleanenv --bind /scratch/users/ehz0002,/home/users/ehz0002 \
  --env ELAN_HOME=$H/elan --env PATH=$H/elan/bin:/usr/local/bin:/usr/bin:/bin --env TGENGIN_MF2F_HOME=$H \
  /scratch/users/ehz0002/containers/py312-bookworm.sif $H/venv/bin/python examples/benchmark/minif2f/stand.py --level 1
```
其中 `H=/scratch/users/ehz0002/tgengin-minif2f-ctr`。引擎（bun）在宿主机，只认 `http://127.0.0.1:7903/{stated,compiles,sound}`。
