"""Stored-only independently recompute reference/control links. No grading, network, Docker or SQLite."""
from pathlib import Path
import hashlib, json, os, re
ROOT = Path(__file__).resolve().parents[2]
DOC = ROOT / 'docs/repair-2026-10-08'
HOME = DOC / 'chemiq-34-public-name-lookup-0f0e620335c44d119b938dbb2524283f'
OUT = DOC / 'chemiq34-independent-stored-review-v1'
def sha(p):
    h = hashlib.sha256()
    with Path(p).open('rb') as f:
        for b in iter(lambda: f.read(1024 * 1024), b''): h.update(b)
    return h.hexdigest()
def pin(p):
    p = Path(p).resolve(); return dict(path=str(p), bytes=p.stat().st_size, sha256=sha(p))
inputs = {}
def read(p):
    p = Path(p); before = pin(p); value = json.loads(p.read_bytes()); assert pin(p) == before
    inputs[str(p.resolve())] = before; return value
def bound(p):
    assert pin(p['path']) == p
    inputs[str(Path(p['path']).resolve())] = p; return read(p['path'])
def write(p,j):
    raw = (json.dumps(j,ensure_ascii=False,indent=2)+'\n').encode(); p.parent.mkdir(parents=True,exist_ok=True)
    with p.open('xb') as f: f.write(raw); f.flush(); os.fsync(f.fileno())
    assert p.read_bytes() == raw; return pin(p)
book_path = ROOT / '.phase1-data/chemiq/vendor/ChemIQ/questions/chemiq.jsonl'
book_pin = pin(book_path); assert book_pin['sha256'] == '4b11ba7dbcef8f075941c2e5337d687fa94d28837fc93e87a4eed1673a99646f'
inputs[str(book_path.resolve())] = book_pin
book = [json.loads(x) for x in book_path.read_bytes().splitlines() if x]; all_ids = {'chemiq-'+q['uuid'] for q in book}; assert len(book)==len(all_ids)==816
non = read(DOC/'legacy-chemiq-616-nonopsin-controls-raw-length.json')
iupac = read(DOC/'legacy-chemiq-200-iupac-controls-raw-length.json')
assert non['adapter_sha256'] == iupac['adapter_sha256'] == '0d45cab758e9d0137dad3271618d7b37d291541144369ecc4bf892b01c916cda'
for report in [non,iupac]:
    assert report['profile']['level']==0 and report['profile']['length_policy']=='raw-input-length'
    assert report['profile']['opsin']['profile']=='local-2.8' and report['profile']['opsin']['rest_fallback'] is False
old_rows = non['records'] + iupac['records']; assert len(old_rows)==816 and {r['task'] for r in old_rows}==all_ids
old_positive = {r['task'] for r in old_rows if r['positive']['valid'] and r['positive']['nodes']=={'parsed':True,'correct':True}}
assert len(old_positive)==782 and len(all_ids-old_positive)==34
for r in non['records']:
    assert r['wrong_value']['valid'] and r['wrong_value']['nodes']=={'parsed':True,'correct':False}
    assert r['wrong_format']['valid'] and r['wrong_format']['nodes']=={'parsed':False,'correct':False}
for r in iupac['records']:
    assert r['wrong_structure']['valid'] and r['wrong_structure']['nodes']=={'parsed':True,'correct':False}
    assert r['wrong_format']['valid'] and r['wrong_format']['nodes']=={'parsed':False,'correct':False}
extension = read(HOME/'private-extension-v1/references.json'); assert len(extension['records'])==34
assert extension['privateOnlyNeverSolverVisible'] and extension['noOldReferencesOrCacheModified'] and extension['modelCalls']==0 and not extension['formalScoreCertified']
for p in extension['sourcePins']: assert pin(p['path'])==p; inputs[str(Path(p['path']).resolve())]=p
refs = {r['task']:r for r in extension['records']}; assert len(refs)==34 and set(refs)==all_ids-old_positive
origins = {'PubChem returned name':0,'assistant constructed from public SMILES; PubChem CID0 and NCI404':0}
original_checker_ids = set()
for r in refs.values():
    assert hashlib.sha256(r['reference_name'].encode()).hexdigest()==r['reference_name_sha256'] and r['reference_found']
    assert r['nameOrigin'] in origins; origins[r['nameOrigin']]+=1
    ctl=bound(r['actualOriginalCheckerControlPin']); stdout=bound(ctl['stdoutPin'])
    assert ctl['child']['exit']==0 and ctl['child']['childClosed'] and ctl['modelCalls']==0 and ctl['existingCacheModified'] is False
    assert stdout['originalSourcesUnchanged'] and stdout['oldOpsinCacheUnchanged'] and stdout['memoryOnlyCache'] and stdout['externalRequests']==stdout['modelCalls']==0
    row=next(x for x in stdout['results'] if x['taskId']==r['task'])
    assert row['referenceName']==r['reference_name'] and row['convertedSmiles']==r['convertedSmiles'] and row['lookupIndex']==r['lookupIndex']
    assert row['positive']['is_correct'] and not row['wrongStructure']['is_correct'] and not row['wrongFormat']['is_correct']
    if r['nameOrigin']=='PubChem returned name':
        response=read(HOME/f"response-{r['lookupIndex']}.json")
        assert response['PropertyTable']['Properties'][0]['IUPACName']==r['reference_name']
    original_checker_ids.add(r['task'])
assert origins=={'PubChem returned name':26,'assistant constructed from public SMILES; PubChem CID0 and NCI404':8}
recovered=read(HOME/'http-controls-v1/control-recovered.json'); result=bound(recovered['actualHTTPResultPin'])
assert result==recovered['result'] and result['httpRequests']==204 and len(result['records'])==34
assert result['sourceHashes']['/adapter/stand.py']==non['adapter_sha256'] and result['sourceHashes']['/oracle/vendor/ChemIQ/questions/chemiq.jsonl']==book_pin['sha256']
assert result['health']['items']==816 and result['health']['level']==0 and result['health']['length_policy']=='raw-input-length'
assert result['health']['opsin']['profile']=='local-2.8' and result['health']['opsin']['rest_fallback'] is False
assert result['oldCacheUnchanged'] and result['originalSourcesUnchanged'] and result['serverChildClosed'] and result['modelCalls']==result['externalRequests']==0
http_ids=set(); wire_count=0
for row in result['records']:
    assert row['task'] not in http_ids and row['task'] in refs; http_ids.add(row['task']); ref=refs[row['task']]
    assert row['referenceOrigin']==ref['nameOrigin']
    for kind,answer in [('positive',ref['reference_name']),('wrong_structure','methane'),('wrong_format','Z'*301)]:
        o=row['outcomes'][kind]; expected={'parsed':kind!='wrong_format','correct':kind=='positive'}
        assert o['valid'] and o['nodes']==expected and len(o['wire'])==2
        assert [w['node'] for w in o['wire']]==['parsed','correct']
        for w in o['wire']:
            request=json.loads(w['request']); response=json.loads(w['response'])
            assert w['status']==200 and request['input']['task']['id']==row['task'] and request['input']['result']['body']==answer
            assert type(response['value']) is bool and response['value']==expected[w['node']]; wire_count+=1
assert http_ids==original_checker_ids==set(refs) and wire_count==204 and old_positive|http_ids==all_ids and not old_positive&http_ids
for p in recovered['sourcePins']: assert pin(p['path'])==p; inputs[str(Path(p['path']).resolve())]=p
intent=read(HOME/'http-controls-v1/intent.json'); created=read(HOME/'http-controls-v1/container-created.json'); ended=read(HOME/'http-controls-v1/container-exited.json')
cid=recovered['exactContainerId']; assert created['id']==ended['id']==cid and re.fullmatch('[a-f0-9]{64}',cid)
for actor in [created,ended]:
    inspect=actor['inspect']; assert inspect['Id']==cid and inspect['Image']==intent['image'] and inspect['Name']=='/'+intent['containerName'] and inspect['Config']['Labels']['objrun.reference.nonce']==intent['nonce']
    assert inspect['HostConfig']['NetworkMode']=='none' and inspect['HostConfig']['ReadonlyRootfs'] and not inspect['HostConfig']['Privileged'] and inspect['HostConfig']['PidMode']==''
    assert all(not m['RW'] or m['Destination']=='/opsin-jobs' for m in inspect['Mounts'])
assert ended['inspect']['State']['Running'] is False and ended['inspect']['State']['ExitCode']==0
removed=bound(recovered['containerRemovalPin']); absent=bound(recovered['exactAbsencePin']); assert removed['argv'][3:]==['rm',cid] and removed['exit']==0 and removed['childClosed']
assert absent['argv'][3:]==['inspect','--format','{{json .}}',cid] and absent['exit']==1 and absent['childClosed']
for child in [removed,absent]:
    for key in ['stdoutPin','stderrPin']: p=child[key]; assert pin(p['path'])==p; inputs[str(Path(p['path']).resolve())]=p
diag=Path(absent['stderrPin']['path']).read_text().strip(); raw_out=Path(absent['stdoutPin']['path']).read_bytes()
assert raw_out.strip() in [b'',b'[]'] and re.fullmatch('(?i:Error: No such object: )'+re.escape(cid),diag)
assert diag.startswith('error: no such object: ') and diag not in ['Error: No such object: '+cid,'Error response from daemon: No such container: '+cid]
bridge=bound(recovered['recoveryIntentPin']); final=read(HOME/'http-controls-v1/opsin-jobs/status.json')
assert bridge['owner']==recovered['nativeBridgeOwner'] and bridge['pid']==final['pid']==recovered['nativeBridgeOwner']['ProcessId']==117884
assert recovered['nativeBridgeExitedObserved'] and recovered['nativeBridgeExitCode']==0 and recovered['bridgeFinalStatus']==final
assert final['stopped'] is True and final['failed']==final['external_requests']==0 and recovered['containerClosed'] and recovered['originalDriverErrorRetained']
for p in bridge['sourcePins']: assert pin(p['path'])==p; inputs[str(Path(p['path']).resolve())]=p
for name in ['root-chemiq-private-http-controls-guest.py','root-chemiq-private-http-controls-host.py','root-chemiq-http-control-owned-recovery.py']:
    p=ROOT/'.scratch'/name; inputs[str(p.resolve())]=pin(p)
union=read(HOME/'private-extension-v1/stored-coverage-audit.json')
for p in union['sourcePins']: assert pin(p['path'])==p; inputs[str(Path(p['path']).resolve())]=p
assert union['oldPositiveTaskCount']==782 and union['newOriginalCheckerPositiveTaskCount']==34 and union['unionPositiveTaskCount']==816 and union['missingControlTaskIds']==[] and union['formalScoreCertified'] is False
balance_pin=pin(DOC/'deepseek-balance-readonly-2026-10-09T07-00-01-827Z.json'); balance=bound(balance_pin)
assert balance['method']=='GET' and balance['modelCalls']==0 and balance['httpStatus']==200 and balance['isAvailable']
assert balance['balances'][0]['currency']=='CNY' and balance['balances'][0]['total_balance']=='52.81'
limits=[
 'This is a stored-only independent binding audit; no parser, checker, Java, HTTP, Docker, model or original SQLite was executed here.',
 '782 old service controls were stored without full per-request wire;34 new HTTP controls carry204 raw request/response strings. The union is control coverage, not a model score or816 HTTP cold-run certificate.',
 'The original driver failed only its case-sensitive absence predicate before bridge stop. That original failure remains; recovered stop/exit evidence is a later distinct source-bound operation.',
 'Bridge WaitForSingleObject/GetExitCodeProcess success is recorded by the pinned recovery source and recovered JSON; no separate native wait transcript/current PID absence is certified by this stored-only audit.',
 'The private extension original actualNewStandHTTPEndToEndValidated=false field predates HTTP recovery and is not overwritten. The new audit links the later HTTP result independently.',
 'Original references/cache stay unchanged.26 new names were PubChem responses;8 were Root constructions from public SMILES, after PubChem CID0/NCI404, then actual Java and original-checker validation.',
 'No full model environment/new paid-entry cold graph or economic sufficiency follows from these controls.',
]
review={'protocol':'chemiq34-independent-stored-review-v1','validated':True,'inputPins':list(inputs.values()),'sourcePin':pin(__file__),
 'bookDenominator':816,'oldStoredPositiveControls':782,'newDirectCheckerControls':34,'newOriginalStandHTTPControls':34,'rawHTTPRequestsVerified':204,
 'fullUnionKeyset':True,'overlap':0,'missing':0,'referenceOrigins':origins,'oldSourceAndCacheActualPinsUnchanged':True,'privateContainer':{'id':cid,'networkMode':'none','readonlyRootfs':True,'removedCLIExit':0,'preciseAbsenceCLIExit':1,'diagnosticCaseMismatchPreserved':True},
 'nativeBridge':{'pid':117884,'recordedExit':0,'stopped':True,'currentAbsenceQueried':False},'formalScoreCertified':False,'modelCalls':0,'gradeCalls':0,
 'currentCash':{'balancePin':balance_pin,'observedBalanceCny':'52.81','unknownCarryCny':'8.39218','operatorHeadroomCny':'30','maximumNewEnvelopeCny':'14.41782','rechargePromisedIsNotCredited':True,'freshAdmissionBalanceStillRequired':True,
 'complete16F900Guaranteed':False,'comparison':'Nonrepresentative10NMR F180 scalar900 scenario for16 is aboutCNY66.98 cached /477.21 no-cache;14.41782 cannot justify that scenario. Other strata may be cheaper, but no sufficient full16 budget is established.'},'limits':limits}
for p in inputs.values(): assert pin(p['path'])==p
report=write(OUT/'review.json',review)
md='The 34 additional original HTTP evidence records join successfully record by record: 204 actual request/response values agree with the 34 private references and 26+8 original checker comparisons. They do not duplicate the 782 existing stored positive controls, and the 816 official keyset is complete. Of these names, 26 are PubChem names and 8 were constructed by Root and then verified using actual Java and the original checker.\n\nThe original host driver lowercase-absence error has not been rewritten; the later recovered exactCID removal and native bridge117884 exit 0 are independent subsequent evidence. Actual pins for the original cache/refs and sources remain unchanged individually before and after.\n\nThis establishes stored-control coverage only, not formal scores or a cold end-to-end run through the new entry point. From the current CNY 52.81, subtracting CNY 8.39218 for earlier unknown costs and a CNY 30 buffer leaves at most CNY 14.41782 for new requests; this cannot guarantee completion of 16F900. Earlier NMR stress at the same configuration cost about CNY 66.98 cached / CNY 477.21 without caching, well above the current new envelope. Actual costs across different strata remain unknown, and a promise to top up is not treated as received funds.\n\n'+ '\n'.join('- '+x for x in limits)+'\n'
md_pin=write(OUT/'README.md',md)
print(json.dumps({'reviewPin':report,'readmePin':md_pin,'modelCalls':0,'verifiedHTTPRecords':204},ensure_ascii=False))
