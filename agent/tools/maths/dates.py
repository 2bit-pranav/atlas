"""Date functions for the `dates` tool: days between, weekdays, working days."""

from __future__ import annotations

import datetime as dt
import re
from collections.abc import Callable
from decimal import Decimal
from typing import Any

from agent.tools.maths.evaluator import NUMBER_FUNCTIONS, MathError, _number

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


DATE_FUNCTIONS["days_until"] = lambda date: _between(dt.date.today(), date)


__all__ = ["DATE_FUNCTIONS"]
