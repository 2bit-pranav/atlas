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

from typing import Any

from strands import tool

from agent.tools.maths.dates import DATE_FUNCTIONS
from agent.tools.maths.evaluator import NUMBER_FUNCTIONS, _result

# ------------------------------------------------------------------ tools --

@tool(name="calculate")
def calculate(expression: str) -> dict[str, Any]:
    """Work out arithmetic exactly. Use this for EVERY sum, total, difference,
    percentage, average or tax amount -- never add or multiply numbers yourself.

    Write the whole calculation as one expression, with the numbers copied
    exactly as they appear in the source:
      calculate("3940 + 824.82 + 1895.5 + 3245 + 3892.82")    -> 13798.14
      calculate("sum([3940, 824.82, 1895.5])")                  -> 6660.32
      calculate("percent(18, 2750)")     (18% GST on 2,750)     -> 495
      calculate("2750 + percent(18, 2750)")  (total with GST)   -> 3245
      calculate("as_percent(495, 2750)") (495 is what % of 2750) -> 18
      calculate("round(13798.14 / 5, 2)")                      -> 2759.63
      calculate("max(3940, 824.82, 3892.82)")                   -> 3940
    Operators: + - * / // ** and brackets. Functions: sum, min, max, average,
    round(x, places), abs, sqrt, percent(rate, amount), as_percent(part, whole).
    "18% of 2750" and
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


def maths_tools() -> list[Any]:
    return [calculate, dates]


#: The tools this module provides, by the name the agent sees.
NAMES = ("calculate", "dates")


__all__ = ["NAMES", "calculate", "dates", "maths_tools"]
