"""F-only regression/transaction controls. No E access, Docker, model or GET."""
from pathlib import Path
import copy
import hashlib
import importlib.util
import json
import os
import struct
import unittest
from unittest.mock import patch
import uuid

PROJECT=Path(__file__).resolve().parents[1]
AREA=PROJECT/(".scratch/minif-fast-v2-controls-"+uuid.uuid4().hex)
AREA.mkdir()
def load(name,leaf):
    path=PROJECT/"scripts/benchmark-repair"/leaf
    s=importlib.util.spec_from_file_location(name,path);m=importlib.util.module_from_spec(s);s.loader.exec_module(m);return m
fast=load("fast_v2_controls","minif2f_fast_unpack_v2.py")
old=load("old_fast_controls","minif2f_fast_unpack.py")
recover=load("recovery_controls","minif2f_fast_prefix0_recovery.py")
DIAG=json.loads((PROJECT/"docs/repair-2026-10-08/minif2f-fast-first-archive-diagnosis.json").read_bytes())
SNAP=PROJECT/"docs/repair-2026-10-08/minif2f-fast-first-failure-readonly-snapshot"
NAMES=[v["relativePath"] for v in DIAG["stageInventory"]]
checks=[]
PRIOR_REVISION=PROJECT/"docs/repair-2026-10-08/minif2f-fast-v2-revision-2fc700188088"

def archive(trace=".lake/build/lib/F.trace",others=(".lake/build/lib/F.hash",)):
    b=b"LTR2"+struct.pack("<Q",37)+trace.encode()+b"\0\3"+struct.pack("<Q",37)
    for name in others:b+=name.encode()+b"\0\2"+struct.pack("<Q",71)
    return b

def closed_fixture():
    root=AREA/("closed-"+uuid.uuid4().hex);audit=root/"audit";audit.mkdir(parents=True)
    history=audit/recover.HISTORY;history.mkdir()
    for n in recover.FILES:(history/n).write_bytes((SNAP/n).read_bytes())
    stage=audit/recover.OLD_STAGE;stage.mkdir()
    for name in sorted(NAMES,key=lambda s:(s.count('/'),s)):(stage/name).mkdir(exist_ok=True)
    before=recover.stage_inventory(stage,NAMES);root_before=recover.stage_root_identity(stage)
    stage.rename(history/"stage")
    after=recover.stage_inventory(history/"stage",NAMES);root_after=recover.stage_root_identity(history/"stage")
    for n in ["cache-unpacked.jsonl","cache-fast-commits.jsonl"]:(audit/n).write_bytes(b"")
    (audit/"public-cache-acquisition.lock").write_bytes((PRIOR_REVISION/"original-public-acquisition/public-cache-acquisition.lock").read_bytes())
    value={"executionPins":[recover.pin(PROJECT/"scripts/benchmark-repair"/n) for n in ["minif2f_fast_unpack_v2.py","minif2f_fast_prefix0_recovery.py"]],
        "protectedPins":[recover.pin(PROJECT/"scripts/benchmark-repair/minif2f_fast_unpack.py")],"fixtureOnly":True}
    review_path=root/"fixture-review.json";recover.save(review_path,value);review_pin=recover.pin(review_path)
    nonce=uuid.uuid4().hex
    fresh=audit/"cache-fast-unpack.lock";own=audit/"cache-fast-prefix0-recovery.lock"
    for path,marker in [(fresh,{"protocol":"public-cache-acquisition-v1","run_id":"01a119ed-fdf7-7c32-b323-de9bab1290b6","lease_id":nonce,"held":False,"pid":os.getpid(),"stage":recover.PROTOCOL,"outcome":"recovered_prefix0_not_decoded"}),
        (own,{"protocol":recover.PROTOCOL,"ownerNonce":nonce,"held":False,"pid":os.getpid(),"reviewSha256":review_pin["sha256"],"outcome":"recovered_prefix0_not_decoded"})]:
        h=recover.Handle(path,True)
        try:h.write(marker)
        finally:h.close()
    original_pins={n:{"path":str(audit/n),"bytes":e[0],"sha256":e[1]} for n,e in recover.FILES.items()}
    intent_path=audit/("cache-fast-prefix0-transaction-"+nonce+".json")
    recover.save(intent_path,{"protocol":recover.PROTOCOL+"-intent","ownerNonce":nonce,"reviewPin":review_pin,"originalPins":original_pins,
        "stageOriginalInventory":before,"stageRootOriginalIdentity":root_before})
    p=json.loads((history/"cache-fast-progress.json").read_bytes())
    receipt={"protocol":recover.PROTOCOL,"closed":True,"nativeLeaseHandlesClosed":True,"decoded_objects":0,"cache_unpack_complete":False,
        "reviewPin":review_pin,"sourcePins":value["executionPins"]+value["protectedPins"],"ownerNonce":nonce,"history":str(history),"originalPins":original_pins,
        "stageOriginalInventory":before,"stageArchivedInventory":after,"stageRootBefore":root_before,"stageRootAfter":root_after,
        "inputProvenance":p["input_provenance"],"sourceIdentity":p["source_before"],"intentPin":recover.pin(intent_path),
        "freshFastLeasePin":recover.pin(fresh),"recoveryLeasePin":recover.pin(own),"fixtureOnly":True}
    receipt_path=audit/"cache-fast-prefix0-recovery.json";recover.save(receipt_path,receipt)
    fast.durable_json(audit/"cache-fast-progress.json",recover.baseline(recover.digest(receipt_path)))
    return root,value,review_path


class Controls(unittest.TestCase):
    def test_exact_byte_delta_only_protocol_helper_two_calls(self):
        a=(PROJECT/"scripts/benchmark-repair/minif2f_fast_unpack.py").read_bytes()
        b=(PROJECT/"scripts/benchmark-repair/minif2f_fast_unpack_v2.py").read_bytes()
        nl=b"\r\n" if b"\r\n" in a else b"\n"
        block=nl.join([b"def archive_output_path(value):",b"    canonical_value = value[2:] if value.startswith('./') else value",b"    return output_path(canonical_value)",b"",b"",b"def ltar_paths(data):"])
        reverse=b.replace(b"PROTOCOL = 'bounded-official-cache-unpack-v2-archive-dot-prefix'",b"PROTOCOL = 'bounded-official-cache-unpack-v1'",1).replace(block,b"def ltar_paths(data):",1).replace(b"paths = [archive_output_path(cstring())]",b"paths = [output_path(cstring())]",1).replace(b"paths.append(archive_output_path(value))",b"paths.append(output_path(value))",1)
        self.assertEqual(reverse,a)
        self.assertEqual(hashlib.sha256(a).hexdigest(),recover.OLD_SHA)
        self.assertEqual(hashlib.sha256(b).hexdigest(),recover.FAST_SHA)
        checks.append("original-other-bytes-exact-after-four-delta-reversal")
    def test_real_first_two_original_byte_red_green(self):
        for name in ["b9a8c5908014b028.ltar","e313882b91df53b2.ltar"]:
            data=(SNAP/name).read_bytes()
            with self.assertRaises(old.InfraError):old.ltar_paths(data)
            paths=fast.ltar_paths(data);self.assertEqual(len(paths),7)
            self.assertTrue(all(not p.startswith("./") for p in paths))
        checks.append("two-real-F-archived-objects-original-red-v2-parser-green-no-decode")
    def test_narrow_archive_positive_and_strict_other_callsite(self):
        self.assertEqual(fast.ltar_paths(archive()),old.ltar_paths(archive()))
        self.assertEqual(fast.ltar_paths(archive("./.lake/build/lib/F.trace",("./.lake/build/lib/F.hash",))),[".lake/build/lib/F.trace",".lake/build/lib/F.hash"])
        self.assertEqual(fast.ltar_paths(archive("./.lake/packages/aesop/.lake/build/lib/A.trace",())),[".lake/packages/aesop/.lake/build/lib/A.trace"])
        with self.assertRaises(fast.InfraError):fast.output_path("./.lake/build/lib/F.trace")
        checks.append("archive-only-single-prefix-generic-output-receipt-stays-strict")
    def test_path_duplicate_length_depth_and_layout_guards(self):
        cases=["././.lake/build/lib/F","/.lake/build/lib/F",".//.lake/build/lib/F","./../F","./.lake/build/../F","./.lake/build/lib/./F","./.lake//build/lib/F","./.lake/build/lib/A\\B","./.lake/build/lib/A:B","./.lake/build/lib/A\nB","./Mathlib/F.lean","./.lake/packages/aesop/Aesop.lean","./.lake/build/lib/"+"x"*260,"./.lake/build/"+"a/"*17+"F"]
        for p in cases:
            with self.subTest(path=p):
                with self.assertRaises(fast.InfraError):fast.ltar_paths(archive(p,()))
        for data in [archive("./.lake/build/lib/A",(".lake/build/lib/A",)),archive("./.lake/build/lib/A",("./.lake/build/lib/a",)),archive()[:-1],archive(others=tuple("./.lake/build/lib/F"+str(i) for i in range(8)))]:
            with self.assertRaises(fast.InfraError):fast.ltar_paths(data)
        checks.append("all14-path-negatives-duplicates-truncation-and-eight-file-bound-remain")
    def test_fixed_failed_phase_semantics_and_mutations(self):
        p,o,l=[json.loads((SNAP/n).read_bytes()) for n in ["cache-fast-progress.json","cache-fast-container.json","cache-fast-unpack.lock"]]
        recover.semantics(p,o,l)
        for which,key,value in [(0,"processed_prefix",1),(0,"validated",True),(0,"reviewed_script_sha256","0"*64),(0,"error_type","different"),(1,"container_id","0"*64),(1,"state","running"),(1,"owner_label","different"),(2,"held",True),(2,"pid",107913)]:
            rows=copy.deepcopy([p,o,l]);rows[which][key]=value
            with self.assertRaises(RuntimeError):recover.semantics(*rows)
        checks.append("only-fixed-failed-prefix0-cid-source-outcome-and-released-pid")
    def test_original_metadata_hash_and_unknown_stage_file_denied(self):
        root=AREA/"stage";root.mkdir()
        for name in sorted(NAMES,key=lambda s:(s.count('/'),s)):(root/name).mkdir(exist_ok=True)
        rows=recover.stage_inventory(root,NAMES);self.assertEqual(len(rows),28)
        (root/"unknown-partial").write_bytes(b"keep")
        with self.assertRaises(RuntimeError):recover.stage_inventory(root,NAMES)
        self.assertEqual((root/"unknown-partial").read_bytes(),b"keep")
        meta=AREA/"bad-progress.json";meta.write_bytes(b"{}");
        with self.assertRaises(RuntimeError):recover.file_pin(meta,recover.FILES["cache-fast-progress.json"])
        checks.append("unknown-stage-partial-and-changed-original-metadata-denied-preserved")
    def test_new_empty_prefix_and_partial_anchor_never_decode_or_old_retry(self):
        root=AREA/"prefix";(root/"audit").mkdir(parents=True)
        for n in ["cache-unpacked.jsonl","cache-fast-commits.jsonl"]:(root/"audit"/n).write_bytes(b"")
        path=root/"audit/cache-fast-progress.json"
        path.write_text(json.dumps(recover.pending_baseline("x")))
        with self.assertRaises(fast.InfraError):fast.verified_prefix(root,[])
        b=recover.baseline("0"*64);path.write_text(json.dumps(b))
        self.assertEqual(fast.verified_prefix(root,[]),([],set()))
        self.assertFalse(b["cache_unpack_complete"]);self.assertEqual(b["decoded_objects"],0)
        with self.assertRaises(old.InfraError):old.verified_prefix(root,[])
        checks.append("pending-recovery-rejected-v2-empty-prefix-only-old-decoder-rejected")
    def test_actual_native_wx_share_deny_release(self):
        path=AREA/"native.lock";h=recover.Handle(path,True)
        try:
            rawsha=h.write({"held":True,"fixtureOnly":True})
            self.assertEqual(len(rawsha),64)
            with self.assertRaises(RuntimeError):recover.Handle(path,True)
            with self.assertRaises(PermissionError):path.open("rb")
            h.write({"held":False,"fixtureOnly":True})
        finally:h.close()
        self.assertFalse(json.loads(path.read_bytes())["held"])
        checks.append("actual-native-create-new-share-deny-and-close-not-caller-boolean")
    def test_real_fsync_fault_retains_failed_receipt(self):
        path=AREA/"failed-fsync.json"
        with patch.object(recover.os,"fsync",side_effect=OSError("F-only native fsync fault")):
            with self.assertRaises(OSError):recover.save(path,{"closed":False,"fixtureOnly":True})
        self.assertTrue(path.exists());self.assertFalse(json.loads(path.read_bytes())["closed"])
        checks.append("real-fsync-error-preserves-failed-partial-no-success-certificate")
    def test_real_source_intent_and_unknown_partials_rejected_before_external_guard(self):
        source=(PROJECT/"scripts/benchmark-repair/minif2f_fast_unpack_v2.py").read_text()
        self.assertIn("durable_json(self.root / 'audit/cache-fast-item.json', intent)",source)
        for name in ["cache-fast-item.json","cache-fast-intent.json","pending.new","pending.part"]:
            root=AREA/("intent-"+uuid.uuid4().hex);audit=root/"audit";audit.mkdir(parents=True)
            for n in recover.FILES:(audit/n).write_bytes((SNAP/n).read_bytes())
            stage=audit/recover.OLD_STAGE;stage.mkdir()
            for n in sorted(NAMES,key=lambda s:(s.count('/'),s)):(stage/n).mkdir(exist_ok=True)
            partial=audit/name;partial.write_bytes(b'{"state":"materialized","fixtureOnly":true}')
            with patch.object(recover,"ROOT",root):
                with self.assertRaisesRegex(RuntimeError,"Unclosed intent/new/partial"):
                    recover.validate({})
            self.assertTrue(partial.exists())
        checks.append("source-bound-real-item-intent-and-new-partials-denied-before-external-work")
    def test_check_closed_requires_real_prefix0_and_native_share_deny_reopens(self):
        root,value,review_path=closed_fixture()
        with patch.object(recover,"ROOT",root):
            result=recover.check_closed(value,review_path)
            self.assertEqual(result["nativeShareDenyReopensVerified"],3)
            self.assertEqual(result["decoded_objects"],0);self.assertFalse(result["cache_unpack_complete"])
            lock=recover.Handle(root/"audit/cache-fast-prefix0-recovery.lock")
            try:
                with self.assertRaisesRegex(RuntimeError,"Native share-deny"):
                    recover.check_closed(value,review_path)
            finally:lock.close()
        for failure in ["pending","journal","prefix1","receiptsha","nativebool"]:
            root,value,review_path=closed_fixture();audit=root/"audit";progress=audit/"cache-fast-progress.json"
            if failure=="pending":progress.write_text(json.dumps(recover.pending_baseline("x")))
            elif failure=="journal":(audit/"cache-unpacked.jsonl").write_bytes(b'{}\n')
            else:
                doc=json.loads(progress.read_bytes())
                if failure=="prefix1":doc["processed_prefix"]=1
                elif failure=="receiptsha":doc["recovery_receipt_sha256"]="0"*64
                else:
                    receipt=audit/"cache-fast-prefix0-recovery.json";r=json.loads(receipt.read_bytes());r["nativeLeaseHandlesClosed"]=False
                    receipt.write_text(json.dumps(r));doc=recover.baseline(recover.digest(receipt))
                progress.write_text(json.dumps(doc))
            with patch.object(recover,"ROOT",root):
                with self.assertRaises(RuntimeError):recover.check_closed(value,review_path)
        checks.append("closed-receipt-alone-rejected-pending-nonempty-prefix1-wrong-sha-and-real-held-native-handle")
    def test_success_receipt_then_baseline_fsync_failure_is_not_closed(self):
        root,value,review_path=closed_fixture();audit=root/"audit";progress=audit/"cache-fast-progress.json"
        receipt=audit/"cache-fast-prefix0-recovery.json";original_receipt=receipt.read_bytes()
        progress.write_text(json.dumps(recover.pending_baseline("x")))
        with patch.object(fast.os,"fsync",side_effect=OSError("F-only baseline fsync fault")):
            with self.assertRaises(OSError):fast.durable_json(progress,recover.baseline(recover.digest(receipt)))
        with patch.object(recover,"ROOT",root):
            with self.assertRaisesRegex(RuntimeError,"Unclosed intent/new/partial"):recover.check_closed(value,review_path)
        self.assertTrue(progress.with_name(progress.name+".new").exists())
        self.assertEqual(receipt.read_bytes(),original_receipt)
        self.assertFalse(json.loads(progress.read_bytes())["validated"])
        checks.append("real-baseline-publication-fsync-fault-preserves-new-and-success-receipt-but-checkclosed-denies")
    def test_fresh_stage_root_identity_survives_same_volume_rename_and_rejects_other_root(self):
        first=AREA/"root-before";first.mkdir();before=recover.stage_root_identity(first)
        moved=AREA/"root-after";first.rename(moved);after=recover.stage_root_identity(moved)
        recover.same_renamed_root(before,after)
        other=AREA/"root-other";other.mkdir()
        with self.assertRaises(RuntimeError):recover.same_renamed_root(before,recover.stage_root_identity(other))
        checks.append("fresh-stage-root-device-fileid-mtime-same-volume-rename-verified-no-historical-id-claim")

if __name__=="__main__":
    suite=unittest.defaultTestLoader.loadTestsFromTestCase(Controls)
    result=unittest.TextTestRunner(verbosity=2).run(suite)
    def pin(p):return {"path":str(p),"bytes":p.stat().st_size,"sha256":hashlib.sha256(p.read_bytes()).hexdigest()}
    report={"protocol":"minif2f-fast-v2-F-controls-v1","testsRun":result.testsRun,"failures":len(result.failures),"errors":len(result.errors),"checks":checks,"fixtureRoot":str(AREA),"E_C_D_modified":False,"dockerOperations":0,"decoderInvocations":0,"modelRequests":0,"productionRestoreExecuted":False,"actualOfficialDecodedPositiveStillRequired":True,"sourcePins":[pin(PROJECT/"scripts/benchmark-repair"/n) for n in ["minif2f_fast_unpack_v2.py","minif2f_fast_prefix0_recovery.py"]],"testSourcePin":pin(Path(__file__))}
    target=PROJECT/"docs/repair-2026-10-08"/("minif2f-fast-v2-controls-"+AREA.name.split('-')[-1]+".json")
    recover.save(target,report);print(json.dumps(pin(target)))
    raise SystemExit(0 if result.wasSuccessful() else 1)
