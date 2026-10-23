"""F-only carry controls: synthetic binary responses, actual file fsync/lease.

No official GET, E stage, Docker, model, candidate, Lean or original DB call.
Successful payloads are synthetic, not an actual downloaded official blob.
"""
import base64
from copy import deepcopy
from datetime import datetime
import hashlib
from http.client import HTTPMessage
import importlib.util
import json
from pathlib import Path
import ssl
import unittest
from unittest.mock import patch
import urllib.error
import uuid

PROJECT = Path(__file__).resolve().parents[1]
PATH = PROJECT/"scripts/benchmark-repair/minif2f_public_cache_root_carry.py"
spec = importlib.util.spec_from_file_location("carry_under_control", PATH)
w = importlib.util.module_from_spec(spec)
spec.loader.exec_module(w)
BASE = PROJECT/".scratch/minif2f-root-carry-tests"
BASE.mkdir(exist_ok=True)
AUTH = json.loads((PROJECT/w.AUTH_REL).read_bytes())


def h(data):
    return hashlib.sha256(data).hexdigest()


class Response:
    def __init__(self, policy, data, error=None, error_after=1):
        self.status, self.url = 200, policy["url"]
        self.headers = HTTPMessage()
        for name, value in (("Content-Length", str(policy["contentLength"])),
                            ("Content-MD5", policy["contentMd5"]), ("ETag", policy["etag"])):
            self.headers.add_header(name, value)
        self.data, self.at, self.error, self.error_after = data, 0, error, error_after
        self.reads, self.closed = 0, False

    def geturl(self):
        return self.url

    def read1(self, _limit):
        self.reads += 1
        if self.error and self.reads > self.error_after:
            raise self.error
        value = self.data[self.at:self.at+16384]
        self.at += len(value)
        return value

    def __enter__(self):
        return self

    def __exit__(self, *_):
        self.closed = True


class Opener:
    def __init__(self, response=None, error=None):
        self.response, self.error, self.calls, self.requests = response, error, 0, []

    def open(self, request, timeout):
        self.calls += 1
        self.requests.append(request)
        if self.error:
            raise self.error
        return self.response


class CarryControls(unittest.TestCase):
    def setUp(self):
        self.root = BASE/str(uuid.uuid4())
        self.root.mkdir()
        (self.root/"audit").mkdir()
        (self.root/"downloads/mathlib-cache").mkdir(parents=True)
        (self.root/"fixture-only.json").write_text('{"fixtureOnly":true,"networkCalls":0}\n')
        self.receipt = self.root/"audit/cache-downloads.jsonl"
        self.original = b'\n'  # Kernel preserves any pre-existing bytes; production checks fixed3554 SHA.
        self.receipt.write_bytes(self.original)
        self.lease = type("FixtureLease", (), {"id": str(uuid.uuid4())})()
        self.book = w.v3.Book(0, 292278, reserve=lambda *_: {"fixtureOnly": True})
        self.book.recoveries = 6
        self.journal = w.AttemptJournal(self.root/w.EVENTS_REL, self.lease.id, "a"*64)

    def fixture(self, index=0):
        policy = deepcopy(AUTH["keys"][index])
        data = (b"synthetic-public-binary-control\x00"*4000)[:policy["contentLength"]]
        self.assertEqual(len(data), policy["contentLength"])
        policy["contentMd5"] = base64.b64encode(hashlib.md5(data, usedforsecurity=False).digest()).decode()
        for prefix in policy["prefixes"]:
            prefix["sha256"] = h(data[:prefix["bytes"]])
        row = {"ltar": policy["key"], "module": "Fixture/Control.lean"}
        return policy, data, row

    def run_one(self, policy, data, row, opener=None, guard=lambda: None):
        opener = opener or Opener(Response(policy, data))
        result = w.fresh_one(policy, row, self.root, self.lease, self.book,
                             self.journal, guard, self.receipt, opener)
        return result, opener

    def test_synthetic_fatal_get3_body3_verifies_both_windows_and_complete_md5(self):
        policy, data, row = self.fixture()
        result, opener = self.run_one(policy, data, row)
        self.assertEqual(opener.calls, 1)
        self.assertEqual(result["cumulative_key_gets_exact"], 3)
        self.assertEqual(result["body_generations"], 3)
        self.assertEqual(result["sha256"], h(data))
        self.assertEqual(result["transport_protocol"], w.TRANSPORT)
        self.assertTrue(result["all_failed_prefix_windows_verified"])
        self.assertEqual(result["failed_prefix_bytes_reused_in_body"], 0)
        self.assertTrue(self.receipt.read_bytes().startswith(self.original))
        self.assertLessEqual(len(w.v3.encode_row(result)), 2048)
        self.assertEqual(opener.requests[0].get_method(), "GET")
        self.assertNotIn("Range", opener.requests[0].headers)
        self.assertNotIn("Authorization", opener.requests[0].headers)

    def test_stopped_additional_request_keeps_unknown_old_interval(self):
        policy, data, row = self.fixture(1)
        result, opener = self.run_one(policy, data, row)
        self.assertEqual(opener.calls, 1)
        self.assertIsNone(result["cumulative_key_gets_exact"])
        self.assertEqual(result["cumulative_key_gets_interval"], [2, 4])
        self.assertEqual(result["body_generations"], 2)

    def test_two_requests_chain_has1507_known_total_and_exact_commits(self):
        policies = []
        for index in (0, 1):
            policy, data, row = self.fixture(index)
            policies.append(policy)
            self.run_one(policy, data, row)
        inspected = w.inspect_attempts(self.root/w.EVENTS_REL, self.lease.id, "a"*64,
                                       {"keys": policies}, self.receipt.read_bytes())
        self.assertEqual(set(inspected["commits"]), set(w.KEYS))
        self.assertEqual(inspected["events"], 6)
        self.assertEqual(self.journal.footer()["opener_calls"], 2)
        self.assertEqual(self.journal.footer()["new_get_intents"], 2)

    def test_no_fourth_get_or_new_journal_after_consumed_allowance(self):
        policy, data, row = self.fixture()
        _, opener = self.run_one(policy, data, row)
        with self.assertRaises(RuntimeError):
            self.journal.dispatch(policy)
        with self.assertRaises(FileExistsError):
            w.AttemptJournal(self.root/w.EVENTS_REL, str(uuid.uuid4()), "a"*64)
        self.assertEqual(opener.calls, 1)

    def test_short_eof_preserves_actual_prefix_and_has_no_completion_or_retry(self):
        policy, data, row = self.fixture()
        opener = Opener(Response(policy, data[:-6450]))
        with self.assertRaisesRegex(RuntimeError, "EOF"):
            self.run_one(policy, data, row, opener)
        part = self.root/"downloads/mathlib-cache"/(policy["key"]+".part")
        self.assertEqual(part.read_bytes(), data[:-6450])
        self.assertEqual(self.receipt.read_bytes(), self.original)
        self.assertEqual(opener.calls, 1)
        self.assertTrue(opener.response.closed)
        self.assertEqual(self.journal.footer()["acknowledged_committed_keys"], [])

    def test_opening_http_tls_timeout_and_url_errors_do_not_retry(self):
        policy, data, row = self.fixture()
        for error in (TimeoutError("fixture"), ssl.SSLError("fixture"),
                      urllib.error.HTTPError(policy["url"], 403, "fixture", None, None)):
            root = self.root/str(uuid.uuid4())
            root.mkdir()
            (root/"audit").mkdir()
            journal = w.AttemptJournal(root/w.EVENTS_REL, self.lease.id, "a"*64)
            book = w.v3.Book(0, reserve=lambda *_: {})
            opener = Opener(error=error)
            with self.assertRaises(type(error)):
                w.fresh_one(policy, row, root, self.lease, book, journal, lambda: None, self.receipt, opener)
            self.assertEqual(opener.calls, 1)
            self.assertEqual(len(journal.used), 1)
            self.assertEqual(self.receipt.read_bytes(), self.original)

    def test_read_timeout_has_one_call_actual_retained_bytes_and_no_commit(self):
        policy, data, row = self.fixture()
        opener = Opener(Response(policy, data, TimeoutError("fixture")))
        with self.assertRaises(TimeoutError):
            self.run_one(policy, data, row, opener)
        self.assertEqual(opener.calls, 1)
        self.assertEqual((self.root/"downloads/mathlib-cache"/(policy["key"]+".part")).stat().st_size, 16384)
        self.assertEqual(self.receipt.read_bytes(), self.original)

    def test_body_oversize_and_complete_md5_mismatch_never_promote(self):
        policy, data, row = self.fixture()
        opener = Opener(Response(policy, data+b"x"))
        with self.assertRaisesRegex(RuntimeError, "exceeds"):
            self.run_one(policy, data, row, opener)
        self.assertFalse((self.root/"downloads/mathlib-cache"/policy["key"]).exists())
        self.assertEqual(opener.calls, 1)

    def test_body_tail_md5_mismatch_and_both_prefix_drifts_are_rejected(self):
        for where in (0, 20000, 85000):
            child = CarryControls("runTest")
            child.setUp()
            policy, data, row = child.fixture()
            bad = bytearray(data)
            bad[where] ^= 1
            opener = Opener(Response(policy, bytes(bad)))
            with self.assertRaisesRegex(RuntimeError, "prefix|MD5"):
                child.run_one(policy, data, row, opener)
            self.assertEqual(child.receipt.read_bytes(), child.original)
            self.assertEqual(opener.calls, 1)

    def test_changed_headers_duplicate_url_or_status_fail_without_body(self):
        for variant in ("length", "md5", "etag", "duplicate", "url", "status"):
            child = CarryControls("runTest")
            child.setUp()
            policy, data, row = child.fixture()
            response = Response(policy, data)
            if variant == "length":
                response.headers.replace_header("Content-Length", "87930")
            elif variant == "md5":
                response.headers.replace_header("Content-MD5", base64.b64encode(b"x"*16).decode())
            elif variant == "etag":
                response.headers.replace_header("ETag", "W/\"fixture\"")
            elif variant == "duplicate":
                response.headers.add_header("Content-Length", str(len(data)))
            elif variant == "url":
                response.url += "/redirect"
            else:
                response.status = 403
            opener = Opener(response)
            with self.assertRaises(RuntimeError):
                child.run_one(policy, data, row, opener)
            self.assertEqual(response.reads, 0)
            self.assertEqual(opener.calls, 1)
            self.assertEqual(child.receipt.read_bytes(), child.original)

    def test_dispatch_journal_fsync_failure_consumes_intent_but_sends_zero_calls(self):
        policy, data, row = self.fixture()
        opener = Opener(Response(policy, data))
        with patch.object(w, "sync", side_effect=OSError("fixture fsync")):
            with self.assertRaises(OSError):
                self.run_one(policy, data, row, opener)
        self.assertEqual(opener.calls, 0)
        self.assertEqual(len(self.journal.used), 1)
        self.assertFalse(self.journal.footer()["exact_acknowledged_tail"])
        self.assertEqual(self.journal.footer()["opener_calls"], 0)

    def test_body_fsync_and_receipt_fsync_failure_do_not_acknowledge_completion(self):
        for failing_name in (".part", "cache-downloads.jsonl"):
            child = CarryControls("runTest")
            child.setUp()
            policy, data, row = child.fixture()
            original_sync = w.sync
            def fail(stream):
                if str(stream.name).endswith(failing_name):
                    raise OSError("fixture fsync")
                original_sync(stream)
            opener = Opener(Response(policy, data))
            with patch.object(w, "sync", side_effect=fail):
                with self.assertRaises(OSError):
                    child.run_one(policy, data, row, opener)
            self.assertEqual(opener.calls, 1)
            self.assertEqual(child.journal.footer()["acknowledged_committed_keys"], [])
            with self.assertRaises(FileExistsError):
                w.AttemptJournal(child.root/w.EVENTS_REL, child.lease.id, "a"*64)

    def test_guard_after_intent_keeps_consumption_but_no_open(self):
        policy, data, row = self.fixture()
        calls = 0
        def guard():
            nonlocal calls
            calls += 1
            if calls == 2:
                raise RuntimeError("fixture owner/source/resource")
        opener = Opener(Response(policy, data))
        with self.assertRaisesRegex(RuntimeError, "owner"):
            self.run_one(policy, data, row, opener, guard)
        self.assertEqual(opener.calls, 0)
        self.assertEqual(len(self.journal.used), 1)

    def test_unauthorized_key_before_any_open(self):
        policy, data, row = self.fixture()
        policy["key"] = row["ltar"] = "0000000000000000.ltar"
        opener = Opener(Response(policy, data))
        with self.assertRaises(RuntimeError):
            self.run_one(policy, data, row, opener)
        self.assertEqual(opener.calls, 0)

    def test_original_deadline_clock_rollback_and_expiry_are_not_reset(self):
        wall = datetime.fromisoformat("2026-10-08T16:10:00+00:00").timestamp()
        state = [wall, 0.0]
        clock = w.Deadline(lambda: state[0], lambda: state[1])
        clock.check()
        state[0] -= 1
        with self.assertRaises(RuntimeError):
            clock.check()
        with self.assertRaises(RuntimeError):
            w.Deadline(lambda: w.DEADLINE, lambda: 0)
        with self.assertRaises(RuntimeError):
            w.Deadline(lambda: w.ARCHIVE_WALL_FLOOR-1, lambda: 0)
        clock = w.Deadline(lambda: wall, lambda: 0)
        clock.monotonic = lambda: clock.remaining+1
        with self.assertRaises(RuntimeError):
            clock.check()

    def test_real_f_share_deny_ownership_and_handle_closed(self):
        lease = w.OwnedLease(self.root/"audit/fixture-owned.lock")
        lease.acquire()
        try:
            lease.assert_owned()
            with self.assertRaises(OSError):
                (self.root/"audit/fixture-owned.lock").read_bytes()
            second = w.OwnedLease(self.root/"audit/fixture-owned.lock")
            with self.assertRaises(RuntimeError):
                second.acquire()
        finally:
            lease.close()
        with self.assertRaises(RuntimeError):
            lease.assert_owned()

    def test_real_archived_authorization_pins_are_read_only_and_exact(self):
        auth, directory, prior = w.load_authorization()
        self.assertEqual(auth["budget"]["maximumFinalObjects"], 3556)
        self.assertEqual(prior["transport_gets"], 1505)
        self.assertFalse(auth["budget"]["mayEmit5826CompletionCertificate"])
        self.assertTrue(directory.is_relative_to(PROJECT))

    def test_resource_cap_and_attempt_receipt_chain_tampering_fail_closed(self):
        with self.assertRaises(RuntimeError):
            w.v3.Book(w.base.CAP, reserve=lambda *_: {})
        policy, data, row = self.fixture()
        self.run_one(policy, data, row)
        text = (self.root/w.EVENTS_REL).read_bytes()
        events = [json.loads(line) for line in text.splitlines()]
        events[0]["aggregate_consumed_get_allowance"] = 1505
        (self.root/w.EVENTS_REL).write_bytes(b"".join(w.v3.encode_row(e) for e in events))
        with self.assertRaises(RuntimeError):
            w.inspect_attempts(self.root/w.EVENTS_REL, self.lease.id, "a"*64,
                               {"keys": [policy]}, self.receipt.read_bytes())


if __name__ == "__main__":
    unittest.main(verbosity=2)
