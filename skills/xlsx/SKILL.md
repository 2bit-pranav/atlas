---
name: xlsx
description: Read, query, combine and export Excel spreadsheets (.xlsx, .xlsm, .xltx) - list sheets, inspect columns and formulas, compute totals, sums, averages and group-by results with SQL, combine workbooks or sheets, and export sheets as CSV. Use this whenever a spreadsheet is attached or mentioned. Also creates spreadsheets from Markdown tables.
---

# Spreadsheets

Run the scripts with `shell`. To answer a question about a spreadsheet, take
the two numbered steps below, always in that order.

`python` is already the right interpreter — do not look for another one, and do
not run `pip install` to fix a complaint about a missing library. That is a
setup problem to report to the user.

## Combine and export

These need no reading first, and one call does every file or sheet.

Several workbooks, chosen sheets (`file.xlsx:Sheet`) or CSVs into one
workbook, a sheet each:

```
python "$ATLAS_SKILLS/xlsx/scripts/combine_xlsx.py" combined.xlsx "jan.xlsx" "feb.xlsx:Sales" "mar.csv"
```

Add `--stack` to append all rows into one sheet instead (the headers must
match; a `source` column records where each row came from).

Export every sheet as CSV, one file each (add `--sheet Mar` for just one):

```
python "$ATLAS_SKILLS/xlsx/scripts/xlsx_to_csv.py" "<file>"
```

## 1. Shape first

```
python "$ATLAS_SKILLS/xlsx/scripts/read_xlsx.py" "<file>"
```

Gives every sheet name, then for one sheet its row/column counts and the first
few rows. `--all-sheets` for all of them. `--formulas` to see formula strings
instead of cached values.

**Always do this before querying.** Guessing a sheet name or a column name
produces a wrong number with total confidence, and a wrong number in a
spreadsheet is worse than no number.

## 2. Query with SQL

```
python "$ATLAS_SKILLS/xlsx/scripts/query_xlsx.py" "<file>" 'SELECT SUM("revenue") FROM "Mar"'
```

The sheet name is the table name, so quote it. Column names come from the
first row, exactly as they appear. Not sure of them? This needs no SQL:

```
python "$ATLAS_SKILLS/xlsx/scripts/query_xlsx.py" "<file>" --schema
```

---

## Create or change a document

Do not use `shell` or `write` for this. Call the **`create_document`** tool
with the whole document as **Markdown**:

- `path`: a file name such as `summary.xlsx` (it is saved in your workspace)
- `content`: Markdown -- `#` headings, paragraphs, `**bold**`, `- bullets`,
  `1. numbered`, and tables:

```
| Month | Total |
|---|---|
| Jan | 489337.15 |
```

To change part of an existing file, call **`edit_document`** with the exact
text to `find` and its `replace`ment. Read the file first and copy the text
exactly. Every Markdown table becomes a sheet, named after the heading above it; numbers become real numbers.

## Gotchas that produce wrong answers

These are the failure modes that do **not** announce themselves. Each one has
cost someone a confidently wrong total.

**Cached values and formulas need two different loads.** With
`data_only=True` you get the cached result and the formula is gone. Without
it you get `=SUM(B2:B40)` and no result. One pass cannot give you both --
`read_xlsx.py --formulas` is the second view.

**A workbook openpyxl just wrote has no cached values.** Every formula reads
back as `None` until something recalculates it. If a column is unexpectedly
empty, suspect this before suspecting the data. (A formula whose result is an
empty string also reads as `None`.)

**Types are inferred, because a spreadsheet has no schema.** A column is
`DOUBLE` when at least 90% of its values are numbers; anything less mixed
becomes `VARCHAR`. Real files carry placeholders like `"n/a"`, and
`samples/sales.xlsx` does exactly this.

**Non-numeric cells in a numeric column become NULL, and the count is
printed.** Look for `coerced_cells` in the header. If it is non-zero, the
total excludes those rows -- the script tells you so rather than letting you
report a total that is quietly short.

**A sheet name containing a space must be quoted** in a reference:
`"Assumptions Inputs"`, never bare.

**`.xlsm` files may contain macros.** These scripts only ever *read*, so
nothing is lost, but never re-save an `.xlsm` without `keep_vba=True`.

**A workbook that links to another file can lose those links** when it is
re-saved by openpyxl. These scripts never save, so they cannot do this.

---

## Rules that keep answers honest

- **Re-read a number rather than recalling it.** If a total appeared in a
  truncated output, query it again.
- **Only SELECT runs.** Anything else is refused, so the file cannot be altered.
- Prefer SQL aggregation (`SUM`, `GROUP BY`, `AVG`) over eyeballing sample
  rows. Sample rows are for finding columns, not for computing totals.
- `.xls` is not supported. Ask the user to save as `.xlsx`.
- Row output caps at 200 rows and the script reports the true total.
- **If a script says a library is missing, tell the user. Do not install it.**
  The interpreter running these scripts already has everything it needs; a
  `pip install` from here installs somewhere else and breaks nothing you were
  trying to fix.