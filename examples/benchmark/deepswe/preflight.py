r"""Before starting, check every problem: **can it run on this machine?**

    python3 preflight.py [problem-ids...] [--deep] [--jobs 4] [--keep]

Without IDs, check all 113 problems. Run on **the Docker host**, alongside stand.py. Derive every path from this script's location; none is hard-coded.

## Why preflight?

A complete run takes hours. Missing corpus files or images, or a repository not at its base commit, may surface only during execution. Those failures look indistinguishable from model failures: the problem receives 0.
Before submitting a batch, actually start each container and execute a command in it.

## Seven layers, from cheapest to most expensive

    files     task.toml, instruction.md, four test files, and the solution exist and are nonempty.
    meta      Language, image, and base commit exist; f2p is nonempty.
              Empty f2p makes reward 0 by definition, so nobody can solve that problem.
    image     The pinned image exists locally.
    verifier  The grader image can be built; its tag uses the tests/ fingerprint.
    box       The container starts; /app is a Git repository; HEAD resolves to the base commit.
    net       Networking is actually disabled. Official agent.network_mode is no-network; connectivity invalidates the run.
    forward   The injected runtime responds over MCP, using the kernel's own implementation.

`--deep` adds the most expensive layer:

    golden    Feeding the problem's reference solution into the official grader passes; an empty patch fails.

The first seven layers take two or three seconds per problem, around ten minutes overall. --deep grades twice per problem, taking 3 seconds to 5.5 minutes per grading pass and hours overall.

## Remove containers after checking

Use `dsw:preflight/<problem-id>`, separate from real-run containers `dsw:<run-name>/<problem-id>`, so preflight never changes a real workspace. --keep retains the containers."""

from __future__ import annotations

import argparse
import concurrent.futures
import json
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import stand  # noqa: E402 — Reuse one implementation for the corpus, Docker, forwarding, and grading.

PLACE = "dsw:preflight/{}"


def check(tid: str, deep: bool, keep: bool) -> dict:
    r"""Check one problem and return `{tid, ok, layer, detail}`. **Report the exact layer that failed.**"""
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
        # Official reward is 1 iff |f2p| > 0, all f2p tests pass, and no p2p tests fail.
        # Empty f2p makes reward 1 impossible **by definition**; submitting such a problem only wastes a run.
        if f2p == 0:
            return dict(tid=tid, ok=False, layer="meta", detail="f2p_node_ids is empty - reward can never be 1")
        if cfg.get("base_commit") != m["base_commit"]:
            return dict(tid=tid, ok=False, layer="meta",
                        detail=f"base commit disagrees: task.toml {m['base_commit'][:12]} vs config.json {str(cfg.get('base_commit'))[:12]}")

        # ── image ──
        #
        # **Distinguish an unpulled image from an unreachable daemon.** Otherwise a Docker outage makes all 113 problems appear to lack images. This occurs with snap Docker: idle mount units may be unmounted and restart on the next use.
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
        # **Let Git resolve the base commit rather than comparing strings.**
        #
        # Some corpus base_commit_hash values are abbreviated (68dafce, 7cef35b, or 12 characters). Comparing them with a full 40-character HEAD always fails, producing messages such as "HEAD is 68dafce500a8, base commit is 68dafce".
        # Resolution also verifies that the base commit **actually exists** in the repository.
        b = stand.sh("docker", "exec", "-w", "/app", name, "git", "rev-parse", m["base_commit"] + "^{commit}")
        if b.returncode != 0:
            return dict(tid=tid, ok=False, layer="box",
                        detail=f"the base commit {m['base_commit']} is not in this repo: {b.stderr.strip()[:160]}")
        if head != b.stdout.strip():
            return dict(tid=tid, ok=False, layer="box",
                        detail=f"HEAD is {head[:12]}, base commit resolves to {b.stdout.strip()[:12]}")

        # ── net ──
        # Both sides are officially no-network. Connectivity invalidates the run because reference solutions are public on GitHub.
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
                # **Distinguish inability to grade from a wrong verdict.** The former usually reflects infrastructure (OOM or timeout), often fixed by more memory and a retry; the latter indicates that the problem genuinely cannot be used on this machine.
                broke = a.get("why") or b.get("why")
                return dict(tid=tid, ok=False, layer="golden",
                            detail=(f"{broke} ({timing})" if broke else
                                    f"empty={a.get('reward')} golden={b.get('reward')} "
                                    f"f2p={b.get('f2p_passed')}/{b.get('f2p_total')} "
                                    f"p2p={b.get('p2p_passed')}/{b.get('p2p_total')} ({timing})"))

        extra = ""
        if deep:
            # Record two timing columns: **a slow empty patch means the suite itself is costly; a large difference means changed code requires recompilation.** One combined grading duration would hide the distinction.
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

    # **Check the daemon first.** If it is down, every problem fails at whichever layer encounters it. Report this immediately along with memory and CPU counts, which determine feasible concurrency.
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
