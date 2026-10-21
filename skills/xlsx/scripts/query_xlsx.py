"""Aggregate a spreadsheet with SQL, read-only.

    python query_xlsx.py sales.xlsx --schema
    python query_xlsx.py sales.xlsx "SELECT SUM(revenue) FROM Mar"

Answers questions like "what is the total for March". Each sheet is loaded
into an in-memory DuckDB table, queried, and discarded: no database file, so
nothing to lock, and the spreadsheet on disk is never modified.

**Read-only.** Only `SELECT` is accepted: a spreadsheet is someone's source
data, and a mangled file is far worse than a wrong number.
"""

from __future__ import annotations

import argparse
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from _shared import (  # noqa: E402
    add_common_arguments,
    fail,
    header,
    join_sql,
    limit_for,
    main_wrapper,
    require,
    resolve,
    truncate,
    unquote,
)

duckdb, openpyxl = require("duckdb", "openpyxl")

#: Anything that is not a plain read. Checked before the query runs, because
#: DuckDB would accept DDL and writes, and a read tool must never write.
FORBIDDEN = re.compile(
    r"\b(insert|update|delete|drop|create|alter|attach|copy|install|load|"
    r"export|call|pragma|set|reset|merge|truncate)\b",
    re.IGNORECASE,
)


def quote(name: str) -> str:
    return '"' + name.replace('"', '""') + '"'


def load(path: Path, con, only: str = "") -> tuple[list[str], int]:
    """Load `only` (or every sheet) as tables; return (sheet names, cells coerced to NULL).

    The coercion count is printed, so a total missing some values says so.
    """
    book = openpyxl.load_workbook(str(path), read_only=True, data_only=True)
    names = [only] if only else book.sheetnames
    coerced = 0
    if only and only not in book.sheetnames:
        book.close()
        raise KeyError(f"no sheet named {only!r}; sheets are {book.sheetnames}")
    for name in names:
        sheet = book[name]
        rows = sheet.iter_rows(values_only=True)
        header = next(rows, None)
        if header is None:
            continue
        columns = [str(c).strip() or f"column_{i + 1}"
                   for i, c in enumerate(header)]
        # Duplicate header names would make the CREATE ambiguous: suffix them.
        seen: dict[str, int] = {}
        unique = []
        for col in columns:
            if col in seen:
                seen[col] += 1
                col = f"{col}_{seen[col]}"
            else:
                seen[col] = 0
            unique.append(col)
        rows = [tuple(r) for r in rows if any(v is not None for v in r)]
        if not rows:
            continue
        # DuckDB requires column types (`CREATE TABLE t (a, b)` is a syntax
        # error). They are inferred rather than all VARCHAR because SUM over
        # VARCHAR fails, and "what is the total" is the most common question.
        types = [
            _infer_type([r[i] if i < len(r) else None for r in rows])
            for i in range(len(unique))
        ]
        coerced += _coerced_count(rows, types, len(unique))
        con.execute(
            f"CREATE TABLE {quote(name)} ("
            + ", ".join(f"{quote(c)} {t}" for c, t in zip(unique, types))
            + ")"
        )
        placeholders = ", ".join("?" for _ in unique)
        con.executemany(
            f"INSERT INTO {quote(name)} VALUES ({placeholders})",
            [_blank_non_numeric(r, types) for r in rows],
        )
    book.close()
    return names, coerced


#: Fraction of a column that must be numeric for it to be typed DOUBLE.
#: Real columns carry the odd placeholder ("n/a"); an all-or-nothing rule
#: would type them VARCHAR and make SUM fail. The odd non-numeric cell becomes
#: NULL instead, and the count is printed so the coercion is never silent.
NUMERIC_MAJORITY = 0.9


def _infer_type(values: list) -> str:
    """DOUBLE when the column is overwhelmingly numeric, else VARCHAR.

    bool is excluded on purpose: `True` is an int in Python, and a column of
    checkboxes should not become a column of 1s and 0s.
    """
    seen = [v for v in values if v is not None]
    if not seen or all(isinstance(v, bool) for v in seen):
        return "VARCHAR"
    numeric = [v for v in seen if isinstance(v, (int, float))]
    if not numeric:
        return "VARCHAR"
    if len(numeric) / len(seen) >= NUMERIC_MAJORITY:
        return "DOUBLE"
    return "VARCHAR"


def _blank_non_numeric(row: tuple, types: list) -> tuple:
    """NULL out non-numeric cells in DOUBLE columns (NULL, not zero, so they
    do not distort SUM or AVG)."""
    out = list(row)
    for i, kind in enumerate(types):
        if kind != "DOUBLE" or i >= len(out):
            continue
        value = out[i]
        if value is None:
            continue
        if isinstance(value, bool) or not isinstance(value, (int, float)):
            out[i] = None
    return tuple(out)


def _coerced_count(rows: list, types: list, width: int) -> int:
    """How many cells `_blank_non_numeric` will turn into NULL."""
    total = 0
    for row in rows:
        for i, kind in enumerate(types):
            if kind == "DOUBLE" and i < len(row):
                v = row[i]
                if v is not None and (isinstance(v, bool)
                                      or not isinstance(v, (int, float))):
                    total += 1
    return total


def _cell(value: object) -> str:
    """One result cell, as text worth reading.

    Floating point turns a total into `425184.6699999999`, which reads as bad
    data. So a float prints at the fewest of 2-6 decimal places that stays
    within relative 1e-9 (money lands on 2dp); anything more precise keeps
    its digits, and whole numbers print as integers, never `4.00`.
    """
    if value is None:
        return ""
    if isinstance(value, bool):
        return "true" if value else "false"
    if isinstance(value, int):
        return str(value)
    if isinstance(value, float):
        if value != value or value in (float("inf"), float("-inf")):
            return str(value)
        if value.is_integer():
            return str(int(value))
        tolerance = 1e-9 * max(1.0, abs(value))
        for places in range(2, 7):
            rounded = round(value, places)
            # Never round a non-zero value to `0.00`.
            if rounded == 0 and value != 0:
                continue
            if abs(value - rounded) <= tolerance:
                return f"{rounded:.{places}f}"
        return repr(value)
    return str(value)


def main() -> int:
    parser = argparse.ArgumentParser(description="Query a spreadsheet with SQL")
    parser.add_argument("path")
    # nargs="*" and rejoined by join_sql: `cmd.exe` can split a quoted statement
    # on its spaces, and a single argument would then fail as "unrecognized".
    parser.add_argument("sql", nargs="*", help="a SELECT statement")
    parser.add_argument("--sheet", default="",
                        help="load only this sheet (faster on wide workbooks)")
    parser.add_argument("--schema", action="store_true",
                        help="print the tables and columns instead of running")
    add_common_arguments(parser)
    args = parser.parse_args()

    path = resolve(args.path)
    if not path.is_file():
        return fail(f"no such file: {path}")

    sql = unquote(join_sql(args.sql)).rstrip(";")
    # `--schema` needs no SQL; it is how the model finds the names to query.
    want_schema = args.schema
    if not sql and not want_schema:
        return fail(
            "no SQL statement and no --schema",
            hint="usage: query_xlsx.py <path> \"SELECT SUM(col) FROM sheet\""
                 "   -- or to see the tables and columns first: "
                 "query_xlsx.py <path> --schema",
        )
    if FORBIDDEN.search(sql):
        return fail(
            "this tool only runs SELECT statements",
            hint=f"rejected: {sql[:60]!r}. Aggregate in SQL (SUM, GROUP BY) "
                 "rather than writing anything.",
        )

    con = duckdb.connect(":memory:")
    try:
        names, coerced = load(path, con, args.sheet)
    except KeyError as exc:
        con.close()
        return fail(str(exc).strip("'"))

    if want_schema:
        print(header(file=path.name, sheets=", ".join(names)))
        for name in names:
            cols = con.execute(
                "SELECT column_name, data_type FROM information_schema.columns "
                "WHERE table_name = ? ORDER BY ordinal_position", [name]
            ).fetchall()
            print(f"--- {name} ---")
            for col, kind in cols:
                print(f"  {col}: {kind}")
        con.close()
        return 0

    try:
        result = con.execute(sql)
        rows = result.fetchall()
        columns = [d[0] for d in result.description]
    except Exception as exc:  # noqa: BLE001
        con.close()
        return fail(f"{type(exc).__name__}: {exc}",
                    hint="use --schema to see the real table and column names")

    limit, hint = limit_for(args)
    lines = [f"rows: {len(rows)}"]
    if rows:
        lines.append(" | ".join(columns))
        for row in rows[:200]:
            lines.append(" | ".join(_cell(v) for v in row))
        if len(rows) > 200:
            lines.append(f"[showing 200 of {len(rows)} rows]")
    else:
        lines.append("(no rows -- check the sheet name and the WHERE clause)")

    body, cut = truncate("\n".join(lines), limit, more_hint=hint)
    con.close()
    print(header(file=path.name, sheets=", ".join(names), truncated=cut or "no", coerced_cells=coerced))
    print()
    print(body)
    return 0


if __name__ == "__main__":
    raise SystemExit(main_wrapper(main))