"""One-bit GPQA adapter. The official parser and answer comparison stay unchanged."""
import argparse
import datetime
import hashlib
import importlib.util
import json
import os
from http.server import ThreadingHTTPServer
from pathlib import Path

parser = argparse.ArgumentParser()
parser.add_argument('--source', required=True)
parser.add_argument('--ready', required=True)
parser.add_argument('--events', required=True)
parser.add_argument('--selftest', action='store_true')
args = parser.parse_args()
os.environ['TGENGIN_GPQA_LEVEL'] = '0'
spec = importlib.util.spec_from_file_location('official_gpqa_adapter', args.source)
base = importlib.util.module_from_spec(spec)
spec.loader.exec_module(base)


def binary(answer, item):
    # Both unparseable answers and parsed wrong choices produce exactly this shape.
    return {'value': bool(base.judge(answer, item)[1])}


checks = 0
for item in base.BOOK.values():
    for index, letter in enumerate('ABCD'):
        result = binary(f'The correct answer is ({letter})', item)
        assert result == {'value': index == item['_example'].correct_index}
        checks += 1
    assert binary('I do not know.', item) == {'value': False}
    checks += 1
assert len(base.BOOK) == 198
if args.selftest:
    print(json.dumps({'passed': True, 'questions': 198, 'checks': checks,
                      'feedbackKeys': ['value'], 'seed': base.SEED}))
    raise SystemExit(0)


class Handler(base.Handler):
    def do_GET(self):
        if self.path == '/health':
            self._send({'ok': True, 'items': len(base.BOOK), 'seed': base.SEED,
                        'level': 0, 'feedback': 'binary-only', 'selftestChecks': checks})
        else:
            super().do_GET()

    def do_POST(self):
        if self.path not in ('/ready', '/correct'):
            self._send({'error': 'unknown_route'}, 404)
            return
        try:
            body = json.loads(self.rfile.read(int(self.headers.get('content-length') or 0)))
            tid, item, answer = base.answer_of(body)
            if item is None:
                raise LookupError('UnknownTask')
            result = {'value': True} if self.path == '/ready' else binary(answer, item)
            with open(args.events, 'a', encoding='utf-8') as file:
                file.write(json.dumps({'at': datetime.datetime.now(datetime.timezone.utc).isoformat(),
                                       'taskId': tid, 'node': self.path,
                                       'candidateSha256': hashlib.sha256(answer.encode()).hexdigest(),
                                       'response': result}) + '\n')
            self._send(result)
        except Exception as error:
            self._send({'valid': False, 'outcome': 'grader_error',
                        'error': type(error).__name__}, 503)


server = ThreadingHTTPServer(('127.0.0.1', 0), Handler)
Path(args.ready).write_text(json.dumps({'port': server.server_port, 'pid': os.getpid()}), encoding='utf-8')
server.serve_forever()
