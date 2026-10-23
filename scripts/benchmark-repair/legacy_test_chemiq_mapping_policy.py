"""Real pinned-dataset regression for the explicit mapping length policy."""
import ast
from contextlib import redirect_stdout, redirect_stderr
import io
import json
import os
import sys
import unittest

from legacy_regrade import module_from

os.environ["TGENGIN_CHEMIQ_HOME"] = "/oracle"
os.environ["TGENGIN_CHEMIQ_OPSIN_PROFILE"] = "rest"
mod = module_from("/adapter/stand.py")


def compact(answer):
    pairs = ast.literal_eval(answer) if isinstance(answer, str) else answer
    return "[" + ",".join("(" + ",".join(str(n) for n in pair) + ")" for pair in pairs) + "]"


class MappingPolicy(unittest.TestCase):
    def setUp(self):
        self.saved_policy = getattr(mod, "LENGTH_POLICY", "official-parsed")
        self.mapping = {u: q for u, q in mod.BOOK.items() if q["verification_method"] == "list_of_tuples"}
        self.large = max(self.mapping, key=lambda u: len(str(self.mapping[u]["answer"])))
        self.small = min(self.mapping, key=lambda u: len(str(self.mapping[u]["answer"])))

    def tearDown(self):
        mod.LENGTH_POLICY = self.saved_policy

    def judge(self, uuid, answer, policy):
        mod.LENGTH_POLICY = policy
        with redirect_stdout(io.StringIO()), redirect_stderr(io.StringIO()):
            return mod.judge(uuid, answer)

    def test_default_preserves_official_parsed_length(self):
        result = self.judge(self.large, compact(self.mapping[self.large]["answer"]), "official-parsed")
        self.assertFalse(result["correct"])

    def test_compact_25_atom_mapping_passes_raw_policy(self):
        answer = compact(self.mapping[self.large]["answer"])
        self.assertLessEqual(len(answer), 200)
        self.assertGreater(len(str(mod.PARSER.parse(self.large, answer))), 200)
        self.assertTrue(self.judge(self.large, answer, "raw-input-length")["correct"])

    def test_30_guard_gaps_all_pass_raw_policy(self):
        gaps = [u for u, q in self.mapping.items() if len(str(mod.PARSER.parse(u, compact(q["answer"])))) > 200]
        self.assertEqual(len(gaps), 30)
        for uuid in gaps:
            with self.subTest(task=uuid):
                self.assertTrue(self.judge(uuid, compact(self.mapping[uuid]["answer"]), "raw-input-length")["correct"])

    def test_raw_longer_than_200_rejected(self):
        answer = " " * 201 + compact(self.mapping[self.small]["answer"])
        self.assertFalse(self.judge(self.small, answer, "raw-input-length")["correct"])

    def test_raw_newline_rejected(self):
        answer = compact(self.mapping[self.small]["answer"]) + "\n"
        self.assertFalse(self.judge(self.small, answer, "raw-input-length")["correct"])

    def test_raw_carriage_return_rejected(self):
        answer = compact(self.mapping[self.small]["answer"]) + "\r"
        self.assertFalse(self.judge(self.small, answer, "raw-input-length")["correct"])

    def test_wrong_compact_mapping_rejected(self):
        self.assertFalse(self.judge(self.large, "[(999,999)]", "raw-input-length")["correct"])

    def test_mapping_parse_failure_rejected(self):
        self.assertFalse(self.judge(self.large, "no mapping", "raw-input-length")["correct"])

    def test_empty_mapping_preserves_falsey_rejection(self):
        self.assertFalse(self.judge(self.large, "[]", "raw-input-length")["correct"])

    def test_non_mapping_behavior_unchanged(self):
        for uuid, q in mod.BOOK.items():
            if q["verification_method"] in {"opsin", "list_of_tuples"}:
                continue
            answer = str(q["answer"])
            self.assertEqual(self.judge(uuid, answer, "official-parsed")["correct"], self.judge(uuid, answer, "raw-input-length")["correct"])


if __name__ == "__main__":
    stream = io.StringIO()
    result = unittest.TextTestRunner(stream=stream, verbosity=2).run(unittest.defaultTestLoader.loadTestsFromTestCase(MappingPolicy))
    print(stream.getvalue())
    print(json.dumps({"tests": result.testsRun, "failures": len(result.failures), "errors": len(result.errors), "source": "Real official pinned dataset, parser and checker; no OPSIN calls"}))
    sys.exit(0 if result.wasSuccessful() else 1)
