"""Safe profile formula compiler: `x`, numbers, + - * /, unary +/-, parens.

Formulas come from profile TOML files; we never eval arbitrary code. The
expression is parsed with `ast` and walked against a strict whitelist into a
closure tree.
"""

from __future__ import annotations

import ast
import math
import operator
from collections.abc import Callable

from .errors import E36Error

_BINOPS: dict[type, Callable[[float, float], float]] = {
    ast.Add: operator.add,
    ast.Sub: operator.sub,
    ast.Mult: operator.mul,
    ast.Div: operator.truediv,
}


class FormulaError(E36Error, ValueError):
    """Formula failed to parse or used a disallowed construct."""


def compile_formula(expr: str) -> Callable[[float], float]:
    try:
        tree = ast.parse(expr, mode="eval")
    except SyntaxError as exc:
        raise FormulaError(f"invalid formula {expr!r}: {exc.msg}") from exc
    return _build(tree.body, expr)


def _build(node: ast.AST, expr: str) -> Callable[[float], float]:
    if isinstance(node, ast.Constant):
        if isinstance(node.value, bool) or not isinstance(node.value, (int, float)):
            raise FormulaError(f"non-numeric literal in formula {expr!r}")
        try:
            value = float(node.value)
        except OverflowError as exc:
            raise FormulaError(f"literal too large in formula {expr!r}") from exc
        if not math.isfinite(value):
            raise FormulaError(f"non-finite literal in formula {expr!r}")
        return lambda x: value
    if isinstance(node, ast.Name):
        if node.id != "x" or not isinstance(node.ctx, ast.Load):
            raise FormulaError(f"only variable 'x' is allowed, got {node.id!r} in {expr!r}")
        return lambda x: x
    if isinstance(node, ast.BinOp):
        op = _BINOPS.get(type(node.op))
        if op is None:
            raise FormulaError(f"operator {type(node.op).__name__} not allowed in {expr!r}")
        left = _build(node.left, expr)
        right = _build(node.right, expr)
        return lambda x: op(left(x), right(x))
    if isinstance(node, ast.UnaryOp):
        inner = _build(node.operand, expr)
        if isinstance(node.op, ast.USub):
            return lambda x: -inner(x)
        if isinstance(node.op, ast.UAdd):
            return inner
        raise FormulaError(f"unary {type(node.op).__name__} not allowed in {expr!r}")
    raise FormulaError(f"{type(node).__name__} not allowed in formula {expr!r}")


def decode_raw(data: bytes, size: int, signed: bool = False, endian: str = "big") -> int:
    """Decode `size` raw bytes into an integer per profile field settings."""
    if len(data) != size:
        raise ValueError(f"expected {size} bytes, got {len(data)}")
    if endian not in ("big", "little"):
        raise ValueError(f"endian must be 'big' or 'little', got {endian!r}")
    return int.from_bytes(data, endian, signed=signed)
