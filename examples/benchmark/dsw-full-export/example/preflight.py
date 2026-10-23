"""开跑之前把每一道题都过一遍：**这道题在这台机器上跑得起来吗。**

    python3 preflight.py [题号...] [--deep] [--jobs 4] [--keep]

不给题号就是全部 113 道。跑在**装了 docker 的那台机器上**（跟 `stand.py` 同一台），
路径全从这个脚本自己的位置推 —— 一处都不写死。

## 为什么要有这一步

一趟跑几个钟头。一道题的语料缺一个文件、镜像没拉下来、容器里那个仓库不在
base commit 上 —— 这些**到跑的时候才会露出来，而且露出来的样子跟「模型不行」
分不开**：那道题判 0，成绩单上就是个 0。

所以在发批之前，每一道都真起一次容器、真在里头跑一条命令。

## 一道题查七层，从便宜到贵

    files     task.toml / instruction.md / tests 那四个 / solution 那一份，在不在、空不空
    meta      语言、镜像、base commit 有没有；f2p 是不是空的
              （f2p 空的话 reward 按定义永远是 0 —— 那道题谁也做不成）
    image     那个钉死的镜像本地有没有
    verifier  判据镜像建得出来吗（tag 认 tests/ 的指纹）
    box       容器起得来吗；/app 是不是 git 仓库；HEAD 是不是 base commit
    net       容器里网**断没断**（官方 agent.network_mode = no-network，通了就是这一跑不作数）
    forward   送进去的运行时应不应答（跟内核同一份实现，MCP）

`--deep` 再加一层，也是最贵的一层：

    golden    拿这道题自己的参考解喂回官方判据，该判 1；空补丁该判 0

前七层一道两三秒，全量十来分钟；`--deep` 一道要判两次卷（3 秒到 5 分半不等），
全量得几个钟头。

## 查完就把容器删掉

用的是 `dsw:preflight/<题号>`，跟真跑那一趟的容器（`dsw:<跑名>/<题号>`）不是同一个，
所以查这一趟不会动到任何一趟的工作区。`--keep` 留着不删。
"""

from __future__ import annotations

import argparse
import concurrent.futures
import json
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import stand  # noqa: E402  —— 一份实现：语料、docker、转发、判卷全用它那一套

PLACE = "dsw:preflight/{}"


def check(tid: str, deep: bool, keep: bool) -> dict:
    """一道题过一遍。回 `{tid, ok, layer, detail}` —— **断在哪一层就报哪一层**。"""
    place = PLACE.format(tid)
    name = f"dsw-preflight-{tid}"
    try:
        d = Path(stand.BOOK[tid]["dir"])

        # ── files ──
        want = ["task.toml", "instruction.md", "tests/test.sh", "tests/grader.py",
                "tests/config.json", "tests/test.patch", "tests/Dockerfile",
                "solution/solution.patch"]
        missing = [f for f in want if not (d / f).is_file() or (d / f).stat().st_size == 0]
        if missing:
            return dict(tid=tid, ok=False, layer="files", detail=f"missing or empty: {', '.join(missing)}")

        # ── meta ──
        m = stand.BOOK[tid]
        for k in ("language", "image", "base_commit"):
            if not m.get(k):
                return dict(tid=tid, ok=False, layer="meta", detail=f"task.toml has no {k}")
        cfg = json.loads((d / "tests" / "config.json").read_text())
        f2p, p2p = len(cfg.get("f2p_node_ids", [])), len(cfg.get("p2p_node_ids", []))
        # 官方判据：reward = 1 当且仅当 |f2p| > 0 且 f2p 全过且 p2p 无挂。
        # f2p 是空的话那道题**按定义**判不出 1 来 —— 发出去只会白烧一趟。
        if f2p == 0:
            return dict(tid=tid, ok=False, layer="meta", detail="f2p_node_ids is empty - reward can never be 1")
        if cfg.get("base_commit") != m["base_commit"]:
            return dict(tid=tid, ok=False, layer="meta",
                        detail=f"base commit disagrees: task.toml {m['base_commit'][:12]} vs config.json {str(cfg.get('base_commit'))[:12]}")

        # ── image ──
        #
        # **「没拉」和「连不上守护进程」得分开说。** 一律报成「没拉」的话，docker
        # 一翻，全部 113 道都会说「镜像没拉」。（snap 装的 docker 闲置会被卸载挂载
        # 单元，下次一用就重启，所以这一句会真的撞上。）
        r = stand.sh("docker", "image", "inspect", m["image"])
        if r.returncode != 0:
            err = (r.stderr or "").strip()
            if "docker.sock" in err or "daemon" in err:
                return dict(tid=tid, ok=False, layer="docker", detail=err[:200])
            return dict(tid=tid, ok=False, layer="image", detail=f"not pulled: {m['image']}")

        # ── verifier ──
        try:
            tag = stand.verify_image(tid)
        except Exception as e:
            return dict(tid=tid, ok=False, layer="verifier", detail=str(e)[:300])

        # ── box ──
        stand.sh("docker", "rm", "-f", name)
        try:
            stand.container_up(place)
        except Exception as e:
            return dict(tid=tid, ok=False, layer="box", detail=str(e)[:300])
        r = stand.sh("docker", "exec", "-w", "/app", name, "git", "rev-parse", "HEAD")
        if r.returncode != 0:
            return dict(tid=tid, ok=False, layer="box", detail=f"/app is not a git repo: {r.stderr.strip()[:200]}")
        head = r.stdout.strip()
        # **base commit 让 git 自己去解，别拿字符串比。**
        #
        # 语料里有几道题的 `base_commit_hash` 写的是**缩写**（`68dafce`、`7cef35b`、
        # 12 位的也有）。拿 40 位的 HEAD 去跟它做全等，那几道永远不等 —— 而报出来
        # 的样子是「HEAD is 68dafce500a8, base commit is 68dafce」。
        #
        # 解一遍还顺带查了另一件事：那个 base commit 在这个仓库里**真的存在**。
        b = stand.sh("docker", "exec", "-w", "/app", name, "git", "rev-parse", m["base_commit"] + "^{commit}")
        if b.returncode != 0:
            return dict(tid=tid, ok=False, layer="box",
                        detail=f"the base commit {m['base_commit']} is not in this repo: {b.stderr.strip()[:160]}")
        if head != b.stdout.strip():
            return dict(tid=tid, ok=False, layer="box",
                        detail=f"HEAD is {head[:12]}, base commit resolves to {b.stdout.strip()[:12]}")

        # ── net ──
        # 官方两侧都是 no-network。通了的话这一跑不作数 —— 参考解就公开在 GitHub 上。
        r = stand.sh("docker", "exec", name, "sh", "-c",
                     "getent hosts github.com >/dev/null 2>&1 && echo OPEN || echo CLOSED")
        if "OPEN" in r.stdout:
            return dict(tid=tid, ok=False, layer="net", detail="the container can resolve github.com - it is not isolated")

        # ── forward ──
        try:
            out = stand.runtime_of(place).call("bash", {"command": "pwd && git rev-parse --short HEAD"})
        except Exception as e:
            return dict(tid=tid, ok=False, layer="forward", detail=str(e)[:300])
        if not isinstance(out, dict) or "/app" not in str(out.get("stdout", "")):
            return dict(tid=tid, ok=False, layer="forward", detail=f"the runtime answered oddly: {str(out)[:200]}")

        # ── golden ──
        if deep:
            golden = (d / "solution" / "solution.patch").read_text(encoding="utf-8")
            a = stand.run_verifier(tid, "")
            b = stand.run_verifier(tid, golden)
            timing = f"{a.get('seconds', '?')}s/{b.get('seconds', '?')}s"
            if int(a.get("reward", -1)) != 0 or int(b.get("reward", -1)) != 1:
                # **判不出来跟判错了要分开报。** 前者多半是机器（OOM、超时），
                # 提一次内存重跑就好；后者才是这道题在这台机器上真的用不了。
                broke = a.get("why") or b.get("why")
                return dict(tid=tid, ok=False, layer="golden",
                            detail=(f"{broke} ({timing})" if broke else
                                    f"empty={a.get('reward')} golden={b.get('reward')} "
                                    f"f2p={b.get('f2p_passed')}/{b.get('f2p_total')} "
                                    f"p2p={b.get('p2p_passed')}/{b.get('p2p_total')} ({timing})"))

        extra = ""
        if deep:
            # 两栏分开记：**空补丁那一栏大 = 套件本身贵；差值大 = 改了代码要重编。**
            # 混成一个「判一次多久」的话，这两种慢就再也分不开了。
            e, g = float(a.get("seconds", 0)), float(b.get("seconds", 0))
            extra = f"  suite {e:>6.1f}s  rebuild +{g - e:>6.1f}s"
        return dict(tid=tid, ok=True, layer="",
                    detail=f"{m['language']:<10} f2p {f2p:>3} p2p {p2p:>5}{extra}")
    except Exception as e:
        return dict(tid=tid, ok=False, layer="?", detail=f"{type(e).__name__}: {e}"[:300])
    finally:
        if not keep:
            stand.sh("docker", "rm", "-f", name)


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("tasks", nargs="*", metavar="TASK_ID")
    ap.add_argument("--deep", action="store_true", help="also grade each task's own reference solution (hours)")
    ap.add_argument("--jobs", type=int, default=4)
    ap.add_argument("--keep", action="store_true", help="leave the preflight containers behind")
    a = ap.parse_args()

    # **守护进程先确认一次。** 它没起的话下面每一道都会失败，而失败的样子取决于撞在
    # 哪一层。这一句在第一行就把它说清楚，顺带报出内存和核数：并发开多大看这两个数。
    info = stand.sh("docker", "info", "--format", "{{.ServerVersion}} {{.MemTotal}} {{.NCPU}}")
    if info.returncode != 0:
        print(f"docker is not answering: {(info.stderr or '').strip()[:200]}")
        return 1
    ver, mem, cpus = info.stdout.split()
    print(f"docker {ver} | {int(mem) / 1024 ** 3:.1f} GiB | {cpus} cpus")

    ids = a.tasks or sorted(stand.BOOK)
    print(f"preflight: {len(ids)} tasks, {a.jobs} at a time{', deep' if a.deep else ''}\n", flush=True)

    t0 = time.time()
    rows: list[dict] = []
    with concurrent.futures.ThreadPoolExecutor(max_workers=a.jobs) as pool:
        for r in pool.map(lambda t: check(t, a.deep, a.keep), ids):
            rows.append(r)
            mark = "ok  " if r["ok"] else "FAIL"
            where = "" if r["ok"] else f"[{r['layer']}] "
            print(f"  {mark} {r['tid']:<52} {where}{r['detail']}", flush=True)

    bad = [r for r in rows if not r["ok"]]
    print(f"\n{len(rows) - len(bad)} of {len(rows)} usable, {time.time() - t0:.0f}s")
    if bad:
        print("\nnot usable on this machine:")
        for r in bad:
            print(f"  {r['tid']:<52} [{r['layer']}] {r['detail']}")
        print("\nleave them out of the batch, or fix what the layer says.")
    return 1 if bad else 0


if __name__ == "__main__":
    sys.exit(main())
