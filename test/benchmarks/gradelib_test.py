"""The shared grader must preserve task identity and distinguish outages from rejection."""
import json
import socket
import subprocess
import sys
import time
import unittest
import urllib.error
import urllib.request
from pathlib import Path

LIB = Path(__file__).resolve().parents[2] / "examples/benchmark/_lib"

class GraderProtocol(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        with socket.socket() as sock:
            sock.bind(("127.0.0.1", 0))
            cls.port = sock.getsockname()[1]
        script = f"""
import sys
sys.path.insert(0, {str(LIB)!r})
from gradelib import serve
def correct(text, item):
    if text == 'outage': raise RuntimeError('private gold must not appear in response')
    return text == 'right'
serve({{'sample-0': {{'id': 'sample-0'}}}}, lambda x: x, {{'parsed': lambda s, x: bool(s), 'correct': correct}}, {cls.port})
"""
        cls.process = subprocess.Popen([sys.executable, "-c", script], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        for _ in range(50):
            try:
                urllib.request.urlopen(f"http://127.0.0.1:{cls.port}/health", timeout=1).close()
                break
            except OSError:
                time.sleep(.05)
        else: raise RuntimeError('grader did not start')

    @classmethod
    def tearDownClass(cls):
        cls.process.terminate()
        cls.process.wait(timeout=5)

    def request(self, task, answer, nested=False):
        body = {'input': {'task': {'id': task}}}
        if nested: body['input']['result'] = {'body': answer}
        else: body['input']['task']['result'] = answer
        request = urllib.request.Request(f'http://127.0.0.1:{self.port}/correct', json.dumps(body).encode(), {'content-type': 'application/json'})
        try:
            with urllib.request.urlopen(request) as response:
                return response.status, json.load(response)
        except urllib.error.HTTPError as response:
            return response.code, json.load(response)

    def test_namespaced_delivered_candidate(self):
        self.assertEqual(self.request('pilot/sample-0', 'right', nested=True), (200, True))

    def test_fault_is_not_rejection_and_private_text_is_not_returned(self):
        status, body = self.request('sample-0', 'outage')
        self.assertEqual(status, 503)
        self.assertEqual(body['outcome'], 'grader_error')
        self.assertNotIn('private gold', json.dumps(body))
        self.assertEqual(self.request('sample-0', 'right'), (200, True))

    def test_unknown_task_is_protocol_error(self):
        status, body = self.request('not-in-book', 'right')
        self.assertEqual(status, 422)
        self.assertEqual(body['outcome'], 'grader_error')

    def test_valid_wrong_answer_remains_boolean_false(self):
        self.assertEqual(self.request('sample-0', 'wrong'), (200, False))

if __name__ == '__main__': unittest.main()
