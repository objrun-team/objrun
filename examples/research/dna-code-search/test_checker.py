import itertools
import random
import unittest
from pathlib import Path

from checker import check, independent_check, COMPLEMENT


class CheckerTests(unittest.TestCase):
    def test_reference_and_strict_discrepancy(self):
        words = (Path(__file__).resolve().parents[3] / 'data/dna-code-search/preparation/published-fss.txt').read_text().split()
        report = check(words)
        self.assertEqual(len(words), 676)
        self.assertTrue(report['valid'])
        self.assertTrue(independent_check(words))
        self.assertFalse(report['improved'])
        self.assertFalse(report['strict_r_rc_valid'])
        self.assertEqual(report['reverse_distance_min'], 0)
        self.assertTrue(check(words, 675)['improved'])
        self.assertFalse(check(words + words[:1])['valid'])
        self.assertFalse(check(words[:-1])['valid'])

    def test_independent_agreement_on_mutations(self):
        words = (Path(__file__).resolve().parents[3] / 'data/dna-code-search/preparation/published-fss.txt').read_text().split()
        rng = random.Random(7)
        for _ in range(30):
            chosen = rng.sample(words, 3)
            closed = sorted({x for w in chosen for x in (w, w[::-1], w.translate(COMPLEMENT), w.translate(COMPLEMENT)[::-1])})
            if rng.random() < .5:
                pos = rng.randrange(len(closed))
                closed[pos] = 'A' + closed[pos][1:]
            self.assertEqual(check(closed)['valid'], independent_check(closed))

    def test_malformed_and_close_pairs(self):
        for bad in [[], ['ACGT'], ['AAAAACCCCX'], ['AAAAACCCCC', 'AAAACCCCCC']]:
            self.assertFalse(check(bad)['valid'])
        pairs = ['AAAAACCCCC', 'AAAACACCCC']
        closed = sorted({x for w in pairs for x in (w, w[::-1], w.translate(COMPLEMENT), w.translate(COMPLEMENT)[::-1])})
        self.assertFalse(check(closed)['valid'])
        self.assertFalse(independent_check(closed))


if __name__ == '__main__':
    unittest.main()
