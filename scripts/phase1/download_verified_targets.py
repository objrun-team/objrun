from __future__ import annotations
import hashlib
import json
from pathlib import Path
import shutil
import urllib.request

ROOT = Path(__file__).resolve().parents[2]
HOME = ROOT / ".phase1-data/scicode-verified"
TARGET = HOME / "test_data_cleaned.h5"
EXPECTED_MD5 = "2b41a7df40ddc23ce651ec05b8ecb6f8"
SOURCE = "https://huggingface.co/datasets/shhu2001/SciCode-Verified/resolve/main/test_data_cleaned.h5"
HOME.mkdir(parents=True, exist_ok=True)
if not TARGET.exists():
    if shutil.disk_usage(HOME).free < 1_108_078_257 + 1024 * 1024 * 1024:
        raise RuntimeError("Verified targets need 1.1 GB plus 1 GiB free headroom; deferred")
    count = 0
    temporary = TARGET.with_suffix(".h5.part")
    with urllib.request.urlopen(SOURCE, timeout=60) as response, temporary.open("wb") as output:
        while chunk := response.read(1024 * 1024):
            if count == 0 and not chunk.startswith(b"\x89HDF\r\n\x1a\n"):
                raise RuntimeError("The versioned source did not return HDF5 data")
            output.write(chunk)
            count += len(chunk)
            if count % (64 * 1024 * 1024) == 0:
                print(json.dumps({"downloadedBytes": count}), flush=True)
    temporary.replace(TARGET)
md5 = hashlib.md5()
sha256 = hashlib.sha256()
with TARGET.open("rb") as data:
    while chunk := data.read(1024 * 1024):
        md5.update(chunk)
        sha256.update(chunk)
if md5.hexdigest() != EXPECTED_MD5:
    raise RuntimeError("SciCode-Verified target file does not match the published release checksum")
record = {"source": SOURCE, "variant": "SciCode-Verified v2", "bytes": TARGET.stat().st_size, "md5": md5.hexdigest(), "sha256": sha256.hexdigest()}
TARGET.with_suffix(".source.json").write_text(json.dumps(record, indent=2) + "\n", encoding="utf-8")
print(json.dumps(record), flush=True)
