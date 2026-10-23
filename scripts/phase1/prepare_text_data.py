"""Download versioned text datasets; derivation runs in the pinned Python container."""
import argparse
import gzip
import hashlib
import json
from pathlib import Path
import shutil
import urllib.request

ROOT = Path(__file__).resolve().parents[2]
HOME = ROOT / ".phase1-data"

def fetch(slug, url, name):
    target = HOME / slug / name
    target.parent.mkdir(parents=True, exist_ok=True)
    if not target.exists():
        with urllib.request.urlopen(url, timeout=60) as response:
            length = int(response.headers.get('Content-Length', '0'))
            limit = 192 * 1024 * 1024
            if length > limit or shutil.disk_usage(target.parent).free < max(length, limit) + 1024 * 1024 * 1024:
                raise ValueError('Dataset download exceeds the light-preparation size or free-space limit; deferred')
            raw = response.read(limit + 1)
            if len(raw) > limit:
                raise ValueError('Dataset exceeds the 192 MiB preparation download limit; deferred')
        decoded = gzip.decompress(raw) if name.endswith('.jsonl') and url.endswith('.gz') else raw
        if len(decoded) > limit:
            raise ValueError('Decompressed dataset exceeds the 192 MiB preparation limit; deferred')
        target.write_bytes(decoded)
    return {"url": url, "file": name, "sha256": hashlib.sha256(target.read_bytes()).hexdigest(), "bytes": target.stat().st_size}

def prepare(slug):
    if slug == "aime":
        files = [fetch(slug, "https://huggingface.co/datasets/AI-MO/aimo-validation-aime/resolve/13f9e12f613e720c2a2b2f345dd04b998a29494d/data/train-00000-of-00001.parquet", "raw/aimo-validation-aime.parquet"),
                 fetch(slug, "https://huggingface.co/datasets/math-ai/aime25/resolve/563bb8404243c5f09de6ec262f2db674fe5bce9b/test.jsonl", "raw/math-ai-aime25.jsonl")]
        for part in ["I", "II"]:
            files.append(fetch(slug, f"https://huggingface.co/datasets/opencompass/AIME2025/resolve/a6ad95f611d72cf628a80b58bd0432ef6638f958/aime2025-{part}.jsonl", f"raw/opencompass-aime2025-{part}.jsonl"))
        record = {"dataset": "AIME 2024/2025, 60 questions", "files": files, "graderPackage": "math-verify==0.9.0"}
    elif slug == "chembench":
        revision = "6e1d25748952393f44e35b8e85bbe567246a6430"
        topics = "analytical_chemistry chemical_preference general_chemistry inorganic_chemistry materials_science organic_chemistry physical_chemistry technical_chemistry toxicity_and_safety".split()
        files = [fetch(slug, f"https://huggingface.co/datasets/jablonkagroup/ChemBench/resolve/{revision}/{topic}/train-00000-of-00001.parquet", f"parquet/{topic}.parquet") for topic in topics]
        record = json.loads((HOME / slug / "source.json").read_text(encoding="utf-8")) | {"datasetRevision": revision, "filesData": files}
    elif slug == "humaneval-plus":
        file = fetch(slug, "https://github.com/evalplus/humanevalplus_release/releases/download/v0.1.10/HumanEvalPlus.jsonl.gz", "HumanEvalPlus.jsonl")
        record = json.loads((HOME / slug / "source.json").read_text(encoding="utf-8")) | {"datasetVersion": "HumanEvalPlus v0.1.10 (full enhanced inputs)", "filesData": [file]}
    elif slug == "atomworld":
        revision = "c37d5db9b4b4ae87b6356638fb7297327f1525d0"
        files = [fetch(slug, f"https://huggingface.co/datasets/Master-AI-Lab/AtomWorldBench/resolve/{revision}/{name}", name) for name in ['bench/AddAtomAction.json', 'system_prompt.txt', 'README.md']]
        record = json.loads((HOME / slug / "source.json").read_text(encoding="utf-8")) | {"datasetRevision":revision,"datasetRepository":"Master-AI-Lab/AtomWorldBench","pilotSubset":"bench/AddAtomAction (train split excluded)","filesData":files}
    elif slug == "llm-srbench":
        revision = "f4101e201952bb35cab8332b6dcf337b6df02aa8"
        names=['lsr_transform/train-00000-of-00002.parquet','lsr_transform/train-00001-of-00002.parquet','README.md']
        files = [fetch(slug, f"https://huggingface.co/datasets/pkuHaowei/llm-srbench/resolve/{revision}/{name}", 'public-release/'+name) for name in names]
        record = json.loads((HOME / slug / "source.json").read_text(encoding="utf-8")) | {"datasetRevision":revision,"datasetRepository":"pkuHaowei/llm-srbench","representation":"Public author release with embedded arrays; original gated nnheui release is not reproduced.","filesData":files}
    else:
        raise ValueError(slug)
    (HOME / slug / "source.json").write_text(json.dumps(record, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({"benchmark": slug, "dataFiles": len(record.get("filesData", record.get("files", [])))}), flush=True)

if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('benchmarks', nargs='+')
    args = parser.parse_args()
    for slug in args.benchmarks: prepare(slug)
