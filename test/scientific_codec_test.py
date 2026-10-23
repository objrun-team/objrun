"""Preserve official scientific return types without executing serialized code."""
import sys
import unittest
sys.path.insert(0, '/worker')
import numpy as np
import sympy as sp
from codec import encode, decode, UnsupportedScientificObject

class Codec(unittest.TestCase):
    def test_symbols_in_keys_and_values(self):
        a, b = sp.Symbol('e01'), sp.Symbol('e10', real=True)
        original = ({'e01': a, 'e10': b}, {a: .2, b: -.2})
        self.assertEqual(decode(encode(original)), original)

    def test_numeric_arrays_and_complex(self):
        array = np.array([[1 + 2j, 3 + 4j]], dtype=np.complex128)
        result = decode(encode(array))
        np.testing.assert_array_equal(result, array)
        self.assertEqual(result.dtype, array.dtype)
        self.assertEqual(decode(encode(3 + 4j)), 3 + 4j)

    def test_atomic_sympy_numbers(self):
        for value in [sp.Integer(1), sp.Rational(3, 7), sp.Float('0.123456789123456789', precision=100)]:
            self.assertEqual(decode(encode(value)), value)

    def test_unrecognized_data_cannot_execute(self):
        with self.assertRaises(ValueError):
            decode({'kind': 'expression', 'value': "__import__('os').system('echo bad')"})
        value = decode({'kind': 'symbol', 'name': "__import__('os')", 'assumptions': {}})
        self.assertIsInstance(value, sp.Symbol)
        with self.assertRaises(UnsupportedScientificObject): encode(lambda: 1)

if __name__ == '__main__': unittest.main()
