"""Private scorer. Public endpoints expose a strict question-field whitelist."""
import argparse
import hashlib
import json
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from grade import Scorer


def serve(home, vendor, port, token):
    scorer = Scorer(vendor)
    book = {r['id']: r for r in json.loads((home / 'private-tasks.json').read_text(encoding='utf-8'))}
    for row in book.values():
        scorer.target(row)
    cache = {}
    lock = threading.Lock()

    class Handler(BaseHTTPRequestHandler):
        def log_message(self, *_):
            pass

        def send(self, data, code=200):
            raw = json.dumps(data, allow_nan=False).encode()
            self.send_response(code)
            self.send_header('Content-Type', 'application/json')
            self.send_header('Content-Length', str(len(raw)))
            self.end_headers()
            self.wfile.write(raw)

        def do_GET(self):
            if self.path == '/health':
                self.send({'ok': True, 'tasks': len(book), 'revision': 'e14e0ca3d3db0f02928a18d435b9c3d15656a7c5'})
            elif self.path == '/problems':
                self.send([scorer.public(r) for r in book.values()])
            else:
                self.send({'errorType': 'NotFound'}, 404)

        def do_POST(self):
            if self.headers.get('X-SciBench-Token') != token:
                self.send({'errorType': 'Unauthorized'}, 403)
                return
            if self.path not in ['/parsed', '/correct', '/accept']:
                self.send({'errorType': 'NotFound'}, 404)
                return
            try:
                size = int(self.headers.get('Content-Length', 0))
                if not 0 < size <= 2 * 1024 * 1024:
                    self.send({'errorType': 'InvalidBodySize'}, 422)
                    return
                body = json.loads(self.rfile.read(size))
                inp = body.get('input', {})
                task = inp.get('task', {})
                tid = str(task.get('id', '')).split('/')[-1]
                if tid not in book:
                    self.send({'errorType': 'UnknownTask'}, 422)
                    return
                answer = inp.get('result', task.get('result', ''))
                if isinstance(answer, dict):
                    answer = answer.get('body', '')
                if not isinstance(answer, str):
                    self.send({'errorType': 'InvalidCandidateType'}, 422)
                    return
                key = (tid, hashlib.sha256(answer.encode()).hexdigest())
                with lock:
                    if key not in cache:
                        cache[key] = scorer.judge(answer, book[tid])
                    verdict = cache[key]
                if self.path == '/accept':
                    self.send(verdict)
                else:
                    node = self.path[1:]
                    self.send({'value': verdict['parsed' if node == 'parsed' else 'passed'],
                               'note': 'End with a boxed finite numeric answer in the requested unit.'
                               if node == 'parsed' and not verdict['parsed'] else ''})
            except Exception as error:
                self.send({'valid': False, 'outcome': 'grader_error', 'errorType': type(error).__name__}, 503)

    server = ThreadingHTTPServer(('127.0.0.1', port), Handler)
    print(json.dumps({'pid': __import__('os').getpid(), 'port': server.server_port, 'tasks': len(book)}), flush=True)
    server.serve_forever()


if __name__ == '__main__':
    ap = argparse.ArgumentParser()
    ap.add_argument('--home', type=Path, required=True)
    ap.add_argument('--vendor', type=Path, required=True)
    ap.add_argument('--port', type=int, default=0)
    args = ap.parse_args()
    import os
    serve(args.home, args.vendor, args.port, os.environ['SCIBENCH_GRADER_TOKEN'])
