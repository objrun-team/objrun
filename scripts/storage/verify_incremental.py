"""Verify new packs and records while reusing the accepted base pack manifest."""
import argparse,collections,gzip,hashlib,json,pathlib,re,sys
import zstandard as zstd
from records import Records,contents,database_exports
from export_records import Scrubber

def main():
    ap=argparse.ArgumentParser(description=__doc__);ap.add_argument('--base',type=pathlib.Path,required=True);ap.add_argument('--root',type=pathlib.Path,required=True);ap.add_argument('--workspace',type=pathlib.Path,required=True);ap.add_argument('--reuse-verified-root',type=pathlib.Path,help='Previously fully verified immutable candidate; only matching bytes and mappings are reused');args=ap.parse_args()
    base=Records(args.base);root=args.root.resolve();scrub=Scrubber(args.workspace)
    known=[v.encode() for v in scrub.values];patterns=[re.compile(p.pattern.encode(),p.flags&~re.UNICODE) for p in scrub.patterns]
    original_collections={c['collection'] for c in base.catalog['collections']};oldpacks=base.packs
    old_metadata={p.relative_to(base.root).as_posix():hashlib.sha256(p.read_bytes()).digest() for p in base.root.rglob('*') if p.is_file() and p.relative_to(base.root).parts[0]!='packs'}
    accepted=Records(args.reuse_verified_root) if args.reuse_verified_root else None;accepted_contents=set();accepted_tables={};accepted_members=collections.defaultdict(dict)
    def signature(c):return (c['sha256'],c['bytes'],tuple(c['parts']))
    if accepted:
        accepted_hashes=set()
        for h,obj in accepted.objects.items():accepted_members[obj['pack']][h]=obj['bytes']
        for e in accepted.entries():
            if e['collection'] in original_collections:continue
            # The prior verifier reassembled the first descriptor for each hash.
            # Different fragment sequences with the same claimed hash are checked
            # again below rather than inheriting that earlier proof.
            for c in contents(e):
                if c['sha256'] not in accepted_hashes:accepted_contents.add(signature(c));accepted_hashes.add(c['sha256'])
            for db in database_exports(e):
                if db.get('integrity')!='ok' or not db.get('rows_verified'):continue
                for t in db['tables']:
                    if not t.get('excluded'):accepted_tables[signature(t['content'])]=t['exported_rows']
    def audit(event,a):
        if event=='open' and isinstance(a[0],(str,bytes)) and not pathlib.Path(a[0]).resolve().is_relative_to(root):raise PermissionError('Only candidate Git records may be opened')
    sys.addaudithook(audit);r=Records(root);newpacks=0;newobjects=0;scanned=0;reused_packs=0;reused_contents=0;current_members=collections.defaultdict(dict)
    assert {p.relative_to(root).as_posix() for p in (root/'packs').iterdir() if p.is_file()}==set(r.packs),'Unindexed or missing physical pack'
    for h,obj in r.objects.items():current_members[obj['pack']][h]=obj['bytes']
    def scan(data,location='record boundary'):
        nonlocal scanned
        scanned+=len(data)
        assert not any(v in data for v in known),'Known credential in exported payload: '+location
        assert not any(p.search(data) for p in patterns),'Credential pattern in exported payload: '+location
    metadata=0
    for p in root.rglob('*'):
        if not p.is_file() or p.relative_to(root).parts[0]=='packs':continue
        data=p.read_bytes()
        if old_metadata.get(p.relative_to(root).as_posix())==hashlib.sha256(data).digest():continue
        if p.suffix=='.gz':data=gzip.decompress(data)
        elif p.suffix=='.zst':data=zstd.ZstdDecompressor().decompress(data)
        scan(data,p.relative_to(root).as_posix());metadata+=1
    for name,proof in oldpacks.items():assert r.packs[name]==proof,'Base pack changed'
    for name in r.packs:
        if name in oldpacks:continue
        newpacks+=1
        if accepted and name in accepted.packs and all(r.packs[name].get(k)==accepted.packs[name].get(k) for k in ('bytes','sha256','tar_sha256')) and current_members[name]==accepted_members[name]:
            packed=(root/name).read_bytes();assert len(packed)<=25*1024*1024 and hashlib.sha256(packed).hexdigest()==r.packs[name]['sha256'];reused_packs+=1;newobjects+=len(current_members[name]);continue
        r.load_pack(name)
        for h,data in r.cache.items():assert r.objects[h]['pack']==name and r.objects[h]['bytes']==len(data);scan(data,name+' object '+h);newobjects+=1
    overrides=r.catalog.get('entry_overrides',{});override_targets=set()
    for value in overrides.values():
        visited=set();target=tuple(value)
        while (key:=json.dumps(list(target),separators=(',',':'))) in overrides:
            assert key not in visited,'Cyclic entry override';visited.add(key);target=tuple(overrides[key])
        override_targets.add(target)
    missing_targets=set(override_targets)
    seen=set();used=set(base.objects);files=0;tables=0;rows=0;databases=0;foreign=0;benches=collections.Counter();table_counts={}
    for e in r.entries():
        missing_targets.discard((e['collection'],e['path']))
        if e['collection'] in original_collections:continue
        files+=1;benches[e['bench']]+=1
        for c in contents(e):
            used.update(c['parts'])
            assert sum(r.objects[h]['bytes'] for h in c['parts'])==c['bytes']
            sig=signature(c)
            if sig in seen:continue
            seen.add(sig);tail=b''
            if signature(c) in accepted_contents:
                assert sum(r.objects[h]['bytes'] for h in c['parts'])==c['bytes'];reused_contents+=1;continue
            for block in r.parts(c):scan(tail+block[:4096]);tail=block[-4096:]
        for db in database_exports(e):
            databases+=1;assert db['integrity']=='ok' and db['rows_verified'];foreign+=db['foreign_key_violation_count']
            for t in db['tables']:
                if t.get('excluded'):continue
                h=t['content']['sha256']
                if h not in table_counts:table_counts[h]=accepted_tables[signature(t['content'])] if signature(t['content']) in accepted_tables else sum(x.count(b'\n') for x in r.parts(t['content']))
                assert t['source_rows']==t['exported_rows']==table_counts[h]
                tables+=1;rows+=t['exported_rows']
    assert used==set(r.objects),'Unreferenced new content or missing object mapping'
    assert not missing_targets,'Entry override points to an absent record'
    print(json.dumps(dict(new_packs=newpacks,new_objects=newobjects,reused_previously_decompressed_packs=reused_packs,new_packs_decompressed_this_pass=newpacks-reused_packs,reused_verified_content_sequences=reused_contents,new_or_changed_metadata_files_scanned=metadata,selected_new_file_records=files,by_bench=dict(benches),unique_reassembled_contents=len(seen),databases=databases,tables=tables,rows=rows,source_foreign_key_violations=foreign,credential_findings=0,scanned_bytes_including_overlap=scanned,base_pack_manifest_unchanged=True,no_unindexed_packs=True,no_unreferenced_new_content=True,isolated_file_access_guard=True,original_archive_access_permitted=False)))

if __name__=='__main__':main()
