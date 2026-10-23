import os, runpy
from pathlib import Path
ROOT=Path(__file__).resolve().parents[4]
for key in list(os.environ):
    if 'API_KEY' in key or key.endswith('_TOKEN'): os.environ.pop(key,None)
os.environ['TGENGIN_CHB_HOME']=str(ROOT/'.phase1-data/chembench')
os.environ['TGENGIN_CHB_LEVEL']='1'
runpy.run_path(str(ROOT/'examples/benchmark/chembench/stand.py'),run_name='__main__')
