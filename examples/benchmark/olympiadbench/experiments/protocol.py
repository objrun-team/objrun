"""OlympiadBench Physics EN Text 236: frozen, rule-scored two-arm protocol."""
import hashlib
import json

NAME = 'olympiadbench-formal-20261017-v1-deepseek-c16'
REVISION = '91184b52131e7fc9455fef848035173aea8cc01a'
UPSTREAM = 'ba5b26a7e2849940b598a9159c1190daa2b9175f'
DATA_SHA = '69c45e28ff9d8cf2e385d1b298e9ef2264dfa83755cac956d3e3e7b37e4ce4f6'
BASE = 'https://api.deepseek.com'
PARAMETERS = {'model': 'deepseek-flash', 'thinking': {'type': 'enabled'},
              'reasoning_effort': 'high', 'max_tokens': 16384, 'stream': False}
TOOLS = ['submit', 'verify', 'task_tree', 'node_load']
SYSTEM = 'You are an AI assistant. Please answer the following Physics competition questions as required.'

def digest(value):
    if not isinstance(value, bytes):
        value = (value if isinstance(value, str) else json.dumps(value, sort_keys=True, ensure_ascii=False, allow_nan=False)).encode()
    return hashlib.sha256(value).hexdigest()

RULES = {'upstream': UPSTREAM, 'entry': 'inference/judge.py', 'judger': 'inference/code/math_judger.py',
         'argumentOrder': ['extracted_candidate', 'final_answer[0]'],
         'extraction': 'extract_answer(False, candidate, False): official English competition prompt',
         'tolerance': 'official per-row error scalar/list; missing list item 1e-8; Tuple uses default',
         'empty': 'valid model failure', 'no_submission': 'valid method failure',
         'exceptions': 'unknown; never convert worker failure/timeout into incorrect',
         'deps': {'sympy': '1.12', 'antlr4-python3-runtime': '4.11.0', 'mpmath': '1.3.0'}}
PROTOCOL_SHA = digest(RULES)
