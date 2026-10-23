"""Deterministic OPSIN failure/negative-answer regressions; no external requests."""
import json
import os
from pathlib import Path
import sys
import threading
import unittest
import urllib.request
import urllib.error

from legacy_regrade import module_from

os.environ["TGENGIN_CHEMIQ_OPSIN_PROFILE"] = "rest"
os.environ["TGENGIN_CHEMIQ_HOME"] = "/oracle"
MOD = module_from("/adapter/stand.py")
UUID = next(u for u, q in MOD.BOOK.items() if q["verification_method"] == "opsin")


class Response:
    def __init__(self, status=200, data=None, malformed=False):
        self.status_code = status
        self.data = data
        self.malformed = malformed

    def json(self):
        if self.malformed:
            raise ValueError("Synthetic malformed JSON")
        return self.data

    def raise_for_status(self):
        if self.status_code >= 400:
            raise MOD.requests.HTTPError("Synthetic HTTP fault")


class OpsinFailureTests(unittest.TestCase):
    def setUp(self):
        MOD.requests.get = MOD.observed_get
        MOD.CACHE.clear()
        MOD.VERIFIER._opsin_cache.clear()
        MOD.OPSIN_FAILURE = None
        self.calls = []
        self.saved_get = MOD._original_get

    def tearDown(self):
        MOD._original_get = self.saved_get

    def returns(self, response):
        def get(*args, **kwargs):
            self.calls.append(1)
            return response
        MOD._original_get = get

    def test_http_failure_cannot_poison_next_candidate_measurement(self):
        self.returns(Response(503, {"status": "FAILURE"}))
        first = MOD.judge(UUID, "ethane")
        self.assertTrue(first.get("error"))
        self.assertNotIn("ethane", MOD.VERIFIER._opsin_cache)
        self.returns(Response(200, {"status": "SUCCESS", "smiles": "CC"}))
        second = MOD.judge(UUID, "ethane")
        self.assertFalse(second.get("error"))
        self.assertEqual(len(self.calls), 2)

    def test_transport_failure_does_not_leave_false_cache(self):
        def get(*args, **kwargs):
            raise MOD.requests.Timeout("Synthetic timeout")
        MOD._original_get = get
        result = MOD.judge(UUID, "ethane")
        self.assertTrue(result.get("error"))
        self.assertNotIn("ethane", MOD.VERIFIER._opsin_cache)

    def test_malformed_json_is_unavailable_not_a_wrong_answer(self):
        self.returns(Response(200, malformed=True))
        result = MOD.judge(UUID, "ethane")
        self.assertTrue(result.get("error"))
        self.assertNotIn("ethane", MOD.VERIFIER._opsin_cache)

    def test_gateway_404_without_opsin_failure_payload_is_unavailable(self):
        self.returns(Response(404, malformed=True))
        self.assertTrue(MOD.judge(UUID, "ethane").get("error"))
        self.assertNotIn("ethane", MOD.VERIFIER._opsin_cache)

    def test_explicit_opsin_name_rejection_is_a_valid_negative(self):
        self.returns(Response(404, {"status": "FAILURE", "message": "Synthetic unrecognized name"}))
        result = MOD.judge(UUID, "ethane")
        self.assertFalse(result.get("error"))
        self.assertFalse(result["correct"])
        self.assertIs(MOD.VERIFIER._opsin_cache["ethane"], False)

    def test_missing_smiles_success_payload_is_unavailable(self):
        self.returns(Response(200, {"status": "SUCCESS"}))
        self.assertTrue(MOD.judge(UUID, "ethane").get("error"))
        self.assertNotIn("ethane", MOD.VERIFIER._opsin_cache)

    def test_valid_conversion_can_remain_a_wrong_structure(self):
        self.returns(Response(200, {"status": "SUCCESS", "smiles": "CC"}))
        result = MOD.judge(UUID, "ethane")
        self.assertFalse(result.get("error"))
        self.assertTrue(result["parsed"])
        self.assertEqual(MOD.VERIFIER._opsin_cache["ethane"], "CC")

    def test_failed_verdict_is_not_memoized(self):
        self.returns(Response(429, {"status": "FAILURE"}))
        with self.assertRaises(RuntimeError):
            MOD.verdict(UUID, "ethane")
        self.assertNotIn((UUID, "ethane"), MOD.CACHE)
        self.assertNotIn("ethane", MOD.VERIFIER._opsin_cache)

    def test_official_length_guard_is_wrong_answer_without_network(self):
        def get(*args, **kwargs):
            self.fail("The 200-character guard must run before OPSIN")
        MOD._original_get = get
        result = MOD.judge(UUID, "x" * 201)
        self.assertFalse(result.get("error"))
        self.assertFalse(result["correct"])

    def test_explicit_200_failure_is_a_valid_negative(self):
        self.returns(Response(200, {"status": "FAILURE", "message": "Synthetic invalid name"}))
        result = MOD.judge(UUID, "ethane")
        self.assertFalse(result.get("error"))
        self.assertFalse(result["correct"])


@unittest.skipUnless(Path("/opsin-jobs/profile.json").exists(), "local bridge profile not mounted")
class LocalProfileTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        os.environ["TGENGIN_CHEMIQ_OPSIN_PROFILE"] = "local-2.8"
        os.environ["TGENGIN_CHEMIQ_OPSIN_JOBS"] = "/opsin-jobs"
        cls.mod = module_from("/adapter/stand.py")
        os.environ["TGENGIN_CHEMIQ_OPSIN_PROFILE"] = "rest"

    def setUp(self):
        self.mod.requests.get = self.mod.observed_get
        self.mod.CACHE.clear()
        self.mod.VERIFIER._opsin_cache.clear()
        self.saved_convert = self.mod.local_opsin
        self.saved_get = self.mod._original_get

    def tearDown(self):
        self.mod.local_opsin = self.saved_convert
        self.mod._original_get = self.saved_get

    def test_local_mode_prohibits_rest_before_any_request(self):
        requests = []
        self.mod._original_get = lambda *a, **k: requests.append(1)
        with self.assertRaises(RuntimeError):
            self.mod.observed_get("https://example.invalid/never-send")
        self.assertEqual(requests, [])

    def test_local_conversion_cache_never_uses_the_fixed_rest_cache(self):
        conversions = []
        self.mod.local_opsin = lambda name: conversions.append(name) or "CC"
        self.mod._original_get = lambda *a, **k: self.fail("REST fallback prohibited")
        first = self.mod.judge(UUID, "ethane")
        second = self.mod.judge(UUID, "ethane")
        self.assertFalse(first.get("error"))
        self.assertFalse(second.get("error"))
        self.assertEqual(conversions, ["ethane"])
        self.assertEqual(self.mod.VERIFIER._opsin_cache["ethane"], "CC")

    def test_local_bridge_failure_returns_http_503_without_boolean_verdict(self):
        def unavailable(name):
            raise RuntimeError("SyntheticBridgeFailure")
        self.mod.local_opsin = unavailable
        server = self.mod.HTTPServer(("127.0.0.1", 0), self.mod.Handler)
        response = {}
        def client():
            body = {"input": {"task": {"id": "chemiq-" + UUID}, "result": {"body": "ethane"}}}
            request = urllib.request.Request(f"http://127.0.0.1:{server.server_port}/correct", json.dumps(body).encode(), {"content-type": "application/json"})
            try:
                urllib.request.urlopen(request, timeout=10)
            except urllib.error.HTTPError as error:
                response["status"] = error.code
                response["body"] = json.load(error)
        thread = threading.Thread(target=client)
        thread.start()
        server.handle_request()  # Original signal-based evaluator stays in main thread.
        thread.join(timeout=10)
        server.server_close()
        self.assertEqual(response.get("status"), 503)
        self.assertIs(response["body"]["valid"], False)
        self.assertNotIn("value", response["body"])
        self.assertNotIn("ethane", self.mod.VERIFIER._opsin_cache)


if __name__ == "__main__":
    unittest.main(verbosity=2)
