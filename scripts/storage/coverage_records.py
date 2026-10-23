"""Summarize current record coverage without requiring original archives."""
import argparse,collections,csv,json,pathlib,re,hashlib
import zstandard as zstd
from records import Records
from export_records import bench_of,scope_of,encoded,COLLECTION_BENCH

def main():
    ap=argparse.ArgumentParser(description=__doc__);ap.add_argument('--root',type=pathlib.Path,required=True);ap.add_argument('--output',type=pathlib.Path);ap.add_argument('--samples',type=pathlib.Path);a=ap.parse_args();r=Records(a.root);out=a.output or r.root/'reports';out.mkdir(parents=True,exist_ok=True)
    counts=collections.defaultdict(collections.Counter);sources=collections.defaultdict(set);scopes=collections.defaultdict(set);states=collections.defaultdict(set);issues=collections.defaultdict(list);status=collections.defaultdict(collections.Counter)
    def walk(v,b,origin,path):
        if not isinstance(v,dict):return
        if v.get('disposition')=='excluded':counts[b]['excluded_member_references']+=1;return
        if v.get('format')=='unavailable-source' or v.get('pending'):
            issues[b].append(dict(collection=origin,path=path,reason=v.get('pending',v.get('reason'))));return
        if v.get('source_truncation'):
            if 'public-bundle-safety-fixtures-' in path:counts[b]['synthetic_malformed_fixture_references']+=1
            else:issues[b].append(dict(collection=origin,path=path,reason='original text/member truncated',detail=v['source_truncation']))
        if v.get('format')=='sqlite-tables':
            counts[b]['database_references']+=1
            states[b].add(tuple((t['name'],t.get('content',{}).get('sha256')) for t in v['tables']))
            for t in v['tables']:
                if t.get('excluded'):continue
                counts[b]['database_row_references']+=t['exported_rows']
                if t['name']=='agent_bot_msg':counts[b]['message_row_references']+=t['exported_rows']
                if t['name']=='task':counts[b]['task_row_references']+=t['exported_rows']
                status[b].update(t.get('observed_status_fields',{}))
        elif v.get('format')=='text':
            counts[b]['text_record_references']+=1
            if v.get('content',{}).get('bytes',0)>0:
                if re.search(r'(?:^|/)(?:provider-\d+-)?request\.json(?:\.gz)?$',path):counts[b]['request_file_references']+=1
                if re.search(r'(?:^|/)(?:provider-\d+-)?response\.json(?:\.gz)?$',path):counts[b]['response_file_references']+=1
                if re.search(r'(result|score|grade|verdict)',path,re.I):counts[b]['result_named_file_references']+=1
        for m in v.get('members',[]):walk(m,b,origin,path+'!/'+m['path'])
    for e in r.entries():
        b=e['bench'];origin=e.get('source_collection',e['collection']);counts[b]['retained_outer_files']+=1;sources[b].add(origin);scopes[b].add(e['run_scope']);status[b].update(e.get('observed_status_fields',{}));walk(e,b,origin,e['path'])
    # Each source inventory is counted once even when an incremental alias replaces
    # only some entries from an older selection.
    latest={}
    for c in r.catalog['collections']:latest[c.get('source_collection',c['collection'])]=c
    for origin,c in latest.items():
        for b,n in c.get('by_bench',{}).items():
            if origin in COLLECTION_BENCH:b=COLLECTION_BENCH[origin]
            if origin=='docs-repair-2026-10-09' and b=='shared-or-unassigned':b='terminal-bench'
            counts[b]['discovered_outer_files']+=n.get('discovered_files',0);counts[b]['inventory_excluded_files']+=n.get('excluded_files',0)
    excluded_outer=collections.defaultdict(set);excluded_members=collections.defaultdict(set);seen_shards=set()
    for p in (r.root/'reports').glob('preparation-*.json'):
        report=json.loads(p.read_text(encoding='utf-8'))
        for issue in report.get('unreadable',[]):
            b=bench_of(issue['collection'],issue['path']);issues[b].append(issue)
        def resource_rows():
            yield from report.get('resource_exclusions',[])
            for shard in report.get('resource_exclusion_shards',[]):
                packed=(r.root/shard['path']).read_bytes();assert hashlib.sha256(packed).hexdigest()==shard['sha256']
                for line in zstd.ZstdDecompressor().decompress(packed).splitlines():yield json.loads(line)
        for item in resource_rows():
            b=bench_of(item['collection'],item['path']);key=(item['collection'],item['path'])
            (excluded_members if '!/' in item['path'] else excluded_outer)[b].add(key)
    for p in list((r.root/'reports').glob('finalization-*.json'))+[r.root/'reports/incremental-finalization.json']:
        if not p.exists():continue
        report=json.loads(p.read_text(encoding='utf-8'))
        for shard in report.get('resource_exclusion_shards',[]):
            if shard['sha256'] in seen_shards:continue
            seen_shards.add(shard['sha256'])
            for line in zstd.ZstdDecompressor().decompress((r.root/shard['path']).read_bytes()).splitlines():
                x=json.loads(line);b=x.get('bench') or bench_of(x['collection'],x['path']);key=(x['collection'],x['path'])
                (excluded_members if '!/' in x['path'] else excluded_outer)[b].add(key)
    for b,values in excluded_outer.items():counts[b]['reviewed_excluded_outer_files']=len(values)
    for b,values in excluded_members.items():counts[b]['reviewed_excluded_member_references']=len(values)
    sample_path=a.samples or r.root/'reports/remaining-sample-verification.json';samples=json.loads(sample_path.read_text(encoding='utf-8')).get('samples',[]) if sample_path.exists() else []
    sampled={s['bench'] for s in samples if s.get('verified')}
    old_samples=r.root/'reports/bench-samples-bench5-20261024.json';reused=set()
    if old_samples.exists():reused={s['bench'] for s in json.loads(old_samples.read_text(encoding='utf-8'))['samples'] if s.get('restored_and_hashed')}
    unreadable=collections.defaultdict(list);unreadable_path=r.root/'reports/unreadable-sources.json'
    if unreadable_path.exists():
        for item in json.loads(unreadable_path.read_text(encoding='utf-8'))['paths']:unreadable[bench_of('',item['path'])].append(item)
    original_gaps=r.root/'reports/original-source-gaps.json'
    if original_gaps.exists():
        for item in json.loads(original_gaps.read_text(encoding='utf-8')):issues[item['bench']].append(item)
    output={}
    for b,n in sorted(counts.items()):
        detail=n['message_row_references']>0 or (n['request_file_references']>0 and n['response_file_references']>0)
        classification='partial-source-damaged' if issues[b] else 'all-found-readable-records' if detail else 'no-usable-detail-found'
        if unreadable[b]:classification='unprocessed-sources-remain'
        if b=='shared-or-unassigned':classification='mixed-unassigned-evidence'
        affected={scope_of(x.get('collection',''),x['path']) for x in issues[b] if x.get('path')}
        output[b]=dict(classification=classification,counts=dict(n),source_collections=sorted(sources[b]),run_scopes=len(scopes[b]),known_affected_source_run_scopes=len(affected),unreadable_directory_count=len(unreadable[b]),unverified_file_count=None if unreadable[b] else len({(x.get('collection'),x.get('path')) for x in issues[b]}),unverified_file_count_unit='known affected record/member paths; opaque directory file counts are unknown',unique_database_table_states=len(states[b]),observed_status_fields=dict(status[b]),attributed_compressed_pack_bytes=r.catalog['benches'].get(b,{}).get('attributed_pack_bytes',0),verified_sample=b in sampled or b in reused,reused_sample_report='bench-samples-bench5-20261024.json' if b in reused else None,issues=issues[b],unreadable_sources=unreadable[b])
    report=dict(benches=output,unprocessed_sources=r.catalog.get('deferred_original_collections',[]),counting_notes=['Outer-file counts exclude the nested-member reference count.','Source inventories and retained entries use path-based Bench attribution; shared evidence is kept separately.','Run scopes, status occurrences, file references and database states are not independent experiment or trajectory counts.','Complete means all found readable record candidates in inspected sources; it does not assert every historical run produced every kind of record.','No-usable-detail means inspected sources contain no stored input/output evidence detected by this audit; metadata remains available.','Sample success does not prove all runs complete.'])
    (out/'current-bench-coverage.json').write_bytes(encoded(report))
    with (out/'bench-coverage.csv').open('w',encoding='utf-8',newline='') as f:
        writer=csv.writer(f);writer.writerow(['bench','classification','discovered_outer_files','retained_outer_files','retained_source_run_scopes','inventory_excluded_files','reviewed_excluded_outer_files','reviewed_excluded_member_references','known_affected_source_run_scopes','unreadable_directories','unverified_file_count','message_row_references','unique_database_table_states','attributed_compressed_pack_bytes','verified_sample','issue_references'])
        for b,v in output.items():writer.writerow([b,v['classification'],v['counts'].get('discovered_outer_files',0),v['counts'].get('retained_outer_files',0),v['run_scopes'],v['counts'].get('inventory_excluded_files',0),v['counts'].get('reviewed_excluded_outer_files',0),v['counts'].get('reviewed_excluded_member_references',0),v['known_affected_source_run_scopes'],v['unreadable_directory_count'],v['unverified_file_count'],v['counts'].get('message_row_references',0),v['unique_database_table_states'],v['attributed_compressed_pack_bytes'],v['verified_sample'],len(v['issues'])])
    print(json.dumps({b:{k:v[k] for k in ('classification','run_scopes','attributed_compressed_pack_bytes','verified_sample')} for b,v in output.items()}))

if __name__=='__main__':main()
