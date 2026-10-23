"""Pure score/manifest/TAR adversarial controls, with zero environment/model work."""
from __future__ import annotations
import ast
import copy
import hashlib
import io
from pathlib import Path
import sys
import tarfile
import tempfile
import importlib.util
import sqlite3
import threading
import time
from contextlib import closing
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
SCRIPTS = ROOT / "scripts/repair-2026-10-08"
sys.path.insert(0, str(SCRIPTS))
import skb_artifact_private_eval_v2 as evaluator
import skb_artifact_task_v2 as task
import skb_artifact_capture_v2 as capture
import skb_artifact_ram_plan_v2 as ram
import skb_artifact_ram_executor_v2 as ram_executor
import skb_artifact_solver_v2 as solver_module
_spec=importlib.util.spec_from_file_location('skb_stand',SCRIPTS/'skb-artifact-stand-v2.py')
stand=importlib.util.module_from_spec(_spec);_spec.loader.exec_module(stand)


def job(task_id="lab-unit-harmonization", nodes=None):
    if nodes is None: nodes = ["test_outputs.py::test_one", "test_outputs.py::test_two"]
    memory, seconds = evaluator.RESOURCE[task_id]
    manifest = task.trusted_input_manifest()
    inputs = copy.deepcopy(next(x["inputs"] for x in manifest["tasks"] if x["taskId"] == task_id))
    return {"protocol": "skillsbench-private-offline-job-v2", "taskId": task_id, "mode": "grade",
            "taskDescriptorSha256": "1"*64, "runnerSourceSha256": "2"*64,
            "trustedManifestSha256": hashlib.sha256(task.canonical(manifest)).hexdigest(),
            "pythonPath": "/opt/objrun-verifier/bin/python", "pythonSha256": "3"*64, "pythonVersion": "3.12.3",
            "dependencies": evaluator.DEPENDENCIES, "inputs": inputs, "expectedNodeIds": nodes,
            "outputArtifactPath": evaluator.TASK_OUTPUTS[task_id], "scoreRule": "original-three-decimal-passed-over-passed-plus-failed" if task_id == "lab-unit-harmonization" else "original-pytest-exit-binary",
            "pdftotext": None, "memoryBytes": memory*1024**2, "timeoutSec": seconds}


def events(nodes, fail=()):
    return [{"nodeId": n, "phase": phase, "outcome": "failed" if n in fail and phase == "call" else "passed", "wasXfail": None}
            for n in nodes for phase in ("setup", "call", "teardown")]


class PrivateControls(unittest.TestCase):
    def test_failed_node_submission_does_not_close_claimed_task(self):
        with tempfile.TemporaryDirectory(dir=ROOT) as tmp:
            path=Path(tmp)/'h2h.sqlite'
            with closing(sqlite3.connect(path)) as db:
                db.executescript("create table task(id text,state text);create table agent_bot_msg(instance text,kind text,body text);")
                db.execute('insert into task values (?,?)',('owned-task','claimed'))
                db.execute('insert into agent_bot_msg values (?,?,?)',('owned-task#1','tool','{"name":"submit"}'))
                db.commit()
            bridge=stand.Bridge.__new__(stand.Bridge);bridge.db=path;bridge.task_id='owned-task'
            self.assertFalse(bridge.final())
            with closing(sqlite3.connect(path)) as db:db.execute("update task set state='done'");db.commit()
            self.assertTrue(bridge.final())

    def test_grade_cache_rejects_another_arm_and_revision(self):
        b=stand.Bridge.__new__(stand.Bridge);b.place='skb:run/skillsbench/U/0/a';b.counter=1;b.captures=[]
        b.solver=type('S',(),{'dp':{'sha256':'a'*64},'nonce':'b'*32})();b.lock=threading.RLock()
        body={'place':b.place,'said':'same'};key=b.cache_key(body)
        with self.assertRaises(task.TaskFault):b.cache_key({**body,'place':'skb:run/skillsbench/F/0/a'})
        b.counter=2;self.assertNotEqual(key,b.cache_key(body))
        key=b.cache_key(body);b.captures=[{'capturePin':{'sha256':'c'*64}}];self.assertNotEqual(key,b.cache_key(body))

    def test_deadline_crossed_during_request_copy_never_dispatches_exec(self):
        with tempfile.TemporaryDirectory(dir=ROOT) as tmp:
            s=solver_module.Solver.__new__(solver_module.Solver);s.running=True;s.expired=False;s.deadline=int(time.time()*1000)+10000
            s.box=Path(tmp);s.root=ROOT;s.nonce='a'*32;s.cid='b'*64;s.tool_no=0;s.inspect=lambda *a:None;commands=[]
            def command(*args,**kwargs):commands.append(args);s.deadline=int(time.time()*1000)-1;return {},b'',b''
            s.command=command
            with self.assertRaises(task.TaskFault) as e:s.call_locked('write',{'file_path':'/tmp/x','content':'x'})
            self.assertEqual(e.exception.kind,'solver_deadline');self.assertEqual([x[0] for x in commands],['cp'])

    def test_namespace_before_after_probes_keep_distinct_raw_pins(self):
        descriptor=task.descriptor('citation-check')
        runtime={'protocol':'skillsbench-sealed-private-runtime-v1','imageId':'sha256:'+'0'*64,'runnerSourcePin':descriptor['runnerSourcePin'],
                 'trustedManifestSha256':descriptor['trustedManifestSha256'],'pythonPath':'/opt/objrun-verifier/bin/python','pythonSha256':'1'*64,'pythonVersion':'3.12.3'}
        plan=ram.plan(descriptor,runtime,'b'*32)
        measured={'protocol':ram.PROTOCOL+'-native-mount-probe','nonce':plan['nonce'],'imageId':plan['imageId'],
            'pythonPath':plan['trustedPythonPath'],'pythonVersion':plan['trustedPythonVersion'],'pythonSha256':plan['trustedPythonSha256'],
            'rootReadonlyWriteRejected':True,'capacityProbeExecuted':False,'devTmpfsBytes':64*1024**2,'shmTmpfsBytes':ram.SHM,
            'paths':[{'path':p,'filesystem':'tmpfs','fsid':'1','device':'1','blockSize':4096,'totalBlocks':ram.RAM//4096} for p in ram.MOUNTS]}
        with tempfile.TemporaryDirectory(dir=ROOT) as tmp:
            executor=ram_executor.Executor.__new__(ram_executor.Executor);executor.plan=plan;executor.box=Path(tmp);executor.root=ROOT
            executor.identities={'grader':{'containerID':'a'*64},'seeder':{'containerID':'b'*64}}
            def command(*args,**kwargs):
                value=measured if args[1]=='a'*64 else {'devBytes':64*1024**2,'shmBytes':ram.SHM}
                return {},task.canonical(value),b''
            executor.command=command
            before=executor.probe(False,'before');after=executor.probe(False,'after')
            self.assertNotEqual(before['path'],after['path']);self.assertEqual(before['sha256'],after['sha256'])
            self.assertTrue(Path(before['path']).is_file());self.assertTrue(Path(after['path']).is_file())

    def test_private_log_tar_rejects_unknown_links_and_duplicate_results(self):
        def archive(names):
            out=io.BytesIO()
            with tarfile.open(fileobj=out,mode='w') as tar:
                for name,kind in names:
                    item=tarfile.TarInfo(name);item.size=2
                    if kind=='link':item.type=tarfile.SYMTYPE;item.linkname='/root/output';item.size=0;tar.addfile(item)
                    else:tar.addfile(item,io.BytesIO(b'{}'))
            return out.getvalue()
        self.assertEqual(ram_executor.logs_from_tar(archive([('private-result.json','file')]))['private-result.json'],b'{}')
        for rows in [[('../private-result.json','file')],[('private-result.json','link')],[('private-result.json','file')]*2,[('unexpected.py','file')]]:
            with self.assertRaises(task.TaskFault):ram_executor.logs_from_tar(archive(rows))

    def test_omitted_candidate_requires_actual_path_absence(self):
        with tempfile.TemporaryDirectory(dir=ROOT) as tmp:
            output = Path(tmp) / "output.json"
            with patch.dict(evaluator.TASK_OUTPUTS, {"citation-check": str(output)}):
                evaluator.verify_candidate_absence("citation-check", set())
                output.write_bytes(b"stale")
                with self.assertRaises(evaluator.EvaluationFault): evaluator.verify_candidate_absence("citation-check", set())
                output.unlink(); output.mkdir()
                with self.assertRaises(evaluator.EvaluationFault): evaluator.verify_candidate_absence("citation-check", set())
                output.rmdir()
                # lexists must also reject a dangling link; exists would miss it.
                with patch.object(evaluator.os.path, "lexists", return_value=True):
                    with self.assertRaises(evaluator.EvaluationFault): evaluator.verify_candidate_absence("citation-check", set())

    def test_task_specific_ram_argv_and_generated_probe_syntax(self):
        for tid in task.TASK_IDS:
            descriptor = task.descriptor(tid)
            runtime = {"protocol":"skillsbench-sealed-private-runtime-v1", "imageId":"sha256:"+"0"*64,
                       "runnerSourcePin":descriptor["runnerSourcePin"], "trustedManifestSha256":descriptor["trustedManifestSha256"],
                       "pythonPath":"/opt/objrun-verifier/bin/python", "pythonVersion":"3.12.3", "pythonSha256":"1"*64}
            value = ram.plan(descriptor, runtime, "a"*32)
            self.assertEqual(value["privateCPUs"], descriptor["originalResources"]["environment"]["cpus"])
            self.assertEqual(value["privateMemoryBytes"], descriptor["originalResources"]["environment"]["memory_mb"]*1024**2)
            self.assertEqual(value["originalVerifierSeconds"], descriptor["originalResources"]["verifier"]["timeout_sec"])
            self.assertFalse(value["actualReady"])
            ast.parse(ram.mount_probe_code(value, True)); ast.parse(ram.mount_probe_code(value, False))

    def test_syntax_and_inert_imports(self):
        names = ["skb_artifact_task_v2.py", "skb_artifact_storage_v2.py", "skb_artifact_capture_v2.py", "skb_artifact_transport_v2.py", "skb_artifact_private_eval_v2.py"]
        for name in names: ast.parse((SCRIPTS / name).read_bytes(), filename=name)

    def test_lab_fractional_reward_and_binary_rule(self):
        lab = job(); nodes = lab["expectedNodeIds"]
        result = evaluator.score_result(lab, nodes, events(nodes, [nodes[1]]), 1, [])
        self.assertTrue(result["valid"]); self.assertFalse(result["pass"]); self.assertEqual(result["officialReward"], .5)
        binary = job("citation-check", nodes)
        result = evaluator.score_result(binary, nodes, events(nodes, [nodes[1]]), 1, [])
        self.assertTrue(result["valid"]); self.assertEqual(result["officialReward"], 0)

    def test_rounded_official_one_does_not_turn_failure_into_allpass(self):
        nodes = ["test_outputs.py::test_" + str(i) for i in range(2001)]
        result = evaluator.score_result(job(nodes=nodes), nodes, events(nodes, [nodes[-1]]), 1, [])
        self.assertEqual(result["officialReward"], 1.0); self.assertTrue(result["valid"])
        self.assertFalse(result["allTestsPassed"]); self.assertFalse(result["pass"])

    def test_absent_output_setup_error_is_retained_with_official_zero(self):
        value = job("offer-letter-generator"); nodes = value["expectedNodeIds"]
        raw = [{"nodeId": n, "phase": p, "outcome": "failed" if p == "setup" else "passed", "wasXfail": None}
               for n in nodes for p in ("setup", "teardown")]
        result = evaluator.score_result(value, nodes, raw, 1, [])
        self.assertEqual(result["officialReward"], 0); self.assertFalse(result["valid"])
        self.assertIn("skip_error_or_missing_phase", result["validationIssues"])

    def test_xpass_skip_missing_extra_and_duplicate_events_never_validate(self):
        value = job(); nodes = value["expectedNodeIds"]
        for kind in ("xpass", "skip", "missing", "extra", "duplicate", "collector_skip"):
            observed = nodes[:]; raw = events(nodes); errors = []
            if kind == "xpass": raw[1]["wasXfail"] = "original mark"
            if kind == "skip": raw[1]["outcome"] = "skipped"
            if kind == "missing": observed.pop()
            if kind == "extra": observed.append("test_outputs.py::unexpected")
            if kind == "duplicate": raw.append(copy.deepcopy(raw[0]))
            if kind == "collector_skip": errors.append({"nodeId": "module", "outcome": "skipped"})
            with self.subTest(kind=kind):
                result = evaluator.score_result(value, observed, raw, 0, errors)
                self.assertFalse(result["valid"]); self.assertFalse(result["pass"])
                self.assertTrue(result["validationIssues"])

    def test_original_verifier_cannot_be_replaced_with_self_consistent_hash(self):
        value = job(); manifest = task.trusted_input_manifest()
        self.assertEqual(evaluator.validate_trusted_manifest(value, manifest), value["inputs"])
        altered = copy.deepcopy(value); altered["inputs"][0]["sha256"] = "0"*64
        with self.assertRaises(evaluator.EvaluationFault): evaluator.validate_trusted_manifest(altered, manifest)
        altered = copy.deepcopy(manifest); altered["tasks"][0]["inputs"][0]["sha256"] = "0"*64
        with self.assertRaises(evaluator.EvaluationFault): evaluator.validate_trusted_manifest(value, altered)

    def test_capture_tar_scope_and_exact_missing_error(self):
        body = b"untrusted ordinary data"
        out = io.BytesIO()
        with tarfile.open(fileobj=out, mode="w") as archive:
            info = tarfile.TarInfo("answer.json"); info.size = len(body); archive.addfile(info, io.BytesIO(body))
        result, actual = capture.parse_artifact_tar(out.getvalue(), "answer.json", 1024)
        self.assertEqual(result["state"], "regular"); self.assertEqual(actual, body)
        with self.assertRaises(task.TaskFault): capture.parse_artifact_tar(out.getvalue(), "other.json", 1024)
        cid = "a"*64; path = "/root/answer.json"
        error = ("Error response from daemon: Could not find the file " + path + " in container " + cid + "\n").encode()
        self.assertTrue(capture.missing_artifact(1, b"", error, path, cid))
        self.assertFalse(capture.missing_artifact(0, b"", error, path, cid))
        self.assertFalse(capture.missing_artifact(1, b"", error, path, "b"*64))
        self.assertFalse(capture.missing_artifact(1, b"", error+b"unknown failure\n", path, cid))


if __name__ == "__main__":
    unittest.main(verbosity=2)
