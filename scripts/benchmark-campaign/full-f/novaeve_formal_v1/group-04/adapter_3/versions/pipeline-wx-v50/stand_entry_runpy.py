"""Runpy bootstrap for the exact native-qualified Stand entry bytes."""
import sys,runpy
from pathlib import Path
HERE=Path(__file__).resolve().parent
sys.path.insert(0,str(HERE))
runpy.run_path(str(HERE/'stand_entry.py'),run_name='__main__' if __name__=='__main__' else 'pipeline_static_preflight')
