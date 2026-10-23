"""Isolated adapter imports; unchanged shared helpers are read only."""
import sys
from pathlib import Path
ROOT=next(p for p in Path(__file__).resolve().parents if (p/'.phase1-data/terminal-bench/source.json').is_file())
LOCAL=Path(__file__).resolve().parent
SHARED=ROOT/'scripts/repair-2026-10-10/full-f/terminal-bench'
def install():
 sys.path[:0]=[str(LOCAL),str(SHARED)]
 return ROOT
