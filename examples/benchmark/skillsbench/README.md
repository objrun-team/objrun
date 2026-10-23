# SkillsBench 1.1

[SkillsBench](https://arxiv.org/abs/2602.12670)（[benchflow-ai/skillsbench](https://github.com/benchflow-ai/skillsbench)，tag `v1.1`）：87 道跨 8 个领域的容器化任务，每道自带一组 Agent Skills、一个 pytest 判据、一个人写的 oracle。论文比的是同一模型**有 / 无 skills** 的通过率（33.9% → 50.5%）。判据全是确定性的 pytest，没有 LLM judge；判卷细节和坑见 [G.md](./G.md)。

```
        引擎那台机器                          有 docker 的机器（WSL）
  ┌───────────────────────────┐      ┌──────────────────────────────────────────┐
  │ 引擎                      │      │ 台子 stand.py :7903                       │
  │  place=skb:<run>/<id> ───────────▶ /place    → docker exec 进干活容器 /rt   │
  │  G: verified → passed ───────────▶ /verified → docker commit 快照            │
  │                           │      │ /passed    → 一次性容器跑官方 verifier/   │
  └───────────────────────────┘      │ 题库 ~/.cache/tgengin-skillsbench/       │
                                     │   tasks/<id>/{task.md,environment,       │
                                     │               oracle/,verifier/}  ← 不出 │
                                     └──────────────────────────────────────────┘
```

| 端点 | 干什么 |
| --- | --- |
| `GET /health` | 题数、level、skills 模式、network 模式 |
| `GET /problems?n=&seed=` | 题面 + workdir + 官方时限 + skill 名/描述。**不带 oracle，不带 verifier** |
| `POST /place` | 把一次工具调用转发进那道题的容器（地址写法 `skb:[<run>/]<task-id>`） |
| `POST /verified` | 官方 `verifier/test.sh` 跑完并写出了 `reward.txt` |
| `POST /passed` | `reward == 1.0`（根） |

三条命令，前两条在 WSL：

```bash
ssh wsl "bash /mnt/e/sgu-bzhc/EACN_EX/TgEngin/examples/benchmark/skillsbench/setup.sh 10 0"
ssh wsl "cd /mnt/e/sgu-bzhc/EACN_EX/TgEngin/examples/benchmark/skillsbench && ~/.cache/tgengin-skillsbench/venv/bin/python stand.py --level 2 --skills with"
cd app && bun run start
```

`setup.sh`：clone 到 `$HOME/.cache/tgengin-skillsbench/`（钉 `b63b7b28`，对不上就停）→ venv（只装 PyYAML）→ 查 docker → 拷运行时 → 建点到名的镜像 → 自检（空容器判 0、官方 oracle 判 1）。**Sherlock 上只能走到 clone**——没有 docker。

旋钮：`--level 0..3`（note 详略，3 会漏 GT）、`--skills with|none`（benchmark 的自变量，两趟实验）、`--network official|none`（官方 86/87 道是 public；`none` 不是榜上那个实验）。

发批脚本（`send.ts` / `run.sh`）还没写：照 deepswe 那两份改端口 7903、地址前缀 `skb:`、节点名 `verified`/`passed`，并把 `/problems` 给的 `skills` 拼进题面即可。
