"""Stream verified local archives into self-contained, content-addressed Git records.

Original archives and external sources are read-only. No Git mutation is performed.
"""
import argparse,base64,codecs,collections,concurrent.futures,csv,gzip,hashlib,io,json,os,pathlib,re,shutil,sqlite3,subprocess,tarfile,threading,time,traceback,zipfile
import zstandard as zstd

def encoded(x):
    # TAR may expose undecodable filename bytes as surrogate escapes. JSON escapes
    # preserve those identifiers without dropping a whole source collection.
    try:return json.dumps(x,ensure_ascii=False,separators=(',',':'),allow_nan=False).encode('utf-8')
    except UnicodeEncodeError:return json.dumps(x,ensure_ascii=True,separators=(',',':'),allow_nan=False).encode('ascii')
def sha(x): return hashlib.sha256(x).hexdigest()
def file_sha(p):
    with p.open('rb') as f:return hashlib.file_digest(f,'sha256').hexdigest()

def database_sidecar(path, suffix):
    return path[:-9]+suffix+'.snapshot' if path.endswith('.snapshot') else path+suffix

def database_main(path):
    for suffix in ('-wal','-shm'):
        if path.endswith(suffix+'.snapshot'):return path[:-len(suffix+'.snapshot')]+'.snapshot'
        if path.endswith(suffix):return path[:-len(suffix)]
    return None

def reviewed_resource_match(value, hashes):
    # A main-file hash alone does not identify a SQLite state with WAL frames.
    if value.get('format')=='sqlite-tables' and (value.get('wal_bytes',0)>0 or value.get('wal_sha256') not in (None,'e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855')):return False
    if value.get('transformations',{}).get('sqlite_multiple_wal_states'):return False
    if value.get('format')=='sqlite-review-required' and (value.get('wal') or {}).get('bytes',0)>0:return False
    return value.get('source_sha256') in hashes

ALIASES=[('humaneval-plus',r'human.?eval'),('mbpp-plus',r'mbpp'),('llm-srbench',r'llm.?srbench|lsr.?bench'),('terminal-bench',r'terminal.?bench|(?:^|[/_-])tb(?:[/_-]|$)'),('skillsbench',r'skillsbench|(?:^|[/_-])skb(?:[/_-]|$)|(?:^|/)sb_'),('deepswe',r'deepswe|(?:^|[/_-])dsw(?:[/_-]|$)')]+[(x,re.escape(x)) for x in ('aime','gpqa','cmt','minif2f','chembench','chemiq','bird','classeval','scibench','scicode','theophyseval','frontierscience','olympiadbench','labbench','scienceworld','biocoder','atmossci')]
ALIASES=[(a,re.compile(b,re.I)) for a,b in ALIASES]
ENV_PARTS={'.git','node_modules','site-packages','dist-packages','__pycache__','.bun-cache','.venv','venv','hf-cache','hf-objects','.private-wheels','.private-apt','.lake','.mypy_cache','.pytest_cache'}
ENV_RE=re.compile(r'(?:^|/)(?:rootfs|container-rootfs|docker-root|docker-save|local-docker-store|go/pkg|conda-meta|wheelhouse|pip-cache|npm-cache|registry-blobs)(?:/|$)',re.I)
RESOURCE_NAME=re.compile(r'(?:docker(?:-archive|-save|-exported)?|official-image|original-image|image-archives?|original-images|owned-asset-context|image-export|\.ext4|\.vhdx|\.qcow|\.safetensors|\.gguf|\.whl$|\.deb$)',re.I)
CODE_RE=re.compile(r'\.(?:py|ts|js|mjs|cjs|sh|ps1|patch|diff|toml|yaml|yml|md|tex|lock)$',re.I)
STATUS_RE=re.compile(r'"(?:status|state|outcome|finish_reason)"\s*:\s*"(success|succeeded|passed|completed|failed|failure|error|interrupted|cancelled|canceled|aborted|timeout|timed_out|needs_attention)"',re.I)
ID_RE=re.compile(r'"(run_id|runId|trial_id|trialId|attempt_id|task_id|taskId)"\s*:\s*"([^"\r\n]{1,200})"')
COLLECTION_BENCH={'fullf-terminal-bench':'terminal-bench','fullf-skillsbench':'skillsbench','fullf-chemiq':'chemiq','fullf-chembench':'chembench','docs-labbench':'labbench','docs-gpqa':'gpqa','docs-minif2f':'minif2f','docs-frontierscience':'frontierscience','docs-llm-srbench':'llm-srbench','docs-olympiadbench':'olympiadbench','scibench':'scibench','scicode-external':'scicode','external-phase1-scicode-verified':'scicode'}

def bench_of(collection,path):
    # A dataset or dependency name inside a single-Bench run is not a new Bench.
    if collection in COLLECTION_BENCH:return COLLECTION_BENCH[collection]
    for name,pattern in ALIASES:
        if pattern.search(path):return name
    for name,pattern in ALIASES:
        if pattern.search(collection):return name
    return 'shared-or-unassigned'

def scope_of(collection,path):
    p=path.split('!/',1)[0].split('/')
    if collection=='legacy-runs':return collection+'/'+p[0]
    for marker in ('runs','trials','jobs','campaigns'):
        if marker in p and p.index(marker)+1<len(p):return collection+'/'+'/'.join(p[:p.index(marker)+2])
    for i,s in enumerate(p[:-1]):
        if re.fullmatch(r'[a-f0-9]{32}|[a-f0-9]{8}(?:-[a-f0-9]{4}){3}-[a-f0-9]{12}',s):return collection+'/'+'/'.join(p[:i+1])
    return collection+'/'+('/'.join(p[:min(2,len(p)-1)]) or '.')

def path_policy(collection,path):
    p=path.replace('\\','/').lower();parts=set(p.split('/'))
    if collection in ('chembench-runtime','gpqa-runtime','newbench-runtime'):return 'installed-runtime'
    if collection in ('paper-history','paper-revisions'):return 'historical-paper-copy'
    if parts & ENV_PARTS or ENV_RE.search(p):return 'environment-or-cache-tree'
    if collection=='phase1' and ('vendor' in parts or 'public-release' in parts or 'raw' in parts):return 'upstream-dataset-or-vendor'
    if any(s in parts for s in ('datasets','model-weights')):return 'dataset-or-model-tree'
    return None

def magic(data):
    if data.startswith((b'\xff\xfe',b'\xfe\xff',b'\xef\xbb\xbf')):return 'text'
    if data.startswith(b'SQLite format 3\x00'):return 'sqlite'
    if data[:4] in (b'7\x7f\x06\x82',b'7\x7f\x06\x83'):return 'wal'
    if data.startswith(b'PK\x03\x04'):return 'zip'
    if data.startswith(b'\x1f\x8b'):return 'gzip'
    if data.startswith(b'\x28\xb5\x2f\xfd'):return 'zstd'
    if len(data)>262 and data[257:262]==b'ustar':return 'tar'
    for sig,name in [(b'\x7fELF','executable'),(b'MZ','executable'),(b'\x89PNG','image'),(b'\xff\xd8\xff','image'),(b'%PDF-','pdf'),(b'PAR1','parquet'),(b'\x93NUMPY','numpy'),(b'\x89HDF','hdf'),(b'\xfd7zXZ','xz'),(b'BZh','bz2'),(b'\x1f\x9d','compress')]:
        if data.startswith(sig):return name
    if b'\x00' in data:return 'binary'
    try:data.decode('utf-8');return 'text'
    except UnicodeDecodeError:
        try:data.decode('utf-8-sig');return 'text'
        except UnicodeDecodeError:return 'unknown-encoding'

def is_tar_header(data):
    """Validate a complete TAR header; digits alone also occur in JSON text."""
    if len(data)<512:return False
    try:
        tarfile.TarInfo.frombuf(data[:512],encoding='utf-8',errors='surrogateescape')
        return True
    except tarfile.HeaderError:return False

class ForwardReader:
    """Seek forward by draining bounded buffers; avoid tarfile's slicing stream."""
    def __init__(self,source):self.source=source;self.position=0
    def tell(self):return self.position
    def read(self,n=-1):
        data=self.source.read(n);self.position+=len(data);return data
    def seek(self,offset,whence=0):
        target=offset if whence==0 else self.position+offset
        if target<self.position:raise ValueError('Backward seek in streaming archive')
        while self.position<target:
            data=self.read(min(1024*1024,target-self.position))
            if not data:raise EOFError('Truncated archive while skipping resource')
        return self.position

class PrefixReader:
    def __init__(self,head,source):self.head=head;self.source=source
    def read(self,n=-1):
        if n<0:r=self.head+self.source.read();self.head=b'';return r
        r=self.head[:n];self.head=self.head[n:];return r+self.source.read(n-len(r))

class Scrubber:
    def __init__(self,workspace):
        values=[]
        for p in (workspace/'objrun/.env',workspace/'TgEngin.env',workspace/'_objrun-archive/review/private/TgEngin.env'):
            if p.is_file():
                for line in p.read_text(encoding='utf-8',errors='replace').splitlines():
                    if '=' in line:
                        key,value=line.split('=',1);value=value.strip().strip('\"\'')
                        if re.search('key|token|secret|password',key,re.I) and len(value)>=8:values.append(value)
        self.values=sorted(set(values),key=len,reverse=True)
        self.patterns=[re.compile(r'\b(?:sk-(?:proj-|ant-)?[A-Za-z0-9_-]{20,}|gh[pousr]_[A-Za-z0-9]{20,}|github_pat_[A-Za-z0-9_]{20,}|AKIA[A-Z0-9]{16})\b',re.ASCII),re.compile(r'(?i)(?:Bearer\s+)[A-Za-z0-9_./+=-]{16,}'),re.compile(r'-----BEGIN (?:RSA |EC |OPENSSH )?PRIVATE KEY-----[\s\S]*?-----END (?:RSA |EC |OPENSSH )?PRIVATE KEY-----')]
        self.assignment=re.compile(r'(?i)(["\']?(?:api[_-]?key|access[_-]?token|secret[_-]?key|password|authorization)["\']?\s*[:=]\s*["\'])([^"\'\r\n]{8,})(["\'])')
        self.b64=re.compile(r'(?<![A-Za-z0-9+/])[A-Za-z0-9+/]{8192,}={0,2}(?![A-Za-z0-9+/])')
    def text(self,s):
        counts=collections.Counter()
        for value in self.values:
            if value in s:counts['credential_redaction']+=s.count(value);s=s.replace(value,'[REDACTED_CREDENTIAL]')
        checks=(any(v in s for v in ('sk-','ghp_','gho_','ghu_','ghs_','ghr_','github_pat_','AKIA')), 'bearer' in s.lower(), 'PRIVATE KEY' in s)
        for active,pattern in zip(checks,self.patterns):
            if active:s,n=pattern.subn('[REDACTED_CREDENTIAL]',s);counts['credential_redaction']+=n
        lowered=s.lower()
        if any(v in lowered for v in ('api_key','api-key','apikey','access_token','access-token','secret_key','secret-key','password','authorization')):
            s,n=self.assignment.subn(lambda m:m[1]+'[REDACTED_CREDENTIAL]'+m[3],s);counts['credential_redaction']+=n
        resources=[]
        def redact_payload(m):
            token=m[0]
            try:
                prefix=base64.b64decode(token[:4096],validate=True)
                if magic(prefix) not in ('zip','gzip','zstd','tar','executable','image','pdf','parquet','numpy','hdf','xz','bz2'):return token
                raw=base64.b64decode(token,validate=True)
            except Exception:return token
            # Encoded archives may contain unique logs; preserve rather than guess.
            if magic(raw[:1024]) in ('zip','gzip','zstd','tar'):return token
            item=dict(bytes=len(raw),sha256=sha(raw),encoding='base64',kind=magic(prefix));resources.append(item)
            return '[RESOURCE_REMOVED bytes='+str(item['bytes'])+' sha256='+item['sha256']+' kind='+item['kind']+']'
        if any(v in s for v in ('iVBORw0KGgo','/9j/','JVBERi0','f0VMRg','TVqQ','k05VTVBZ','UEsDB','H4sI','KLUv')):s=self.b64.sub(redact_payload,s)
        if resources:counts['embedded_resource_removal']+=len(resources)
        return s,{k:v for k,v in counts.items() if v},resources

class PackStore:
    def __init__(self,root,prefix='part'):
        if not re.fullmatch(r'[a-zA-Z0-9_-]+',prefix):raise ValueError('Unsafe pack prefix')
        self.prefix=prefix;self.root=root;self.lock=threading.RLock();self.objects={};self.packs=[];self.buffer=io.BytesIO();self.tar=tarfile.open(fileobj=self.buffer,mode='w');self.raw=0;self.owners=collections.Counter();self.level=12
    def flush(self):
        if not self.raw:return
        self.tar.close();data=self.buffer.getvalue();packed=zstd.ZstdCompressor(level=self.level,threads=2).compress(data)
        assert len(packed)<=25*1024*1024
        name=f'packs/{self.prefix}-{len(self.packs):05d}.tar.zst';(self.root/name).write_bytes(packed)
        self.packs.append(dict(path=name,bytes=len(packed),sha256=sha(packed),tar_bytes=len(data),tar_sha256=sha(data),owner_raw_bytes=dict(self.owners)))
        self.buffer=io.BytesIO();self.tar=tarfile.open(fileobj=self.buffer,mode='w');self.raw=0;self.owners.clear()
    def put(self,data,bench):
        pieces=[]
        # Fixed-size fragments also give complete reassembly for huge outputs.
        for offset in range(0,len(data),256*1024):
            block=data[offset:offset+256*1024];h=sha(block);pieces.append(h)
            with self.lock:
                if h in self.objects:continue
                if self.raw+len(block)>16*1024*1024:self.flush()
                name=f'packs/{self.prefix}-{len(self.packs):05d}.tar.zst';info=tarfile.TarInfo('objects/'+h);info.size=len(block);info.mtime=0
                self.tar.addfile(info,io.BytesIO(block));self.raw+=len(block);self.owners[bench]+=len(block)
                self.objects[h]=dict(pack=name,bytes=len(block))
        return dict(bytes=len(data),sha256=sha(data),parts=pieces)
    def finish(self):
        with self.lock:self.flush();self.tar.close()
        with gzip.open(self.root/'manifests/objects.jsonl.gz','wt',encoding='utf-8',compresslevel=9) as f:
            for key,value in self.objects.items():f.write(json.dumps(dict(sha256=key,**value),separators=(',',':'))+'\n')
        (self.root/'manifests/packs.json').write_bytes(encoded(self.packs))

class JsonShards:
    def __init__(self,root,name):self.root=root;self.name=name;self.buffer=bytearray();self.paths=[]
    def write(self,row):
        b=encoded(row)+b'\n'
        if self.buffer and len(self.buffer)+len(b)>8*1024*1024:self.flush()
        self.buffer.extend(b)
    def flush(self):
        if not self.buffer:return
        p=f'manifests/{self.name}-{len(self.paths):03d}.jsonl.zst';data=zstd.ZstdCompressor(level=12).compress(self.buffer);assert len(data)<25*1024*1024
        (self.root/p).write_bytes(data);self.paths.append(dict(path=p,bytes=len(data),sha256=sha(data)));self.buffer.clear()
    def finish(self):self.flush();return self.paths

class Exporter:
    def __init__(self,args):
        self.args=args;self.ws=args.workspace.resolve();self.root=getattr(args,'output',None) or self.ws/'objrun/experiments/records';self.work=getattr(args,'work',None) or self.ws/'_publication-preview/2026-10-23/records-export';self.work.mkdir(parents=True,exist_ok=True)
        for n in ('runs','summaries','packs','manifests','reports'): (self.root/n).mkdir(parents=True,exist_ok=True)
        if any((self.root/'packs').iterdir()):raise ValueError('Output packs already exist; refusing overwrite')
        self.store=PackStore(self.root);self.store.level=getattr(args,'compression_level',12);self.scrub=Scrubber(self.ws);self.cache={};self.lock=threading.RLock();self.results=[];self.started=time.time()
        self.db_blobs=self.work/('database-blobs-'+str(os.getpid()));self.db_blobs.mkdir(exist_ok=True)
    def transform_text(self,data,bench):
        try:s=data.decode('utf-8-sig');encoding='utf-8-sig' if data.startswith(b'\xef\xbb\xbf') else 'utf-8'
        except UnicodeDecodeError:
            try:s=data.decode('utf-16');encoding='utf-16'
            except UnicodeDecodeError:s=data.decode('latin-1');encoding='latin-1'
        out,changes,resources=self.scrub.text(s)
        transformed=out.encode('utf-8') if changes or encoding!='utf-8' else data
        if encoding!='utf-8':changes['encoding_conversion']=encoding
        result=dict(format='text',content=self.store.put(transformed,bench),transformations=changes)
        if resources:result['removed_resources']=resources
        statuses=collections.Counter(STATUS_RE.findall(out));ids=sorted(set(ID_RE.findall(out)))
        if statuses:result['observed_status_fields']=dict(statuses)
        if ids:result['identifiers']=[list(x) for x in ids[:2000]];result['identifiers_total']=len(ids)
        return result
    def save_database_member(self,data,path):
        h=sha(data);dest=self.db_blobs/h
        with self.lock:
            if not dest.exists():dest.write_bytes(data)
        return dict(disposition='pending-database' if magic(data[:4096])=='sqlite' else 'database-sidecar',source_blob_sha256=h)
    def finish_archive(self,members,collection,path,bench,kind,exclusions):
        """Pair nested SQLite/WAL members after all archive entries are available."""
        by_path={m['path']:m for m in members}
        for m in members:
            if m.get('disposition')!='pending-database':continue
            base=dict(sha256=m['source_blob_sha256'],bytes=m['source_bytes'])
            side=by_path.get(database_sidecar(m['path'],'-wal'))
            wal=dict(sha256=side['source_blob_sha256'],bytes=side['source_bytes']) if side and side.get('source_blob_sha256') else None
            result=self.database(collection,path+'!/'+m['path'],base,wal,bench)
            m.pop('source_blob_sha256',None);m.update(result)
        for m in members:
            if m.get('disposition')!='database-sidecar':continue
            main=database_main(m['path'])
            if main in by_path and by_path[main].get('format') in ('sqlite-tables','sqlite-review-required'):
                m.update(disposition='retained',format='sqlite-sidecar-reference',paired_with=main)
            else:
                m.update(disposition='retained',format='orphan-database-sidecar',pending='no associated main database in archive',content=self.store.put((self.db_blobs/m['source_blob_sha256']).read_bytes(),bench))
            m.pop('source_blob_sha256',None)
        return dict(disposition='retained',format='archive-members',members=members,excluded_member_counts=dict(exclusions),transformations={'archive_expansion':kind})
    def process_payload(self,data,collection,path,bench,depth=0):
        kind=magic(data[:4096]);h=sha(data)
        if kind in ('sqlite','wal') or path.endswith(('-wal','-shm')):return self.save_database_member(data,path)
        if kind in ('tar','zip','gzip','zstd'):
            if RESOURCE_NAME.search(path):return dict(disposition='excluded',reason='identified-resource-archive',detected=kind)
            if depth>4:return dict(disposition='retained',format='nested-archive-review-required',content=self.store.put(data,bench),pending='archive nesting exceeds four')
            members=[];exclusions=collections.Counter()
            try:
                if kind=='zip':
                    with zipfile.ZipFile(io.BytesIO(data)) as z:
                        iterator=((x.filename,z.open(x)) for x in z.infolist() if not x.is_dir())
                        for name,f in iterator:
                            reason=path_policy(collection,name)
                            if reason:exclusions[reason]+=1;f.close();continue
                            raw=f.read();f.close();out=self.process_payload(raw,collection,path+'!/'+name,bench,depth+1)
                            if out.get('disposition')=='excluded':exclusions[out['reason']]+=1
                            else:members.append(dict(path=name,source_sha256=sha(raw),source_bytes=len(raw),**out))
                else:
                    stream=io.BytesIO(data)
                    if kind=='gzip':stream=gzip.GzipFile(fileobj=stream)
                    if kind=='zstd':stream=zstd.ZstdDecompressor().stream_reader(stream)
                    head=stream.read(512)
                    if is_tar_header(head):
                        class Prefix:
                            def __init__(self,h,s):self.h=h;self.s=s
                            def read(self,n=-1):
                                if n<0:r=self.h+self.s.read();self.h=b'';return r
                                r=self.h[:n];self.h=self.h[n:];return r+self.s.read(n-len(r))
                        with tarfile.open(fileobj=Prefix(head,stream),mode='r|',bufsize=1024*1024) as tar:
                            for m in tar:
                                tar.members=[]
                                if not m.isfile():continue
                                if m.sparse and m.size>64*1024*1024:
                                    exclusions['sparse-resource-member']+=1;continue
                                reason=path_policy(collection,m.name)
                                if reason:exclusions[reason]+=1;continue
                                if RESOURCE_NAME.search(m.name):exclusions['resource-member']+=1;continue
                                f=tar.extractfile(m);raw=f.read();out=self.process_payload(raw,collection,path+'!/'+m.name,bench,depth+1)
                                if out.get('disposition')=='excluded':exclusions[out['reason']]+=1
                                else:members.append(dict(path=m.name,source_sha256=sha(raw),source_bytes=len(raw),**out))
                    else:
                        if magic(head) in ('binary','executable','image','pdf','parquet','numpy','hdf','xz','bz2','compress'):return dict(disposition='excluded',reason='compressed-binary-resource-'+magic(head))
                        tail=stream.read(64*1024*1024)
                        if len(tail)==64*1024*1024:return dict(disposition='retained',format='compressed-text-review-required',content=self.store.put(data,bench),pending='decompressed text exceeds 64 MiB; complete original compressed payload preserved')
                        return self.process_payload(head+tail,collection,path+'!/decoded',bench,depth+1)|dict(container_kind=kind)
                return self.finish_archive(members,collection,path,bench,kind,exclusions)
            except (tarfile.TarError,zipfile.BadZipFile,EOFError,zstd.ZstdError,OSError,UnicodeError,ValueError,OverflowError,RuntimeError) as e:
                return dict(disposition='retained',format='archive-review-required',content=self.store.put(data,bench),pending=type(e).__name__)
        if kind in ('executable','image','pdf','parquet','numpy','hdf','xz','bz2','compress','binary'):
            return dict(disposition='excluded',reason='binary-resource-'+kind,detected=kind)
        return dict(disposition='retained',**self.transform_text(data,bench))
    def stream_archive(self,source,head,collection,path,bench,depth=0):
        kind=magic(head);stream=PrefixReader(head,source)
        if kind=='gzip':stream=gzip.GzipFile(fileobj=stream)
        elif kind=='zstd':stream=zstd.ZstdDecompressor().stream_reader(stream)
        prefix=stream.read(512);members=[];excluded=collections.Counter()
        if not is_tar_header(prefix):
            if magic(prefix) in ('binary','executable','image','pdf','parquet','numpy','hdf','xz','bz2','compress'):
                return dict(disposition='excluded',reason='compressed-binary-resource-'+magic(prefix),detected=kind)
            data=prefix+stream.read();return self.process_payload(data,collection,path+'!/decoded',bench,depth+1)
        with tarfile.open(fileobj=ForwardReader(PrefixReader(prefix,stream)),mode='r:') as tar:
            for member in tar:
                tar.members=[]
                if not member.isfile():continue
                if member.sparse and member.size>64*1024*1024:
                    excluded['sparse-resource-member']+=1;continue
                reason=path_policy(collection,member.name)
                if reason:excluded[reason]+=1;continue
                f=tar.extractfile(member);h=f.read(min(4096,member.size));detected=magic(h)
                if detected in ('sqlite','wal') or member.name.endswith(('-wal','-shm')):
                    raw=h+f.read();out=self.save_database_member(raw,member.name)
                    members.append(dict(path=member.name,source_bytes=member.size,source_sha256=sha(raw),**out));continue
                if detected in ('executable','image','pdf','parquet','numpy','hdf','xz','bz2','compress','binary'):
                    excluded['binary-resource-'+detected]+=1;continue
                if detected in ('tar','zip','gzip','zstd') and RESOURCE_NAME.search(member.name):excluded['resource-archive-member']+=1;continue
                if detected in ('tar','gzip','zstd') and member.size>16*1024*1024 and depth<4:
                    out=self.stream_archive(f,h,collection,path+'!/'+member.name,bench,depth+1)
                    raw_sha=None
                elif member.size>64*1024*1024 and detected not in ('zip','tar','gzip','zstd'):
                    out=self.stream_text(f,h,bench);raw_sha=None
                else:
                    raw=h+f.read();raw_sha=sha(raw);out=self.process_payload(raw,collection,path+'!/'+member.name,bench,depth+1)
                if out.get('disposition')=='excluded':excluded[out['reason']]+=1
                else:members.append(dict(path=member.name,source_bytes=member.size,source_sha256=raw_sha,**out))
        return self.finish_archive(members,collection,path,bench,kind,excluded)
    def stream_text(self,source,head,bench):
        decoder=codecs.getincrementaldecoder('utf-8')('surrogateescape');parts=[];hasher=hashlib.sha256();size=0;changes=collections.Counter();status=collections.Counter();carry='';block=head
        while block:
            text=carry+decoder.decode(block);carry=text[-1024:];text=text[:-1024] if len(text)>=1024 else ''
            out,cs,resources=self.scrub.text(text);changes.update(cs);status.update(STATUS_RE.findall(out));b=out.encode('utf-8','surrogateescape');hasher.update(b);size+=len(b);parts.extend(self.store.put(b,bench)['parts']);block=source.read(1024*1024)
        out,cs,resources=self.scrub.text(carry+decoder.decode(b'',final=True));changes.update(cs);b=out.encode('utf-8','surrogateescape');hasher.update(b);size+=len(b);parts.extend(self.store.put(b,bench)['parts'])
        return dict(disposition='retained',format='text',content=dict(bytes=size,sha256=hasher.hexdigest(),parts=parts),transformations=dict(changes),observed_status_fields=dict(status))
    def database(self,collection,path,base,wal,bench):
        key=sha((base['sha256']+':'+(wal or {}).get('sha256','')).encode())
        with self.lock:
            if key in self.cache:return self.cache[key]
        folder=self.work/'sqlite-copies'/(key+'-'+str(os.getpid())+'-'+str(threading.get_ident()));folder.mkdir(parents=True,exist_ok=True);db=folder/'database.sqlite'
        shutil.copyfile(self.db_blobs/base['sha256'],db)
        if wal:shutil.copyfile(self.db_blobs/wal['sha256'],folder/'database.sqlite-wal')
        result=dict(disposition='retained',format='sqlite-tables',source_database_sha256=base['sha256'],wal_sha256=(wal or {}).get('sha256'),wal_bytes=(wal or {}).get('bytes',0),tables=[],transformations={'sqlite_consistent_export':True})
        connection=None;cursor=None
        try:
            connection=sqlite3.connect(db);connection.execute('PRAGMA busy_timeout=5000')
            # BEGIN pins the snapshot including valid committed WAL frames.
            connection.execute('BEGIN');integrity=connection.execute('PRAGMA quick_check').fetchall();assert integrity==[('ok',)],integrity[:3]
            fk=connection.execute('PRAGMA foreign_key_check').fetchall();result['foreign_key_violation_count']=len(fk)
            for name,sql in connection.execute("SELECT name,sql FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%' ORDER BY name").fetchall():
                q='"'+name.replace('"','""')+'"';columns=connection.execute('PRAGMA table_info('+q+')').fetchall();cols=[x[1] for x in columns];count=connection.execute('SELECT COUNT(*) FROM '+q).fetchone()[0]
                if name.lower() in ('cache','http_cache','download_cache','embedding_cache','embeddings'):
                    result['tables'].append(dict(name=name,source_rows=count,excluded=True,reason='explicit-cache-table',columns=cols));continue
                try:cursor=connection.execute('SELECT rowid,* FROM '+q+' ORDER BY rowid');rowid=True
                except sqlite3.OperationalError:
                    keys=[x[1] for x in sorted(columns,key=lambda x:x[5]) if x[5]];order=','.join('"'+k.replace('"','""')+'"' for k in keys)
                    cursor=connection.execute('SELECT * FROM '+q+(' ORDER BY '+order if order else ''));rowid=False
                chunks=[];buffer=bytearray();h=hashlib.sha256();outbytes=0;rows=0;changes=collections.Counter();status=collections.Counter()
                def flush():
                    nonlocal buffer
                    if buffer:chunks.extend(self.store.put(bytes(buffer),bench)['parts']);buffer.clear()
                for values in cursor:
                    output=[]
                    for column_index,value in enumerate(values):
                        ci=column_index-(1 if rowid else 0)
                        if 0<=ci<len(cols) and cols[ci].lower() in ('status','state','outcome','finish_reason') and isinstance(value,str):
                            if value.lower() in ('success','succeeded','passed','completed','failed','failure','error','interrupted','cancelled','canceled','aborted','timeout','timed_out','needs_attention'):status[value.lower()]+=1
                        if isinstance(value,bytes):
                            if magic(value[:4096]) in ('text','unknown-encoding'):
                                txt,cs,rs=self.scrub.text(value.decode('utf-8',errors='backslashreplace'));value={'blob_text':txt};changes.update(cs)
                            elif len(value)<=4096:value={'blob_base64':base64.b64encode(value).decode()}
                            else:value={'resource_removed':True,'bytes':len(value),'sha256':sha(value),'kind':magic(value[:4096])};changes['blob_resource_removal']+=1
                        elif isinstance(value,str):value,cs,rs=self.scrub.text(value);changes.update(cs);status.update(STATUS_RE.findall(value))
                        elif isinstance(value,float) and (value!=value or value in (float('inf'),float('-inf'))):value={'sqlite_float':repr(value)}
                        output.append(value)
                    b=encoded(dict(rowid=output[0] if rowid else None,values=output[1:] if rowid else output))+b'\n';h.update(b);outbytes+=len(b);rows+=1
                    if buffer and len(buffer)+len(b)>256*1024:flush()
                    buffer.extend(b)
                    if len(buffer)>=256*1024:flush()
                flush();assert rows==count
                result['tables'].append(dict(name=name,sql=sql,columns=cols,source_rows=count,exported_rows=rows,order='rowid' if rowid else 'primary-key',content=dict(bytes=outbytes,sha256=h.hexdigest(),parts=chunks),transformations=dict(changes),observed_status_fields=dict(status)))
            connection.rollback();connection.close();result['integrity']='ok';result['rows_verified']=True
        except Exception as e:
            result=dict(disposition='retained',format='sqlite-review-required',pending=type(e).__name__,database=self.store.put((self.db_blobs/base['sha256']).read_bytes(),bench),wal=self.store.put((self.db_blobs/wal['sha256']).read_bytes(),bench) if wal else None)
        if cursor is not None:
            try:cursor.close()
            except Exception:pass
        if connection is not None:
            try:connection.close()
            except Exception:pass
        # Copies are temporary, scoped files; unique source archives remain untouched.
        try:
            for p in folder.iterdir():
                if p.is_file():p.unlink()
            folder.rmdir()
        except PermissionError:
            # A Windows lock on a disposable copy must not discard an export or
            # mislabel the immutable source as corrupt. Leave the copy for review.
            result['temporary_copy_cleanup']='deferred-windows-file-lock'
        with self.lock:self.cache[key]=result
        return result
    def collection(self,item):
        name=item['id'];run=self.ws/'_objrun-archive/collections'/name;record=json.loads((run/'record.json').read_text(encoding='utf-8'));started=time.time()
        assert record['restore_verified'] and record['integrity_verified']
        rows=[];required={};by_path={};counts=collections.defaultdict(collections.Counter);excluded=collections.Counter();excluded_bytes=collections.Counter();examples={}
        with gzip.open(run/'files-sha256.jsonl.gz','rt',encoding='utf-8') as f:
            for line in f:
                row=json.loads(line)
                if 'sha256' not in row:continue
                path=row['path'];bench=bench_of(name,path);counts[bench]['discovered_files']+=1;counts[bench]['discovered_bytes']+=row['bytes'];reason=path_policy(name,path)
                if getattr(self.args,'benches',None) and bench not in self.args.benches:reason='outside-requested-bench-selection'
                if name=='workspace-tmp' and (path.startswith('theophyseval-runtime/') or '/parquet-runtime/' in path):reason='installed-runtime'
                if reason:excluded[reason]+=1;excluded_bytes[reason]+=row['bytes'];counts[bench]['excluded_files']+=1;continue
                rows.append(row);by_path[path]=row;required.setdefault(row['sha256'],row)
        # Include excluded aliases only as possible canonical TAR hardlink bodies.
        bodies={}
        with gzip.open(run/'files-sha256.jsonl.gz','rt',encoding='utf-8') as f:
            for line in f:
                row=json.loads(line)
                if row.get('sha256') in required:bodies[row['path']]=row
        found={};db_hashes=set();sidecars={x['sha256'] for x in rows if database_main(x['path']) is not None};manifest=JsonShards(self.root,name);scopes={};pending=[]
        if required:
            base=[str(self.args.restic),'--repo',str(self.ws/'_objrun-archive/restic'),'--cache-dir',str(self.work/'restic-cache'),'--insecure-no-password']
            source=pathlib.Path(record['source']);prefix='/'+source.as_posix().replace(':','').strip('/')
            dump=[record['snapshot'],'/payload.tar'] if record.get('transport')=='tar' else [record['snapshot']+':'+prefix,'/']
            with (self.work/(name+'.stderr')).open('wb') as err:
                proc=subprocess.Popen(base+['dump']+dump,stdout=subprocess.PIPE,stderr=err)
                try:
                    with tarfile.open(fileobj=ForwardReader(proc.stdout),mode='r:') as tar:
                        for member in tar:
                            tar.members=[]
                            if not member.isfile():continue
                            path=member.name.lstrip('/').removeprefix('./');row=bodies.get(path)
                            # Canonical hardlink body can be under an excluded alias.
                            if row is None:continue
                            h=row['sha256']
                            if h in found:continue
                            target=required[h];bench=bench_of(name,target['path']);f=tar.extractfile(member);head=f.read(min(4096,member.size));kind=magic(head)
                            is_sidecar=h in sidecars
                            if kind=='sqlite' or is_sidecar:
                                dest=self.db_blobs/h
                                if not dest.exists():
                                    temp=dest.with_name(h+'.'+threading.current_thread().name+'.partial')
                                    with temp.open('wb') as out:out.write(head);shutil.copyfileobj(f,out,1024*1024)
                                    assert file_sha(temp)==h
                                    try:os.link(temp,dest)
                                    except FileExistsError:pass
                                    temp.unlink()
                                if kind=='sqlite':found[h]=dict(disposition='pending-database');db_hashes.add(h);continue
                                if row['bytes']==0:found[h]=dict(disposition='retained',**self.transform_text(b'',bench))
                                else:found[h]=dict(disposition='database-sidecar')
                                continue
                            with self.lock:cached=self.cache.get(h)
                            if cached is not None:found[h]=cached;continue
                            if kind in ('tar','zip','gzip','zstd') and RESOURCE_NAME.search(target['path']):out=dict(disposition='excluded',reason='identified-resource-archive',detected=kind)
                            elif kind in ('executable','image','pdf','parquet','numpy','hdf','xz','bz2','compress','binary'):out=dict(disposition='excluded',reason='binary-resource-'+kind,detected=kind)
                            elif kind in ('tar','gzip','zstd') and member.size>16*1024*1024:
                                try:out=self.stream_archive(f,head,name,target['path'],bench)
                                except Exception as e:out=dict(disposition='retained',format='partial-archive-review-required',pending=type(e).__name__,original_transport_sha256=h,original_transport_bytes=member.size)
                            elif member.size>64*1024*1024 and kind not in ('zip',):out=self.stream_text(f,head,bench)
                            else:
                                data=head+f.read();assert sha(data)==h,(name,path)
                                try:out=self.process_payload(data,name,target['path'],bench)
                                except Exception as e:out=dict(disposition='retained',format='unclassified-payload-review-required',pending=type(e).__name__,source_payload_sha256=h,source_payload_bytes=len(data))
                            with self.lock:self.cache[h]=out
                            found[h]=out
                    while proc.stdout.read(4*1024*1024):pass
                    if proc.wait():raise RuntimeError('Restic dump failed: '+name)
                finally:
                    if proc.poll() is None:proc.kill();proc.wait()
        for row in rows:
            path=row['path'];h=row['sha256'];bench=bench_of(name,path);scope=scope_of(name,path);out=found.get(h)
            if out is None:
                with self.lock:out=self.cache.get(h)
            if out is None:
                pending.append(dict(path=path,reason='canonical-hardlink-body-not-read',source_sha256=h));counts[bench]['unverified_files']+=1;continue
            if out['disposition']=='pending-database':out=self.database(name,path,row,by_path.get(database_sidecar(path,'-wal')),bench)
            elif database_main(path) is not None or out['disposition']=='database-sidecar':
                # Sidecar ownership is represented with the main database export.
                main=database_main(path)
                if main in by_path and by_path[main]['sha256'] in db_hashes:counts[bench]['database_sidecars']+=1;continue
                out=dict(disposition='retained',format='orphan-database-sidecar',content=self.store.put((self.db_blobs/h).read_bytes(),bench),pending='no associated main database')
            if out['disposition']=='excluded':counts[bench]['excluded_files']+=1;excluded[out['reason']]+=1;excluded_bytes[out['reason']]+=row['bytes'];examples.setdefault(out['reason'],path);continue
            counts[bench]['retained_files']+=1;counts[bench]['retained_source_bytes']+=row['bytes']
            entry=dict(collection=name,path=path,bench=bench,run_scope=scope,source_bytes=row['bytes'],source_sha256=h,**out)
            manifest.write(entry)
            s=scopes.setdefault((bench,scope),dict(bench=bench,run_scope=scope,collection=name,retained_files=0,status_fields=collections.Counter(),identifiers=set()))
            s['retained_files']+=1;s['status_fields'].update(out.get('observed_status_fields',{}));s['identifiers'].update(tuple(x) for x in out.get('identifiers',[]))
            for table in out.get('tables',[]):s['status_fields'].update(table.get('observed_status_fields',{}))
            if out.get('pending'):pending.append(dict(path=path,reason=out['pending'],format=out['format']));counts[bench]['unverified_files']+=1
        for s in scopes.values():s['status_fields']=dict(s['status_fields']);s['identifiers']=[list(x) for x in sorted(s['identifiers'])]
        result=dict(collection=name,snapshot=record['snapshot'],source_root=item['source_root'],source_files=item['source_files'],selected_source_files=len(rows),by_bench={k:dict(v) for k,v in counts.items()},manifest_shards=manifest.finish(),scopes=list(scopes.values()),excluded_counts=dict(excluded),excluded_bytes=dict(excluded_bytes),excluded_examples=examples,pending=pending,elapsed_seconds=round(time.time()-started,1))
        (self.work/(name+'.result.json')).write_bytes(encoded(result))
        with self.lock:self.results.append(result)
        print(json.dumps(dict(completed=name,selected=len(rows),pending=len(pending),seconds=result['elapsed_seconds'],packs=len(self.store.packs))),flush=True)
        return result
    def run(self):
        catalog=json.loads((self.ws/'objrun/experiments/archive-catalog.json').read_text(encoding='utf-8'));assert len(catalog['collections'])==66 and catalog['global_data_check']['exit_code']==0
        items=sorted(catalog['collections'],key=lambda x:x['added_packed_bytes'],reverse=not getattr(self.args,'small_first',False))
        if getattr(self.args,'only',None):items=[x for x in items if x['id'] in self.args.only]
        if getattr(self.args,'skip',None):items=[x for x in items if x['id'] not in self.args.skip]
        errors=[]
        with concurrent.futures.ThreadPoolExecutor(max_workers=self.args.workers) as pool:
            jobs={pool.submit(self.collection,x):x['id'] for x in items}
            for future in concurrent.futures.as_completed(jobs):
                try:future.result()
                except Exception as e:
                    errors.append(dict(collection=jobs[future],error=type(e).__name__,message=str(e)));print(json.dumps(errors[-1]),flush=True)
                    (self.work/(jobs[future]+'.exception.txt')).write_text(traceback.format_exc(),encoding='utf-8')
        self.store.finish();benches=collections.defaultdict(collections.Counter);runrows=collections.defaultdict(list)
        for result in self.results:
            for b,counts in result['by_bench'].items():benches[b].update(counts)
            for s in result.pop('scopes'):runrows[s['bench']].append(s)
        for b,rows in runrows.items():
            with (self.root/'runs'/f'{b}.jsonl').open('wb') as f:
                for row in sorted(rows,key=lambda x:x['run_scope']):f.write(encoded(row)+b'\n')
            benches[b]['run_scopes_retained']=len(rows)
        for pack in self.store.packs:
            total=sum(pack['owner_raw_bytes'].values())
            for b,n in pack['owner_raw_bytes'].items():benches[b]['attributed_pack_bytes']+=round(pack['bytes']*n/total)
        report=dict(format_version=1,completed=not errors,collections_expected=len(items),collections_processed=len(self.results),errors=errors,benches={b:dict(v) for b,v in benches.items()},pending=sum(len(x['pending']) for x in self.results),elapsed_seconds=round(time.time()-self.started,1),pack_bytes=sum(p['bytes'] for p in self.store.packs),pack_count=len(self.store.packs),unique_fragments=len(self.store.objects),collections=self.results)
        (self.root/'catalog.json').write_bytes(encoded(report));(self.root/'reports/export.json').write_bytes(encoded({k:v for k,v in report.items() if k!='collections'}))
        print(json.dumps({k:v for k,v in report.items() if k not in ('collections','benches')}),flush=True)

def main():
    ap=argparse.ArgumentParser(description=__doc__);ap.add_argument('--workspace',type=pathlib.Path,required=True);ap.add_argument('--restic',type=pathlib.Path,required=True);ap.add_argument('--workers',type=int,default=2);ap.add_argument('--output',type=pathlib.Path);ap.add_argument('--work',type=pathlib.Path);ap.add_argument('--compression-level',type=int,default=12);ap.add_argument('--benches',nargs='+');ap.add_argument('--only',nargs='+');ap.add_argument('--skip',nargs='+');ap.add_argument('--small-first',action='store_true');args=ap.parse_args();Exporter(args).run()
if __name__=='__main__':main()
