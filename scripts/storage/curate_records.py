"""Build the explicitly selected Git delivery from an existing verified export.

The input is read-only. Deferred entries remain in the original archive and the
previous export; this tool never deletes sources or modifies Git.
"""
import argparse, collections, copy, gzip, io, json, pathlib, re, tarfile
import zstandard as zstd
from export_records import PackStore, JsonShards, Scrubber, encoded, sha, STATUS_RE, ID_RE
from records import Records, contents

FROZEN = {'historical-novaeve-sources', 'historical-terminal-sources',
          'historical-skills-next-segment', 'historical-runner-releases',
          'historical-root-helpers', 'local-tmp', 'novaeve-docker-shims'}
GENERATORS = ['test/repair-campaign-journal.test.ts',
              'test/scientific-financial-interruption.test.ts',
              'test/_financial-revision-fixture.ts',
              'test/chemiq-f-journal-contract.test.ts',
              'test/paid-resource-admission-v2.test.ts',
              'test/repair-paid-pid-diagnostic.test.ts']

def has_pending(value):
    if isinstance(value, dict):
        return bool(value.get('pending')) or any(has_pending(v) for v in value.values())
    return isinstance(value, list) and any(has_pending(v) for v in value)

def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument('--root', type=pathlib.Path, required=True)
    ap.add_argument('--output', type=pathlib.Path, required=True)
    ap.add_argument('--workspace', type=pathlib.Path, required=True)
    a = ap.parse_args(); src = Records(a.root); out = a.output.resolve()
    assert not out.exists(), 'Output must be a new directory'
    assert not out.is_relative_to(a.root.resolve()), 'Output must be outside source'
    out.mkdir(parents=True)
    for n in ('runs','summaries','packs','manifests','reports'): (out/n).mkdir()
    scrub = Scrubber(a.workspace); store = PackStore(out); store.level = 6
    wanted = {}; streams = {}; decisions = JsonShards(out, 'selection-decisions')
    bench = collections.defaultdict(collections.Counter); formats = collections.Counter()
    scopes = collections.defaultdict(dict); reasons = collections.Counter()
    per_collection = collections.defaultdict(collections.Counter)
    synthetic = collections.Counter(); seen_diagnostics = set(); dbproof = []; decoded = []
    oldcols = {x['collection']: x for x in src.catalog['collections']}
    for col in oldcols.values():
        for b, counts in col.get('by_bench',col.get('prior_export_by_bench',{})).items():
            for k in ('discovered_files','discovered_bytes','excluded_files','database_sidecars'):
                bench[b][k] += counts.get(k, 0)
    for e in src.entries():
        name=e['collection']; b=e['bench']; path=e['path']; reason=None
        bench[b]['candidate_entries_before_selection'] += 1
        if e.get('pending') and name == 'fullf-chembench':
            raw=b''.join(src.parts(e['content'])); text=gzip.decompress(raw).decode('utf-8')
            json.loads(text)  # A valid provider response, not a TAR header.
            text, changes, resources = scrub.text(text)
            e['format']='text'; e.pop('pending'); e['content']=store.put(text.encode('utf-8'), b)
            e['transformations']={'gzip_decode':True, **changes}
            if resources: e['removed_resources']=resources
            e['observed_status_fields']=dict(collections.Counter(m.group(1).lower() for m in STATUS_RE.finditer(text)))
            e['identifiers']=[list(x) for x in sorted(set(ID_RE.findall(text)))]
            decoded.append(dict(collection=name,path=path,source_sha256=e['source_sha256'],
                                output_sha256=e['content']['sha256'],bytes=e['content']['bytes']))
        elif has_pending(e): reason='unconfirmed-input-deferred-to-archive'
        elif name in FROZEN: reason='frozen-source-or-build-copy'
        elif re.search(r'(^|/)(?:frozen-source|engine-source)\.(?:zip|tar(?:\.gz|\.zst)?)$',path,re.I):
            reason='frozen-source-bundle'
        elif name == 'scratch-diagnostics-remainder':
            # Only this explicitly identified synthetic collection is reduced.
            # Real runs elsewhere are never classified as noise by failure status.
            synthetic['discovered_entries'] += 1
            if e['format'] != 'text': reason='synthetic-bulk-fixture'
            else:
                data=b''.join(src.parts(e['content'])); s=data.decode('utf-8')
                error=bool(re.search(r'Traceback \(most recent call last\)|\b(?:Error|Exception):|"(?:error|failure_reason)"\s*:\s*(?!null|false|""|\[\]|\{\})',s))
                summary=bool(re.search(r'(^|/)[^/]*(?:summary|report|receipt|selfcheck|audit)[^/]*\.(?:json|jsonl|md|txt|log)$',path,re.I))
                script=bool(re.search(r'\.(?:py|ts|js|sh|ps1|patch|diff)$',path,re.I))
                if not (error or summary or script): reason='synthetic-bulk-fixture'
                elif e['content']['sha256'] in seen_diagnostics: reason='duplicate-synthetic-diagnostic'
                else:
                    seen_diagnostics.add(e['content']['sha256'])
                    e['selection_role']='synthetic-generator' if script else 'synthetic-error' if error else 'synthetic-summary'
                    synthetic[e['selection_role']] += 1
        if reason:
            reasons[reason]+=1; per_collection[name][reason]+=1; bench[b]['archived_candidate_entries']+=1
            decisions.write(dict(collection=name,path=path,bench=b,source_sha256=e.get('source_sha256'),
                                 source_bytes=e.get('source_bytes'),reason=reason))
            continue
        assert not has_pending(e)
        streams.setdefault(name,JsonShards(out,name)).write(e)
        per_collection[name]['selected_entries']+=1; bench[b]['retained_files']+=1
        bench[b]['retained_source_bytes']+=e.get('source_bytes',0); formats[e['format']]+=1
        for c in contents(e):
            for h in c['parts']:
                if h not in store.objects: wanted.setdefault(h,b)
        scope=scopes[b].setdefault(e['run_scope'],dict(run_scope=e['run_scope'],collection=name,files=0,
                                                    status_fields=collections.Counter(),identifiers=set()))
        scope['files']+=1; scope['status_fields'].update(e.get('observed_status_fields',{}))
        scope['identifiers'].update(tuple(x) for x in e.get('identifiers',[]))
        if e['format']=='sqlite-tables':
            for t in e['tables']:scope['status_fields'].update(t.get('observed_status_fields',{}))
            dbproof.append(dict(collection=name,path=path,source_sha256=e['source_sha256'],
                wal_sha256=e.get('wal_sha256'),wal_bytes=e.get('wal_bytes'),integrity=e['integrity'],
                foreign_key_violation_count=e['foreign_key_violation_count'],
                tables=[{k:t.get(k) for k in ('name','source_rows','exported_rows','order','excluded')} for t in e['tables']]))
    groups=collections.defaultdict(set)
    for h in wanted:groups[src.objects[h]['pack']].add(h)
    for i,(pack,hashes) in enumerate(groups.items()):
        src.load_pack(pack)
        # Keep related fragments adjacent, improving compression and reproducibility.
        for h,data in src.cache.items():
            if h in hashes:store.put(data,wanted[h])
        if i%25==0:print(json.dumps({'repacked_source_packs':i+1,'total':len(groups)}),flush=True)
    store.finish(); selected=[]
    for name,col in oldcols.items():
        c=copy.deepcopy(col); c['manifest_shards']=streams[name].finish() if name in streams else []
        c['prior_export_pending_count']=len(c.pop('pending',[])); c['pending']=[]
        c['selection_counts']=dict(per_collection[name]); selected.append(c)
    for b, items in scopes.items():
        bench[b]['run_scopes_retained']=len(items)
        with (out/'runs'/f'{b}.jsonl').open('wb') as f:
            for s in items.values():
                s['status_fields']=dict(s['status_fields']);s['identifiers']=[list(x) for x in sorted(s['identifiers'])]
                f.write(encoded(s)+b'\n')
    for p in store.packs:
        total=sum(p['owner_raw_bytes'].values())
        for b,n in p['owner_raw_bytes'].items():bench[b]['attributed_pack_bytes']+=round(p['bytes']*n/total)
    report=dict(policy='User approved 2026-10-24: deliver confirmed necessary subset; archive remainder for later review',
        reasons=dict(reasons),by_collection={k:dict(v) for k,v in per_collection.items()},
        decoded_valid_gzip_responses=decoded,synthetic=dict(synthetic),generator_references=GENERATORS,
        deferred_original_collections=src.catalog['missing_collections'],decision_manifest_shards=decisions.finish(),
        all_sources_preserved=True,original_archive_deletion_authorized=False)
    catalog=dict(format_version=1,delivery_scope='confirmed-selected-records',completed=True,full_original_coverage=False,
        collections_expected=66,collections_processed=len(oldcols),collections_with_selected_records=len(streams),
        collections=selected,benches={k:dict(v) for k,v in bench.items()},formats=dict(formats),pending=0,
        missing_collections=src.catalog['missing_collections'],deferred_original_collections=src.catalog['missing_collections'],
        pack_count=len(store.packs),pack_bytes=sum(p['bytes'] for p in store.packs),unique_fragments=len(store.objects))
    for filename,value in [('catalog.json',catalog),('reports/selection.json',report),
                           ('reports/database-consistency.json',dbproof),('reports/pending.json',[])]:
        (out/filename).write_bytes(encoded(value))
    print(json.dumps({k:v for k,v in catalog.items() if k not in ('collections','benches')}),flush=True)

if __name__=='__main__':main()
