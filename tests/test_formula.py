import math

import pytest
from hypothesis import given
from hypothesis import strategies as st

from e36cli.formula import FormulaError, compile_formula, decode_raw


@pytest.mark.parametrize(
    "expr,x,expected",
    [
        ("x", 7, 7.0),
        ("x * 0.75 - 48", 0, -48.0),
        ("x * 0.75 - 48", 184, 90.0),
        ("(x + 1) * 2", 3, 8.0),
        ("x + 2 * 3", 1, 7.0),  # precedence
        ("-x", 5, -5.0),
        ("+x", 5, 5.0),
        ("x / 4", 10, 2.5),
        ("3.5", 999, 3.5),
        ("-(x - 1) / 2", 5, -2.0),
    ],
)
def test_valid_formulas(expr, x, expected):
    fn = compile_formula(expr)
    assert fn(x) == pytest.approx(expected)


@pytest.mark.parametrize(
    "expr",
    [
        "__import__('os')",
        "x.__class__",
        "open('/etc/passwd')",
        "y",
        "x ** 2",
        "x % 2",
        "x // 2",
        "x > 1",
        "x if x else 0",
        "[x]",
        "lambda y: y",
        "x; x",
        "True",
        "'a'",
        "x @ x",
        "",
        "x +",
    ],
)
def test_rejected_formulas(expr):
    with pytest.raises(FormulaError):
        compile_formula(expr)


@given(a=st.floats(-1e6, 1e6), b=st.floats(-1e6, 1e6), x=st.integers(0, 65535))
def test_linear_formula_matches_python(a, b, x):
    fn = compile_formula(f"x * {a!r} + {b!r}")
    assert math.isclose(fn(x), x * a + b, rel_tol=1e-12, abs_tol=1e-9)


def test_decode_raw():
    assert decode_raw(b"\x01\x02", 2, endian="big") == 0x0102
    assert decode_raw(b"\x01\x02", 2, endian="little") == 0x0201
    assert decode_raw(b"\xff", 1, signed=True) == -1
    assert decode_raw(b"\xff", 1, signed=False) == 255


def test_decode_raw_errors():
    with pytest.raises(ValueError):
        decode_raw(b"\x01", 2)
    with pytest.raises(ValueError):
        decode_raw(b"\x01", 1, endian="middle")


def test_huge_literal_rejected():
    with pytest.raises(FormulaError):
        compile_formula("x * 1" + "0" * 400)


def test_inf_literal_rejected():
    with pytest.raises(FormulaError):
        compile_formula("x + 10e400")
