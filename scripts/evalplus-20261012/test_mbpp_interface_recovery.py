import importlib.util,json,tempfile,unittest
from pathlib import Path
spec=importlib.util.spec_from_file_location('mbpp_recovery',Path(__file__).with_name('prepare-mbpp-interface-recovery.py'))
module=importlib.util.module_from_spec(spec);spec.loader.exec_module(module)

class RecoveryTests(unittest.TestCase):
 def setUp(self):
  self.tmp=tempfile.TemporaryDirectory();self.addCleanup(self.tmp.cleanup);self.out=Path(self.tmp.name)
  self.scope={'fullTaskIds':['Mbpp/1','Mbpp/2'],'taskIds':['Mbpp/1']}
  self.result=self.out/'results/objrun/Mbpp-1.json'
  module.save(self.result,{'officialId':'Mbpp/1','interfaceFailure':True,'grade':{'valid':False}})
  module.save(self.out/'results/objrun/Mbpp-2.json',{'officialId':'Mbpp/2','grade':{'valid':True,'passed':False}})
  self.group=self.out/'calls/objrun/Mbpp-1/schema-v3/hash/attempt-0'
  module.save(self.group/'dispatch.json',{'pid':123})
  module.save(self.group/'receipt.json',{'httpStatus':0,'fault':'The socket connection was closed unexpectedly','unknownCost':True,'actualCostUsd':None})
 def plan(self):return module.make_plan(self.out,self.scope,[])
 def test_only_invalid_interface_tasks_and_all_cost_evidence_retained(self):
  valid=self.out/'results/objrun/Mbpp-2.json';before=valid.read_bytes()
  plan=self.plan();self.assertEqual(plan['guards'],[]);self.assertEqual(len(plan['targets']),1)
  result=module.apply_plan(self.out,plan);self.assertEqual(result['state'],'ready')
  self.assertEqual(valid.read_bytes(),before);self.assertTrue(self.result.exists())
  receipts=list((self.out/'calls').rglob('receipt.json'));self.assertEqual(len(receipts),1)
  self.assertTrue(module.read(receipts[0])['unknownCost']);self.assertIsNone(module.read(receipts[0])['actualCostUsd'])
 def test_successful_cached_group_is_not_moved(self):
  success=self.group.parent.parent/'successful/attempt-0'
  module.save(success/'receipt.json',{'httpStatus':200,'fault':None,'actualCostUsd':0.1})
  module.save(success/'response.json',{'id':'saved-provider-response'})
  module.apply_plan(self.out,self.plan());self.assertTrue((success/'response.json').exists())
 def test_live_owner_or_unreconciled_dispatch_blocks_preparation(self):
  plan=module.make_plan(self.out,self.scope,[{'ProcessId':123}]);self.assertIn('OwnedRunnerOrEngineStillLive',plan['guards'])
  (self.group/'receipt.json').unlink();self.assertTrue(self.plan()['guards'])
  with self.assertRaisesRegex(RuntimeError,'RecoveryNotSafe'):module.apply_plan(self.out,self.plan())
 def test_exited_interrupted_dispatch_requires_explicit_new_scope_and_stays_unknown(self):
  (self.group/'receipt.json').unlink()
  module.save(self.group/'dispatch-disposition.json',{'state':'interrupted_no_response','ownerExited':True,'unknownCost':True,'retryForbidden':True,'upperBoundUsd':0.03})
  plan=self.plan();self.assertEqual(plan['guards'],[]);self.assertEqual(len(plan['targets']),1)
  module.apply_plan(self.out,plan)
  evidence=list((self.out/'calls').rglob('dispatch-disposition.json'));self.assertEqual(len(evidence),1)
  self.assertEqual(module.read(evidence[0])['upperBoundUsd'],0.03);self.assertTrue(module.read(evidence[0])['retryForbidden'])
 def test_recovered_solving_failure_is_never_generated_again(self):
  module.save(self.result,{'officialId':'Mbpp/1','grade':{'valid':True,'passed':False}})
  self.assertEqual(self.plan()['targets'],[])
 def test_a_completed_successful_retry_is_not_invalidated(self):
  module.save(self.group/'authorized-interface-retry-1/receipt.json',{'httpStatus':200,'fault':None,'actualCostUsd':0.01})
  plan=self.plan();self.assertEqual(plan['targets'],[]);self.assertEqual(len(plan['blockedTasks']),1)
 def test_paths_cannot_escape_result_root(self):
  with self.assertRaisesRegex(RuntimeError,'RecoveryPathOutsideResultRoot'):module.within(self.out.parent,self.out)

if __name__=='__main__':unittest.main()
