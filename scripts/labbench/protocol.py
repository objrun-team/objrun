"""Frozen LAB-Bench public MCQ protocol; no provider calls on import."""
import hashlib
import json
import re

NAME = 'labbench-formal-20261019-v2-openrouter-c16'
REVISION = '998a8e0a40cf116c80e1b0e7a805ebb5fb9fa838'
MODEL = 'deepseek/deepseek-v4.1-flash'
CANONICAL = 'deepseek/deepseek-v4.1-flash-20260910'
BASE = 'https://openrouter.ai/api/v1'
PARAMETERS = {'model': MODEL, 'provider': {'only': ['digitalocean'], 'allow_fallbacks': False, 'require_parameters': True},
              'reasoning': {'enabled': True, 'effort': 'high', 'exclude': False},
              'temperature': 0, 'max_tokens': 16384, 'stream': False}
TOOLS = ['submit', 'verify', 'task_tree', 'node_load']
SYSTEM = 'You are an AI assistant. Solve the biology question using only the supplied question and choices.'
REFUSE = 'Insufficient information to answer the question'
DEFECT = 'ded3f6ac-c54c-4626-86b4-cc607a44334f'


def digest(value):
    if not isinstance(value, bytes):
        value = (value if isinstance(value, str) else json.dumps(value, sort_keys=True, ensure_ascii=False, allow_nan=False)).encode()
    return hashlib.sha256(value).hexdigest()


def parse(candidate, count):
    text = candidate.strip()
    tags = re.findall(r'\[ANSWER\](.*?)\[/ANSWER\]', text, re.I | re.S)
    if tags:
        if len(tags) != 1 or len(re.findall(r'\[/?ANSWER\]', text, re.I)) != 2:
            return None
        text = tags[0].strip()
    elif re.search(r'\[/?ANSWER', text, re.I):
        return None
    if re.fullmatch('[A-Z]', text.upper()) and ord(text.upper()) - ord('A') < count:
        return text.upper()
    return None


def grade(candidate, row):
    label = parse(candidate, row['choiceCount'])
    return {'valid': True, 'parsed': label is not None, 'label': label,
            'passed': label == row['target'], 'sure': label is not None and label != row['unsure'],
            'abstain': label == row['unsure'], 'formatInvalid': label is None,
            'candidateSha256': digest(candidate), 'taskId': row['id'], 'permutationSha256': row['permutationSha256'],
            'protocolSha256': PROTOCOL_SHA}


RULES = {'parser': 'exactly one ANSWER block containing one in-range letter, else bare single letter; uppercase; never reasoning',
         'score': 'official randomized ideal identity, exact label; parse failure uses UnanswerableError semantics',
         'feedback': 'parsed format note only; correct boolean and empty note',
         'knownDuplicateChoice': DEFECT, 'unit': 'one full MCQ', 'oracleFeedback': True}
PROTOCOL_SHA = digest({'revision': REVISION, 'rules': RULES, 'parameters': PARAMETERS})
