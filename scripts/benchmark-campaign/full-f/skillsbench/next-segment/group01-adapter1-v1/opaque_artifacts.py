"""Bounded daemon TAR decoder; opaque browser/Scala sources never execute here."""
import hashlib,io,tarfile
from pathlib import PurePosixPath
def parse_daemon_tar(raw,policy):
    if len(raw)>policy['maximumBytes']+(policy['maximumFiles']+8)*2048: raise ValueError('archive_limit')
    root=PurePosixPath(policy['path']);seen=set();files=[];total=0
    with tarfile.open(fileobj=io.BytesIO(raw),mode='r:') as archive:
        for member in archive:
            name=member.name.removeprefix('./').rstrip('/')
            parts=name.split('/')
            if not name or name.startswith('/') or '\\' in name or any(p in ('','.','..') for p in parts) or name in seen: raise ValueError('archive_member')
            seen.add(name)
            if parts[0]!=root.name: raise ValueError('archive_root')
            if member.isdir(): continue
            if not member.isfile() or policy['kind']=='file' and len(parts)!=1 or policy['kind']=='directory' and len(parts)==1: raise ValueError('ordinary_file_only')
            total+=member.size
            if total>policy['maximumBytes'] or len(files)>=policy['maximumFiles']: raise ValueError('artifact_limit')
            body=archive.extractfile(member).read(); destination=root.parent.joinpath(*parts).as_posix()
            files.append({'destination':destination,'body':body,'sha256':hashlib.sha256(body).hexdigest()})
    return {'files':files}
