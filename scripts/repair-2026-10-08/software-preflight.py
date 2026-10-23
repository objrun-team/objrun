"""SkillsBench source/cache inventory and bounded empty/oracle preflight.

No LLM calls, image pulls/builds, corpus mutations, or removals of user resources.
Every task remains in the full denominator. Cached task images must match a hash
of the actual environment; generic/base images never count as task environments.
"""
from __future__ import annotations

import argparse
import ast
from collections import Counter, deque
import hashlib
import json
import os
from pathlib import Path
import re
import shutil
import subprocess
import sys
import threading
import time
import tomllib
import uuid

import yaml

ROOT = Path(__file__).resolve().parents[2]
DEFAULT_CORPUS = ROOT / ".phase1-data/skillsbench/vendor/skillsbench"
DEFAULT_REPORT = ROOT / "docs/repair-2026-10-08/software-preflight.json"
ADAPTER = ROOT / "examples/benchmark/skillsbench/stand.py"
PIN = "b63b7b2850226b6aa4fb5929a8c1ac7bc4d9a6af"


def sha256_file(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


def tree_digest(path: Path, *, posix: bool = True) -> str:
    """The adapter's exact byte fingerprint, without reading large files at once."""
    h = hashlib.sha256()
    for file in sorted(path.rglob("*")):
        if file.is_file():
            relative = file.relative_to(path)
            h.update((relative.as_posix() if posix else str(relative)).encode())
            with file.open("rb") as stream:
                for chunk in iter(lambda: stream.read(1024 * 1024), b""):
                    h.update(chunk)
    return h.hexdigest()


def definitions(names: set[str], namespace: dict) -> dict:
    tree = ast.parse(ADAPTER.read_text(encoding="utf-8"))
    selected = [n for n in tree.body if isinstance(n, (ast.FunctionDef, ast.ClassDef)) and n.name in names]
    if len(selected) != len(names):
        raise RuntimeError("Missing required real adapter definitions")
    exec(compile(ast.Module(body=selected, type_ignores=[]), str(ADAPTER), "exec"), namespace)
    return namespace


def old_skip_reasons() -> dict[str, str]:
    tree = ast.parse(ADAPTER.read_text(encoding="utf-8"))
    for node in tree.body:
        if isinstance(node, ast.AnnAssign) and isinstance(node.target, ast.Name) and node.target.id in ("APPTAINER_SKIP", "SKIP") and isinstance(node.value, ast.Dict):
            return ast.literal_eval(node.value)
    raise RuntimeError("Cannot find the recorded legacy backend skip evidence")


def docker_read(*args: str) -> subprocess.CompletedProcess:
    result = subprocess.run(["docker", *args], capture_output=True, text=True, timeout=30)
    if result.returncode:
        raise RuntimeError(f"Docker {args[0]} failed: {result.stderr[-500:]}")
    return result


def cache_inventory() -> tuple[dict[str, dict], dict]:
    # Do not print or save Config.Env: it can contain image credentials.
    rows = [json.loads(line) for line in docker_read("image", "ls", "--no-trunc", "--format", "{{json .}}").stdout.splitlines() if line.strip()]
    tags: dict[str, dict] = {}
    unique_ids = sorted({row["ID"] for row in rows})
    by_id: dict[str, dict] = {}
    for start in range(0, len(unique_ids), 32):
        inspected = json.loads(docker_read("image", "inspect", *unique_ids[start:start + 32]).stdout)
        for image in inspected:
            by_id[image["Id"]] = {"imageId": image["Id"], "repoDigests": image.get("RepoDigests") or [], "sizeBytes": image.get("Size"), "created": image.get("Created")}
    for row in rows:
        if row["Repository"] != "<none>" and row["Tag"] != "<none>":
            tags[f"{row['Repository']}:{row['Tag']}"] = by_id[row["ID"]]
    info = json.loads(docker_read("info", "--format", "{{json .}}").stdout)
    summary = {"uniqueImageCount": len(unique_ids), "tagCount": len(tags), "engineVersion": info.get("ServerVersion"), "dockerMemoryBytes": info.get("MemTotal"), "storageDriver": info.get("Driver"), "runningContainers": info.get("ContainersRunning")}
    return tags, summary


def host_free(path: Path) -> int:
    return shutil.disk_usage(path.resolve()).free


def dockerfile_bases(text: str, tags: dict[str, dict]) -> list[dict]:
    """Read top-level FROM only; Python imports inside RUN heredocs are not images."""
    bases, stages, heredocs = [], set(), []
    continued = False
    for line in text.splitlines():
        stripped = line.strip()
        if heredocs:
            if stripped == heredocs[0]:
                heredocs.pop(0)
            continue
        if not stripped or stripped.startswith("#"):
            continue
        was_continued, continued = continued, stripped.endswith("\\")
        if not was_continued and re.match(r"(?:RUN|COPY|ADD)\s", stripped, flags=re.I):
            heredocs = re.findall(r"<<-?\s*['\"]?([A-Za-z_][A-Za-z0-9_]*)['\"]?", line)
        if was_continued:
            continue
        match = re.match(r"\s*FROM\s+(?:--platform=\S+\s+)?(\S+)", line, flags=re.I)
        if not match:
            continue
        ref = match.group(1)
        lookup = ref if ":" in ref or "@" in ref else ref + ":latest"
        if ref in stages:
            bases.append({"reference": ref, "kind": "local-build-stage", "cached": None})
        else:
            bases.append({"reference": ref, "kind": "external-base-image", "cached": lookup in tags,
                          "imageId": tags.get(lookup, {}).get("imageId"), "knownSizeBytes": tags.get(lookup, {}).get("sizeBytes")})
        stage = re.search(r"\s+AS\s+(\S+)", line, flags=re.I)
        if stage:
            stages.add(stage.group(1))
    return bases


def inspect_tasks(corpus: Path, tags: dict[str, dict]) -> list[dict]:
    loader = {"Path": Path, "yaml": yaml, "re": re, "TASKS": corpus / "tasks"}
    definitions({"split_task_md", "workdir_of", "skills_of", "load_corpus"}, loader)
    book = loader["load_corpus"]()
    legacy_skip = old_skip_reasons()
    rows = []
    for tid, task in sorted(book.items()):
        directory = Path(task["dir"])
        context_files = [file for file in (directory / "environment").rglob("*") if file.is_file()]
        context_bytes = sum(file.stat().st_size for file in context_files)
        canonical = tree_digest(directory / "environment")
        native = tree_digest(directory / "environment", posix=False)
        expected = f"skb-task-{tid}:{canonical[:12]}"
        candidates = [expected]
        if native != canonical:
            candidates.append(f"skb-task-{tid}:{native[:12]}")
        cached_tag = next((tag for tag in candidates if tag in tags), None)
        dockerfile = directory / "environment/Dockerfile"
        base_refs = dockerfile_bases(dockerfile.read_text(encoding="utf-8", errors="replace"), tags)
        oracle_file = directory / "oracle/solve.sh"
        oracle_text = oracle_file.read_text(encoding="utf-8", errors="replace") if oracle_file.is_file() else ""
        large_dependency_flags = [name for name, pattern in {
            "huggingface-model": r"huggingface|hf_hub_download|snapshot_download|transformers.*from_pretrained",
            "large-dataset-download": r"wget.*(?:dataset|\.zip|\.tar)|curl.*(?:dataset|\.zip|\.tar)",
        }.items() if re.search(pattern, oracle_text, flags=re.I)]
        definition = directory / "task.md"
        rows.append({"taskId": tid, "definition": {"path": str(definition), "sha256": sha256_file(definition)},
                     "environment": {"path": str(directory / "environment"), "sha256": canonical, "legacyNativeSha256": native, "buildContextBytes": context_bytes, "fileCount": len(context_files)},
                     "oracle": {"path": str(oracle_file), "sha256": sha256_file(oracle_file) if oracle_file.is_file() else None, "largeDependencyFlags": large_dependency_flags},
                     "verifier": {"path": str(directory / "verifier"), "sha256": tree_digest(directory / "verifier")},
                     "officialBudget": {"agentSeconds": task["seconds"], "verifierSeconds": task["verify_seconds"], "cpus": task["cpus"], "memoryMB": int(task["memory"][:-1]), "networkMode": task["network"], "workdir": task["workdir"]},
                     "image": {"expectedTag": expected, "acceptedTags": candidates, "cachedTag": cached_tag, "cached": bool(cached_tag), "imageId": None, **(tags[cached_tag] if cached_tag else {}), "baseImages": base_refs},
                     "legacyApptainerSkip": legacy_skip.get(tid),
                     "preflight": {"status": "not_run" if cached_tag else "blocked_missing_cached_task_image", "empty": None, "oracle": None},
                     "_adapterTask": task})
    return rows


class OverallBoundary(RuntimeError):
    pass


class Runner:
    def __init__(self, report: dict, args: argparse.Namespace):
        self.args = args
        self.deadline = time.monotonic() + args.total_seconds
        self.owned_containers: set[str] = set()
        self.owned_images: set[str] = set()
        self.prefix = "objrun-skb-preflight-" + uuid.uuid4().hex[:12]
        self.logs = args.output.parent / ("software-preflight-logs-" + self.prefix.rsplit("-", 1)[-1])
        self.logs.mkdir(parents=True, exist_ok=False)
        self.report = report
        sys.path.insert(0, str(ROOT / "examples/benchmark/_lib"))
        from grader_status import require_result
        self.require_result = require_result
        self.adapter = {"Path": Path, "json": json, "os": os, "shutil": shutil, "subprocess": subprocess, "time": time,
                        "BACKEND": "docker", "NETWORK": "official", "LEVEL": 2, "ALLOW_UNSAFE_DIAGNOSTIC": False,
                        "BOOK": {}, "LOGS": self.logs, "sh": self.shell}
        definitions({"require_isolation", "network_of", "wipe", "run_verifier"}, self.adapter)

    def check_resources(self):
        if time.monotonic() >= self.deadline:
            raise OverallBoundary("overall_wall_clock_budget_exhausted")
        if host_free(ROOT) < self.args.min_free_gib * 1024 ** 3:
            raise OverallBoundary("host_workspace_disk_below_reserved_free_space")

    def shell(self, *argv: str, **kwargs) -> subprocess.CompletedProcess:
        if argv[0] != "docker" or argv[1] in ("pull", "build"):
            raise RuntimeError("Only cached Docker image operations are allowed")
        cleanup = argv[1] in ("rm", "rmi")
        if cleanup:
            owned = self.owned_containers if argv[1] == "rm" else self.owned_images
            target = argv[-1]
            if target not in owned:
                raise RuntimeError("Refusing to remove a resource not created by this preflight")
        else:
            self.check_resources()
        args = list(argv)
        if argv[1] in ("create", "run"):
            if self.owned_containers:
                # A candidate is removed before the independent verifier starts.
                for name in self.owned_containers:
                    found = subprocess.run(["docker", "inspect", name], capture_output=True, text=True, timeout=10)
                    if found.returncode == 0:
                        raise RuntimeError("One-container preflight limit reached")
            name = args[args.index("--name") + 1]
            if not (name.startswith(self.prefix) or name.startswith("skb-verify-")):
                raise RuntimeError("Unexpected preflight container name")
            self.owned_containers.add(name)
            memory = args[args.index("--memory") + 1]
            args[2:2] = ["--pull", "never", "--memory-swap", memory, "--label", "objrun.software-preflight=" + self.prefix]
        if argv[1] == "commit":
            self.owned_images.add(argv[-1])
        timeout = kwargs.pop("timeout", 30)
        effective_timeout = timeout if cleanup else min(timeout, max(.1, self.deadline - time.monotonic()))
        try:
            result = self.bounded_run(args, effective_timeout, cleanup=cleanup, **kwargs)
            if cleanup and result.returncode == 0:
                owned.discard(target)
            return result
        except subprocess.TimeoutExpired as error:
            if not cleanup and time.monotonic() >= self.deadline:
                raise OverallBoundary("overall_wall_clock_budget_exhausted") from error
            raise

    def bounded_run(self, args: list[str], timeout: float, *, cleanup: bool = False, **kwargs) -> subprocess.CompletedProcess:
        """Keep CLI output bounded and stop our long-running container on disk limits."""
        outputs = [deque(maxlen=128), deque(maxlen=128)]  # at most 1 MiB per stream
        process = subprocess.Popen(args, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, **kwargs)

        def drain(stream, chunks):
            try:
                for chunk in iter(lambda: stream.read(8192), ""):
                    chunks.append(chunk)
            finally:
                stream.close()

        readers = [threading.Thread(target=drain, args=(stream, chunks), daemon=True) for stream, chunks in zip((process.stdout, process.stderr), outputs)]
        for reader in readers:
            reader.start()
        started, monitored_at = time.monotonic(), 0.0
        watched = None
        if args[1] in ("exec", "start", "commit"):
            watched = next((name for name in self.owned_containers if name in args), None)
        try:
            while process.poll() is None:
                if time.monotonic() - started >= timeout:
                    raise subprocess.TimeoutExpired(args, timeout)
                if not cleanup and time.monotonic() - monitored_at >= 1:
                    self.check_resources()
                    monitored_at = time.monotonic()
                    if watched:
                        size = subprocess.run(["docker", "inspect", "--size", "--format", "{{.SizeRw}}", watched], capture_output=True, text=True, timeout=10)
                        if size.returncode == 0 and int(size.stdout.strip()) > self.args.max_writable_mb * 1024 ** 2:
                            raise OverallBoundary("running_container_writable_layer_exceeds_preflight_disk_budget")
                time.sleep(.05)
        finally:
            if process.poll() is None:
                process.kill()
                process.wait(timeout=5)
            for reader in readers:
                reader.join(timeout=2)
        return subprocess.CompletedProcess(args, process.returncode, "".join(outputs[0]), "".join(outputs[1]))

    def cleanup(self):
        for name in list(self.owned_containers):
            result = self.shell("docker", "rm", "-f", name)
            if result.returncode and "No such container" not in result.stderr:
                self.report.setdefault("cleanupFaults", []).append({"resource": name, "error": result.stderr[-500:]})
            elif "No such container" in result.stderr:
                self.owned_containers.discard(name)
        for image in list(self.owned_images):
            result = self.shell("docker", "rmi", image)
            if result.returncode and "No such image" not in result.stderr:
                self.report.setdefault("cleanupFaults", []).append({"resource": image, "error": result.stderr[-500:]})
            elif "No such image" in result.stderr:
                self.owned_images.discard(image)

    def score(self, row: dict, image: str, phase: str) -> dict:
        started = time.monotonic()
        tid = row["taskId"]
        self.adapter["BOOK"][tid] = row["_adapterTask"]
        key = self.prefix + "-" + phase + "-" + uuid.uuid4().hex[:8]
        result = self.adapter["run_verifier"](tid, image, key)
        result.pop("_tests", None)
        try:
            self.require_result(result)
            result["valid"] = True
        except Exception:
            result["valid"] = False
        result["wallSeconds"] = round(time.monotonic() - started, 3)
        result["logs"] = str(self.logs / f"{tid}-{key}")
        return result

    def oracle_snapshot(self, row: dict) -> tuple[str, dict]:
        tid, budget = row["taskId"], row["officialBudget"]
        name = self.prefix + "-oracle-" + tid
        image = self.prefix + ":" + uuid.uuid4().hex[:12]
        started = time.monotonic()
        result = self.shell("docker", "run", "-d", "--name", name, "--network", self.adapter["network_of"](tid),
                            "--cpus", budget["cpus"], "--memory", str(budget["memoryMB"]) + "m", "-w", budget["workdir"],
                            row["image"]["imageId"], "sleep", "infinity")
        if result.returncode:
            raise RuntimeError("Cannot create oracle candidate: " + result.stderr[-500:])
        try:
            copied = self.shell("docker", "cp", str(Path(row["oracle"]["path"]).parent) + "/.", name + ":/oracle")
            if copied.returncode:
                raise RuntimeError("Cannot upload official oracle: " + copied.stderr[-500:])
            oracle = self.shell("docker", "exec", "-w", budget["workdir"], name, "bash", "/oracle/solve.sh", timeout=budget["agentSeconds"])
            log = self.logs / (tid + "-oracle-execution.txt")
            log.write_text((oracle.stdout + oracle.stderr)[-200000:], encoding="utf-8")
            size = self.shell("docker", "inspect", "--size", "--format", "{{.SizeRw}}", name)
            if size.returncode == 0 and int(size.stdout.strip()) > self.args.max_writable_mb * 1024 ** 2:
                raise OverallBoundary("oracle_writable_layer_exceeds_preflight_disk_budget")
            snapshot = self.shell("docker", "commit", name, image)
            if snapshot.returncode:
                raise RuntimeError("Cannot snapshot official oracle: " + snapshot.stderr[-500:])
            return image, {"exitCode": oracle.returncode, "wallSeconds": round(time.monotonic() - started, 3), "logs": str(log)}
        finally:
            self.shell("docker", "rm", "-f", name)

    def run_task(self, row: dict):
        budget, result = row["officialBudget"], row["preflight"]
        if not row["image"]["cached"]:
            return
        if budget["memoryMB"] > self.args.max_memory_mb or float(budget["cpus"]) > self.args.max_cpus:
            result["status"] = "blocked_official_resources_above_preflight_admission_limit"
            return
        if row["oracle"]["largeDependencyFlags"]:
            result["status"] = "blocked_oracle_large_dependency_requires_resource_review"
            return
        started = time.monotonic()
        try:
            result["empty"] = self.score(row, row["image"]["imageId"], "empty")
            if not result["empty"]["valid"]:
                result["status"] = "blocked_empty_grader_fault"
                return
            image, execution = self.oracle_snapshot(row)
            result["oracleExecution"] = execution
            result["oracle"] = self.score(row, image, "oracle")
            if not result["oracle"]["valid"]:
                result["status"] = "blocked_oracle_grader_fault"
            elif result["empty"]["reward"] >= 1:
                result["status"] = "blocked_empty_candidate_passes"
            elif result["oracle"]["reward"] != 1:
                result["status"] = "blocked_official_oracle_not_full_pass"
            elif execution["exitCode"] != 0:
                result["status"] = "blocked_official_oracle_execution_error"
            else:
                result["status"] = "ready_empty_rejects_oracle_passes"
        except OverallBoundary as error:
            result.update(status="blocked_operational_resource_boundary", reason=str(error))
            raise
        except subprocess.TimeoutExpired:
            result["status"] = "blocked_official_oracle_timeout"
        except Exception as error:
            result.update(status="blocked_preflight_failure", reason=str(error)[-500:])
        finally:
            result["wallSeconds"] = round(time.monotonic() - started, 3)
            self.cleanup()


def save_report(report: dict, output: Path):
    report["statusCounts"] = dict(Counter(row["preflight"]["status"] for row in report["tasks"]))
    report["readyTaskIds"] = [row["taskId"] for row in report["tasks"] if row["preflight"]["status"] == "ready_empty_rejects_oracle_passes"]
    report["cachedTaskCount"] = sum(bool(row["image"]["cached"]) for row in report["tasks"])
    cleaned = {**report, "tasks": [{k: v for k, v in row.items() if k != "_adapterTask"} for row in report["tasks"]]}
    output.parent.mkdir(parents=True, exist_ok=True)
    staged = output.with_name(output.name + ".pending")
    staged.write_text(json.dumps(cleaned, ensure_ascii=False, indent=2), encoding="utf-8")
    staged.replace(output)


def write_markdown(report: dict, output: Path):
    volume = report["volumeMetadata"]
    lines = ["# SkillsBench 官方预检与镜像清单", "", "日期：2026-10-08。检查已有题库与镜像；未调用 LLM，未拉取或构建镜像。", "",
             f"完整分母 **{report['denominator']}**；精确任务环境缓存 **{report['cachedTaskCount']}**；empty/oracle 对照通过、可启动新 LLM 实验的任务 **{len(report['readyTaskIds'])}**。", "",
             "当前每题均缺少绑定真实环境指纹的完整任务镜像，所以官方空候选和参考解没有实际执行。这里的 blocked 表示环境尚不可启动，不能作为模型失败或 oracle 失败。", "",
             f"题库记录的 commit 为 `{report['source'].get('commit')}`，与固定 v1.1 commit 匹配；每个 task.md、environment、oracle/solve.sh 和 verifier 的 SHA256 已保存到 JSON。", "",
             f"当前 Docker 有 {report['docker']['uniqueImageCount']} 个 image ID、{report['docker']['tagCount']} 个 tag，其中没有任何一个匹配87题的完整环境。", "",
             "## 缺项体积：仅记录可知元数据", "",
             f"87题已有构建输入合计 **{volume['existingBuildContextBytes'] / 1024 ** 2:.1f} MiB**，已经位于本地，无需再次下载。这是 context 文件大小，不能等同于完整镜像或新增层大小。", "",
             f"{volume['tasksWithAtLeastOneCachedExternalBase']}题至少有一个 FROM 基底已缓存。已知、去重的基底镜像 Size 合计 **{volume['knownCachedBaseImageBytes'] / 1024 ** 2:.1f} MiB**，这些同样已经占用磁盘。基底不能替代包含题目输入和依赖的最终任务镜像。", "",
             f"缺少最终任务镜像：**{volume['missingTaskImageCount']}**。缺少或无法确认的外部 FROM 引用共 **{len(volume['uncachedExternalBaseReferences'])}** 个：", "",
             ", ".join(f"`{ref}`" for ref in volume["uncachedExternalBaseReferences"]), "",
             "apt/pip/npm/模型下载会产生多少新增层没有已知可靠元数据，因此最终镜像下载/构建体积为**未知**，不能按其他基准的平均镜像大小凑出估算。F盘当前约2.3 GiB可用，这不是全量构建87题环境的可行性证明。", "",
             "## 恢复与资源边界", "",
             "原 Apptainer SKIP11 在 Docker 中尚无官方对照通过证据；本次没有删除或覆盖这些旧失败理由。下表保留87题，未执行的 empty/oracle 不计0。", "",
             "预检脚本只消费已有精确镜像，禁止 pull/build；同一时刻最多一个自己创建的任务/评分容器。官方 CPU、内存和阶段时限不放宽；默认只准入 ≤2 GiB、≤2 CPU 的任务。对超过上限的题记录资源阻塞，不降低限额后伪报 oracle 失败。", "",
             "运行时 CLI 输出限制为每流1 MiB，容器不使用额外 swap，监视可写层512 MiB与宿主剩余空间2 GiB；整体预检默认1800秒。到达运行边界记录操作性阻塞，保留分母和已完成结果。候选先拍快照并移除，再启动独立评分实例。", "",
             "复现命令（仓库根目录）：", "", "```powershell", "python TgEngin/scripts/repair-2026-10-08/software-preflight.py --inventory-only", "python TgEngin/scripts/repair-2026-10-08/software-preflight.py --max-tasks 3", "```", "",
             "若缓存与资源已补齐，第二条命令优先检查旧SKIP的低预算任务；每题必须 empty<1、oracle=1 且评分有效、参考解执行成功，才进入 readyTaskIds。此前必须先获得实际任务环境，不能用 `python:...` 基底替代。", "",
             "## 完整87题清单", "", "| 任务ID | 原Apptainer跳过 | CPU / MiB | 求解 / 评分秒 | 本地context MiB | 完整镜像 | empty / oracle | 状态 |", "| --- | --- | --- | --- | --- | --- | --- | --- |"]
    for row in report["tasks"]:
        budget, pf = row["officialBudget"], row["preflight"]
        def reward(result):
            return str(result.get("reward")) if result else "未执行"
        lines.append(f"| {row['taskId']} | {'是' if row['legacyApptainerSkip'] else '否'} | {budget['cpus']} / {budget['memoryMB']} | {budget['agentSeconds']} / {budget['verifierSeconds']} | {row['environment']['buildContextBytes'] / 1024 ** 2:.2f} | {'缓存' if row['image']['cached'] else '缺失'} | {reward(pf['empty'])} / {reward(pf['oracle'])} | {pf['status']} |")
    output.with_suffix(".md").write_text("\n".join(lines) + "\n", encoding="utf-8")


def tb_cached_metadata(tags: dict[str, dict], output: Path) -> dict:
    """Check cached TB aliases with tiny registry manifests; never pull layers."""
    corpus = ROOT / ".phase1-data/terminal-bench/vendor/terminal-bench-2-1"
    rows = []
    for path in sorted((corpus / "tasks").glob("*/task.toml")):
        definition = tomllib.loads(path.read_text(encoding="utf-8"))
        environment = definition.get("environment", {})
        expected = environment.get("docker_image", "")
        repository = expected.rsplit(":", 1)[0]
        candidates = [{"tag": tag, **image} for tag, image in tags.items() if tag.rsplit(":", 1)[0] == repository]
        sources = "\n".join(file.read_text(encoding="utf-8", errors="replace") for file in (path.parent / "tests").rglob("*") if file.suffix in (".py", ".sh"))
        hints = {"httpOrSocket": bool(re.search(r"requests\.|localhost|127\.0\.0\.1|socket|grpc", sources)),
                 "processOrProc": bool(re.search(r"/proc/|\bps\b|\bpgrep\b|\bpidof\b|psutil|process_iter", sources)),
                 "dynamicLog": bool(re.search(r"/var/log|access\.log|error\.log", sources))}
        rows.append({"taskId": path.parent.name, "definitionSha256": sha256_file(path), "expectedReference": expected,
                     "cachedCandidates": candidates, "referenceVerified": expected in tags,
                     "officialBudget": {"memoryMB": environment.get("memory_mb"), "cpus": environment.get("cpus"),
                                        "agentSeconds": definition.get("agent", {}).get("timeout_sec"), "verifierSeconds": definition.get("verifier", {}).get("timeout_sec")},
                     "staticInspectionHints": hints, "protocolReady": False})
    # Confirm two live-service tasks and one filesystem task already in cache.
    for tid in ("nginx-request-logging", "configure-git-webserver", "sanitize-git-repo"):
        row = next((row for row in rows if row["taskId"] == tid), None)
        if not row or not row["cachedCandidates"]:
            continue
        try:
            response = docker_read("buildx", "imagetools", "inspect", row["expectedReference"], "--raw")
            manifest = json.loads(response.stdout)
            if "config" not in manifest:
                descriptor = next(item for item in manifest["manifests"] if item.get("platform", {}).get("os") == "linux" and item.get("platform", {}).get("architecture") == "amd64")
                response = docker_read("buildx", "imagetools", "inspect", row["expectedReference"].rsplit(":", 1)[0] + "@" + descriptor["digest"], "--raw")
                manifest = json.loads(response.stdout)
            config_digest = manifest["config"]["digest"]
            matches = [image for image in row["cachedCandidates"] if image["imageId"] == config_digest]
            row.update(referenceVerified=bool(matches), matchedImageIds=[image["imageId"] for image in matches],
                       registryMetadata={"configDigest": config_digest, "manifestSha256": hashlib.sha256(response.stdout.encode()).hexdigest(),
                                         "compressedLayerBytes": sum(layer["size"] for layer in manifest.get("layers", [])),
                                         "imageLayersDownloaded": False})
        except Exception as error:
            row["metadataFault"] = str(error)[-500:]
    source = json.loads((ROOT / ".phase1-data/terminal-bench/source.json").read_text(encoding="utf-8"))
    result = {"benchmark": "Terminal-Bench", "date": "2026-10-08", "source": source, "denominator": len(rows),
              "tasksWithCachedRepository": sum(bool(row["cachedCandidates"]) for row in rows),
              "referenceVerifiedTaskIds": [row["taskId"] for row in rows if row["referenceVerified"]],
              "readyTaskIds": [], "imagePulls": False, "llmRequests": 0,
              "note": "Static hints are audit prompts, not a proof of snapshot equivalence or grading isolation", "tasks": rows}
    output.with_name("software-preflight-tb-inventory.json").write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
    return result


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--corpus", type=Path, default=DEFAULT_CORPUS)
    parser.add_argument("--output", type=Path, default=DEFAULT_REPORT)
    parser.add_argument("--inventory-only", action="store_true")
    parser.add_argument("--tb-metadata", action="store_true", help="also inspect cached TB aliases using registry manifest metadata only")
    parser.add_argument("--tasks", nargs="*")
    parser.add_argument("--max-tasks", type=int, default=3)
    parser.add_argument("--max-memory-mb", type=int, default=2048)
    parser.add_argument("--max-cpus", type=float, default=2)
    parser.add_argument("--max-writable-mb", type=int, default=512)
    parser.add_argument("--min-free-gib", type=float, default=2)
    parser.add_argument("--total-seconds", type=int, default=1800)
    args = parser.parse_args()
    args.output = args.output.resolve()
    if not args.output.is_relative_to(ROOT / "docs/repair-2026-10-08"):
        raise SystemExit("Preflight outputs must remain within this task's repair documentation directory")
    if not (args.corpus / "tasks").is_dir():
        raise SystemExit("The existing SkillsBench corpus was not found; no downloads are attempted")
    if args.max_tasks < 0 or min(args.max_memory_mb, args.max_cpus, args.max_writable_mb, args.total_seconds) <= 0:
        raise SystemExit("Resource limits must be positive")
    tags, docker_summary = cache_inventory()
    source_file = args.corpus.parents[1] / "source.json"
    source = json.loads(source_file.read_text(encoding="utf-8")) if source_file.is_file() else {}
    rows = inspect_tasks(args.corpus, tags)
    if args.tasks and set(args.tasks) - {row["taskId"] for row in rows}:
        raise SystemExit("An explicitly requested task ID is absent from the full corpus")
    bases = {base["imageId"]: base["knownSizeBytes"] for row in rows for base in row["image"]["baseImages"] if base.get("imageId") and base.get("knownSizeBytes") is not None}
    missing_bases = sorted({base["reference"] for row in rows for base in row["image"]["baseImages"] if base["kind"] == "external-base-image" and not base["cached"]})
    report = {"benchmark": "SkillsBench", "date": "2026-10-08", "denominator": len(rows), "expectedDenominator": 87,
              "source": {**source, "expectedCommit": PIN, "metadataMatchesPin": source.get("commit") == PIN},
              "adapter": {"path": str(ADAPTER), "sha256": sha256_file(ADAPTER)}, "docker": docker_summary,
              "policy": {"imagePulls": False, "imageBuilds": False, "llmRequests": 0, "maxSimultaneousOwnedContainers": 1,
                         "maxMemoryMBAdmission": args.max_memory_mb, "maxCPUsAdmission": args.max_cpus, "maxWritableMB": args.max_writable_mb,
                         "minHostFreeGiB": args.min_free_gib, "totalSeconds": args.total_seconds, "officialPerPhaseBudgetsPreserved": True},
              "workspaceFreeBytesBefore": host_free(ROOT), "tasks": rows}
    report["volumeMetadata"] = {"existingBuildContextBytes": sum(row["environment"]["buildContextBytes"] for row in rows),
                                "missingTaskImageCount": sum(not row["image"]["cached"] for row in rows),
                                "tasksWithAtLeastOneCachedExternalBase": sum(any(base["kind"] == "external-base-image" and base["cached"] for base in row["image"]["baseImages"]) for row in rows),
                                "knownCachedBaseImageBytes": sum(bases.values()), "uncachedExternalBaseReferences": missing_bases,
                                "missingFinalImageDownloadBytes": None, "unknownReason": "No published final-image size or new dependency-layer size in the existing source metadata"}
    save_report(report, args.output)
    if len(rows) != 87 or not report["source"]["metadataMatchesPin"]:
        raise SystemExit("Corpus identity mismatch; inventory saved, grading refused")
    cached = [row for row in rows if row["image"]["cached"]]
    if not args.inventory_only and cached:
        selected = sorted(cached, key=lambda row: (not bool(row["legacyApptainerSkip"]), row["officialBudget"]["memoryMB"], row["officialBudget"]["agentSeconds"], row["taskId"]))
        if args.tasks:
            requested = set(args.tasks)
            selected = [row for row in selected if row["taskId"] in requested]
        selected = selected[:args.max_tasks] if args.max_tasks else selected
        runner = Runner(report, args)
        try:
            for row in selected:
                try:
                    runner.run_task(row)
                except OverallBoundary:
                    save_report(report, args.output)
                    break
                save_report(report, args.output)
                print(json.dumps({"taskId": row["taskId"], **row["preflight"]}, ensure_ascii=False), flush=True)
        finally:
            runner.cleanup()
    report["workspaceFreeBytesAfter"] = host_free(ROOT)
    save_report(report, args.output)
    write_markdown(report, args.output)
    if args.tb_metadata:
        tb = tb_cached_metadata(tags, args.output)
        print(json.dumps({"tbDenominator": tb["denominator"], "tbCachedRepositoryTasks": tb["tasksWithCachedRepository"], "tbVerifiedReferenceIds": tb["referenceVerifiedTaskIds"], "tbReadyIds": tb["readyTaskIds"]}), flush=True)
    print(json.dumps({"denominator": report["denominator"], "cachedTaskCount": report["cachedTaskCount"], "readyTaskIds": report["readyTaskIds"], "statusCounts": report["statusCounts"], "report": str(args.output)}, ensure_ascii=False), flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
