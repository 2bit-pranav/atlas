"""The safe expression evaluator behind `calculate` and `dates`: an allow-list
over Python's parser, exact decimals, and the forms people write."""

from __future__ import annotations

import ast
import datetime as dt
import operator
import re
from collections.abc import Callable
from decimal import Decimal, InvalidOperation, localcontext
from typing import Any

#: Larger exponents or values are refused: `9 ** 9 ** 9` would hang the backend.
_MAX_EXPONENT = 1000


_MAX_DIGITS = 60


_BINARY: dict[type, Callable[[Any, Any], Any]] = {
    ast.Add: operator.add, ast.Sub: operator.sub, ast.Mult: operator.mul,
    ast.Div: operator.truediv, ast.FloorDiv: operator.floordiv, ast.Mod: operator.mod,
    ast.Pow: operator.pow,
}


_UNARY: dict[type, Callable[[Any], Any]] = {ast.UAdd: operator.pos, ast.USub: operator.neg}


class MathError(ValueError):
    """An expression that cannot be evaluated; the message says how to fix it."""


def _number(value: Any) -> Decimal:
    if isinstance(value, bool) or not isinstance(value, (int, float, Decimal)):
        raise MathError(f"expected a number, got {value!r}")
    return value if isinstance(value, Decimal) else Decimal(str(value))


def _values(args: tuple[Any, ...]) -> list[Decimal]:
    """`sum(1, 2, 3)` and `sum([1, 2, 3])` alike."""
    flat = list(args[0]) if len(args) == 1 and isinstance(args[0], list) else list(args)
    if not flat:
        raise MathError("needs at least one number")
    return [_number(v) for v in flat]


def _round(value: Any, places: Any = 0) -> Decimal:
    return round(_number(value), int(places))


def _average(*args: Any) -> Decimal:
    values = _values(args)
    return sum(values, Decimal(0)) / len(values)


def _percent(part: Any, whole: Any) -> Decimal:
    """What percent `part` is of `whole`."""
    return _number(part) * 100 / _number(whole)


NUMBER_FUNCTIONS: dict[str, Callable[..., Any]] = {
    "sum": lambda *a: sum(_values(a), Decimal(0)),
    "min": lambda *a: min(_values(a)),
    "max": lambda *a: max(_values(a)),
    "average": _average,
    "round": _round,
    "abs": lambda v: abs(_number(v)),
    "sqrt": lambda v: _number(v).sqrt(),
    "percent": _percent,
}


class _Evaluator:
    """Walks the parsed expression; anything not allowed is a `MathError`."""

    def __init__(self, functions: dict[str, Callable[..., Any]]) -> None:
        self.functions = functions

    def run(self, source: str) -> Any:
        try:
            tree = ast.parse(source, mode="eval")
        except SyntaxError as exc:
            raise MathError(f"cannot read the expression at position {exc.offset}: {exc.msg}") from None
        return self.eval(tree.body)

    def eval(self, node: ast.AST) -> Any:
        if isinstance(node, ast.Constant):
            if isinstance(node.value, bool) or not isinstance(node.value, (int, float, str)):
                raise MathError(f"{node.value!r} is not a number or a quoted date")
            return node.value if isinstance(node.value, str) else Decimal(str(node.value))
        if isinstance(node, ast.BinOp) and type(node.op) in _BINARY:
            left, right = self.eval(node.left), self.eval(node.right)
            if isinstance(node.op, ast.Pow) and abs(_number(right)) > _MAX_EXPONENT:
                raise MathError("exponent too large")
            try:
                result = _BINARY[type(node.op)](_number(left), _number(right))
            except (ZeroDivisionError, InvalidOperation):
                raise MathError("division by zero") from None
            if result.adjusted() > _MAX_DIGITS:
                raise MathError("the result is too large")
            return result
        if isinstance(node, ast.UnaryOp) and type(node.op) in _UNARY:
            return _UNARY[type(node.op)](_number(self.eval(node.operand)))
        if isinstance(node, (ast.List, ast.Tuple)):
            return [self.eval(e) for e in node.elts]
        if isinstance(node, ast.Call) and isinstance(node.func, ast.Name):
            fn = self.functions.get(node.func.id)
            if fn is None:
                raise MathError(f"unknown function {node.func.id}(); available: {', '.join(self.functions)}")
            args = [self.eval(a) for a in node.args]
            kwargs = {k.arg: self.eval(k.value) for k in node.keywords if k.arg}
            try:
                return fn(*args, **kwargs)
            except MathError:
                raise
            except TypeError as exc:
                raise MathError(f"{node.func.id}(): {exc}") from None
        if isinstance(node, ast.Name):
            raise MathError(f"unknown name {node.id!r}: write numbers, and quote dates like \"2 Oct 2026\"")
        raise MathError(f"{type(node).__name__} is not allowed here")


#: A number written with thousands separators: groups of three (13,798.14) or
#: the Indian 2-2-3 (1,00,000). Only these lose their commas; any other comma
#: separates arguments, so `max(10,20)` stays two numbers, not `max(1020)`.
_GROUPED = re.compile(r"(?<![\d.])(?:\d{1,3}(?:,\d{3})+|\d{1,2}(?:,\d{2})+,\d{3})(?:\.\d+)?(?!\d|,\d)")


def _tidy(source: str) -> str:
    """The forms a model writes that Python reads differently."""
    s = source.strip().strip("`").strip()
    s = re.sub(r"(?:Rs\.?|INR|₹|\$|€|£)\s*", "", s)          # currency marks
    s = _GROUPED.sub(lambda m: m[0].replace(",", ""), s)      # 13,798.14 and 1,00,000
    s = s.replace("×", "*").replace("÷", "/").replace("^", "**")
    s = re.sub(r"(?<=[\d)])\s*[xX]\s*(?=[\d(])", "*", s)      # 2750 x 3
    s = re.sub(r"(\d(?:\.\d+)?)\s*%\s*of\b", r"\1/100*", s)   # 18% of 2750
    s = re.sub(r"(\d(?:\.\d+)?)\s*%", r"(\1/100)", s)          # 2750 * 18%
    return s


def _show(value: Any) -> str:
    if isinstance(value, list):
        return "[" + ", ".join(_show(v) for v in value) + "]"
    if isinstance(value, Decimal):
        if value == value.to_integral_value():
            return f"{value.quantize(Decimal(1)):f}"
        return f"{value.quantize(Decimal('1.0000000000')).normalize():f}"
    if isinstance(value, dt.date):
        return value.strftime("%a %d %b %Y")
    return str(value)


def _result(expression: str, functions: dict[str, Callable[..., Any]]) -> dict[str, Any]:
    with localcontext() as ctx:
        ctx.prec = 50
        try:
            value = _Evaluator(functions).run(_tidy(expression))
        except MathError as exc:
            return {"status": "error", "content": [{"text": f"Error: {exc}. Expression: {expression}"}]}
    return {"status": "success", "content": [{"text": f"{expression} = {_show(value)}"}]}


__all__ = ["MathError", "NUMBER_FUNCTIONS"]
