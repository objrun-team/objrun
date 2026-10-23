"""Sample owned Buildx temp allocation with an explicit64MiB race reserve."""
from pathlib import Path
import os
import shutil
import stat
import skb_artifact_storage_v2 as storage

TEMP_RESERVE=64*1024**2


def observe(layout):
    storage.validate_descriptor(layout)
    root=Path(layout['storePhysical']);temp=Path(layout['directories']['tmp'])
    storage.ordinary(root,Path('D:/'))
    unit=storage.cluster_size(root);total=TEMP_RESERVE;files=dirs=0;vanished=[]
    def transient(path):
        p=Path(path)
        return p!=temp and temp in p.parents
    def gone(path):
        storage.require(transient(path),'build_store_race','Only exact owned transient Buildx temp may disappear')
        vanished.append(str(path))
    def error(e):
        if isinstance(e,FileNotFoundError):gone(e.filename)
        else:raise e
    for parent,names,entries in os.walk(root,followlinks=False,onerror=error):
        try:storage.ordinary(parent,root)
        except FileNotFoundError:gone(parent);continue
        total+=unit;dirs+=1
        for name in names:
            try:storage.ordinary(Path(parent)/name,root)
            except FileNotFoundError:gone(Path(parent)/name)
        for name in entries:
            path=Path(parent)/name
            try:z=path.lstat()
            except FileNotFoundError:gone(path);continue
            storage.require(stat.S_ISREG(z.st_mode) and z.st_nlink==1 and not getattr(z,'st_file_attributes',0)&0x400,
                            'build_store_kind','Nonregular/reparse/hardlinked entry refuses')
            total+=max(unit,(z.st_size+unit-1)//unit*unit);files+=1
    free={k:shutil.disk_usage(k+':/').free for k in ('C','D','F')}
    storage.require(total<=storage.STORE_CAP and free['D']>=storage.D_MIN,'build_store_bound','Owned sampled allocation/reserve exceeded')
    return {'allocatedEnvelopeBytes':total,'allocationUnit':unit,'files':files,'directories':dirs,'volumeFreeBytes':free,
            'transientReservationBytes':TEMP_RESERVE,'vanishedOwnedTempPaths':vanished,'kernelQuotaCertified':False,
            'scope':'Polled resource envelope with64MiB conservative owned temp reservation; immutable evidence path disappearance still rejects'}
