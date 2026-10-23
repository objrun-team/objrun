"""Isolated adapter imports; unchanged shared helpers are read only."""
import sys
from pathlib import Path
ROOT=next(p for p in Path(__file__).resolve().parents if (p/'.phase1-data/terminal-bench/source.json').is_file())
LOCAL=Path(__file__).resolve().parent
SHARED=ROOT/'scripts/benchmark-campaign/full-f/terminal-bench'
def install():
 sys.path[:0]=[str(LOCAL),'F:\\git\\TgEngin-handoff-2026-10-07\\TgEngin\\scripts\\benchmark-campaign\\full-f\\novaeve_formal_v1\\group-04\\adapter_3\\versions\\pipeline-wx-v50',str(SHARED)]
 return ROOT
