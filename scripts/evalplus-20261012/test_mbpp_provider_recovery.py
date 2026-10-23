import importlib.util,tempfile,unittest
from pathlib import Path
spec=importlib.util.spec_from_file_location('provider_prepare',Path(__file__).with_name('prepare-mbpp-provider-recovery.py'))
module=importlib.util.module_from_spec(spec);spec.loader.exec_module(module)
class ProviderPreparationTests(unittest.TestCase):
 def setUp(self):
  self.tmp=tempfile.TemporaryDirectory();self.addCleanup(self.tmp.cleanup)
  self.saved=(module.OUT,module.MBPP);module.MBPP=Path(self.tmp.name);module.OUT=module.MBPP/'full'
  self.addCleanup(lambda:setattr(module,'OUT',self.saved[0]));self.addCleanup(lambda:setattr(module,'MBPP',self.saved[1]))
  old=module.old;self.result=module.OUT/'results/objrun/Mbpp-1.json'
  old.save(self.result,{'officialId':'Mbpp/1','grade':{'valid':False},'interfaceFailure':True,'error':'ProviderFault:timeout'})
  old.save(module.OUT/'results/objrun/Mbpp-2.json',{'officialId':'Mbpp/2','grade':{'valid':True,'passed':False}})
  old.save(module.MBPP/'interface-recovery-scope.json',{'fullTaskIds':['Mbpp/1','Mbpp/2'],'taskIds':['Mbpp/1']})
  previous=module.OUT/'recovery/interface-pass-0002.json'
  old.save(previous,{'state':'stopped','targets':[{'officialId':'Mbpp/1','resultSha256':old.sha(self.result)}]})
  old.save(module.OUT/'recovery/active-pass.json',{'path':str(previous)})
 def test_gracefully_stopped_prepared_task_can_resume_without_recreating_old_failed_calls(self):
  plan=module.make_plan([]);self.assertEqual(plan['guards'],[]);self.assertEqual(plan['blockedTasks'],[])
  self.assertEqual(len(plan['targets']),1);self.assertTrue(plan['targets'][0]['unattemptedBecauseOfGracefulStop'])
  self.assertEqual(plan['targets'][0]['failedRequestGroups'],[])
 def test_result_hash_change_blocks_unattempted_shortcut(self):
  module.old.save(self.result,{'officialId':'Mbpp/1','grade':{'valid':False},'interfaceFailure':True,'error':'changed'})
  self.assertEqual(len(module.make_plan([])['blockedTasks']),1)
 def test_living_process_still_blocks_preparation(self):
  self.assertIn('OwnedRunnerOrEngineStillLive',module.make_plan([{'pid':1}])['guards'])
 def test_successful_existing_solving_failure_is_excluded(self):
  module.old.save(self.result,{'officialId':'Mbpp/1','grade':{'valid':True,'passed':False}})
  self.assertEqual(module.make_plan([])['targets'],[])
if __name__=='__main__':unittest.main()
