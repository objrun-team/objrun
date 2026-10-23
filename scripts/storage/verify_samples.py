"""Restore selected real-run evidence with file reads confined to Git records."""
import argparse,collections,json,pathlib,sys
from records import Records,contents

def main():
    ap=argparse.ArgumentParser(description=__doc__);ap.add_argument('--root',type=pathlib.Path,required=True);ap.add_argument('--selection',type=pathlib.Path,required=True);a=ap.parse_args()
    selection=json.loads(a.selection.read_text(encoding='utf-8'));root=a.root.resolve()
    def audit(event,args):
        if event=='open' and isinstance(args[0],(str,bytes)) and not pathlib.Path(args[0]).resolve().is_relative_to(root):raise PermissionError('Original archives and other files are unavailable')
    sys.addaudithook(audit);r=Records(root);targets={json.dumps([x['collection'],x['path']]):x for x in selection};entries={}
    for entry in r.entries():
        key=json.dumps([entry['collection'],entry['path']])
        if key in targets:entries[key]=entry
    report=[]
    for key,choice in targets.items():
        e=entries[key];value=e
        for member in choice.get('members',[]):value=next(x for x in value['members'] if x['path']==member)
        proof={k:v for k,v in choice.items()};proof['content_hashes']=[];proof['restored_bytes']=0
        for content in contents(value):
            raw=b''.join(r.parts(content));proof['restored_bytes']+=len(raw);proof['content_hashes'].append(content['sha256'])
        assert proof['restored_bytes']>0,'Empty evidence is not a detailed sample'
        if value['format']=='sqlite-tables':
            tables={}
            for t in value['tables']:
                if t.get('excluded'):continue
                rows=[json.loads(line) for line in b''.join(r.parts(t['content'])).splitlines()]
                assert len(rows)==t['source_rows']==t['exported_rows']
                ids=[x['rowid'] for x in rows]
                if t['order']=='rowid':assert ids==sorted(ids)
                tables[t['name']]=[dict(zip(t['columns'],x['values'])) for x in rows]
            tasks=tables.get('task',[]);contexts=tables.get('agent_bot_ctx',[]);messages=tables.get('agent_bot_msg',[])
            selected=None
            for task in tasks:
                instances={x['instance'] for x in contexts if x['task']==task['id']}
                msgs=[x for x in messages if x['instance'] in instances]
                if any(x.get('role')=='user' and x.get('body') for x in msgs) and any(x.get('role')=='assistant' and x.get('body') for x in msgs):
                    selected=(task,msgs);break
            assert selected is not None,'No real input/output pair in selected database'
            task,msgs=selected
            assert not str(task.get('id','')).startswith('synthetic-')
            proof.update(task_id=task['id'],task_state=task.get('state'),task_result_present=bool(task.get('result')),message_rows_for_task=len(msgs),roles=dict(collections.Counter(x['role'] for x in msgs)),kinds=dict(collections.Counter(x['kind'] for x in msgs)),message_order_fields=['instance','unit','seq','at'],database_table_rows={k:len(v) for k,v in tables.items()},database_wal_sha256=value.get('wal_sha256'),source_foreign_key_violations=value['foreign_key_violation_count'])
            proof['wire_http_records']='Separate HTTP envelopes are not asserted by this database sample; stored inputs, outputs, tool bodies and results are restored.'
        else:
            data=b''.join(r.parts(value['content']));parsed=json.loads(data)
            proof['json_fields']=list(parsed) if isinstance(parsed,dict) else ['array']
            if choice.get('role')=='request':assert parsed.get('messages') or parsed.get('input') or parsed.get('prompt')
            if choice.get('role')=='response':assert parsed.get('choices') or parsed.get('output') or parsed.get('error')
        proof['verified']=True;report.append(proof)
    print(json.dumps(dict(samples=report,original_archive_access_permitted=False,isolated_file_access_guard=True,sample_success_does_not_imply_all_runs_complete=True)))

if __name__=='__main__':main()
