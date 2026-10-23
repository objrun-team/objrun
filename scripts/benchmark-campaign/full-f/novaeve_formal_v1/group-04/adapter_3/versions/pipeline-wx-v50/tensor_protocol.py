import base64,json,os,time,stat
from pathlib import Path
LIMIT=1024**3


def write(path, value):
    path = Path(path)
    raw = json.dumps(value, separators=(',', ':'), allow_nan=False).encode()
    if len(raw) > LIMIT:
        raise ValueError('Mailbox message exceeds transport data limit')
    temporary = path.with_suffix('.new')
    temporary.write_bytes(raw)
    os.replace(temporary, path)

def read(path):
    path=Path(path)
    info=path.lstat()
    if not stat.S_ISREG(info.st_mode) or info.st_size>LIMIT:raise ValueError('Mailbox requires bounded regular data file')
    fd=os.open(path,os.O_RDONLY|getattr(os,'O_NOFOLLOW',0))
    with os.fdopen(fd,'rb') as stream:
        actual=os.fstat(stream.fileno())
        if (actual.st_dev,actual.st_ino)!=(info.st_dev,info.st_ino):raise ValueError('Mailbox file identity changed')
        raw=stream.read(LIMIT+1)
    if len(raw) > LIMIT:
        raise ValueError('Mailbox message exceeds transport data limit')
    return json.loads(raw)

def tensor_pack(tensor):
    tensor = tensor.detach().cpu().contiguous()
    return {'dtype': str(tensor.dtype).split('.')[-1], 'shape': list(tensor.shape),
            'data': base64.b64encode(tensor.view(__import__('torch').uint8).numpy().tobytes()).decode()}

def tensor_unpack(value):
    import torch
    allowed = {'float32', 'float64', 'int64', 'int32', 'uint8', 'bool', 'bfloat16', 'float16'}
    if value['dtype'] not in allowed or any(type(n) is not int or n < 0 for n in value['shape']):
        raise ValueError('Unsupported tensor descriptor')
    raw = base64.b64decode(value['data'], validate=True)
    dtype = getattr(torch, value['dtype'])
    elements = 1
    for n in value['shape']:
        elements *= n
    if len(raw) != elements * torch.empty((), dtype=dtype).element_size():
        raise ValueError('Tensor byte length mismatch')
    return torch.frombuffer(bytearray(raw), dtype=dtype).clone().reshape(value['shape'])