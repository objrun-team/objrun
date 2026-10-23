"""Pinned original guard, with actual Bun stdout/stderr/FILETIME preserved; decision unchanged."""
import hashlib,importlib.util,pathlib
_base=pathlib.Path(__file__).with_name('adopted_owner_guard_shared_read.py')
_raw=_base.read_bytes()
assert hashlib.sha256(_raw).hexdigest()=='88bbf763cd9797ca136fa8c8c565eb77eb7eccbf906037b5efd064c016764ba1'
_root=pathlib.Path(__file__).resolve().parents[5]
_capture=_root/'scripts/bench-runner/adopted_guard_capture.py'
assert hashlib.sha256(_capture.read_bytes()).hexdigest()=='75b443006df895da509de4cc9fde94c695ef49b2d93bd9f999e88eb7abcdd514'
_spec=importlib.util.spec_from_file_location('_bench_adopted_guard_capture',_capture)
_bench_guard_bridge=importlib.util.module_from_spec(_spec);_spec.loader.exec_module(_bench_guard_bridge)
_anchor=" child=subprocess.run([str(BUN),'--smol',str(BRIDGE),str(ACTIVATION)],cwd=ROOT,stdin=subprocess.DEVNULL,stdout=subprocess.PIPE,stderr=subprocess.PIPE,timeout=15,creationflags=subprocess.CREATE_NO_WINDOW)"
_code=_raw.decode('utf8');assert _code.count(_anchor)==1
_code=_code.replace(_anchor,_anchor.replace('subprocess.run(','_bench_guard_bridge.run_guard_bridge(',1))
exec(compile(_code,str(_base),'exec'),globals())
