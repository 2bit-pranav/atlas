"""Offline tests for `calculate` and `dates` (agent/tools/maths/)."""

from __future__ import annotations

import datetime as dt

import pytest

from agent.tools.maths.dates import DATE_FUNCTIONS
from agent.tools.maths.evaluator import NUMBER_FUNCTIONS, _result


def calc(expression: str) -> str:
    out = _result(expression, NUMBER_FUNCTIONS)
    assert out["status"] == "success", out
    return out["content"][0]["text"].split(" = ", 1)[1]


def date(expression: str) -> str:
    out = _result(expression, DATE_FUNCTIONS)
    assert out["status"] == "success", out
    return out["content"][0]["text"].split(" = ", 1)[1]


def refused(expression: str, functions=NUMBER_FUNCTIONS) -> str:
    out = _result(expression, functions)
    assert out["status"] == "error", out
    return out["content"][0]["text"]


@pytest.mark.parametrize("expression, expected", [
    ("3940 + 824.82 + 1895.5 + 3245 + 3892.82", "13798.14"),
    ("0.1 + 0.2", "0.3"),                     # exact decimals, not floats
    ("sum([3940, 824.82, 1895.5])", "6660.32"),
    ("2750 * 18 / 100", "495"),
    ("round(13798.14 / 5, 2)", "2759.63"),
    ("max(3940, 824.82, 3892.82)", "3940"),
    ("average(1, 2, 4)", "2.3333333333"),
    ("percent(18, 2750)", "495"),             # 18% of 2750: what a model means by it
    ("2750 + percent(18, 2750)", "3245"),
    ("as_percent(495, 2750)", "18"),
    ("-(2 - 5) ** 2", "-9"),
])
def test_arithmetic(expression: str, expected: str) -> None:
    assert calc(expression) == expected


@pytest.mark.parametrize("expression, expected", [
    ("18% of 2750", "495"),
    pytest.param("2750 * 18%", "495", marks=pytest.mark.xfail(
        reason="B16: the % rewrite takes one digit, so 18% becomes 1(8/100)", strict=True)),
    ("Rs. 1,250.50 + ₹ 1,00,000", "101250.5"),   # currency marks, Indian grouping
    ("13,798.14 - 798.14", "13000"),
    ("2750 x 3", "8250"),
    ("6 × 7 ÷ 2", "21"),
])
def test_forms_people_write(expression: str, expected: str) -> None:
    assert calc(expression) == expected


@pytest.mark.parametrize("expression, message", [
    ("__import__('os').system('echo hi')", "not allowed"),
    ("open('settings.json')", "unknown function"),
    ("x + 1", "unknown name"),
    ("(1).__class__", "not allowed"),
    ("9 ** 9 ** 9", "exponent too large"),
    ("1 / 0", "division by zero"),
    ("2 +", "cannot read"),
])
def test_refused_with_a_reason(expression: str, message: str) -> None:
    assert message in refused(expression)


def test_dates() -> None:
    assert date('days_between("2 Oct 2026", "15 Nov 2026")') == "44"
    assert date('add_days("2 Oct 2026", 45)') == "Mon 16 Nov 2026"
    assert date('weekday("15 Aug 2026")') == "Saturday"
    # Day first, as written in India; ISO stays ISO.
    assert date('weekday("02/10/2026")') == date('weekday("2026-10-02")') == "Friday"
    assert date('workdays("1 Oct 2026", "31 Oct 2026", ["2 Oct 2026", "20 Oct 2026"])') == "20"
    assert date('workdays("1 Oct 2026", "31 Oct 2026", weekend=["Sun"])') == "27"
    assert date('days_off("1 Oct 2026", "4 Oct 2026", ["2 Oct 2026"])') == \
        "[Fri 02 Oct 2026, Sat 03 Oct 2026, Sun 04 Oct 2026]"


def test_days_until_counts_from_today() -> None:
    target = dt.date.today() + dt.timedelta(days=10)
    assert date(f'days_until("{target.isoformat()}")') == "10"


def test_bad_dates_are_refused() -> None:
    assert "cannot read" in refused('weekday("tomorrowish")', DATE_FUNCTIONS)
    assert "ten years" in refused('workdays("2000-01-01", "2030-01-01")', DATE_FUNCTIONS)
    assert "day of the week" in refused('workdays("1 Oct 2026", "2 Oct 2026", weekend=["Funday"])',
                                        DATE_FUNCTIONS)


@pytest.mark.parametrize("expression, expected", [
    ("max(10,20)", "20"),                    # B8: became max(1020)
    ("sum([10,20,30])", "60"),
    ("min(5,12)", "5"),
    ("max(1,000, 2,500)", "2500"),           # grouped numbers inside a call still read as numbers
    ("13,798.14 + 1,00,000", "113798.14"),
])
def test_commas_between_arguments_are_not_thousands(expression: str, expected: str) -> None:
    assert calc(expression) == expected
