"""Actual fixed-source solver/private builds with bounded native and owned probes."""
from __future__ import annotations
import argparse
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import re
import shutil
import uuid
import skb_artifact_task_v2 as task
import skb_artifact_storage_v2 as storage
import skb_artifact_transport_v2 as transport
import skb_artifact_build_storage_v1 as build_storage

ROOT = Path(__file__).resolve().parents[2]
PLAN = ROOT / "docs/repair-2026-10-08/skillsbench-ten-artifact-readonly-preflight/selection-v1/private-depot-and-adapter-plan.json"
PLAN_SHA = "6d32f483019f71eac076d7d1fb3c789c2ef23f4e7692a16eb0ebda9af35000a2"
JPG = "sha256:92892771245d31d0b1af4a0c603effbdaf02bf62c1c055081f44a462f5261ced"


def save(path, raw, boundary):
    storage.ordinary(path.parent, boundary)
    with path.open("xb") as f:
        task.demand(f.write(raw) == len(raw), "build_write", "Build evidence short write")
        f.flush(); os.fsync(f.fileno())
    task.demand(path.read_bytes() == raw, "build_readback", "Build evidence fsync/readback differs")
    return task.pin(path)


def save_json(path, value, boundary): return save(path, task.canonical(value), boundary)


def missing_container(row, out, err, target):
    if row.get("exitCode") != 1 or len(out) > 64 or len(err) > 2048: return False
    try:
        if out.strip() and json.loads(out) != []: return False
        lines = err.decode("utf-8", errors="strict").splitlines()
    except (ValueError, UnicodeError): return False
    if len(lines) != 1: return False
    return any(re.fullmatch("(?i:" + re.escape(prefix) + ")" + re.escape(target), lines[0].strip()) is not None
               for prefix in ("Error response from daemon: No such container: ", "Error: No such object: ", "No such container: ", "No such object: "))


def installed_probe_code(private):
    """This is trusted producer code; it never consumes a candidate artifact."""
    return r'''import hashlib,importlib.metadata,json,os,pathlib,re,subprocess,sys
pkgs={d.metadata['Name']:d.version for d in importlib.metadata.distributions()}
dpkg=subprocess.run(['/usr/bin/dpkg-query','-W','-f=${Package}\t${Version}\n'],capture_output=True,text=True,check=True).stdout
result={'pythonPath':sys.executable,'pythonVersion':sys.version.split()[0],'pythonRealPath':str(pathlib.Path(sys.executable).resolve()),'pythonSha256':hashlib.sha256(pathlib.Path(sys.executable).read_bytes()).hexdigest(),'installedPackages':pkgs,'dpkgPackages':dpkg}
private=''' + repr(private) + r'''
if private:
 import numpy,pandas,openpyxl,pypdf,docx,lxml.etree,defusedxml,rapidfuzz,pytest
 result['numericAbiProbe']={'numpy':numpy.__version__,'pandas':pandas.__version__,'arraySum':int(numpy.arange(3).sum()),'frameSum':int(pandas.DataFrame({'a':[1,2]}).a.sum())}
 roots=[p for p in sys.path if p.endswith('/site-packages')]
 files=[]
 for root in roots:
  for p in sorted(pathlib.Path(root).rglob('*')):
   if p.is_file():files.append({'path':str(p),'bytes':p.stat().st_size,'sha256':hashlib.sha256(p.read_bytes()).hexdigest()})
 result['installedRuntimeFiles']=files
 result['runnerSha256']=hashlib.sha256(pathlib.Path('/opt/objrun/private_eval.py').read_bytes()).hexdigest()
 result['trustedManifestSha256']=hashlib.sha256(pathlib.Path('/opt/objrun/trusted-inputs.json').read_bytes()).hexdigest()
 exe='/usr/bin/pdftotext'
 version=subprocess.run([exe,'-v'],capture_output=True,text=True,check=True)
 ldd=subprocess.run(['/usr/bin/ldd',exe],capture_output=True,text=True,check=True).stdout
 paths=sorted(set(re.findall(r'(?<!\S)(/[^\s()]+)',ldd)))
 libraries=[]
 for path in paths:
  p=pathlib.Path(path).resolve();libraries.append({'path':path,'realPath':str(p),'bytes':p.stat().st_size,'sha256':hashlib.sha256(p.read_bytes()).hexdigest()})
 result['pdftotext']={'path':exe,'sha256':hashlib.sha256(pathlib.Path(exe).read_bytes()).hexdigest(),'version':(version.stdout+version.stderr).strip(),'lddRaw':ldd,'libraries':libraries}
print(json.dumps(result,sort_keys=True,separators=(',',':')))
'''


class Builder:
    def __init__(self, prepared, prepared_pin, initial_pin):
        self.prepared, self.prepared_pin, self.initial_pin = prepared, prepared_pin, initial_pin
        self.layout = task.read_json(prepared["storageDescriptorPin"]); storage.validate_descriptor(self.layout)
        self.root = Path(self.layout["storePhysical"])
        initial = task.read_json(initial_pin)
        task.demand(initial.get("protocol") == "skb-ten-D-store-initialization-v2" and initial.get("storageDescriptorPin") == prepared["storageDescriptorPin"]
                    and initial.get("preparationPin") == prepared_pin and initial.get("setupNativeHandleClosed") is True,
                    "build_initial_store", "Actual exact fresh initialized store required")
        storage.native_actor_absent(initial["creatorPid"])
        free = {x: shutil.disk_usage(x + ":/").free for x in ("C", "D", "F")}
        task.demand(storage.assess_resources(self.layout, free, False)["admitted"] and free["F"] >= 12*1024**3,
                    "build_initial_resources", "Actual resource reserve must pass before new build evidence writes")
        self.box = Path(self.layout["directories"]["taskmeta"]) / ("environment-builds-" + uuid.uuid4().hex)
        self.box.mkdir(exist_ok=False); storage.ordinary(self.box, self.root)
        self.env = transport.sanitized_environment(self.layout, storage)
        self.env['DOCKER_HOST'] = transport.DOCKER_HOST
        # Docker's plugin discovery otherwise falls back to legacy build after
        # APPDATA/HOME/DOCKER_CONFIG are moved to the owned D namespace.
        config_path = Path(self.env['DOCKER_CONFIG']) / 'config.json'
        config = {'cliPluginsExtraDirs': ['D:/Program/resources/cli-plugins']}
        task.demand(not config_path.exists(), 'build_fresh_docker_config', 'Do not overwrite a prior Docker client configuration')
        self.plugin_config_pin = save_json(config_path, config, self.root)
        self.buildx_pin = task.pin('D:/Program/resources/cli-plugins/docker-buildx.exe')
        self.ca_pin = task.pin('D:/ProgramData/anaconda3/Lib/site-packages/certifi/cacert.pem')
        task.demand(self.ca_pin['sha256']=='c55b21f907f7f86d48add093552fb5651749ff5f860508ccbb423d6c1fbd80c7', 'build_ca', 'Actual reviewed certificate bundle changed')
        self.before = [task.pin(__file__), task.pin(task.__file__), task.pin(storage.__file__), task.pin(transport.__file__), task.pin(build_storage.__file__)] + transport.component_pins()
        self.client_pin = task.pin(transport.DOCKER)
        task.demand(self.client_pin["sha256"] == transport.DOCKER_SHA, "build_client", "Actual fixed Docker client differs")
        self.plan_pin = task.pin(PLAN); task.demand(self.plan_pin["sha256"] == PLAN_SHA, "build_plan", "Frozen nine FROM recipes changed")
        self.plan = task.read_json(self.plan_pin)
        self.snapshots = []; source_box = self.box / "executed-source"; source_box.mkdir()
        for source in self.before:
            snapshot = save(source_box / Path(source["path"]).name, Path(source["path"]).read_bytes(), self.root)
            task.demand(snapshot["sha256"] == source["sha256"], "build_source", "Executed source snapshot differs")
            self.snapshots.append({"originalPin": source, "snapshotPin": snapshot})
        self.results = []; self.failed = None; self.serial = 0; self.command_box = None; self.records = []

    def stable(self):
        for source in self.before: task.verify_pin(source)
        task.verify_pin(self.plugin_config_pin); task.verify_pin(self.buildx_pin, 128*1024**2)
        task.verify_pin(self.ca_pin)
        task.verify_pin(self.client_pin, 64*1024**2); task.verify_pin(self.prepared_pin); task.verify_pin(self.plan_pin)

    def guard(self, amount=0, closing=False):
        observation = build_storage.observe(self.layout)
        task.demand(observation["allocatedEnvelopeBytes"] + amount <= storage.STORE_CAP - (0 if closing else 2*1024**2),
                    "build_store_cap", "Build/capture producer cannot preserve D envelope")
        free = {x: shutil.disk_usage(x + ":/").free for x in ("C", "D", "F")}
        task.demand(free["D"] >= storage.D_MIN + amount, "build_D_floor", "Next build evidence consumes D physical reserve")
        if not closing:
            resources = storage.assess_resources(self.layout, free, False)
            task.demand(resources["admitted"], "build_resource_gate", "Actual C/D/F build resource gate rejected")
            task.demand(free["F"] >= 12*1024**3 + amount, "build_F_floor", "Conservative image/workspace F reserve missing")

    def command(self, *args, checked=True, timeout=30, cap=2*1024**2, closing=False):
        self.serial += 1
        task.demand(self.serial <= 32, "build_command_cap", "One environment exceeds32 bounded commands")
        if not closing: self.stable()
        # Running the installed Buildx binary directly gives the bounded native
        # primitive the actual build producer PID, without plugin discovery.
        if args[:2] == ('buildx', 'version'):
            argv = [self.buildx_pin['path'], 'version']
        elif args[0] == 'build':
            argv = [self.buildx_pin['path'], *args]
        else:
            argv = [str(transport.DOCKER), "--host", transport.DOCKER_HOST, *args]
        row, out, err = transport.bounded_child(argv, self.env, self.command_box, self.serial,
            lambda n: self.guard(n, closing), timeout, cap)
        pin = task.pin(self.command_box / ("command-%03d.json" % self.serial))
        transport.validate_command_record(pin, os.getpid(), self.serial, argv, self.command_box, cap)
        self.records.append({"recordPin": pin, "argv": argv, "exitCode": row["exitCode"]})
        if checked: task.demand(row["exitCode"] == 0, "build_docker_command", "Actual Docker build/probe failed; bounded raw outputs retained")
        if not closing: self.stable()
        return row, out, err

    def inspect_image(self, image):
        row, raw, err = self.command("image", "inspect", image)
        array = json.loads(raw)
        task.demand(isinstance(array, list) and len(array) == 1 and array[0].get("Id") == image
                    and array[0].get("Os") == "linux" and array[0].get("Architecture") == "amd64",
                    "build_image", "Actual immutable Linux amd64 image identity differs")
        return task.pin(self.command_box / ("command-%03d.stdout.bin" % self.serial)), array[0]

    def probe(self, image, python_path, private):
        nonce = uuid.uuid4().hex; name = "objrun-skb-build-probe-" + nonce
        lease = storage.InstanceLease(self.layout, nonce, self.command_box)
        cid = None; created = False; closed = False; fault = None; packages = None; inspect_pin = None
        lease.acquire()
        try:
            row, out, err = self.command("container", "inspect", name, checked=False)
            task.demand(missing_container(row, out, err, name), "build_probe_fresh", "Probe name absence is ambiguous")
            intent = save_json(self.command_box / "probe-create-intent.json", {"name": name, "nonce": nonce, "imageId": image,
                "actorPid": os.getpid(), "sourcePins": self.before, "role": "trusted-build-probe"}, self.root)
            created = True
            _, out, _ = self.command("create", "--pull", "never", "--name", name, "--label", "objrun.skb.build-probe-nonce=" + nonce,
                "--label", "objrun.skb.role=trusted-build-probe", "--read-only", "--network", "none", "--memory", "1073741824",
                "--memory-swap", "1073741824", "--cpus", "1", "--shm-size", "8388608", "--cap-drop", "ALL",
                "--security-opt", "no-new-privileges", "--log-driver", "none", "--workdir", "/", "--entrypoint", python_path,
                image, "-I", "-B", "-c", installed_probe_code(private))
            cid = out.decode().strip(); task.demand(re.fullmatch("[0-9a-f]{64}", cid), "build_probe_cid", "Actual probe CID missing")
            _, raw, _ = self.command("container", "inspect", cid); actual = json.loads(raw)[0]
            self.validate_probe(actual, cid, name, nonce, image)
            inspect_pin = task.pin(self.command_box / ("command-%03d.stdout.bin" % self.serial))
            _, out, _ = self.command("start", "--attach", cid, timeout=120, cap=8*1024**2)
            packages = json.loads(out)
            package_pin = task.pin(self.command_box / ("command-%03d.stdout.bin" % self.serial))
            _, raw, _ = self.command("container", "inspect", cid); after = json.loads(raw)[0]
            self.validate_probe(after, cid, name, nonce, image)
            task.demand(after["State"]["Running"] is False and after["State"]["ExitCode"] == 0 and after["State"]["Pid"] == 0,
                        "build_probe_exit", "Trusted package/ABI probe did not actually exit0")
        except BaseException as error:
            fault = {"type": type(error).__name__, "kind": getattr(error, "kind", None)}
            raise
        finally:
            try:
                if created and not cid:
                    row, raw, err = self.command("container", "inspect", name, checked=False, closing=True)
                    if row["exitCode"] == 0:
                        actual = json.loads(raw)[0]; cid = actual["Id"]; self.validate_probe(actual, cid, name, nonce, image)
                    else: task.demand(missing_container(row, raw, err, name), "build_probe_unknown", "Unrecorded create outcome remains unknown")
                if cid:
                    _, raw, _ = self.command("container", "inspect", cid, closing=True)
                    self.validate_probe(json.loads(raw)[0], cid, name, nonce, image)
                    self.command("rm", "-f", cid, closing=True)
                    row, raw, err = self.command("container", "inspect", cid, checked=False, closing=True)
                    task.demand(missing_container(row, raw, err, cid), "build_probe_close", "Exact owned probe absence not proven")
                closure = lease.release(); closed = True
                lease_row = storage.validate_instance_closure(closure, self.layout, nonce, os.getpid(), self.command_box)
            except BaseException:
                lease.retain_after_failure(); raise
            owner_pin = save_json(self.command_box / "probe-owner.json", {"protocol": "skillsbench-build-probe-owned-close-v1",
                "actorPid": os.getpid(), "name": name, "nonce": nonce, "containerID": cid, "imageId": image,
                "created": created, "ownedClosed": closed, "fault": fault, "leaseClosurePin": closure,
                "commandRecords": self.records[:], "sourceSnapshots": self.snapshots, "parentActorClosureRequired": True}, self.root)
        return package_pin, packages, owner_pin, inspect_pin

    @staticmethod
    def validate_probe(actual, cid, name, nonce, image):
        h = actual.get("HostConfig", {}); labels = actual.get("Config", {}).get("Labels") or {}
        task.demand(actual.get("Id") == cid and actual.get("Name") == "/" + name and actual.get("Image") == image
                    and labels.get("objrun.skb.build-probe-nonce") == nonce and labels.get("objrun.skb.role") == "trusted-build-probe"
                    and not h.get("Binds") and not h.get("Mounts") and not actual.get("Mounts") and h.get("ReadonlyRootfs") is True
                    and h.get("NetworkMode") == "none" and h.get("Memory") == h.get("MemorySwap") == 1073741824
                    and h.get("NanoCpus") == 10**9 and h.get("CapDrop") == ["ALL"] and not h.get("Privileged"),
                    "build_probe_owner", "Refuse a substituted/foreign probe namespace")

    def build_one(self, task_id):
        self.command_box = self.box / task_id; self.command_box.mkdir(); self.serial = 0; self.records = []
        self.command('buildx', 'version')
        self.guard(); metadata = task.metadata(task_id); original = task.original_sources(task_id)
        descriptor = task.descriptor(task_id)
        if task_id == "jpg-ocr-stat":
            image = JPG; build_recipe = {"mode": "reuse-exact-source-frozen-cached-JPG928", "newBuildExecuted": False}
        else:
            recipe = next(x for x in self.plan["solverImagePlans"] if x["taskId"] == task_id)
            task.verify_pin(recipe["originalDockerfilePin"]); task.verify_pin(recipe["derivedDockerfilePin"])
            base_pin, base = self.inspect_image(recipe["fixedBase"]["cachedImageId"])
            task.demand(recipe["fixedBase"]["derivedFrom"] in base.get("RepoDigests", []), "build_base", "Exact fixed base digest not cached")
            iid_path = self.command_box / "image-id.txt"; tag = "objrun-skb-ten-" + task_id + ":" + self.box.name[-12:]
            retry_recipe = self.apt_transport_recipe(recipe["derivedDockerfilePin"])
            self.command("build", "--pull=false", "--progress=plain", "--iidfile", str(iid_path), "--label", "objrun.skb.task-id=" + task_id,
                "--label", "objrun.skb.environment-tree=" + metadata["environmentSource"]["treeSha256"],
                "--label", "objrun.skb.build-owner-nonce=" + self.layout["ownerNonce"], "--tag", tag,
                '--build-context', 'objrun-ca='+retry_recipe['caContextPath'], "--file", retry_recipe["derivedDockerfilePin"]["path"], recipe["sourceContextRoot"], timeout=recipe["buildTimeoutSec"], cap=4*1024**2)
            image = iid_path.read_text().strip(); task.demand(re.fullmatch("sha256:[0-9a-f]{64}", image), "build_iid", "Completed build did not produce immutable image ID")
            build_recipe = {"mode": "actual-fixed-base-with-declared-apt-transport-retry", "recipe": recipe, "aptTransportVariant": retry_recipe, "baseInspectPin": base_pin,
                            "iidPin": task.pin(iid_path), "tag": tag, "newBuildExecuted": True}
        inspect_pin, image_row = self.inspect_image(image)
        python_path = "/usr/local/bin/python3" if task_id in ("earthquake-plate-calculation", "econ-detrending-correlation", "lab-unit-harmonization") else "/usr/bin/python3"
        package_pin, packages, owner_pin, probe_inspect = self.probe(image, python_path, False)
        task.demand(original == task.original_sources(task_id), "build_task_drift", "Original task source changed across actual build/probe")
        stage = {"protocol": "skillsbench-fixed-task-image-v1", "taskId": task_id, "imageId": image,
            "taskSourcePin": descriptor["taskSourcePin"], "environmentTreeIdentity": descriptor["environmentTreeIdentity"],
            "imageInspectPin": inspect_pin, "installedPackagesPin": package_pin, "buildActorClosurePin": owner_pin,
            "buildRecipe": build_recipe, "probeInspectPin": probe_inspect, "pythonVersion": packages["pythonVersion"],
            "sourceBeforeAfterEqual": True, "sourceSnapshots": self.snapshots, "commandRecords": self.records[:],
            "buildxBinaryPin": self.buildx_pin, "dockerPluginConfigPin": self.plugin_config_pin,
            "actorPid": os.getpid(), "storageDescriptorPin": self.prepared["storageDescriptorPin"], "parentActorClosureRequired": True,
            "completedAtUtc": datetime.now(timezone.utc).isoformat(), "originalEnvironmentHistoricalTagCertified": False,
            "actualColdControls": 0, "modelCalls": 0, "paidReady": False}
        output = save_json(self.command_box / "image-stage.json", stage, self.root)
        self.results.append({"taskId": task_id, "stagePin": output, "imageId": image})
        print(json.dumps({"phase": "task-environment-built-and-probed", "taskId": task_id, "imageId": image, "pythonVersion": packages["pythonVersion"]}), flush=True)

    def apt_transport_recipe(self, original_pin):
        task.verify_pin(original_pin)
        raw = Path(original_pin['path']).read_bytes()
        first, rest = raw.split(b'\n', 1)
        task.demand(first.startswith(b'FROM '), 'retry_recipe', 'Single fixed FROM recipe required')
        ca_context = self.command_box / 'ca-context'; ca_context.mkdir()
        ca_copy = save(ca_context / 'cacert.pem', Path(self.ca_pin['path']).read_bytes(), self.root)
        task.demand(ca_copy['sha256']==self.ca_pin['sha256'], 'build_ca_copy', 'Pinned bootstrap certificate copy differs')
        extra = (b'COPY --from=objrun-ca cacert.pem /etc/ssl/certs/ca-certificates.crt\n'
                 b'RUN sed -i "s@http://archive.ubuntu.com@https://archive.ubuntu.com@g;s@http://security.ubuntu.com@https://security.ubuntu.com@g;s@http://deb.debian.org@https://deb.debian.org@g" /etc/apt/sources.list.d/*.sources && printf \'Acquire::Retries "3";\\nAcquire::http::Timeout "15";\\nAcquire::https::Timeout "15";\\n\' > /etc/apt/apt.conf.d/80objrun-transport\n')
        variant = save(self.command_box / 'Dockerfile.apt-transport', first+b'\n'+extra+rest, self.root)
        return {'protocol':'skillsbench-declared-apt-transport-variant-v2','originalDockerfilePin':original_pin,
                'derivedDockerfilePin':variant,'insertedBytesSha256':hashlib.sha256(extra).hexdigest(),
                'caContextPath':str(ca_context),'caSourcePin':self.ca_pin,'caCopiedPin':ca_copy,'TLSVerificationDisabled':False,
                'difference':'Seed pinned public trust bundle, change official APT source URLs HTTP to HTTPS, retries3 and socket timeout15s; original base, package list and all original instructions remain byte-identical',
                'originalTaskSourcesChanged':False,'historicalEnvironmentClaim':False}

    def build_private(self):
        self.command_box = self.box / "private-runtime"; self.command_box.mkdir(); self.serial = 0; self.records = []
        self.command('buildx', 'version')
        for pin in self.prepared["privateContextPins"]: task.verify_pin(pin, 64*1024**2)
        iid_path = self.command_box / "image-id.txt"; tag = "objrun-skb-ten-private:" + self.box.name[-12:]
        retry_recipe = self.apt_transport_recipe(task.pin(Path(self.prepared['privateImageContext']) / 'Dockerfile'))
        self.command("build", "--pull=false", "--progress=plain", "--iidfile", str(iid_path), "--label", "objrun.skb.role=sealed-private-runtime",
            "--label", "objrun.skb.build-owner-nonce=" + self.layout["ownerNonce"], "--tag", tag, '--build-context', 'objrun-ca='+retry_recipe['caContextPath'], '--file', retry_recipe['derivedDockerfilePin']['path'], self.prepared["privateImageContext"], timeout=600, cap=4*1024**2)
        image = iid_path.read_text().strip(); task.demand(re.fullmatch("sha256:[0-9a-f]{64}", image), "private_iid", "Actual private immutable image ID missing")
        inspect_pin, image_row = self.inspect_image(image)
        package_pin, packages, owner_pin, probe_inspect = self.probe(image, "/opt/objrun-verifier/bin/python", True)
        installed = {re.sub(r"[-_.]+", "-", k).lower(): v for k, v in packages["installedPackages"].items()}
        task.demand(all(installed.get(re.sub(r"[-_.]+", "-", k).lower()) == v for k, v in task.REQUIREMENTS.items())
                    and all(installed.get(x["name"]) == x["version"] for x in self.prepared["resolvedLockedPackages"])
                    and packages["pythonVersion"] == "3.12.3" and packages["runnerSha256"] == self.prepared["privateRunnerPin"]["sha256"]
                    and packages["trustedManifestSha256"] == self.prepared["trustedManifestSha256"]
                    and packages["numericAbiProbe"]["arraySum"] == packages["numericAbiProbe"]["frameSum"] == 3,
                    "private_runtime_probe", "Actual sealed Python/direct/transitive/runner/manifest/NumPy-Pandas ABI differs")
        binary = packages["pdftotext"]
        elf_pin = save_json(self.command_box / "pdftotext-elf-dependencies.json", {"executable": binary["path"], "lddRaw": binary["lddRaw"], "libraries": binary["libraries"]}, self.root)
        stage = {"protocol": "skillsbench-sealed-private-runtime-v1", "imageId": image, "runnerSourcePin": self.prepared["privateRunnerPin"],
            "aptTransportVariant": retry_recipe, "privateContextPins": self.prepared['privateContextPins'],
            "trustedManifestSha256": self.prepared["trustedManifestSha256"], "pythonPath": "/opt/objrun-verifier/bin/python",
            "pythonVersion": packages["pythonVersion"], "pythonSha256": packages["pythonSha256"], "dependencies": task.REQUIREMENTS,
            "imageInspectPin": inspect_pin, "wheelDepotManifestPin": self.prepared["wheelDepotPin"], "installedPackagesPin": package_pin,
            "buildActorClosurePin": owner_pin, "sourceSnapshots": self.snapshots, "commandRecords": self.records[:],
            "buildxBinaryPin": self.buildx_pin, "dockerPluginConfigPin": self.plugin_config_pin,
            "probeInspectPin": probe_inspect, "actorPid": os.getpid(), "parentActorClosureRequired": True,
            "pdftotext": {"path": binary["path"], "sha256": binary["sha256"], "version": binary["version"], "packageReceiptPin": package_pin, "elfDependencyManifestPin": elf_pin},
            "storageDescriptorPin": self.prepared["storageDescriptorPin"], "completedAtUtc": datetime.now(timezone.utc).isoformat(),
            "actualTestCollections": 0, "actualColdControls": 0, "modelCalls": 0, "paidReady": False}
        output = save_json(self.command_box / "private-runtime-stage.json", stage, self.root)
        self.results.append({"taskId": "private-runtime", "stagePin": output, "imageId": image})
        print(json.dumps({"phase": "private-runtime-built-and-abi-probed", "imageId": image, "pythonVersion": packages["pythonVersion"]}), flush=True)


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--preparation", required=True, type=Path); p.add_argument("--preparation-sha256", required=True)
    p.add_argument("--initial-store", required=True, type=Path); p.add_argument("--initial-store-sha256", required=True)
    p.add_argument("--only", choices=(*task.TASK_IDS, "private-runtime"))
    a = p.parse_args(); pp = task.pin(a.preparation); ip = task.pin(a.initial_store)
    task.demand(pp["sha256"] == a.preparation_sha256 and ip["sha256"] == a.initial_store_sha256, "build_cli_pin", "Explicit preparation/initial store changed")
    prepared = task.read_json(pp)
    task.demand(prepared.get("protocol") == "skillsbench-ten-prepared-runtime-v1", "build_preparation", "Wrong prospective ten-task runtime")
    builder = Builder(prepared, pp, ip)
    lease = storage.NativeStorageLease(builder.root, builder.layout["ownerNonce"]); lease.path = builder.root / "leases/build.lock"
    try:
        with lease:
            for tid in ([a.only] if a.only else task.TASK_IDS):
                if tid == "private-runtime": builder.build_private()
                else: builder.build_one(tid)
            if not a.only: builder.build_private()
    except BaseException as error:
        builder.failed = {"type": type(error).__name__, "kind": getattr(error, "kind", None)}
    value = {"protocol": "skillsbench-ten-environment-build-actual-run-v1", "actorPid": os.getpid(),
        "preparedRuntimePin": pp, "initialStorePin": ip, "storageDescriptorPin": prepared["storageDescriptorPin"],
        "sourceSnapshots": builder.snapshots, "results": builder.results, "fault": builder.failed,
        "lastCommandRecords": builder.records, "completedAtUtc": datetime.now(timezone.utc).isoformat(),
        "buildLeasePin": task.pin(lease.path) if lease.path.exists() else None,
        "actualTenSolverImagesAvailableAndProbed": len([r for r in builder.results if r["taskId"] != "private-runtime"]) == 10,
        "newSolverImagesBuilt": len([r for r in builder.results if r["taskId"] not in ("private-runtime", "jpg-ocr-stat")]),
        "actualPrivateImageBuiltAndProbed": any(r["taskId"] == "private-runtime" for r in builder.results),
        "parentActorClosureRequired": True, "modelCalls": 0, "paidReady": False}
    result_pin = save_json(builder.box / "build-run.json", value, builder.root)
    print(json.dumps({"buildRunPin": result_pin, "completedEnvironments": len(builder.results), "fault": builder.failed, "modelCalls": 0}), flush=True)
    raise SystemExit(1 if builder.failed else 0)


if __name__ == "__main__": main()
