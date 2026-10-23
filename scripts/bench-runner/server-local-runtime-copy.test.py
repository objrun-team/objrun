import importlib.util,pathlib,tempfile,unittest,json,os
from unittest.mock import patch
S=pathlib.Path(__file__).with_name('server-local-runtime-copy.py');spec=importlib.util.spec_from_file_location('cached',S);m=importlib.util.module_from_spec(spec);spec.loader.exec_module(m)
class Tests(unittest.TestCase):
 def test_same_actor_cache_receipt(self):
  with tempfile.TemporaryDirectory() as d:
   root=pathlib.Path(d);source=root/'node';source.write_bytes(b'node');helper=root/'server.py';helper.write_text('import json,base64\n')
   labels={'objrun.tb12.owner':'owner','objrun.tb12.role':'candidate','objrun.tb12.native-source':'source'}
   class Native:
    directory=root
    calls=0
    def guard(self):self.calls+=1
    def assert_actor(self,cid):return {'Labels':labels}
   n=Native();digest=m.pin(source)['sha256'];c={'protocol':'bench-server-local-runtime-copy-contract-v1','assetName':'node','assetSha256':digest,'assetBytes':4,'destination':'/rt-node','sshAlias':'novaeve','serverHelperPin':m.pin(helper)}
   result={'protocol':'novaeve-server-local-runtime-copy-v4','complete':True,'cid':'a'*64,'destination':'/rt-node','sha256':digest,'guestSha256':digest,'bytes':4,'expectedLabels':labels,'before':{'Id':'a'*64},'after':{'Id':'a'*64},'remoteDockerUploadBytes':0}
   class Done:returncode=0;stdout=json.dumps(result).encode();stderr=b''
   with patch.dict(os.environ,{'NOVAEVE_RESOURCE_LEASE_PID':'123'}),patch.object(m.subprocess,'run',return_value=Done()) as run:
    receipt=m.copy_cached_runtime(n,source,'a'*64,'/rt-node',c);self.assertTrue(receipt['serverLocalRuntimeCache']);self.assertEqual(n.calls,2);self.assertEqual(run.call_args.kwargs['timeout'],240)
    result['guestSha256']='f'*64;Done.stdout=json.dumps(result).encode()
    with self.assertRaisesRegex(AssertionError,'runtime_cache_copy_result_mismatch'):m.copy_cached_runtime(n,source,'a'*64,'/rt-node',c)
   with patch.object(m.subprocess,'run') as run:
    with self.assertRaisesRegex(AssertionError,'runtime_cache_asset_scope'):m.copy_cached_runtime(n,source,'a'*64,'/other',c)
    self.assertFalse(run.called)
    source.write_bytes(b'evil')
    with self.assertRaisesRegex(AssertionError,'runtime_cache_asset_changed'):m.copy_cached_runtime(n,source,'a'*64,'/rt-node',c)
    self.assertFalse(run.called)
if __name__=='__main__':unittest.main()
