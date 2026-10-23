"""Create the independent SkillsBench v2 copies without editing stopped drafts."""
from __future__ import annotations
import hashlib
import json
import os
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]
HOME = ROOT / "docs/repair-2026-10-08/skillsbench-ten-takeover-v1"
SOURCES = {
    "skb-artifact-journal-contract.ts": "73148b18d6910e94fe8110ee5d93b2e2e79e4cc07a4df1b37f55fe56a8c220cb",
    "skb-artifact-journal-campaign.ts": "3582f13fcd6a81e90b887f9dfd9376146d2b2b2e04e37ce1b554f33470350bad",
    "skb-artifact-storage.ts": "3b004c44c52fdfd5ef0fc1d1fc36db51349534203e6c181c52a3201592c89a70",
    "skb-artifact-native-service-v1.ts": "5ec3b827f94dca8de826337e0a40ddbdb91169f53f1238960ded3efe3a1191a8",
    "skb-artifact-journal-core-v1.ts": "1d4359c921e602e1fbf131cf480efffcb879316c6ad0190f716f99a43f1ed8b0",
    "skb_artifact_storage.py": "d1086ae969b0fa2500cd9d8fc95b1dfb8a13dcdb3aa1ca2bc45a1c502553315c",
    "skb_artifact_task.py": "137f19b5d4302be9f3100f70a4de1bd7859ad1b2868a2845067e9f582c353e8f",
    "skb_artifact_transport.py": "3588a1faab59c6b09ffd5c37586baf145a9da2c295b00c08f8f5d046f29e9157",
    "skb_artifact_capture.py": "746ea49895e88dcec87bed72e12f9865b53d8a1ff2e9ba5fda0d4d824bebd3f5",
    "skb_artifact_private_eval.py": "e7a0759844ebbf09e5b41537b90b8caa55ae7a51cbc58ddf1bc507337bd07ed0",
}
NAMES = {name: name.replace("-v1.ts", "-v2.ts") if name.endswith("-v1.ts") else
         name.replace(".ts", "-v2.ts") if name.endswith(".ts") else name.replace(".py", "_v2.py")
         for name in SOURCES}
NAMES.update({"skb-artifact-paid-admission-v1.ts": "skb-artifact-paid-admission-v2.ts",
              "audit-skb-artifact-journal.py": "audit-skb-artifact-journal-v2.py",
              "skb-artifact-stand-v1.py": "skb-artifact-stand-v2.py",
              "skb_artifact_ram_executor.py": "skb_artifact_ram_executor_v2.py",
              "skb_artifact_solver_plan.py": "skb_artifact_solver_plan_v2.py"})


def change_once(text, old, new):
    if text.count(old) != 1:
        raise RuntimeError("Version transformation expects exactly one known original hunk")
    return text.replace(old, new)


def transform(name, text):
    for old, new in NAMES.items():
        text = text.replace(old, new)
        if old.endswith(".py"):
            text = text.replace(old[:-3] + " as ", new[:-3] + " as ")
            text = text.replace(old[:-3] + " import ", new[:-3] + " import ")
    if name == "skb-artifact-journal-core-v1.ts":
        text = text.replace("import { join, resolve }", "import { AsyncLocalStorage } from 'node:async_hooks';\nimport { join, resolve }")
        text = change_once(text, "  const routes=new Set(input.schedule.map(r=>r.route)),sealed", "  const routeContext=new AsyncLocalStorage<string>();\n  const routes=new Set(input.schedule.map(r=>r.route)),sealed")
        text = change_once(text, "    },transport:input.transport});", "    },transport:async raw=>{const route=routeContext.getStore();demand(typeof route==='string'&&routes.has(route),'skb_transport_request_context_missing');return input.transport(raw,route!);}});")
        text = change_once(text, "  const record=(r:TaskReceipt)=>{demand(receipts.has(r.route),'skb_task_local_route');receipts.get(r.route)!.push(r);};", "  const collect=(route:string)=>{demand(receipts.has(route),'skb_task_local_route');const rows=proxy.takeTaskReceipts(route);for(const r of rows){demand(r.route===route&&!receipts.get(route)!.some(x=>x.requestSeq===r.requestSeq),'skb_task_receipt_duplicate_or_route');receipts.get(route)!.push(r);}return receipts.get(route)!.slice().sort((a,b)=>a.requestSeq-b.requestSeq);};")
        text = change_once(text, "journal,cash,proxy,record,poison,stop,", "journal,cash,proxy,poison,stop,")
        text = change_once(text, "return proxy.handle(route,raw);", "return routeContext.run(route,()=>proxy.handle(route,raw));")
        text = change_once(text, "return receipts.get(route)!.slice().sort((a,b)=>a.requestSeq-b.requestSeq);},", "return collect(route);},")
        text = change_once(text, "      const all=[...receipts.values()]", "      for(const route of routes)collect(route);\n      const all=[...receipts.values()]")
        text = change_once(text, "journal.exportLegacyLedger(join(output,'api-ledger.json'))", "journal.exportLegacyLedger()")
    elif name == "skb-artifact-journal-campaign.ts":
        text = change_once(text, "'skb-artifact-native-service-v2.ts','skb-artifact-stand-v2.py',", "'skb-artifact-native-service-v2.ts','skb-artifact-stand-v2.py','skb-artifact-storage-v2.ts',")
        text = change_once(text, "'skb_artifact_capture_v2.py','skb_artifact_private_eval_v2.py','skb_artifact_ram_executor_v2.py',", "'skb_artifact_capture_v2.py','skb_artifact_private_eval_v2.py','skb_artifact_ram_executor_v2.py','skb_artifact_transport_v2.py','skb_artifact_solver_plan_v2.py',")
        text = text.replace("skillsbench-artifact-preparations", "skillsbench-artifact-preparations-v2")
    return text


def main():
    pending = []
    for name, sha in SOURCES.items():
        raw = (HERE / name).read_bytes()
        if hashlib.sha256(raw).hexdigest() != sha:
            raise RuntimeError("Stopped draft changed: " + name)
        dest = HERE / NAMES[name]
        if dest.exists():
            raise RuntimeError("Do not overwrite any existing takeover version")
        data = transform(name, raw.decode("utf-8")).encode("utf-8")
        pending.append((name, raw, dest, data))
    rows = []
    for name, raw, dest, data in pending:
        with dest.open("xb") as f:
            f.write(data)
            f.flush()
            os.fsync(f.fileno())
        if dest.read_bytes() != data or (HERE / name).read_bytes() != raw:
            raise RuntimeError("Source version fsync/readback/original identity failed")
        rows.append({"original": {"path": str(HERE / name), "bytes": len(raw), "sha256": SOURCES[name]},
                     "initialVersionPin": {"path": str(dest), "bytes": len(data), "sha256": hashlib.sha256(data).hexdigest()}})
    HOME.mkdir(parents=True, exist_ok=True)
    target = HOME / "initial-version-source-map.json"
    with target.open("xb") as f:
        f.write((json.dumps({"protocol": "skillsbench-ten-initial-version-map-v1", "rows": rows,
                             "runtimeValidated": False, "modelCalls": 0, "paidReady": False}, indent=2) + "\n").encode())
        f.flush()
        os.fsync(f.fileno())
    print(json.dumps({"versionedFiles": len(rows), "originalFilesChanged": 0, "manifest": str(target)}))


if __name__ == "__main__":
    main()
