---
name: xlsx
description: Combine Excel workbooks or sheets, export sheets as CSV, create spreadsheets from Markdown tables, and change cells in existing ones. To read a workbook or compute totals, use the read_xlsx tool (its sql argument); no skill is needed.
---

# Spreadsheets

Reading and totals are the `read_xlsx` tool, not this skill. Run the scripts
below with `shell`.

`python` is already the right interpreter -- do not look for another one, and
do not run `pip install` to fix a complaint about a missing library. That is
a setup problem to report to the user.

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

## Create or change a spreadsheet

Do not use `shell` or `write` for this. Call the **`create_document`** tool
with the whole workbook as **Markdown**: every Markdown table becomes a
sheet, named after the heading above it; numbers become real numbers.

```
## Mar
| region | revenue |
|---|---|
| North | 4100.5 |
```

To change a value in an existing file, call **`edit_document`** with the
cell's exact text to `find` and its `replace`ment.

## Things that bite

- `.xls` is not supported. Ask the user to save as `.xlsx`.
- **If a script says a library is missing, tell the user. Do not install it.**
