"""Refresh the small Git-side archive catalog from local verified collection records."""
import argparse,csv,hashlib,json,pathlib,time

def digest(path):
    with path.open('rb') as f: return hashlib.file_digest(f,'sha256').hexdigest()

def normalized(value): return str(value).replace('\\','/').rstrip('/').casefold()

def main():
    ap=argparse.ArgumentParser(description=__doc__)
    ap.add_argument('--workspace',required=True,type=pathlib.Path)
    args=ap.parse_args();root=args.workspace.resolve(strict=True)
    archive=root/'_objrun-archive'; experiments=root/'objrun/experiments'
    entries=[]
    for path in sorted((archive/'collections').glob('*/record.json')):
        r=json.loads(path.read_text(encoding='utf-8-sig'))
        if r.get('status') not in ('archived','archived_external_preserved'): continue
        if not all(r.get(k) for k in ('coverage_verified','integrity_verified','restore_verified')):
            raise ValueError('Completed record lacks verification: '+r['name'])
        proofs={}
        for filename in ('record.json','source-before.jsonl.gz','files-sha256.jsonl.gz'):
            file=path.parent/filename
            proofs[filename]=dict(path=file.relative_to(archive).as_posix(),bytes=file.stat().st_size,sha256=digest(file))
        entries.append(dict(id=r['name'],source_root=r.get('source_relative') or r['source'],
            source_absolute=r['source'],snapshot=r['snapshot'],status=r['status'],transport=r.get('transport','files'),
            source_files=r['before']['files'],source_logical_bytes=r['before']['bytes'],source_links=r['before']['links'],
            added_packed_bytes=r['backup']['data_added_packed'],
            excluded_paths=r.get('excluded',[]),kept_files=r.get('kept_files',[]),
            retained_empty_directories=r.get('retained_empty_directories',[]),
            expanded_kept_files=[name for name in r.get('kept_files',[]) if (pathlib.Path(r['source'])/name).is_file()],
            kept_files_note='Files retained after this collection was compacted; later collections may archive some of them.',
            expanded_source_removed=r['source_removed'],external_original_preserved=bool(r.get('external_readonly')),
            coverage_verified=True,restored_sha256_verified=True,uploaded=False,proofs=proofs))
    entries.sort(key=lambda r:r['id'])
    checks=archive/'verification/full-data-check.json'
    full_check=json.loads(checks.read_text(encoding='utf-8')) if checks.exists() else None
    external_map_path=experiments/'provenance/external-source-map.json'
    external_map=json.loads(external_map_path.read_text(encoding='utf-8')).get('sources',[]) if external_map_path.exists() else []
    completed_ids={entry['id'] for entry in entries}
    result=dict(schema_version=1,generated_at=time.strftime('%Y-%m-%dT%H:%M:%S%z'),
        archive_root='../_objrun-archive',format='restic-v2',password_policy='empty password; filesystem/private-repository access controls only',
        uploaded=False,global_data_check=full_check,collections=entries,external_link_targets=external_map,
        coverage_note='Byte coverage of the listed source collections only. This does not certify trial semantics, paper-score linkage, or unreadable excluded directories.')
    experiments.mkdir(parents=True,exist_ok=True)
    (experiments/'archive-catalog.json').write_text(json.dumps(result,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
    ordered=sorted(entries,key=lambda r:len(normalized(r['source_root'])),reverse=True)
    def locate(value):
        p=normalized(value)
        for link in sorted(external_map,key=lambda x:len(normalized(x['link_path'])),reverse=True):
            alias=normalized(link['link_path'])
            if (p==alias or p.startswith(alias+'/')) and link['archive_id'] in completed_ids:
                return link['archive_id'],'archived_external_preserved'
        for r in ordered:
            base=normalized(r['source_root'])
            if p==base or p.startswith(base+'/'):
                partial=False
                for ex in r['excluded_paths']:
                    absent=base+'/'+normalized(ex)
                    if p==absent or p.startswith(absent+'/'): return None,'preserved_not_archived'
                    if absent.startswith(p+'/'): partial=True
                return r['id'],'archived_with_exclusions' if partial else r['status']
        q=pathlib.Path(value)
        if not q.is_absolute(): q=root/q
        return None,'expanded_local' if q.exists() else 'unmapped'
    for name,column in [('collection-roots.csv','source_root'),('catalog.csv','source_root'),('benchmark-catalog.csv','source_roots')]:
        path=experiments/name
        with path.open(encoding='utf-8-sig',newline='') as f:
            reader=csv.DictReader(f);fields=list(reader.fieldnames);records=list(reader)
        for field in ('local_archive_ids','local_storage_status'):
            if field not in fields: fields.append(field)
        for row in records:
            paths=[x.strip() for x in row[column].split(' | ') if x.strip()]
            if name=='benchmark-catalog.csv' and row.get('external_source'):
                external=row['external_source']
                if pathlib.Path(external).is_absolute(): paths.append(external)
            mapped=[locate(x) for x in paths]
            row['local_archive_ids']=' | '.join(sorted({x[0] for x in mapped if x[0]}))
            row['local_storage_status']=' | '.join(sorted({x[1] for x in mapped}))
        with path.open('w',encoding='utf-8',newline='') as f:
            writer=csv.DictWriter(f,fieldnames=fields);writer.writeheader();writer.writerows(records)
    print(json.dumps(dict(collections=len(entries),source_files=sum(r['source_files'] for r in entries),
        source_logical_bytes=sum(r['source_logical_bytes'] for r in entries),uploaded=False)))

if __name__=='__main__': main()
