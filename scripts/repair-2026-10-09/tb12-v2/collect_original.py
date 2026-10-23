"""Actually collect every original test in fresh read-only private containers."""
import argparse
from datetime import datetime, timezone
import json
from pathlib import Path
import uuid

from docker_owned import OwnedDocker, ROOT, sha

COLLECTION_CODE = """
import hashlib,importlib.metadata,json,os,sys,time
from pathlib import Path
config=json.loads(sys.argv[1])
assert sys.version_info[:3]==(3,13,7)
os.environ['PYTEST_DISABLE_PLUGIN_AUTOLOAD']='1'
import pytest,chess,numpy,pandas,pyarrow,requests
versions={name:importlib.metadata.version(name) for name in config['packages'] if name!='chess'}
versions['chess']=chess.__version__
assert versions==config['packages']
folder=Path('/opt/tb12/tasks')/config['taskId']/'tests'
for name,want in config['officialTestHashes'].items():
 assert hashlib.sha256((folder/name).read_bytes()).hexdigest()==want,name
class Collector:
 def __init__(self):self.names=[]
 def pytest_collection_finish(self,session):self.names=[item.nodeid for item in session.items]
c=Collector()
start=time.time()
code=int(pytest.main(['--collect-only','-q',str(folder/'test_outputs.py'),'-p','ctrf.main','--ctrf','/tmp/collection.json','-o','cache_dir=/tmp/pytest-cache'],plugins=[c]))
assert code==0 and [name.split('::')[-1] for name in c.names]==config['staticTestNames']
result={'protocol':'tb12-original-collection-result-v1','invocationId':config['invocationId'],'taskId':config['taskId'],'exitCode':code,'testIds':c.names,'testCount':len(c.names),'pythonVersion':sys.version,'pythonExecutable':sys.executable,'pythonExecutableSha256':hashlib.sha256(Path(sys.executable).read_bytes()).hexdigest(),'packages':versions,'privateNamespaces':{k:os.readlink('/proc/self/ns/'+k) for k in ('pid','mnt','net')},'guestStart':start,'guestStop':time.time()}
print('TB12_COLLECTION:'+json.dumps(result,separators=(',',':')),flush=True)
"""


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--base-proof", required=True)
    args = parser.parse_args()
    proof_path = Path(args.base_proof).resolve()
    assert proof_path.is_relative_to(ROOT / "docs/repair-2026-10-09/tb12-preparation-v1")
    proof = json.loads(proof_path.read_bytes())
    assert proof["actualPrivateImportsValidated"] and proof["allOwnedBuildersClosed"]
    image = proof["immutablePrivateImageId"]
    context_path = Path(proof["contextManifest"]["path"])
    assert sha(context_path) == proof["contextManifest"]["sha256"]
    context = json.loads(context_path.read_bytes())
    nonce = uuid.uuid4().hex
    output = ROOT / "docs/repair-2026-10-09/tb12-preparation-v1/original-collections" / nonce
    native = OwnedDocker(output, nonce)
    records = []
    fatal = None
    try:
        for task in context["tasks"]:
            invocation = uuid.uuid4().hex
            config = {**task, "packages": context["packages"], "invocationId": invocation}
            cid, initial, create = native.create("collection-" + task["taskId"], image, "/opt/checker/bin/python", ["-I", "-B", "-c", COLLECTION_CODE, json.dumps(config, separators=(",", ":"))], readonly=True, network="none")
            start = native.start(cid, attach=True, timeout=120)
            final = native.assert_actor(cid)
            assert final["State"]["Status"] == "exited" and final["State"]["ExitCode"] == 0
            text = native.text(start)
            last = text.splitlines()[-1]
            assert last.startswith("TB12_COLLECTION:")
            result = json.loads(last[len("TB12_COLLECTION:"):])
            assert result["invocationId"] == invocation and result["taskId"] == task["taskId"]
            assert result["testCount"] == len(task["staticTestNames"]) and result["exitCode"] == 0
            removal, absence = native.remove(cid)
            records.append({"taskId": task["taskId"], "cid": cid, "initialState": initial, "createReceipt": create, "startReceipt": start, "finalState": final, "result": result, "removalReceipt": removal, "absenceReceipt": absence})
            print(json.dumps({"taskId": task["taskId"], "originalTestsActuallyCollected": result["testCount"], "ownedContainerClosed": True, "modelCalls": 0}), flush=True)
    except BaseException as error:
        fatal = {"type": type(error).__name__, "message": str(error)}
        if hasattr(error, "receipt"):
            fatal["nativeReceipt"] = error.receipt
    finally:
        extra_closures = []
        for cid, role, name in native.open_actors():
            try:
                removal, absence = native.remove(cid)
                extra_closures.append({"cid": cid, "removal": removal, "absence": absence})
            except BaseException as error:
                extra_closures.append({"cid": cid, "closureFailure": type(error).__name__, "message": str(error)})
        closed = not native.open_actors()
        if closed:
            native.close()
        all_collected = len(records) == 12 and sum(record["result"]["testCount"] for record in records) == 48 and fatal is None
        report = {"protocol": "tb12-original-tests-private-collection-v1", "ownerNonce": nonce, "baseProof": {"path": str(proof_path), "sha256": sha(proof_path)}, "immutablePrivateImageId": image, "contextManifest": proof["contextManifest"], "createdAtUtc": datetime.now(timezone.utc).isoformat(), "records": records, "allTwelveOriginalCollectionsValidated": all_collected, "totalOriginalTestsCollected": sum(record["result"]["testCount"] for record in records), "allOwnedCollectionContainersClosed": closed, "extraClosures": extra_closures, "fatal": fatal, "modelCalls": 0, "coldControlsValidated": False, "privateScorerReady": False, "paidReady": False}
        target = output / "collection.json"
        target.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        print(json.dumps({"report": str(target), "allTwelveOriginalCollectionsValidated": all_collected, "totalTests": report["totalOriginalTestsCollected"], "allOwnedCollectionContainersClosed": closed, "fatal": fatal, "modelCalls": 0, "paidReady": False}), flush=True)
    if not all_collected or not closed:
        raise SystemExit(2)


if __name__ == "__main__":
    main()
