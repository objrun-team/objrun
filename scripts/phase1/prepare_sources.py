"""Pin public benchmark sources in a local cache. Never expose gold data to a solver."""
from __future__ import annotations
import argparse
import hashlib
import io
import json
from pathlib import Path
import shutil
import urllib.request
import zipfile
from concurrent.futures import ThreadPoolExecutor

ROOT = Path(__file__).resolve().parents[2]
CACHE = ROOT / ".phase1-data"
SOURCE_DOWNLOAD_LIMIT = 64 * 1024 * 1024
SOURCE_EXTRACT_LIMIT = 128 * 1024 * 1024
RESERVED_FREE_BYTES = 1024 * 1024 * 1024
EXCLUDED_ARCHIVE_DIRS = {"results", "outputs", "output", "node_modules", "__pycache__", ".git"}
REPOSITORIES = {
    "chembench": ("lamalab-org/chembench", "45f8bad062fe552810c52be3a328d5da8597ed30"),
    "chemiq": ("oxpig/ChemIQ", None),
    "deepswe": ("datacurve-ai/deep-swe", None),
    "terminal-bench": ("harbor-framework/terminal-bench-2-1", "7131e4375048a0e408a8fb404b5f499d726b695b"),
    "skillsbench": ("benchflow-ai/skillsbench", "b63b7b2850226b6aa4fb5929a8c1ac7bc4d9a6af"),
    "scienceagentbench": ("OSU-NLP-Group/ScienceAgentBench", None),
    "atomworld": ("MasterAI-EAM/atomworld", None),
    "astrovisbench": ("NSF-Simons-CosmicAI-Institute/AstroVisBench", None),
    "llm-srbench": ("deep-symbolic-mathematics/llm-srbench", None),
    "biocoder": ("gersteinlab/biocoder", None),
    "atmossci-bench": ("Relaxed-System-Lab/AtmosSci-Bench", None),
    "lab-bench": ("Future-House/LAB-Bench", None),
    "scienceworld": ("allenai/ScienceWorld", None),
    "putnambench": ("trishullab/PutnamBench", None),
    "humaneval-plus": ("evalplus/evalplus", None),
}

def get(url: str) -> bytes:
    with urllib.request.urlopen(urllib.request.Request(url, headers={"User-Agent": "ObjRun-phase1"}), timeout=60) as response:
        if int(response.headers.get("Content-Length", "0")) > SOURCE_DOWNLOAD_LIMIT:
            raise ValueError("source download exceeds the 64 MiB preparation limit; deferred")
        data = response.read(SOURCE_DOWNLOAD_LIMIT + 1)
        if len(data) > SOURCE_DOWNLOAD_LIMIT:
            raise ValueError("source download exceeds the 64 MiB preparation limit; deferred")
        return data

def source(slug: str, repo: str, revision: str | None = None) -> dict:
    home = CACHE / slug
    home.mkdir(parents=True, exist_ok=True)
    lock = home / "source.json"
    if lock.exists():
        return json.loads(lock.read_text(encoding="utf-8"))
    if shutil.disk_usage(home).free < RESERVED_FREE_BYTES + SOURCE_EXTRACT_LIMIT:
        raise ValueError("insufficient source-cache headroom; large preparation deferred")
    ref = revision or "HEAD"
    commit = ref if len(ref) == 40 else json.loads(get(f"https://api.github.com/repos/{repo}/commits/{ref}"))["sha"]
    print(json.dumps({"benchmark": slug, "commit": commit, "stage": "fetch_source"}), flush=True)
    if slug == "chembench":
        # The source repository contains large example artifacts. Only the
        # pinned grader package is required; the official dataset is fetched separately.
        top = json.loads(get(f"https://api.github.com/repos/{repo}/git/trees/{commit}"))
        src_sha = next(x["sha"] for x in top["tree"] if x["path"] == "src")
        tree = json.loads(get(f"https://api.github.com/repos/{repo}/git/trees/{src_sha}?recursive=1"))
        if tree.get("truncated"):
            raise ValueError("incomplete source tree")
        selected = [dict(x, path="src/" + x["path"]) for x in tree["tree"] if x["type"] == "blob"]
        selected += [x for x in top["tree"] if x["type"] == "blob" and x["path"] in {"README.md", "pyproject.toml", "LICENSE"}]
        def fetch_file(item):
            target = home / "vendor" / repo.split("/")[-1] / item["path"]
            raw = get(f"https://raw.githubusercontent.com/{repo}/{commit}/{item['path']}")
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_bytes(raw)
            return {"path": item["path"], "gitBlob": item["sha"], "sha256": hashlib.sha256(raw).hexdigest()}
        with ThreadPoolExecutor(max_workers=4) as pool:
            files = list(pool.map(fetch_file, selected))
        record = {"repository": f"https://github.com/{repo}", "commit": commit, "sourceScope": "src plus package metadata", "files": files}
        lock.write_text(json.dumps(record, indent=2) + "\n", encoding="utf-8")
        return record
    archive = get(f"https://codeload.github.com/{repo}/zip/{commit}")
    with zipfile.ZipFile(io.BytesIO(archive)) as bundle:
        selected = [m for m in bundle.infolist() if not EXCLUDED_ARCHIVE_DIRS.intersection(Path(m.filename).parts[1:-1])]
        if sum(m.file_size for m in selected) > SOURCE_EXTRACT_LIMIT:
            raise ValueError("source extraction exceeds the 128 MiB preparation limit; deferred")
        for member in selected:
            parts = Path(member.filename).parts[1:]
            if not parts:
                continue
            target = home / "vendor" / repo.split("/")[-1] / Path(*parts)
            if not target.resolve().is_relative_to(home.resolve()):
                raise ValueError("archive path escapes the benchmark cache")
            if member.is_dir():
                target.mkdir(parents=True, exist_ok=True)
            else:
                target.parent.mkdir(parents=True, exist_ok=True)
                target.write_bytes(bundle.read(member))
    record = {"repository": f"https://github.com/{repo}", "commit": commit, "archiveSha256": hashlib.sha256(archive).hexdigest(), "excludedArchiveDirectories": sorted(EXCLUDED_ARCHIVE_DIRS)}
    lock.write_text(json.dumps(record, indent=2) + "\n", encoding="utf-8")
    return record

def prepare(slug: str) -> dict:
    if slug == "gpqa":
        record = source(slug, "idavidrein/gpqa", "56686c06f5e19865c153de0fdb11be3890014df7")
        home = CACHE / slug
        with zipfile.ZipFile(home / "vendor/gpqa/dataset.zip") as bundle:
            for name in ["dataset/gpqa_diamond.csv", "dataset/license.txt"]:
                target = home / name
                target.parent.mkdir(parents=True, exist_ok=True)
                target.write_bytes(bundle.read(name, pwd=b"deserted-untie-orchid"))
        record["datasetSha256"] = hashlib.sha256((home / "dataset/gpqa_diamond.csv").read_bytes()).hexdigest()
    elif slug == "cmt":
        record = source(slug, "JamesRoggeveen/cmt_benchmark_data")
        dataset = CACHE / slug / "cmt_data.jsonl"
        if not dataset.exists():
            dataset.write_bytes(get("https://huggingface.co/datasets/JVRoggeveen/cmt_benchmark/resolve/main/cmt_data.jsonl"))
        record["datasetSha256"] = hashlib.sha256(dataset.read_bytes()).hexdigest()
    elif slug == "scicode":
        record = source(slug, "scicode-bench/SciCode")
    elif slug == "scicode-verified":
        record = source(slug, "flyingwagner/scicode-verified")
    elif slug in REPOSITORIES:
        record = source(slug, *REPOSITORIES[slug])
    else:
        raise ValueError(f"unsupported preparation target: {slug}")
    (CACHE / slug / "source.json").write_text(json.dumps(record, indent=2) + "\n", encoding="utf-8")
    return {"benchmark": slug, **record}

if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("benchmarks", nargs="*", default=["gpqa", "cmt", "scicode"])
    args = parser.parse_args()
    failures = []
    for slug in args.benchmarks:
        try:
            record = prepare(slug)
            print(json.dumps({k: v for k, v in record.items() if k != "files"}), flush=True)
        except Exception as error:
            failures.append(slug)
            print(json.dumps({"benchmark": slug, "stage": "failed", "error": str(error)}), flush=True)
    if failures:
        raise SystemExit(1)
