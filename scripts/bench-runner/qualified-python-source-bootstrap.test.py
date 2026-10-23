import hashlib,json,os,subprocess,tempfile,unittest
from pathlib import Path
BOOT=Path(__file__).with_name('qualified-python-source-bootstrap.py').resolve()
def pin(p):
 b=p.read_bytes();return dict(path=str(p),bytes=len(b),sha256=hashlib.sha256(b).hexdigest())
class Tests(unittest.TestCase):
 def test_pinned_graph_and_guards_before_original_command(self):
  with tempfile.TemporaryDirectory() as t:
   d=Path(t);g=d/'guard.py';g.write_text("def require_activation():return {'dockerHost':'http://127.0.0.1:18750'}\ndef require_lease(*a):assert a==(8,16,'terminal-bench',1)\ndef before_forward_guard():pass\n")
   native=d/'owned.py';native.write_text("class OwnedDocker:\n def command(self):return 'original-command'\n")
   main=d/'entry.py';main.write_text("import owned\nassert owned.OwnedDocker().command()=='original-command'\nprint('original-entry-executed')\n")
   c=dict(protocol='bench-qualified-python-source-mapping-v1',originalStandPin=pin(main),guardPin=pin(g),resource=dict(memoryMb=8,growthBytes=16,bench='terminal-bench'),modules=[dict(name='owned',pin=pin(native),guardOwnedCommand=True)])
   cp=d/'config.json';cp.write_text(json.dumps(c));env=dict(os.environ,DOCKER_HOST='http://127.0.0.1:18750');cmd=[os.sys.executable,'-B',str(BOOT),'--config',str(cp),'--original-script',str(main),'--']
   r=subprocess.run(cmd,env=env,capture_output=True,text=True);self.assertEqual(r.returncode,0,r.stderr);self.assertIn('original-entry-executed',r.stdout)
   r=subprocess.run(cmd,env=dict(env,DOCKER_HOST='wrong'),capture_output=True,text=True);self.assertNotEqual(r.returncode,0);self.assertNotIn('original-entry-executed',r.stdout)
   native.write_text('modified');r=subprocess.run(cmd,env=env,capture_output=True,text=True);self.assertNotEqual(r.returncode,0);self.assertIn('python_mapping_pin_changed',r.stderr)
if __name__=='__main__':unittest.main()
