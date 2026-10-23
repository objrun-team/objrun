"""Prepare the frozen six-tool runtime from a cached Linux Node image.

Never pulls an image, installs dependencies, or changes core source. Requires
the project's existing Bun installation to bundle the TypeScript entry point.
"""
import hashlib
import json
from pathlib import Path
import subprocess
import uuid

ROOT = Path(__file__).resolve().parents[3]
OUTPUT = Path(__file__).with_name(".runtime")
NODE_IMAGE = "sha256:341b84210b3300ec9d6e0f0bcf477b1714b802209b5a4ca475e2077ffc07511d"
ASSETS = {"node": "/usr/local/bin/node", "libgcc_s.so.1": "/lib/x86_64-linux-gnu/libgcc_s.so.1",
          "libstdc++.so.6": "/usr/lib/x86_64-linux-gnu/libstdc++.so.6.0.30"}


def run(*argv, cwd=None):
    result = subprocess.run(argv, cwd=cwd, capture_output=True, encoding="utf-8", timeout=120)
    if result.returncode:
        raise RuntimeError(argv[0] + " failed: " + result.stderr[-500:])
    return result


def digest(path):
    value = hashlib.sha256()
    with path.open("rb") as source:
        while chunk := source.read(1024 * 1024):
            value.update(chunk)
    return value.hexdigest()


def main():
    if run("docker", "image", "inspect", "--format", "{{.Id}}", NODE_IMAGE).stdout.strip() != NODE_IMAGE:
        raise RuntimeError("the pinned Linux Node executor is not cached")
    OUTPUT.mkdir(exist_ok=True)
    run("bun", "build", "--target=node", "--outfile=" + str(OUTPUT / "runtime.mjs"), "src/place/runtime.ts", cwd=ROOT / "app")
    name = "objrun-tb-runtime-assets-" + uuid.uuid4().hex[:12]
    created = False
    try:
        run("docker", "create", "--pull", "never", "--name", name, NODE_IMAGE)
        created = True
        for filename, source in ASSETS.items():
            run("docker", "cp", name + ":" + source, str(OUTPUT / filename))
    finally:
        if created:
            run("docker", "rm", name)
    sources = [ROOT / "app/src/place/runtime.ts", ROOT / "app/src/tools/index.ts", ROOT / "app/src/tools/python.ts"]
    manifest = {"executor": "node:22.22.2-bookworm-slim", "executorImageId": NODE_IMAGE,
                "tools": ["bash", "edit", "glob", "grep", "read", "write"],
                "assets": {filename: digest(OUTPUT / filename) for filename in [*ASSETS, "runtime.mjs"]},
                "frozenSources": {str(path.relative_to(ROOT)).replace("\\", "/"): digest(path) for path in sources},
                "bundleCommand": "bun build --target=node --outfile=../examples/benchmark/terminal-bench/.runtime/runtime.mjs src/place/runtime.ts",
                "python_exec": "unavailable through this six-tool TB path; no replacement implementation"}
    (OUTPUT / "manifest.json").write_text(json.dumps(manifest, indent=2), encoding="utf-8")
    print("prepared four cached runtime assets; no image pulls and no core source changes")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
