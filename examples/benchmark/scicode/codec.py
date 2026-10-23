"""Lossless, non-pickle RPC for scientific function inputs and outputs."""
import base64
import math
import numpy as np
import scipy.sparse as sparse
import sympy as sp

class UnsupportedScientificObject(TypeError):
    pass

def encode(value):
    if isinstance(value, np.generic):
        return encode(value.item())
    if value is None or isinstance(value, (str, bool, int, float)):
        return value
    if isinstance(value, complex):
        return {"kind": "complex", "real": value.real, "imag": value.imag}
    if isinstance(value, sp.Symbol):
        return {"kind": "symbol", "name": str(value), "assumptions": value.assumptions0}
    if isinstance(value, sp.Integer):
        return {"kind": "sympy_integer", "value": int(value)}
    if isinstance(value, sp.Rational):
        return {"kind": "sympy_rational", "p": int(value.p), "q": int(value.q)}
    if isinstance(value, sp.Float):
        return {"kind": "sympy_float", "value": str(value), "precision": value._prec}
    if isinstance(value, np.ndarray):
        if value.dtype.kind not in "biufcSU":
            raise UnsupportedScientificObject("unsupported array dtype in grading RPC")
        array = np.ascontiguousarray(value)
        return {"kind": "array", "dtype": array.dtype.str, "shape": list(array.shape), "data": base64.b64encode(array.tobytes()).decode("ascii")}
    if sparse.issparse(value):
        value = value.tocsr()
        return {"kind": "csr", "shape": list(value.shape), "data": encode(value.data), "indices": encode(value.indices), "indptr": encode(value.indptr)}
    if isinstance(value, (tuple, list, set, frozenset)):
        return {"kind": type(value).__name__, "items": [encode(item) for item in value]}
    if isinstance(value, dict):
        return {"kind": "dict", "items": [[encode(key), encode(item)] for key, item in value.items()]}
    raise UnsupportedScientificObject("unsupported scientific object in grading RPC")

def decode(value):
    if value is None or isinstance(value, (str, bool, int, float)):
        return value
    if not isinstance(value, dict):
        raise ValueError("invalid grading RPC value")
    kind = value.get("kind")
    if kind == "complex":
        return complex(value["real"], value["imag"])
    if kind == "symbol":
        name, assumptions = value["name"], value["assumptions"]
        allowed = {"commutative", "real", "complex", "integer", "rational", "irrational", "nonzero", "zero", "positive", "negative", "nonpositive", "nonnegative", "finite", "infinite", "imaginary", "even", "odd", "prime", "composite", "algebraic", "transcendental", "hermitian", "antihermitian", "extended_real", "extended_positive", "extended_negative", "extended_nonpositive", "extended_nonnegative", "extended_nonzero", "noninteger"}
        if not isinstance(name, str) or len(name) > 1024 or not isinstance(assumptions, dict) or not set(assumptions) <= allowed or any(type(x) is not bool for x in assumptions.values()):
            raise ValueError("invalid symbol RPC")
        return sp.Symbol(name, **assumptions)
    if kind == "sympy_integer":
        if type(value["value"]) is not int: raise ValueError("invalid integer RPC")
        return sp.Integer(value["value"])
    if kind == "sympy_rational":
        if type(value["p"]) is not int or type(value["q"]) is not int or not value["q"]: raise ValueError("invalid rational RPC")
        return sp.Rational(value["p"], value["q"])
    if kind == "sympy_float":
        import re
        text, precision = value["value"], value["precision"]
        if not isinstance(text, str) or len(text) > 4096 or not re.fullmatch(r"[-+]?\d+(?:\.\d*)?(?:[eE][-+]?\d+)?", text) or type(precision) is not int or not 2 <= precision <= 4096: raise ValueError("invalid float RPC")
        return sp.Float(text, precision=precision)
    if kind == "array":
        dtype = np.dtype(value["dtype"])
        shape = value["shape"]
        if dtype.kind not in "biufcSU" or len(shape) > 10 or any(not isinstance(n, int) or n < 0 for n in shape):
            raise ValueError("invalid grading RPC array")
        size = math.prod(shape) * dtype.itemsize
        if size > 256 * 1024 * 1024:
            raise ValueError("grading RPC array too large")
        data = base64.b64decode(value["data"], validate=True)
        if len(data) != size:
            raise ValueError("grading RPC array length mismatch")
        return np.frombuffer(data, dtype=dtype).copy().reshape(shape)
    if kind == "csr":
        return sparse.csr_matrix((decode(value["data"]), decode(value["indices"]), decode(value["indptr"])), shape=tuple(value["shape"]))
    if kind in ("list", "tuple", "set", "frozenset"):
        items = [decode(item) for item in value["items"]]
        return {"list": list, "tuple": tuple, "set": set, "frozenset": frozenset}[kind](items)
    if kind == "dict":
        return {decode(key): decode(item) for key, item in value["items"]}
    raise ValueError("unknown grading RPC type")
