"""Private assertion process -> separate Scala/browser execution namespace."""
import base64
import hashlib
import io
import json
from pathlib import Path, PurePosixPath
import shutil
import subprocess
import tarfile

LIMIT = 128 * 1024**2

def pack(raw):
    if len(raw) > LIMIT: raise ValueError('payload_limit')
    return {'base64': base64.b64encode(raw).decode(), 'sha256': hashlib.sha256(raw).hexdigest()}

def unpack(value):
    if type(value) is not dict or set(value) != {'base64', 'sha256'}: raise ValueError('exact_blob')
    raw = base64.b64decode(value['base64'], validate=True)
    if len(raw) > LIMIT or hashlib.sha256(raw).hexdigest() != value['sha256']: raise ValueError('blob_integrity')
    return raw

def archive_project(path):
    raw = io.BytesIO()
    with tarfile.open(fileobj=raw, mode='w') as out:
        for source in sorted(Path(path).rglob('*')):
            if source.is_symlink(): raise ValueError('project_symlink')
            if source.is_file():
                body = source.read_bytes()
                entry = tarfile.TarInfo(source.relative_to(path).as_posix()); entry.size = len(body); entry.mode = 0o644
                out.addfile(entry, io.BytesIO(body))
                if raw.tell() > LIMIT: raise ValueError('project_limit')
    return pack(raw.getvalue())

def restore_project(blob, path):
    root = Path(path)
    with tarfile.open(fileobj=io.BytesIO(unpack(blob)), mode='r:') as incoming:
        seen = set(); total = 0
        for entry in incoming:
            name = PurePosixPath(entry.name)
            if (not entry.isfile() or name.is_absolute() or any(x in ('..', '.') for x in name.parts)
                    or entry.name in seen or '\\' in entry.name or not name.parts): raise ValueError('project_member')
            seen.add(entry.name); total += entry.size
            if total > LIMIT: raise ValueError('project_limit')
            target = root.joinpath(*name.parts)
            if any(x.is_symlink() for x in [target, *target.parents]): raise ValueError('project_symlink')
            target.parent.mkdir(parents=True, exist_ok=True); target.write_bytes(incoming.extractfile(entry).read()); target.chmod(0o644)

class ScalaBridge:
    def __init__(self, callback, session): self.callback=callback; self.session=session; self.sequence=0; self.failure=None
    def __enter__(self):
        self.original_run = subprocess.run; self.original_which = shutil.which
        subprocess.run = self.run
        shutil.which = lambda name, *args, **kwargs: '/usr/local/bin/sbt' if name=='sbt' else self.original_which(name,*args,**kwargs)
        return self
    def __exit__(self, *args): subprocess.run=self.original_run; shutil.which=self.original_which
    def run(self, argv, **kwargs):
        if (not isinstance(argv,list) or argv not in (['/usr/local/bin/sbt','compile'], ['/usr/local/bin/sbt','test'])
                or set(kwargs)!={'capture_output','text','timeout','cwd'} or kwargs['capture_output'] is not True
                or kwargs['text'] is not True or str(kwargs['cwd'])!='/root/localtest'
                or kwargs['timeout'] != (300 if argv[-1]=='compile' else 600)):
            raise ValueError('original_scala_call_required')
        request={'session':self.session,'sequence':self.sequence,'kind':'scala','argv':argv,'timeout':kwargs['timeout'],
                 'project':archive_project('/root/localtest')}
        try:
            reply=self.callback(request)
            if reply['session']!=self.session or reply['sequence']!=self.sequence: raise ValueError('callback_identity')
            self.sequence+=1
            if reply['status']=='timeout': raise subprocess.TimeoutExpired(argv,kwargs['timeout'])
            if reply['status']!='completed': raise RuntimeError('candidate_execution_fault')
            if type(reply['returncode']) is not int: raise ValueError('callback_exit_code')
            return subprocess.CompletedProcess(argv,reply['returncode'],unpack(reply['stdout']).decode('utf8',errors='replace'),unpack(reply['stderr']).decode('utf8',errors='replace'))
        except Exception as error:
            self.failure={'type':type(error).__name__,'detail':str(error)}
            raise

class BrowserBridge:
    def __init__(self, endpoint): self.endpoint=endpoint
    def __enter__(self):
        from playwright.sync_api import BrowserType
        self.kind=BrowserType; self.launch=BrowserType.launch
        endpoint=self.endpoint
        def remote(kind, **kwargs):
            if kind.name!='chromium' or kwargs!={'headless':True}: raise ValueError('original_chromium_launch_required')
            return kind.connect(endpoint)
        BrowserType.launch=remote
        return self
    def __exit__(self,*args): self.kind.launch=self.launch
