---
name: docx
description: Read, summarise and write Word documents (.docx). Use this whenever a .docx file is attached or mentioned - to summarise it, list its headings, read its tables, or produce a new Word document.
---

# Word documents

Use `shell` to run the scripts. Do not write `python-docx` code yourself.

## Read

```
python skills/docx/scripts/read_docx.py "<path>"
```

Returns the headings, the prose, and every table rendered as a pipe table, in
document order.

## The outline first, for long documents

```
python skills/docx/scripts/read_docx.py "<path>" --headings-only
```

Cheap, and it tells you which section actually answers the question.

## Write

Reads JSON on stdin, so you describe the document rather than code it:

```
echo '{"title":"Findings","blocks":[
  {"type":"heading","level":1,"text":"March total"},
  {"type":"para","text":"The total for March was 425184.67."},
  {"type":"bullet","text":"Confirmed against the workbook."},
  {"type":"table","header":["sheet","total"],"rows":[["Jan","489337.15"]]}
]}' | python skills/docx/scripts/write_docx.py "summary.docx"
```

Block types: `heading` (with `level`), `para`, `bullet`, `table` (with
`header` and `rows`).

## Things that bite

- **A table is usually the answer.** Report and contract .docx files put their
  findings in tables. `read_docx.py` prints them; do not skip straight to prose.
- **Legacy `.doc` is not supported.** The script says so. Ask the user to save
  as `.docx` rather than trying to convert it.
- Output is capped near 1500 tokens and the script says so when it cuts.