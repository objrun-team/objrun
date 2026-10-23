"""Inactive strict qualification for one immutable-data original verifier skip.

This produces supplemental evidence only. It never rewrites a native receipt.
Production integration requires a fresh private-grader image/source boundary.
"""
import hashlib,json
TASK='energy-ac-optimal-power-flow'
NODE='::TestFeasibility::test_branch_current_limits'
NETWORK_SHA='89ad13669c77866c25526fed3a89cd2ec08b997e3eaca07c391355974a967873'
VERIFIER_SHA='6d5ec397bfc3c244e63580ca382134411a3879a4aa6c518570396b5b0097cd47'

def qualify(native,network_bytes,verifier_bytes,collection_nodes):
    assert native['taskId']==TASK
    assert not native['candidateExecutablesUsed'] and not native['candidateSnapshotUsed']
    assert native['network']=='none' and native['hostBinds'] is False
    assert hashlib.sha256(network_bytes).hexdigest()==NETWORK_SHA
    assert hashlib.sha256(verifier_bytes).hexdigest()==VERIFIER_SHA
    assert b'def test_branch_current_limits(self, report, network):' in verifier_bytes
    assert b'Network does not provide branch current limits; ' in verifier_bytes
    network=json.loads(network_bytes)
    for key,description in ((network.get('column_info') or {}).get('branch') or {}).items():
        if not isinstance(description,str):continue
        if any(token in description.lower() for token in ('current','i_max','imax')):
            try:int(key)
            except (ValueError,TypeError):continue
            raise AssertionError('original network now supplies current-limit column')
    nodes=native['nodeIds'];assert nodes==collection_nodes and len(nodes)==24 and len(set(nodes))==24 and NODE in nodes
    assert native['collectionErrors']==[] and native['pytestExitCode'] in (0,1)
    phases={node:{} for node in nodes}
    for report in native['reports']:
        assert report['nodeId'] in phases and report['phase'] not in phases[report['nodeId']]
        assert report.get('wasXfail') is None
        phases[report['nodeId']][report['phase']]=report['outcome']
    passed=failed=errored=0
    for node,reports in phases.items():
        if node==NODE:
            assert reports=={'setup':'passed','call':'skipped','teardown':'passed'}
        elif reports=={'setup':'failed','teardown':'passed'}:errored+=1
        else:
            assert set(reports)=={'setup','call','teardown'} and reports['setup']==reports['teardown']=='passed'
            assert reports['call'] in ('passed','failed')
            passed+=reports['call']=='passed';failed+=reports['call']=='failed'
    assert passed==native['passedTests'] and failed==native['failedTests'] and errored==native['errorTests']
    assert passed+failed+errored+1==len(nodes)
    assert native['validationIssues']==['incomplete_or_skipped_test']
    assert (native['pytestExitCode']==0)==(failed+errored==0)
    return {'taskId':TASK,'qualifiedOriginalImmutableDataSkipNode':NODE,'originalCollectionNodes':nodes,
            'originalNativeComplete':native['complete'],'originalNativeReward':native['reward'],
            'supplementalOfficialExitCodeReward':int(native['pytestExitCode']==0),
            'actualPassedTests':passed,'actualFailedTests':failed,'actualErrorTests':errored,
            'actualOriginalSkippedTests':1,'collectionCount':24,'nativeReceiptUnmodified':True,
            'productionIntegrated':False,'ready':False}
