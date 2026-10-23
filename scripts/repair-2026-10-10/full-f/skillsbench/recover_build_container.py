"""Remove only a stopped failed legacy build container with exact own receipts."""
import argparse
from datetime import datetime
import json
from pathlib import Path
import re
from prepare import HOME,public,save,utc
from build_environment import DOCKER,ENV
from bounded_child import run

def main():
    parser=argparse.ArgumentParser();parser.add_argument('--task',required=True);args=parser.parse_args()
    # Current known legacy failure; newer builds use --force-rm=true. A generic
    # broad container sweep would not have sufficient ownership evidence.
    if args.task!='bike-rebalance':return
    folder=HOME/'environment-preparation/bike-rebalance/6b0a9c3942f342098d4a211ba6f14dbd'
    original=folder/'command-003.json';recovery=folder/'cleanup-recovery.json'
    if not original.exists() or recovery.exists():return
    pin=public.pin(original);record=json.loads(original.read_bytes())
    for key in ('stdoutPin','stderrPin'):assert public.pin(Path(record[key]['path']))==record[key]
    output=Path(record['stdoutPin']['path']).read_text();assert record['exitCode']!=0 and '502  Bad Gateway' in output
    base=re.search(r'Step 1/\d+ : FROM (sha256:[0-9a-f]{64})',output).group(1)
    ids=re.findall(r'Running in ([0-9a-f]{12})',output);assert len(ids)==1
    def command(name,argv):
        prefix=folder/('recovery-'+name);value=run([DOCKER,*argv],ENV,prefix.with_suffix('.stdout'),prefix.with_suffix('.stderr'),30)
        receipt=save(prefix.with_suffix('.json'),{**value,'argv':[DOCKER,*argv],'stdoutPin':public.pin(prefix.with_suffix('.stdout')),'stderrPin':public.pin(prefix.with_suffix('.stderr')),'modelCalls':0},True)
        assert not value['faults']
        return value,prefix,receipt
    result,prefix,inspect_pin=command('inspect',['inspect',ids[0]])
    if result['exitCode']:
        diagnostic=prefix.with_suffix('.stderr').read_text().strip()
        assert diagnostic=='Error: No such object: '+ids[0]
        save(recovery,{'removed':False,'alreadyAbsent':True,'sourceCommandPin':pin,'inspectPin':inspect_pin,'atUtc':utc(),'modelCalls':0},True);return
    container=json.loads(prefix.with_suffix('.stdout').read_bytes())[0]
    assert container['Id'].startswith(ids[0]) and len(container['Id'])==64 and container['Image']==base
    assert not container['State']['Running'] and container['State']['ExitCode']==100
    assert container['Config']['Labels']['objrun.skb.role']=='full-f-pristine' and container['Config']['Labels']['objrun.skb.task-id']==args.task
    assert container['Config']['Cmd']==['/bin/sh','-c','apt-get update && apt-get install -y python3-venv poppler-utils && rm -rf /var/lib/apt/lists/*']
    parsed=lambda value:datetime.fromisoformat(value.replace('Z','+00:00'))
    assert parsed(record['startedAtUtc'])<=parsed(container['Created'])<=parsed(record['finishedAtUtc'])
    removed,_,remove_pin=command('remove',['rm',container['Id']]);assert removed['exitCode']==0
    save(recovery,{'removed':True,'containerId':container['Id'],'ownerReceiptMatched':True,'sourceCommandPin':pin,'inspectPin':inspect_pin,'removePin':remove_pin,'atUtc':utc(),'modelCalls':0},True)

if __name__=='__main__':main()
