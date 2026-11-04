"""List repository indexes; read and verify a complete external records directory."""
import argparse,collections,gzip,hashlib,io,json,os,pathlib,sys,tarfile
import zstandard as zstd

def digest(b):return hashlib.sha256(b).hexdigest()
def read_json(path):return json.loads(path.read_text(encoding='utf-8'))

class Records:
    def __init__(self,root):
        self.root=root.resolve(strict=True);self.catalog=read_json(self.root/'catalog.json');self.packs={x['path']:x for x in read_json(self.root/'manifests/packs.json')};self.objects={};self.cache_name=None;self.cache={};self.lru=collections.OrderedDict()
        legacy=self.root/'manifests/objects.jsonl.gz'
        if legacy.exists():
            with gzip.open(legacy,'rt',encoding='utf-8') as f:
                for line in f:
                    row=json.loads(line);self.objects[row['sha256']]=row
        else:
            index=read_json(self.root/'manifests/object-index.json')
            for shard in index['shards']:
                packed=(self.root/shard['path']).read_bytes();assert len(packed)<=25*1024*1024 and digest(packed)==shard['sha256']
                lines=gzip.decompress(packed).splitlines();assert len(lines)==shard['rows']
                for line in lines:
                    row=json.loads(line);assert row['sha256'] not in self.objects;self.objects[row['sha256']]=row
            assert len(self.objects)==index['objects']
    def entries(self,collection_name=None):
        for collection in self.catalog['collections']:
            if collection_name is not None and collection['collection']!=collection_name:continue
            for shard in collection['manifest_shards']:
                packed=(self.root/shard['path']).read_bytes();assert digest(packed)==shard['sha256']
                raw=zstd.ZstdDecompressor().decompress(packed)
                for line in raw.splitlines():
                    row=json.loads(line)
                    key=json.dumps([row['collection'],row['path']],separators=(',',':'))
                    if key not in self.catalog.get('entry_overrides',{}):yield row
    def load_pack(self,name):
        if name==self.cache_name:return
        if name in self.lru:
            self.cache=self.lru.pop(name);self.lru[name]=self.cache;self.cache_name=name;return
        proof=self.packs[name];packed=(self.root/name).read_bytes();assert len(packed)<=25*1024*1024;assert digest(packed)==proof['sha256']
        raw=zstd.ZstdDecompressor().decompress(packed);assert digest(raw)==proof['tar_sha256'];self.cache={}
        with tarfile.open(fileobj=io.BytesIO(raw),mode='r:') as tar:
            for m in tar:
                assert m.isfile() and m.name.startswith('objects/');h=m.name.removeprefix('objects/');data=tar.extractfile(m).read();assert digest(data)==h;self.cache[h]=data
        self.cache_name=name
        self.lru[name]=self.cache
        while len(self.lru)>24:self.lru.popitem(last=False)
    def parts(self,content):
        hasher=hashlib.sha256();size=0
        for h in content['parts']:
            self.load_pack(self.objects[h]['pack']);data=self.cache[h];hasher.update(data);size+=len(data);yield data
        assert size==content['bytes'] and hasher.hexdigest()==content['sha256']
    def get(self,collection,path):
        seen=set()
        while (key:=json.dumps([collection,path],separators=(',',':'))) in self.catalog.get('entry_overrides',{}):
            if key in seen:raise ValueError('Cyclic record override')
            seen.add(key);collection,path=self.catalog['entry_overrides'][key]
        for row in self.entries(collection):
            if row['collection']==collection and row['path']==path:return row
        raise ValueError('Record not found')

def contents(value):
    if isinstance(value,dict):
        if set(('bytes','sha256','parts'))<=value.keys():yield value
        else:
            for x in value.values():yield from contents(x)
    elif isinstance(value,list):
        for x in value:yield from contents(x)

def database_exports(value):
    if isinstance(value,dict):
        if value.get('format')=='sqlite-tables':yield value
        else:
            for x in value.values():yield from database_exports(x)
    elif isinstance(value,list):
        for x in value:yield from database_exports(x)

def verify(records):
    hashes=set();objects=0
    for name in records.packs:
        records.load_pack(name)
        for h,data in records.cache.items():
            assert records.objects[h]['pack']==name and records.objects[h]['bytes']==len(data)
            hashes.add(h);objects+=1
    assert hashes==records.objects.keys()
    # Reassemble into a bounded spool keyed by content hash once, then check all references.
    # Pack and fragment checks above cover all physical bytes; streamed content checks
    # below also prove order and complete reassembly.
    refs=0;seen=set();databases=0;tables=0;rows_total=0;table_counts={}
    for entry in records.entries():
        for content in contents(entry):
            refs+=1
            assert sum(records.objects[h]['bytes'] for h in content['parts'])==content['bytes']
            signature=(content['sha256'],content['bytes'],tuple(content['parts']))
            if signature not in seen:
                if not content['parts']:assert content['sha256']==digest(b'')
                elif len(content['parts'])==1:assert content['sha256']==content['parts'][0]
                else:
                    for part in records.parts(content):pass
                seen.add(signature)
        for database in database_exports(entry):
            databases+=1;assert database['integrity']=='ok' and database['rows_verified']
            for table in database['tables']:
                if table.get('excluded'):continue
                assert table['source_rows']==table['exported_rows'];tables+=1;rows_total+=table['exported_rows']
                key=table['content']['sha256']
                if key not in table_counts:
                    table_counts[key]=sum(part.count(b'\n') for part in records.parts(table['content']))
                assert table_counts[key]==table['source_rows']
    return dict(packs=len(records.packs),objects=objects,content_references=refs,unique_reassembled_contents=len(seen),all_packs_decompressed_and_sha256_verified=True,all_fragment_references_resolve=True,all_reassembled_hashes_verified=True,databases=databases,tables=tables,database_rows=rows_total)

def main():
    ap=argparse.ArgumentParser(description=__doc__);ap.add_argument('--root',type=pathlib.Path,default=os.environ.get('OBJRUN_RECORDS_ROOT') or pathlib.Path(__file__).resolve().parents[2]/'experiments/records',help='Complete external records directory (or OBJRUN_RECORDS_ROOT); repository indexes are the default');ap.add_argument('--isolated',action='store_true');sub=ap.add_subparsers(dest='mode',required=True)
    p=sub.add_parser('runs');p.add_argument('--bench');p.add_argument('--limit',type=int,default=20)
    p=sub.add_parser('files');p.add_argument('--bench');p.add_argument('--limit',type=int,default=20)
    for name in ('read','extract'):
        p=sub.add_parser(name);p.add_argument('--collection',required=True);p.add_argument('--path',required=True);p.add_argument('--table');p.add_argument('--member',action='append',help='Archive member path; repeat for nested archives, optionally followed by --table')
        if name=='extract':p.add_argument('--output',type=pathlib.Path,required=True)
    sub.add_parser('verify');args=ap.parse_args()
    if args.mode in ('runs','files') and args.limit<1:ap.error('--limit must be positive')
    if not args.root.is_dir():ap.error('Records directory does not exist: '+str(args.root))
    root=args.root.resolve(strict=True)
    if args.isolated:
        def audit(event,a):
            if event=='open' and isinstance(a[0],(str,bytes)):
                p=pathlib.Path(a[0]).resolve()
                if not p.is_relative_to(root):raise PermissionError('Isolated reader cannot open files outside supplied records directory')
        sys.addaudithook(audit)
    if args.mode=='runs':
        paths=[root/'runs'/f'{args.bench}.jsonl'] if args.bench else sorted((root/'runs').glob('*.jsonl'));count=0
        for path in paths:
            with path.open(encoding='utf-8') as f:
                for line in f:
                    print(line.rstrip());count+=1
                    if count>=args.limit:return
        return
    required=[root/'catalog.json',root/'manifests/packs.json',root/'packs']
    legacy=root/'manifests/objects.jsonl.gz'
    if not legacy.is_file():
        index=root/'manifests/object-index.json';required.append(index)
        if index.is_file():required.extend(root/shard['path'] for shard in read_json(index)['shards'])
    missing=[p for p in required if not p.exists()]
    if missing:
        ap.error('Record bodies are stored outside this repository. Supply --root PATH or OBJRUN_RECORDS_ROOT pointing to a complete records directory containing catalog.json, manifests/, packs/ and runs/. See experiments/records/README.md. Missing: '+str(missing[0]))
    records=Records(root)
    if args.mode=='verify':print(json.dumps(verify(records)));return
    if args.mode=='files':
        count=0
        for row in records.entries():
            if args.bench and row['bench']!=args.bench:continue
            print(json.dumps({k:row[k] for k in ('collection','path','bench','format')},ensure_ascii=True));count+=1
            if count>=args.limit:return
        return
    entry=records.get(args.collection,args.path)
    for member in args.member or []:entry=next(x for x in entry['members'] if x['path']==member)
    if args.table:content=next(x['content'] for x in entry['tables'] if x['name']==args.table)
    elif 'content' in entry:content=entry['content']
    else:print(json.dumps(entry,ensure_ascii=True));return
    if args.mode=='read':
        for chunk in records.parts(content):sys.stdout.buffer.write(chunk)
    else:
        output=args.output.absolute();output.parent.mkdir(parents=True,exist_ok=True)
        with output.open('xb') as f:
            for chunk in records.parts(content):f.write(chunk)
        print(json.dumps(dict(output=str(output),bytes=content['bytes'],sha256=content['sha256'],verified=True)))

if __name__=='__main__':main()
