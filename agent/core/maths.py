"""`calculate` and `dates`: exact arithmetic and date counting for the agent.

A 2B model adds five amounts in its head and is off by 60; it counts days
between dates worse. These take what the model writes well -- the sum as an
expression, `3940 + 824.82 + 1895.5` -- and do the part it does badly.

Both take one string, so the model never chooses between operations or
counts arguments. It is parsed with Python's own parser and only an allow-list
of nodes is evaluated (numbers, strings, + - * / // ** and the functions
below): nothing is executed. Money stays exact: numbers are `Decimal`, so
0.1 + 0.2 is 0.3.
"""

from __future__ import annotations

import ast
import datetime as dt
import operator
import re
from decimal import Decimal, InvalidOperation, localcontext
from typing import Any, Callable

from strands import tool

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


def _tidy(source: str) -> str:
    """The forms a model writes that Python reads differently."""
    s = source.strip().strip("`").strip()
    s = re.sub(r"(?:Rs\.?|INR|₹|\$|€|£)\s*", "", s)          # currency marks
    s = re.sub(r"(?<=\d),(?=\d{2,3}\b)", "", s)               # 13,798.14 and 1,00,000
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


# ------------------------------------------------------------------ dates --

def _date(value: Any) -> dt.date:
    """A date as people write it: 2 Oct 2026, 2026-10-02, 02/10/2026 (day first), Oct 2."""
    if isinstance(value, dt.date):
        return value
    if not isinstance(value, str):
        raise MathError(f"expected a quoted date, got {value!r}")
    from dateutil import parser

    try:
        iso = re.fullmatch(r"\d{4}-\d{1,2}-\d{1,2}", value.strip())
        return parser.parse(value, dayfirst=not iso, default=dt.datetime(dt.date.today().year, 1, 1)).date()
    except (ValueError, OverflowError):
        raise MathError(f"cannot read {value!r} as a date; write it like \"2 Oct 2026\"") from None


def _dates(values: Any) -> list[dt.date]:
    return [_date(v) for v in (values if isinstance(values, list) else [values])]


_DAY_NAMES = ["mon", "tue", "wed", "thu", "fri", "sat", "sun"]


def _weekend(names: Any) -> set[int]:
    out = set()
    for n in names if isinstance(names, list) else [names]:
        key = str(n).strip().lower()[:3]
        if key not in _DAY_NAMES:
            raise MathError(f"{n!r} is not a day of the week")
        out.add(_DAY_NAMES.index(key))
    return out


def _between(a: Any, b: Any) -> Decimal:
    return Decimal((_date(b) - _date(a)).days)


def _add_days(date: Any, n: Any) -> dt.date:
    return _date(date) + dt.timedelta(days=int(_number(n)))


def _weekday(dates: Any) -> Any:
    days = _dates(dates)
    named = [f"{d.strftime('%a %d %b %Y')}: {d.strftime('%A')}" for d in days]
    return named[0].split(": ")[1] if not isinstance(dates, list) else named


def _days_off(start: Any, end: Any, holidays: Any = None, weekend: Any = None) -> list[dt.date]:
    a, b = _date(start), _date(end)
    if b < a:
        a, b = b, a
    if (b - a).days > 3660:
        raise MathError("the range is longer than ten years")
    off = _weekend(weekend if weekend is not None else ["Sat", "Sun"])
    free = set(_dates(holidays)) if holidays else set()
    return [a + dt.timedelta(days=i) for i in range((b - a).days + 1)
            if (a + dt.timedelta(days=i)).weekday() in off or (a + dt.timedelta(days=i)) in free]


def _workdays(start: Any, end: Any, holidays: Any = None, weekend: Any = None) -> Decimal:
    a, b = sorted((_date(start), _date(end)))
    return Decimal((b - a).days + 1 - len(_days_off(start, end, holidays, weekend)))


DATE_FUNCTIONS: dict[str, Callable[..., Any]] = {
    "today": lambda: dt.date.today(),
    "days_between": _between,
    "add_days": _add_days,
    "weekday": _weekday,
    "workdays": _workdays,
    "days_off": lambda start, end, holidays=None, weekend=None: _days_off(start, end, holidays, weekend),
    **NUMBER_FUNCTIONS,
}


# ------------------------------------------------------------------ tools --

@tool(name="calculate")
def calculate(expression: str) -> dict[str, Any]:
    """Work out arithmetic exactly. Use this for EVERY sum, total, difference,
    percentage, average or tax amount -- never add or multiply numbers yourself.

    Write the whole calculation as one expression, with the numbers copied
    exactly as they appear in the source:
      calculate("3940 + 824.82 + 1895.5 + 3245 + 3892.82")    -> 13798.14
      calculate("sum([3940, 824.82, 1895.5])")                  -> 6660.32
      calculate("2750 * 18 / 100")       (18% GST on 2,750)     -> 495
      calculate("round(13798.14 / 5, 2)")                      -> 2759.63
      calculate("max(3940, 824.82, 3892.82)")                   -> 3940
    Operators: + - * / // ** and brackets. Functions: sum, min, max, average,
    round(x, places), abs, sqrt, percent(part, whole). "18% of 2750" and
    "1,250.50" are understood too. Quote the result in your answer as given.
    """
    return _result(expression, NUMBER_FUNCTIONS)


@tool(name="dates")
def dates(expression: str) -> dict[str, Any]:
    """Count and look up dates exactly. Use this for every question about how
    many days, which weekday, what date it will be, or how many working days --
    never count days on a calendar yourself.

    Write one expression; quote every date ("2 Oct 2026", "2026-10-02" and
    "02/10/2026" are all 2 October):
      dates('days_between("2 Oct 2026", "15 Nov 2026")')        -> 44
      dates('add_days("2 Oct 2026", 45)')                        -> Mon 16 Nov 2026
      dates('weekday("15 Aug 2026")')                            -> Saturday
      dates('weekday(["15 Aug 2026", "2 Oct 2026"])')            -> each date with its weekday
      dates('workdays("1 Oct 2026", "31 Oct 2026", ["2 Oct 2026", "20 Oct 2026"])')
          -> working days from 1 to 31 October (both included), not counting
             weekends or the listed holidays
      dates('days_off("1 Oct 2026", "31 Oct 2026", ["2 Oct 2026"])')
          -> every weekend day and holiday in that range, as dates
      dates('days_until("25 Dec 2026")') is days_between(today(), "25 Dec 2026").
    Weekends are Saturday and Sunday; pass weekend=["Sun"] where Saturday is a
    working day. Functions: today, days_between, add_days, weekday, workdays,
    days_off (and the arithmetic of `calculate`).
    """
    return _result(expression, DATE_FUNCTIONS)


DATE_FUNCTIONS["days_until"] = lambda date: _between(dt.date.today(), date)


def maths_tools() -> list[Any]:
    return [calculate, dates]


#: The tools this module provides, by the name the agent sees.
NAMES = ("calculate", "dates")

__all__ = ["DATE_FUNCTIONS", "NAMES", "NUMBER_FUNCTIONS", "calculate", "dates", "maths_tools"]
