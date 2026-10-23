"""JSON stdin wrapper for deterministic private MCQ scoring."""
from pathlib import Path
import json
import sys
sys.path.insert(0,str(Path(__file__).resolve().parents[3]/'scripts/labbench'))
from protocol import grade

if __name__=='__main__':
    request=json.load(sys.stdin)
    print(json.dumps(grade(request['candidate'],request['row'])))
